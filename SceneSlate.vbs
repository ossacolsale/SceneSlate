' Double-click on Windows: launches SceneSlate using the .pyw file association.
' Python installed from python.org registers .pyw with pythonw.exe.
Option Explicit
Dim shell, fs, folder, script
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
script = folder & "\scene_slate.pyw"
If Not fs.FileExists(script) Then
    MsgBox "File not found: " & script, vbCritical, "SceneSlate"
    WScript.Quit 1
End If
shell.CurrentDirectory = folder
' 1 = normal GUI window; pythonw's .pyw association creates no CMD console.
shell.Run """" & script & """", 1, False
