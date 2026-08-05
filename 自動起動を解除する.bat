@echo off
chcp 65001 > nul
set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PauseTask.lnk"
if exist "%SHORTCUT%" (
  del "%SHORTCUT%"
  echo 自動起動を解除しました。
) else (
  echo 自動起動は登録されていません。
)
pause
