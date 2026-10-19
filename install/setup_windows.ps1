# Windows setup for Bookings Assistant: install-bookings-assistant.cmd (in the app folder) runs it - nothing to
# answer. Options, from PowerShell: install\setup_windows.ps1 -NoAutostart (or -NoStart, -Classic).
# Installs Python 3.13 if needed (for this user only, no admin rights), the app's libraries, ADOMD.NET and
# the web app; creates .env and a desktop shortcut; then starts the app in the background whenever you sign
# in to Windows, starts it now and opens it in the browser.
# Safe to run again at any time: it repairs or updates what is already there.
param(
    [switch]$NoStart,      # don't start the app or open the browser at the end
    [switch]$NoAutostart,  # don't start it with Windows (start it now in the background instead)
    [switch]$Classic,      # the previous app (Streamlit, port 8501) instead of the new one
    [string]$TaskName = "Bookings Assistant",  # another name and port: a second copy (e.g. to test an install)
    [int]$Port = 0
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"   # much faster downloads in Windows PowerShell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$App = Split-Path $PSScriptRoot -Parent  # the app folder (this file is in its install\)
Set-Location $App
# the setup files from before 2.0.1 next to the app (now in install\, setup.bat and autostart.bat gone)
foreach ($old in "setup.bat", "autostart.bat", "setup_windows.ps1", "install_autostart.ps1", "run_app.bat", "setup.sh", "run_app.sh") {
    Remove-Item (Join-Path $App $old) -Force -ErrorAction SilentlyContinue
}

$PythonVersion = "3.13.15"   # tested with this app; pythonnet needs 64-bit Python 3.12 or 3.13
$NodeVersion = "22.23.3"     # only to build the web app in a copy without it (releases include it built)
$NodeHome = Join-Path $env:LOCALAPPDATA "BookingsAssistant\node"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Fail($text) {
    Write-Host "`nSetup stopped: $text" -ForegroundColor Red
    Write-Host "Fix the problem above, then double-click install-bookings-assistant.cmd again."
    exit 1
}

# True if this python.exe is 64-bit Python 3.12 or 3.13 (not the Microsoft Store placeholder).
function Test-GoodPython($exe) {
    if (-not $exe -or -not (Test-Path $exe) -or $exe -like "*\WindowsApps\*") { return $false }
    $out = & $exe -c "import sys, struct; print(sys.version_info[:2] in [(3, 12), (3, 13)] and struct.calcsize('P') == 8)" 2>$null
    return ($out -eq "True")
}

function Find-Python {
    $candidates = @()
    foreach ($v in "3.13", "3.12") {
        try {
            $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0) { $candidates += $exe }
        } catch {}
    }
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                   "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                   "$env:ProgramFiles\Python313\python.exe",
                   "$env:ProgramFiles\Python312\python.exe"
    foreach ($c in (Get-Command python -All -ErrorAction SilentlyContinue)) { $candidates += $c.Source }
    foreach ($c in $candidates) { if (Test-GoodPython $c) { return $c } }
    return $null
}

function Install-Python {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "    Installing with winget..."
        & winget install --id Python.Python.3.13 -e --source winget --scope user --silent `
            --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
        $found = Find-Python
        if ($found) { return $found }
    }
    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
    $installer = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
    Write-Host "    Downloading Python $PythonVersion from python.org (about 28 MB)..."
    try { Invoke-WebRequest $url -OutFile $installer -UseBasicParsing } catch { Fail "Could not download Python: $_" }
    $sig = Get-AuthenticodeSignature $installer
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notlike "*Python Software Foundation*") {
        Remove-Item $installer -Force
        Fail "The downloaded Python installer is not signed by the Python Software Foundation."
    }
    Write-Host "    Installing (takes a minute)..."
    Start-Process $installer -Wait -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_test=0"
    Remove-Item $installer -Force
    return Find-Python
}

# node.exe of Node.js 20 or newer: on the PATH, installed, or the copy this setup downloaded before.
function Find-Node {
    $candidates = @()
    foreach ($c in (Get-Command node -All -ErrorAction SilentlyContinue)) { $candidates += $c.Source }
    $candidates += (Join-Path $NodeHome "node.exe"), "$env:ProgramFiles\nodejs\node.exe"
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) {
            $v = & $c --version 2>$null
            if ($v -match '^v(\d+)\.' -and [int]$Matches[1] -ge 20) { return $c }
        }
    }
    return $null
}

# Node.js for this user only (no admin rights): the official zip from nodejs.org, checked against the
# checksums nodejs.org publishes for it.
function Install-Node {
    $name = "node-v$NodeVersion-win-x64"
    $base = "https://nodejs.org/dist/v$NodeVersion"
    $zip = Join-Path $env:TEMP "$name.zip"
    Write-Host "    Downloading Node.js $NodeVersion from nodejs.org (about 35 MB)..."
    try {
        Invoke-WebRequest "$base/$name.zip" -OutFile $zip -UseBasicParsing
        $sums = [string](Invoke-WebRequest "$base/SHASUMS256.txt" -UseBasicParsing).Content
    } catch { Fail "Could not download Node.js: $_" }
    $expected = ($sums -split "`n" | Where-Object { $_ -match "\s$([regex]::Escape($name)).zip\s*$" } | Select-Object -First 1) -replace '\s.*$', ''
    $actual = (Get-FileHash $zip -Algorithm SHA256).Hash
    if (-not $expected -or $actual -ne $expected.Trim()) {
        Remove-Item $zip -Force
        Fail "The downloaded Node.js does not match the checksum published on nodejs.org."
    }
    $unpacked = Join-Path $env:TEMP "bookings-assistant-node"
    Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $zip -DestinationPath $unpacked -Force
    Remove-Item $NodeHome -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force (Split-Path $NodeHome) | Out-Null
    Move-Item (Join-Path $unpacked $name) $NodeHome
    Remove-Item $zip, $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    return Find-Node
}

# The built web app is missing, or (in a developer copy) older than its sources.
function Test-WebNeedsBuild {
    $index = Join-Path $App "web\dist\index.html"
    if (-not (Test-Path $index)) { return $true }
    if (-not (Test-Path (Join-Path $App ".git"))) { return $false }  # a release: built with it
    $built = (Get-Item $index).LastWriteTime
    $sources = @(Get-ChildItem "web\src" -Recurse -File) + @(Get-Item "web\index.html", "web\package.json", "web\vite.config.ts")
    return [bool]($sources | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1)
}

Write-Host "Bookings Assistant - Windows setup" -ForegroundColor White
Write-Host "Folder: $App"
$steps = 7

# ---------------------------------------------------------------- 1. Python --
Step "1/$steps  Python"
$python = Find-Python
if ($python) {
    Ok "Found $(& $python --version) at $python"
} else {
    Write-Host "    Python 3.12/3.13 (64-bit) not found."
    $python = Install-Python
    if (-not $python) { Fail "Python could not be installed. Install Python 3.13 (64-bit) from https://www.python.org/downloads/windows/ and run install-bookings-assistant.cmd again." }
    Ok "Installed $(& $python --version)"
}

# ---------------------------------------------------------------- 2. libraries --
Step "2/$steps  App libraries (pandas, FastAPI, Claude SDK, ...)"
$venvPython = Join-Path $App ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $App ".venv\Scripts\pythonw.exe"
if ((Test-Path ".venv") -and -not (Test-GoodPython $venvPython)) {
    Write-Host "    The existing .venv is broken or uses another Python version; rebuilding it."
    Remove-Item ".venv" -Recurse -Force
}
if (-not (Test-Path $venvPython)) {
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the Python environment (.venv)." }
}
& $venvPython -m pip install --upgrade pip --quiet --disable-pip-version-check
& $venvPython -m pip install -r requirements.txt --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Installing the libraries failed. Check the internet connection (or proxy settings)." }
Ok "Libraries installed"

# ---------------------------------------------------------------- 3. settings files --
Step "3/$steps  Settings files"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Ok "Created .env" } else { Ok ".env already exists (kept)" }
if (-not (Test-Path "business_notes.md")) { Copy-Item "business_notes.example.md" "business_notes.md"; Ok "Created business_notes.md" }
New-Item -ItemType Directory -Force "data" | Out-Null
# Skip Streamlit's one-time "enter your email" prompt, which would stop the previous app from starting.
$streamlitDir = Join-Path $env:USERPROFILE ".streamlit"
if (-not (Test-Path "$streamlitDir\credentials.toml")) {
    New-Item -ItemType Directory -Force $streamlitDir | Out-Null
    Set-Content "$streamlitDir\credentials.toml" "[general]`nemail = `"`"" -Encoding ascii
}

# ---------------------------------------------------------------- 4. ADOMD.NET --
Step "4/$steps  ADOMD.NET (connector for the live bookings server)"
& $venvPython -c "import ssas; ssas._load_adomd()" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $venvPython get_adomd.py
    if ($LASTEXITCODE -ne 0) { Write-Warning "ADOMD.NET could not be downloaded. The app still works with local data files; see README to install it." }
}
& $venvPython -c "import ssas; ssas._load_adomd(); import pyadomd" 2>$null
if ($LASTEXITCODE -eq 0) { Ok "ADOMD.NET ready" } else { Write-Warning "ADOMD.NET is not working yet (needed only for the live server). See README > Troubleshooting." }

# ---------------------------------------------------------------- 5. web app --
Step "5/$steps  Web app"
if ($Classic) {
    Ok "Not needed for the previous app"
} elseif (-not (Test-WebNeedsBuild)) {
    Ok "Ready (web\dist)"
} else {
    $node = Find-Node
    if ($node) { Ok "Found Node.js $(& $node --version) at $node" } else { $node = Install-Node; Ok "Installed Node.js $NodeVersion" }
    if (-not $node) { Fail "Node.js could not be installed, so the web app can't be built." }
    $env:Path = "$(Split-Path $node);$env:Path"
    $npm = Join-Path (Split-Path $node) "npm.cmd"
    Push-Location web
    Write-Host "    Building (takes a minute)..."
    & $npm ci --no-audit --no-fund --loglevel=error
    if ($LASTEXITCODE -eq 0) {
        $out = & $npm run build 2>&1
        if ($LASTEXITCODE -ne 0) { $out | Select-Object -Last 30 | ForEach-Object { Write-Host "    $_" } }
    }
    $built = $LASTEXITCODE -eq 0
    Pop-Location
    if (-not $built -or -not (Test-Path "web\dist\index.html")) { Fail "Building the web app failed (see the messages above)." }
    Ok "Built (web\dist)"
}

# ---------------------------------------------------------------- 6. shortcut --
Step "6/$steps  Desktop shortcut"
$portArg = if ($Port) { " --port $Port" } else { "" }
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "$TaskName.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
if ($Classic) {
    $shortcut.TargetPath = Join-Path $PSScriptRoot "run_app.bat"
    $shortcut.Arguments = "classic"
} else {  # opens the app in the browser, starting it first if it isn't running
    $shortcut.TargetPath = $venvPythonw
    $shortcut.Arguments = "`"$(Join-Path $App 'start_api.py')`" --open --task `"$TaskName`"$portArg"
}
$shortcut.WorkingDirectory = $App
$shortcut.Description = "Ask questions about bookings data"
$shortcut.Save()
Ok "Created '$TaskName' on the desktop"

# ---------------------------------------------------------------- 7. Claude --
Step "7/$steps  Claude (use the cubes and dashboards from any Claude conversation)"
if ($TaskName -ne "Bookings Assistant") {
    Ok "A second copy ('$TaskName'): not connected to Claude (the main copy is)"
} else {
    $lines = & $venvPython (Join-Path $PSScriptRoot "connect_claude.py") 2>&1
    if ($LASTEXITCODE -eq 0) { $lines | ForEach-Object { Ok $_ } }
    else { Write-Warning "Claude could not be connected (the app works without it): $($lines -join ' ')" }
}

# ---------------------------------------------------------------- start --
$url = "http://localhost:" + $(if ($Port) { $Port } elseif ($Classic) { 8501 } else { 8600 })
if (-not $Classic -and -not $Port -and (Test-Path ".env")) {
    $line = Select-String -Path ".env" -Pattern '^\s*API_PORT\s*=\s*(\d+)' | Select-Object -First 1
    if ($line) { $url = "http://localhost:" + $line.Matches[0].Groups[1].Value }
}
if (-not $NoStart) {
    if ($NoAutostart) {
        Step "Starting the app"
        if ($Classic) { Start-Process (Join-Path $PSScriptRoot "run_app.bat") -ArgumentList "classic" -WorkingDirectory $App }
        else { Start-Process $venvPythonw -ArgumentList "`"$(Join-Path $App 'start_api.py')`" --open --task `"$TaskName`"$portArg" -WorkingDirectory $App }
    } else {
        Step "Starting the app with Windows (in the background)"
        $auto = @{ TaskName = $TaskName; Port = $Port }
        if ($Classic) { $auto.Classic = $true }
        & (Join-Path $PSScriptRoot "install_autostart.ps1") @auto
        if (-not $?) { Fail "The app could not be set to start with Windows." }
        Start-Process $url
    }
}

Write-Host "`nSetup complete: $url" -ForegroundColor Green
Write-Host "In the app: create the admin password, then under Settings enter the Claude API key and the bookings"
Write-Host "server details. The built-in dashboards then show their numbers; every cube on the server is connected"
Write-Host "until you pick some on the Cubes page, where you also build the data layer (once, for questions)."
Write-Host "Later, open the app with the '$TaskName' shortcut on the desktop."
exit 0
