import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("upload", Path(__file__).resolve().parents[1] / "scripts" / "upload.py")
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)


def session_token(exp=None):
    payload = {
        "iss": "https://accounts.nintendo.com", "typ": "session_token",
        "aud": "71b963c1b7b6d119", "exp": exp if exp is not None else time.time() + 3600,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "eyJhbGciOiJIUzI1NiJ9." + encoded + ".signature"


class UploadTests(unittest.TestCase):
    def test_expired_token_fails_before_network(self):
        with self.assertRaisesRegex(upload.UploadError, "expired"):
            upload.validate_credentials({"API_KEY": "k" * 43, "SESSION_TOKEN": session_token(time.time() - 1)})

    def test_missing_and_invalid_credentials(self):
        for env in ({}, {"API_KEY": "k" * 43}, {"API_KEY": "k" * 43, "SESSION_TOKEN": "not-a-token"}):
            with self.subTest(env=list(env)):
                with self.assertRaises(upload.UploadError):
                    upload.validate_credentials(env)

    def test_redacts_credentials_and_unknown_jwt(self):
        self.assertEqual(upload.redact("key secret eyJabc.payload.signature", ["key", "secret"]),
                         "[REDACTED] [REDACTED] [REDACTED]")

    def perform(self, check_only=False, auth_failure=False, s3s_failure=False):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "s3s.py").write_text("# fake s3s", encoding="utf-8")
            calls = []
            data_dirs = []
            token = session_token()
            output = io.StringIO()

            def fake_process(command, cwd, env, timeout, on_output=None):
                calls.append(command)
                data_dirs.append(Path(env["NXAPI_DATA_PATH"]))
                self.assertNotIn("API_KEY", env)
                self.assertNotIn("SESSION_TOKEN", env)
                self.assertTrue(data_dirs[-1].is_dir())
                if len(calls) == 1:
                    if auth_failure:
                        return subprocess.CompletedProcess(command, 1, "private email and " + token)
                    config = json.loads((root / "config.txt").read_text())
                    config.update(gtoken="generated-gtoken", bullettoken="generated-bullet", acc_loc="ja-JP|JP")
                    (root / "config.txt").write_text(json.dumps(config))
                    return subprocess.CompletedProcess(command, 0, "private account details")
                message = "generated-gtoken generated-bullet " + "k" * 43
                on_output(message)
                return subprocess.CompletedProcess(command, int(s3s_failure), "")

            error = None
            with patch.dict(os.environ, {"API_KEY": "k" * 43, "SESSION_TOKEN": token}, clear=True):
                with patch.object(upload.shutil, "which", return_value="nxapi"):
                    with patch.object(upload, "run_process", side_effect=fake_process):
                        with contextlib.redirect_stdout(output):
                            try:
                                upload.execute(root, check_only)
                            except upload.UploadError as exc:
                                error = exc
            self.assertFalse((root / "config.txt").exists())
            self.assertTrue(all(not path.exists() for path in data_dirs))
            self.assertNotIn("private", output.getvalue())
            self.assertNotIn(token, output.getvalue())
            return calls, output.getvalue(), error

    def test_check_only_does_not_upload(self):
        calls, output, error = self.perform(check_only=True)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(error)
        self.assertIn("no results were uploaded", output)

    def test_upload_redacts_and_disables_legacy_refresh(self):
        calls, output, error = self.perform()
        self.assertEqual(calls[1][-3:], ["-r", "--norefresh", "1"])
        self.assertIsNone(error)
        self.assertNotIn("generated-gtoken", output)
        self.assertNotIn("generated-bullet", output)
        self.assertNotIn("k" * 43, output)

    def test_auth_failure_cleans_up_and_does_not_upload(self):
        calls, output, error = self.perform(auth_failure=True)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(error)
        self.assertNotIn("private", str(error))

    def test_upload_failure_is_not_reported_as_success(self):
        calls, output, error = self.perform(s3s_failure=True)
        self.assertIsNotNone(error)
        self.assertNotIn("Upload completed successfully", output)

    def test_streaming_timeout_preserves_diagnostic_output(self):
        lines = []
        result = upload.run_process(
            [upload.sys.executable, "-u", "-c", "import time; print('started', flush=True); time.sleep(10)"],
            None, dict(os.environ), 0.5, on_output=lines.append,
        )
        self.assertEqual(result.returncode, 124)
        self.assertIn("started", lines)
        self.assertIn("The s3s operation timed out.", lines)

    def test_existing_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "s3s.py").write_text("# fake s3s")
            (root / "config.txt").write_text("keep existing")
            with patch.dict(os.environ, {"API_KEY": "k" * 43, "SESSION_TOKEN": session_token()}, clear=True):
                with patch.object(upload.shutil, "which", return_value="nxapi"):
                    with self.assertRaisesRegex(upload.UploadError, "overwrite"):
                        upload.execute(root)
            self.assertEqual((root / "config.txt").read_text(), "keep existing")


if __name__ == "__main__":
    unittest.main()
