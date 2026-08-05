@echo off
chcp 65001 > nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Unregister-ScheduledTask -TaskName 'PauseTask Watchdog' -Confirm:$false -ErrorAction Stop; Write-Output 'ウォッチドッグを解除しました。' } catch { Write-Output 'ウォッチドッグは登録されていません。' }"
pause
