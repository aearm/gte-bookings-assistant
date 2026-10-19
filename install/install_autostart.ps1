# Starts Bookings Assistant automatically, in the background (no window), with Windows Task Scheduler.
#
# From PowerShell in the app folder (install-bookings-assistant.cmd sets it up for you):
#   install\install_autostart.ps1              start when you sign in to Windows (no password needed)
#   install\install_autostart.ps1 -AtStartup   start when the computer starts, before anyone signs in
#                                              (Windows asks for your account password once, to store it with the task)
#   install\install_autostart.ps1 -Remove      stop starting automatically
#   install\install_autostart.ps1 -Classic     the previous app (Streamlit, port 8501) instead of the new one
#
# The app runs as your Windows account, because the Claude API key and the server password are kept in
# your Credential Manager. It restarts by itself if it stops. Output: data\api.log (data\app.log for the
# previous app). Open http://localhost:8600 (8501 for the previous app).
param([switch]$AtStartup, [switch]$Remove, [switch]$Classic,
      [string]$TaskName = "Bookings Assistant",  # another name and port: a second copy (e.g. to test an install)
      [int]$Port = 0)
$ErrorActionPreference = "Stop"
$App = Split-Path $PSScriptRoot -Parent  # the app folder (this file is in its install\)
$Pythonw = Join-Path $App ".venv\Scripts\pythonw.exe"
$User = "$env:USERDOMAIN\$env:USERNAME"

# This folder's running copies of the app (started by the task, the desktop shortcut or install\run_app.bat) with
# every process they started (the cube workers), so nothing keeps the app's files open. Copies of the app
# in other folders are left alone.
function Stop-App {
    $all = @(Get-CimInstance Win32_Process)
    $mine = @($all | Where-Object { $_.CommandLine -and $_.CommandLine -like "*$App*" -and
                                    $_.CommandLine -match "start_api\.py|start_server\.py|streamlit|run_app\.bat" })
    $ids = New-Object System.Collections.Generic.HashSet[int]
    foreach ($p in $mine) { [void]$ids.Add([int]$p.ProcessId) }
    do {  # and their children, grandchildren...
        $added = 0
        foreach ($p in $all) {
            if ($ids.Contains([int]$p.ParentProcessId) -and $ids.Add([int]$p.ProcessId)) { $added++ }
        }
    } while ($added -gt 0)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    foreach ($id in $ids) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
}

$Remembered = Join-Path $App "data\autostart.json"  # which task starts this copy: the updater and the shortcut use it

if ($Remove) {
    Remove-Item $Remembered -Force -ErrorAction SilentlyContinue
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-App
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Bookings Assistant no longer starts automatically (and the background copy was stopped)."
    } else {
        Write-Host "Bookings Assistant was not set to start automatically."
    }
    exit 0
}
if (-not (Test-Path $Pythonw)) { throw "The app is not installed yet. Double-click install-bookings-assistant.cmd first." }

if ($Classic) {
    if (-not $Port) { $Port = 8501 }
    $arguments = "`"$App\start_server.py`""
} else {
    if (-not $Port) {  # API_PORT in .env, else 8600
        $line = if (Test-Path "$App\.env") { Select-String -Path "$App\.env" -Pattern '^\s*API_PORT\s*=\s*(\d+)' | Select-Object -First 1 }
        $Port = if ($line) { [int]$line.Matches[0].Groups[1].Value } else { 8600 }
    }
    $arguments = "`"$App\start_api.py`" --port $Port"
}
$url = "http://localhost:$Port"

Stop-App
$action = New-ScheduledTaskAction -Execute $Pythonw -Argument $arguments -WorkingDirectory $App
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
if ($AtStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $cred = Get-Credential -UserName $User -Message "Your Windows password for $User, so the app can start before anyone signs in"
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings `
        -Description "Bookings Assistant ($url), started when the computer starts. Folder: $App"
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -User $cred.UserName `
        -Password $cred.GetNetworkCredential().Password -Force | Out-Null
    $when = "when the computer starts"
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "Bookings Assistant ($url), started when $User signs in. Folder: $App"
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    $when = "when $User signs in to Windows"
}

New-Item -ItemType Directory -Force (Split-Path $Remembered) | Out-Null
$app = if ($Classic) { "classic" } else { "web" }
[IO.File]::WriteAllText($Remembered, (@{ task = $TaskName; port = $Port; app = $app } | ConvertTo-Json))
Start-ScheduledTask -TaskName $TaskName
$ready = $false
foreach ($i in 1..90) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { $ready = $true; break }
}
Write-Host "Bookings Assistant now starts automatically $when, in the background."
$log = if ($Classic) { "data\app.log" } else { "data\api.log" }
if ($ready) { Write-Host "It is running now: $url" } else { Write-Host "Starting... see $log if it doesn't open at $url" }
