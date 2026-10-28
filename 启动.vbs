Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
base = fs.GetParentFolderName(WScript.ScriptFullName)
If fs.FileExists(base & "\PeripheralBattery.exe") Then
  shell.Run Chr(34) & base & "\PeripheralBattery.exe" & Chr(34), 0, False
ElseIf fs.FileExists(fs.GetParentFolderName(base) & "\PeripheralBattery.exe") Then
  shell.Run Chr(34) & fs.GetParentFolderName(base) & "\PeripheralBattery.exe" & Chr(34), 0, False
Else
  shell.Run "pythonw " & Chr(34) & base & "\app.py" & Chr(34), 0, False
End If
