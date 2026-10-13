# Starts Bookings Assistant automatically, in the background (no window), with Windows Task Scheduler.
#
#   install_autostart.ps1              start when you sign in to Windows (no password needed)
#   install_autostart.ps1 -AtStartup   start when the computer starts, before anyone signs in
#                                      (Windows asks for your account password once, to store it with the task)
#   install_autostart.ps1 -Remove      stop starting automatically
#
# The app runs as your Windows account, because the Claude API key and the server password are kept in
# your Credential Manager. It restarts by itself if it stops. Output: data\app.log. Open http://localhost:8501.
param([switch]$AtStartup, [switch]$Remove)
$ErrorActionPreference = "Stop"
$TaskName = "Bookings Assistant"
$App = $PSScriptRoot
$Pythonw = Join-Path $App ".venv\Scripts\pythonw.exe"
$User = "$env:USERDOMAIN\$env:USERNAME"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Bookings Assistant no longer starts automatically (and the background copy was stopped)."
    } else {
        Write-Host "Bookings Assistant was not set to start automatically."
    }
    exit 0
}
if (-not (Test-Path $Pythonw)) { throw "The app is not installed yet. Run setup.bat first." }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $TaskName }

$action = New-ScheduledTaskAction -Execute $Pythonw -Argument "`"$App\start_server.py`"" -WorkingDirectory $App
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
if ($AtStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $cred = Get-Credential -UserName $User -Message "Your Windows password for $User, so the app can start before anyone signs in"
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings `
        -Description "Bookings Assistant (http://localhost:8501), started when the computer starts."
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -User $cred.UserName `
        -Password $cred.GetNetworkCredential().Password -Force | Out-Null
    $when = "when the computer starts"
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "Bookings Assistant (http://localhost:8501), started when $User signs in."
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    $when = "when $User signs in to Windows"
}

# Stop a copy started from the desktop shortcut, then start the background one now.
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*streamlit*run*app.py*" -or $_.CommandLine -like "*run_app.bat*" -or
                                               $_.CommandLine -like "*start_server.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-ScheduledTask -TaskName $TaskName
$ready = $false
foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue) { $ready = $true; break }
}
Write-Host "Bookings Assistant now starts automatically $when, in the background."
if ($ready) { Write-Host "It is running now: http://localhost:8501" } else { Write-Host "Starting... see data\app.log if it doesn't open at http://localhost:8501" }
