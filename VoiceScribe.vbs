Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Clear ELECTRON_RUN_AS_NODE
Set WshEnv = WshShell.Environment("Process")
WshEnv.Remove("ELECTRON_RUN_AS_NODE")

' Check prerequisites
Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists("frontend\dist\index.html") Then
    MsgBox "Frontend not built. Run: cd frontend && npx vite build", vbCritical, "VoiceScribe"
    WScript.Quit 1
End If
If Not fso.FileExists("frontend\node_modules\electron\dist\electron.exe") Then
    MsgBox "Electron not installed. Run: cd frontend && npm install", vbCritical, "VoiceScribe"
    WScript.Quit 1
End If
If Not fso.FileExists("backend\.venv\Scripts\python.exe") Then
    MsgBox "Python venv not found.", vbCritical, "VoiceScribe"
    WScript.Quit 1
End If

' Launch Electron silently (no console window)
WshShell.CurrentDirectory = fso.GetAbsolutePathName("frontend")
WshShell.Run """node_modules\electron\dist\electron.exe"" "".""", 0, False
