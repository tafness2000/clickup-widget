@echo off
chcp 65001 > nul
rem 消す先は startup.py と同じ求め方にする。%APPDATA% から組み立てると、
rem スタートアップの場所を変えている環境（会社の設定など）で別の場所を見にいき、
rem 「登録されていません」と言いながら解除できないままになる。
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Join-Path ([Environment]::GetFolderPath('Startup')) 'PauseTask.lnk'; if (Test-Path $p) { Remove-Item $p -Force; Write-Output '自動起動を解除しました。' } else { Write-Output '自動起動は登録されていません。' }"
pause
