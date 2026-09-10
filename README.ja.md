# Omarchy Browser Settings

既定ブラウザーを選び、必要に応じてリンクを現在のワークスペースで開く
Omarchy 4 / Quattro 用プラグインです。

```bash
omarchy plugin add https://github.com/agata/omarchy-browser-settings.git --enable
```

バーのブラウザーアイコンから設定画面を開き、ブラウザーを選択して Apply
を押します。「Open links on the current workspace」を有効にすると、現在の
ワークスペースに対象ブラウザーがあればそのウインドウで、なければ新しい
ウインドウで開きます。初版では標準のネイティブ Chromium / Google Chrome
ランチャーに対応しています。他のブラウザーも通常の既定ブラウザーとして
選択できます。

インストールしただけでは既定ブラウザーは変わりません。Apply を押すと
HTTP・HTTPS・HTML の関連付けを変更します。振り分け本体は独立して動くので、
設定画面を閉じたり Shell を再起動したりしてもリンクを開けます。

設定画面をコマンドから開く場合：

```bash
omarchy-shell shell summon io.github.agata.browser-settings '{}'
```

元に戻すには Restore previous defaults を押します。他の設定アプリで後から
変更した関連付けは維持します。完全に削除する場合は、次の順に実行します。

```bash
~/.local/bin/omarchy-setup-browser-settings uninstall
omarchy plugin remove io.github.agata.browser-settings
```

Apply を使っていなければ、プラグイン削除だけで構いません。プラグインだけ
先に削除しても、独立した振り分け本体と復元コマンドは利用できます。

同一ワークスペース機能は通常プロファイル1つでの利用を対象にした暫定的な
回避策です。複数プロファイル・シークレットウインドウの混在や、リンク送信
直前の手動フォーカス変更には制約があります。ブラウザー本体で「デフォルト
に設定」を押すと振り分けを通らなくなります。

依存関係、変更するファイル、更新手順、制約の詳細は [README](README.md) を
参照してください。更新後は Apply を押すと独立した振り分け本体も更新されます。
