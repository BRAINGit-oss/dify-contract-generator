Option Explicit

Dim svc, procs, p, cmd, stoppedUvicorn, stoppedCloudflared
Set svc = GetObject("winmgmts:\\.\root\cimv2")

stoppedUvicorn = 0
stoppedCloudflared = 0

Set procs = svc.ExecQuery("Select * from Win32_Process")
For Each p In procs
    On Error Resume Next
    cmd = LCase(p.CommandLine & "")
    On Error GoTo 0

    If InStr(cmd, "uvicorn app:app") > 0 And InStr(cmd, "--port 19000") > 0 Then
        p.Terminate
        stoppedUvicorn = stoppedUvicorn + 1
    End If

    If InStr(cmd, "cloudflared") > 0 And InStr(cmd, "tunnel") > 0 And InStr(cmd, "127.0.0.1:19000") > 0 Then
        p.Terminate
        stoppedCloudflared = stoppedCloudflared + 1
    End If
Next

MsgBox "Stopped uvicorn: " & stoppedUvicorn & vbCrLf & "Stopped cloudflared: " & stoppedCloudflared, vbInformation, "Local Service Stop"
