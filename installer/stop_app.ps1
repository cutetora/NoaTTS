# NoaTTS インストーラー用: インストール先で動いているアプリを止める (更新・アンインストールの前に呼ぶ)。
#
# Inno Setup は使用中のファイルを持つアプリを自動で閉じようとするが、ウィンドウの無い pythonw は
# 閉じられず、無人実行 (/VERYSILENT) では中断してしまう。そのため先にこちらで止める。
#
# 対象は「-AppDir 配下の実行ファイル」だけ。別の場所 (開発フォルダなど) で動く NoaTTS は止めない。
# 7870 の daemon も、持ち主が -AppDir 配下のときだけ /quit を送る。
# 終了コード: 0 = 止まった (または元から無かった) / 1 = 残っている
param([Parameter(Mandatory = $true)][string]$AppDir)

$ErrorActionPreference = 'SilentlyContinue'
$AppDir = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\') + '\'

# 安全のため、NoaTTS のインストール先に見える場所だけを対象にする。ドライブ直下 (D:\ など) や、
# 同梱 Python / ランチャーが無いフォルダなら何も止めない (インストール先を浅い場所にされても巻き込まない)。
if ($AppDir.Length -le 3 -or
    -not (Test-Path -LiteralPath (Join-Path $AppDir 'python\python.exe')) -or
    -not (Test-Path -LiteralPath (Join-Path $AppDir 'NoaTTS.exe'))) { exit 0 }

function Get-AppProcesses {
    # unins*.exe は、アンインストーラー自身から呼ばれたときに自分を殺さないよう除く
    Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase) -and
        $_.Name -notlike 'unins*'
    }
}

if (-not (Get-AppProcesses)) { exit 0 }

# 1) daemon は、持ち主がこのインストール先のときだけ、アプリ自身の終了 (/quit) で止める
$listener = Get-NetTCPConnection -LocalPort 7870 -State Listen | Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($owner -and $owner.ExecutablePath -and
        $owner.ExecutablePath.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase)) {
        try { Invoke-WebRequest -Uri 'http://127.0.0.1:7870/quit' -Method Post -TimeoutSec 3 -UseBasicParsing | Out-Null } catch {}
        for ($i = 0; $i -lt 16; $i++) {
            if (-not (Get-Process -Id $owner.ProcessId)) { break }
            Start-Sleep -Milliseconds 500
        }
    }
}

# 2) 残りは、インストール先配下の実行ファイルだけを止める (トレイ、画面 (Gradio)、読み上げ設定のウィンドウなど)。
#    プロセスツリーごと (/T) は止めない: アプリが開いたブラウザなど、利用者のプログラムを巻き込まないため。
#    WebView2 (Edge 側の実行ファイル) は、親が終われば一緒に終わる。
foreach ($p in @(Get-AppProcesses)) {
    Stop-Process -Id $p.ProcessId -Force
}

# 3) 止まるまで少し待つ (読み込み中の .pyd / .exe を上書きできるようにする)
for ($i = 0; $i -lt 20; $i++) {
    if (-not (Get-AppProcesses)) { exit 0 }
    Start-Sleep -Milliseconds 500
}
exit 1
