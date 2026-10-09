# s3s-to-statink

GitHub Actionsで2時間おきにスプラトゥーン3の未送信のバトル・サーモンラン結果をstat.inkへ送信します。

## 認証方式

従来のs3s単体の認証は、Nintendo Switch Onlineアプリの認証変更で停止しています。
npm配布版nxapiで毎回新しいSplatNet 3トークンを取得し、s3sに渡します。
Androidエミュレーター、常駐Bot、Redisは不要です。

nxapiは第三者サービス `nxapi-znca-api.fancy.org.uk` を利用します。
認証に必要な短期トークンや暗号化データが同サービスへ送られます。
任天堂アカウントのパスワードをGitHubや同サービスへ登録する必要はありません。
サービス・任天堂側の変更や障害によって停止する場合があります。

## 必要なGitHub Secrets

[Settings → Secrets and variables → Actions](https://github.com/lasty009/s3s-to-statink/settings/secrets/actions)
の **Repository secrets** に登録します。通常のVariablesには登録しないでください。

| Secret名 | 内容 |
| --- | --- |
| `API_KEY` | stat.inkのプロフィール設定で発行する43文字のAPIキー |
| `SESSION_TOKEN` | Nintendo Switch Online用のNintendo Account session token |

以前の `ACC_LOC` / `GTOKEN` / `BULLETTOKEN` / `F_GEN` は使用しません。
値をソースコード、Issue、Actionsログ、チャットへ貼らないでください。

## SESSION_TOKENの更新

Nintendo Account session tokenには有効期限があります。期限切れのときだけ再ログインが必要です。
以下はローカルのPCで実行します。Actionsのログイン画面で行う操作ではありません。

1. [Node.js](https://nodejs.org/) のLTS版をインストールします。
2. PowerShellまたはターミナルで実行します。

   ```powershell
   npm install --global nxapi@1.6.1-next.257
   nxapi nso auth --no-auth
   ```

3. 表示された任天堂のURLを開き、自分の任天堂アカウントでログインします。
4. アカウントを選ぶページの「この人にする / Select this person」を右クリックしてリンクをコピーします。
   `npf71b963c1b7b6d119://auth` から始まるリンクを、**自分のPCのターミナル**へ貼ります。
5. 表示される `Session token` オブジェクトの `session_token` の値だけをコピーします。
   引用符、`session_token:`、オブジェクト全体は含めません。
6. GitHubのSecret一覧で `SESSION_TOKEN` の鉛筆アイコンを押し、値を更新します。

このコマンドは秘密のトークンをローカルの画面に表示します。画面・出力を共有しないでください。
`--no-auth` はNSOへの接続を省いてsession tokenだけを取得するオプションです。

## 初回確認・再開

1. [Actions](https://github.com/lasty009/s3s-to-statink/actions)で **Splatoon3 Battlelog Uploader** を開きます。
2. `This scheduled workflow is disabled...` が出ている場合は **Enable workflow** を押します。
3. **Run workflow** → Branch: **main** → 認証確認のチェックをオン → **Run workflow**。
4. 成功したら、チェックをオフにしてもう一度 **Run workflow** を実行します。
5. 成功後はmain上のスケジュールで2時間おきに自動実行されます。

予定時刻はUTCの偶数時17分、日本時間では **1:17、3:17、…、23:17** です。
GitHub側の混雑で遅れる場合があり、厳密な時刻・実行間隔は保証されません。
公開リポジトリは60日間活動がないとスケジュールが無効化されることがあります。
その場合はActionsで再び **Enable workflow** を押してください。

## 実装・検証

- s3s: `frozenpandaman/s3s@732c91e5ac9b82a413f96bc75831996f8cf4f9ea`
- nxapi: `1.6.1-next.257`（npm配布の認証対応版）
- Python 3.11 / Node.js 22 / Ubuntu GitHub-hosted runner
- 重複送信を防ぐs3sの `-r` を使用し、バトルとサーモンランの両方が対象です。
- s3sの旧認証更新・対話入力は `--norefresh 1` で止め、失敗を正常終了扱いにしません。
- configとnxapiの認証データは実行終了時に削除します。キャッシュ・artifactへ保存しません。
- nxapiの生ログを公開せず、生成トークンをマスクしてs3sログを出力します。
- 別ブランチへのpush / PRでは秘密情報を使わず、単体テストだけを実行します。

ローカルの単体テスト:

```sh
python -m unittest discover -s tests -v
```

## 参考

- [s3s issue #198（停止原因・nxapiによる更新方法）](https://github.com/frozenpandaman/s3s/issues/198#issuecomment-3243453677)
- [nxapiの認証とサービスの説明](https://github.com/samuelthomas2774/nxapi#coral-client-authentication)
- [nxapiのs3sトークン更新コマンド](https://github.com/samuelthomas2774/nxapi/blob/main/src/cli/util/update-s3s-token.ts)
- [splatoon3-nsoの認証実装](https://github.com/Cypas/splatoon3-nso/blob/master/nonebot_plugin_splatoon3_nso/s3s/iksm.py)
- [GitHubのschedule仕様](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
