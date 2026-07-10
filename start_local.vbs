Option Explicit

Dim shell, fso, scriptDir, batPath, stopPath, secretsPath, q
Dim i, arg, cmd, isCheck, status, generatorUrl, healthUrl, ok

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\start_local.bat"
stopPath = scriptDir & "\stop_local.vbs"
secretsPath = scriptDir & "\secrets.local.txt"
q = Chr(34)

If Not fso.FileExists(batPath) Then
    MsgBox "start_local.bat not found.", vbCritical, "Startup Error"
    WScript.Quit 1
End If

isCheck = False
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "check" Then
        isCheck = True
    End If
End If

If isCheck Then
    status = shell.Run("cmd.exe /c " & q & q & batPath & q & " check" & q, 0, True)
    If status = 0 Then
        WScript.Echo "OK"
    Else
        WScript.Echo "FAIL"
    End If
    WScript.Quit status
End If

generatorUrl = ReadSecretValue(secretsPath, "GENERATOR_URL")
ok = False
If generatorUrl <> "" Then
    healthUrl = Replace(generatorUrl, "/generate-contracts", "/health")
    ok = IsHealthOk(healthUrl)
End If

If ok Then
    MsgBox "Service is healthy. You can run Dify now.", vbInformation, "Dify Local Ready"
    WScript.Quit 0
End If

If fso.FileExists(stopPath) Then
    shell.Run "wscript.exe " & q & stopPath & q, 0, True
End If

cmd = "cmd.exe /c " & q & q & batPath & q
For i = 0 To WScript.Arguments.Count - 1
    arg = WScript.Arguments(i)
    arg = Replace(arg, q, q & q)
    cmd = cmd & " " & q & arg & q
Next
cmd = cmd & q
shell.Run cmd, 0, False

WScript.Sleep 15000
generatorUrl = ReadSecretValue(secretsPath, "GENERATOR_URL")
If generatorUrl <> "" Then
    healthUrl = Replace(generatorUrl, "/generate-contracts", "/health")
    ok = IsHealthOk(healthUrl)
Else
    ok = False
End If

If ok Then
    MsgBox "Restart completed. Service is healthy." & vbCrLf & generatorUrl, vbInformation, "Dify Local Ready"
Else
    MsgBox "Service is still unreachable. Please retry start_local.vbs once more.", vbExclamation, "Dify Local Not Ready"
End If

Function ReadSecretValue(path, key)
    Dim ts, line, prefix
    ReadSecretValue = ""
    If Not fso.FileExists(path) Then Exit Function
    prefix = key & "="
    Set ts = fso.OpenTextFile(path, 1, False)
    Do Until ts.AtEndOfStream
        line = ts.ReadLine
        If Left(line, Len(prefix)) = prefix Then
            ReadSecretValue = Mid(line, Len(prefix) + 1)
            Exit Do
        End If
    Loop
    ts.Close
End Function

Function IsHealthOk(url)
    On Error Resume Next
    Dim http
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 3000, 3000, 3000, 5000
    http.Open "GET", url, False
    http.Send
    IsHealthOk = (Err.Number = 0 And http.Status = 200)
    Set http = Nothing
    Err.Clear
    On Error GoTo 0
End Function
