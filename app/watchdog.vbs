' PauseTask watchdog launcher - runs watchdog.ps1 hidden (no console flash)
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & here & "\watchdog.ps1""", 0, False
