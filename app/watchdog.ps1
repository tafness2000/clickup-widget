# Click Up Widget ウォッチドッグ
# 常駐が落ちていたら起動し直す。タスクスケジューラから 5 分間隔＋ログオン時に呼ばれる。
#
# 生きているかどうかは Python のコマンドラインに pause.pyw があるかで見る。
# スクリプト名を変えるとここも直す必要があるので、名前は据え置いてある。

# このスクリプトは常駐本体と同じ場所（app\）に置かれる。
# Python 本体は 1 つ上の runtime\ にある。
$root      = $PSScriptRoot
$launchBat = Join-Path $root 'launch.bat'
$script    = Join-Path $root 'pause.pyw'
$pythonw   = Join-Path (Split-Path $root -Parent) 'runtime\pythonw.exe'
$logPath   = Join-Path $root 'watchdog.log'

# ログの上限。常駐側（appconfig.log）と同じ 512KB で、1 世代だけ残す。
# 起動し直しが延々と失敗する状況では、ここが 5 分ごとに書かれ続けるため。
$logMax = 512KB

function Write-Log([string]$message) {
    if ((Test-Path $logPath) -and ((Get-Item $logPath).Length -gt $logMax)) {
        Move-Item -Path $logPath -Destination "$logPath.1" -Force -ErrorAction SilentlyContinue
    }
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logPath -Value "$stamp  $message" -Encoding utf8
}

# 更新の最中かどうか。updater.pyw が動いている間だけ立てている印を見る。
#
# プロセスのコマンドラインでは見分けない。あれは名乗るだけの文字列なので、
# 「updater.pyw」を含む引数のプロセスを 1 つ置いておけば、この見張り役を
# 永久に黙らせられてしまう。印は Windows が持つものなので、名乗るだけでは作れない。
function Test-Updating {
    try {
        $held = [System.Threading.Mutex]::OpenExisting('Local\ClickUpPauseUpdating')
        $held.Dispose()
        return $true
    } catch [System.Threading.WaitHandleCannotBeOpenedException] {
        return $false      # 印が無い＝更新していない
    } catch {
        return $false      # 確かめられなかった。常駐が上がらないまま放置されるより、
    }                      # 起動を試す方に倒す
}

try {
    # 更新の最中は手を出さない。updater は常駐をいったん落としてからファイルを
    # 書き換えるので、その隙にここが起動すると、書き換え途中のコードを読んだ常駐が
    # 先にシングルトンの印を取って居座り、updater が起こし直したものが二重起動として
    # 消える。結果として古い版のまま動き続けることになる。
    if (Test-Updating) {
        Write-Log '更新中のため、起動の確認を見送りました'
        return
    }

    # 配布版は pythonw.exe から動くが、開発中は python.exe のことがある。両方見る。
    $python = @(Get-CimInstance Win32_Process `
        -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction Stop)

    # ここに置いてある pause.pyw を指しているものだけを数える。ファイル名だけで見ると、
    # 別の場所へ展開した同じアプリや、たまたま引数に含むものまで「動いている」ことになる。
    $running = @($python | Where-Object {
        $_.CommandLine -and
        $_.CommandLine.IndexOf($script, [StringComparison]::OrdinalIgnoreCase) -ge 0
    })

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
