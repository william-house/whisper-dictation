' launch.vbs — Start Whisper Dictation without a console window
' This script is placed in the Startup folder to auto-launch at login.

Dim objShell, scriptDir, pythonExe, scriptPath

Set objShell = CreateObject("WScript.Shell")

' Get the directory where this VBS file lives
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Path to the Python executable inside the venv
pythonExe = scriptDir & "\venv\Scripts\pythonw.exe"

' Path to the dictation script
scriptPath = scriptDir & "\dictation.pyw"

' Launch without a visible console
objShell.Run """" & pythonExe & """ """ & scriptPath & """", 0, False

Set objShell = Nothing
