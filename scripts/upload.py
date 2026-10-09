"""Refresh SplatNet tokens using nxapi, then upload with s3s.

Credentials and nxapi state are temporary and never uploaded as artifacts.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


class UploadError(Exception):
    pass


def validate_credentials(env):
    api_key = env.get("API_KEY", "").strip()
    token = env.get("SESSION_TOKEN", "").strip()
    if not api_key:
        raise UploadError("Missing repository secret API_KEY (stat.ink API key).")
    if len(api_key) != 43 or api_key == "skip":
        raise UploadError("API_KEY must be the 43-character stat.ink API key.")
    if not token:
        raise UploadError("Missing repository secret SESSION_TOKEN. See README.md.")
    try:
        part = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        valid = (
            payload["iss"] == "https://accounts.nintendo.com"
            and payload["typ"] == "session_token"
            and payload["aud"] == "71b963c1b7b6d119"
            and isinstance(payload["exp"], (int, float))
        )
    except (IndexError, KeyError, ValueError, TypeError):
        valid = False
    if not valid:
        raise UploadError("SESSION_TOKEN is not a Nintendo Account session token. See README.md.")
    if payload["exp"] <= time.time() + 300:
        raise UploadError("SESSION_TOKEN has expired or expires within 5 minutes. Renew it using README.md and update the GitHub secret.")
    return api_key, token


def redact(output, secrets):
    for value in sorted(set(secrets), key=len, reverse=True):
        if value:
            output = output.replace(value, "[REDACTED]")
    # Also remove previously unknown JWTs from third-party error messages.
    return re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", output)


def run_process(command, cwd, env, timeout):
    try:
        return subprocess.run(
            command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise UploadError("The operation timed out. Check Nintendo/nxapi/stat.ink service availability.") from None


def execute(s3s_dir, check_only=False):
    api_key, token = validate_credentials(os.environ)
    nxapi = shutil.which("nxapi")
    if not nxapi:
        raise UploadError("nxapi is not installed.")
    s3s_dir = Path(s3s_dir).resolve()
    if not (s3s_dir / "s3s.py").is_file():
        raise UploadError("s3s.py was not found in --s3s-dir.")
    config_path = s3s_dir / "config.txt"
    if config_path.exists():
        raise UploadError("Refusing to overwrite an existing config.txt. Use a fresh s3s checkout.")

    env = dict(os.environ)
    env["DEBUG"] = ""
    env["NXAPI_DEBUG_FILE"] = "0"
    env["NXAPI_SKIP_UPDATE_CHECK"] = "1"
    env.setdefault("NXAPI_USER_AGENT", "s3s-to-statink/2.0.0 (+https://github.com/lasty009/s3s-to-statink)")
    # Only the controller needs these variables; nxapi receives the token argument.
    env.pop("API_KEY", None)
    env.pop("SESSION_TOKEN", None)
    try:
        config_path.write_text(json.dumps({
            "api_key": api_key, "acc_loc": "", "gtoken": "",
            "bullettoken": "", "session_token": "skip", "f_gen": "",
        }) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        with tempfile.TemporaryDirectory(prefix="s3s-nxapi-") as data_dir:
            env["NXAPI_DATA_PATH"] = data_dir
            print("Refreshing SplatNet 3 authentication with nxapi...", flush=True)
            result = run_process(
                [nxapi, "util", "update-s3s-token", str(config_path), "--token", token],
                s3s_dir, env, 300,
            )
            if result.returncode:
                # nxapi failures can contain credentials and decrypted personal data.
                # Keep raw output private, even on failure.
                hint = "Check Nintendo/nxapi service availability and renew SESSION_TOKEN if necessary."
                if "expired" in result.stdout.lower() or "invalid_grant" in result.stdout.lower():
                    hint = "Renew SESSION_TOKEN using README.md and update the GitHub secret."
                raise UploadError("nxapi authentication failed. " + hint)

            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not all(config.get(key) for key in ("gtoken", "bullettoken", "acc_loc")):
                raise UploadError("nxapi did not produce all required SplatNet 3 credentials.")
            if config.get("api_key") != api_key:
                raise UploadError("The stat.ink API key was unexpectedly changed.")
            secrets = [api_key, token, config["gtoken"], config["bullettoken"]]
            if os.environ.get("GITHUB_ACTIONS") == "true":
                for value in secrets:
                    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                    print("::add-mask::" + escaped)
            print("SplatNet 3 authentication succeeded.", flush=True)
            if check_only:
                print("Authentication check complete; no results were uploaded.")
                return
            print("Uploading missing battles and Salmon Run results...", flush=True)
            result = run_process(
                [sys.executable, "-u", "s3s.py", "-r", "--norefresh", "1"],
                s3s_dir, env, 900,
            )
            # Escape workflow-command syntax in third-party stdout.
            for line in redact(result.stdout, secrets).splitlines():
                print("s3s: " + line)
            if result.returncode:
                raise UploadError("s3s upload failed. See the redacted output above.")
            print("Upload completed successfully.")
    finally:
        config_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3s-dir", default="s3s")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        execute(args.s3s_dir, args.check_only or os.environ.get("CHECK_ONLY") == "1")
    except UploadError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    except Exception:
        # Never print raw exceptions from credential-bearing commands/files.
        print("ERROR: Unexpected failure. Verify the dependencies and retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
