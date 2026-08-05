# Click Up Widget ウォッチドッグ
# 常駐が落ちていたら起動し直す。タスクスケジューラから 5 分間隔＋ログオン時に呼ばれる。
#
# 生きているかどうかは pythonw.exe のコマンドラインに pause.pyw があるかで見る。
# スクリプト名を変えるとここも直す必要があるので、名前は据え置いてある。

# このスクリプトは常駐本体と同じ場所（app\）に置かれる。
# Python 本体は 1 つ上の runtime\ にある。
$root      = $PSScriptRoot
$launchBat = Join-Path $root 'launch.bat'
$script    = Join-Path $root 'pause.pyw'
$pythonw   = Join-Path (Split-Path $root -Parent) 'runtime\pythonw.exe'
$logPath   = Join-Path $root 'watchdog.log'

function Write-Log([string]$message) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logPath -Value "$stamp  $message" -Encoding utf8
}

try {
    $running = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -like '*pause.pyw*' })

    if ($running.Count -eq 0) {
        # 同梱した Python がある配布版を優先する
        if ((Test-Path $pythonw) -and (Test-Path $script)) {
            Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $root
            Write-Log '常駐が停止していたため起動し直しました'
        } elseif (Test-Path $launchBat) {
            Start-Process -FilePath $launchBat -WorkingDirectory $root -WindowStyle Hidden
            Write-Log '常駐が停止していたため launch.bat で起動しました'
        } else {
            Write-Log "起動できるファイルがありません（runtime\pythonw.exe / launch.bat のいずれも見つからず）"
        }
    }
} catch {
    Write-Log "エラー: $($_.Exception.Message)"
}
