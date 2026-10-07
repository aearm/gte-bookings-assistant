# Windows installer for Bookings Assistant. Double-click setup.bat to run it.
# Installs Python 3.13 if needed (for this user only, no admin rights), the app's libraries and
# ADOMD.NET, creates .env and a desktop shortcut, then starts the app.
# Safe to run again at any time: it repairs or updates what is already there.
param([switch]$NoStart)  # -NoStart: don't offer to start the app at the end

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"   # much faster downloads in Windows PowerShell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Set-Location $PSScriptRoot

$PythonVersion = "3.13.15"   # tested with this app; pythonnet needs 64-bit Python 3.12 or 3.13

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Fail($text) {
    Write-Host "`nSetup stopped: $text" -ForegroundColor Red
    Write-Host "Fix the problem above, then double-click setup.bat again."
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

Write-Host "Bookings Assistant - Windows setup" -ForegroundColor White
Write-Host "Folder: $PSScriptRoot"

# ---------------------------------------------------------------- 1. Python --
Step "1/5  Python"
$python = Find-Python
if ($python) {
    Ok "Found $(& $python --version) at $python"
} else {
    Write-Host "    Python 3.12/3.13 (64-bit) not found."
    $python = Install-Python
    if (-not $python) { Fail "Python could not be installed. Install Python 3.13 (64-bit) from https://www.python.org/downloads/windows/ and run setup.bat again." }
    Ok "Installed $(& $python --version)"
}

# ---------------------------------------------------------------- 2. libraries --
Step "2/5  App libraries (pandas, Streamlit, Claude SDK, ...)"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
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
Step "3/5  Settings files"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Ok "Created .env" } else { Ok ".env already exists (kept)" }
if (-not (Test-Path "business_notes.md")) { Copy-Item "business_notes.example.md" "business_notes.md"; Ok "Created business_notes.md" }
# Skip Streamlit's one-time "enter your email" prompt, which would stop the app from starting.
$streamlitDir = Join-Path $env:USERPROFILE ".streamlit"
if (-not (Test-Path "$streamlitDir\credentials.toml")) {
    New-Item -ItemType Directory -Force $streamlitDir | Out-Null
    Set-Content "$streamlitDir\credentials.toml" "[general]`nemail = `"`"" -Encoding ascii
}

# ---------------------------------------------------------------- 4. ADOMD.NET --
Step "4/5  ADOMD.NET (connector for the live bookings server)"
& $venvPython -c "import ssas; ssas._load_adomd()" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $venvPython get_adomd.py
    if ($LASTEXITCODE -ne 0) { Write-Warning "ADOMD.NET could not be downloaded. The app still works with local data files; see README to install it." }
}
& $venvPython -c "import ssas; ssas._load_adomd(); import pyadomd" 2>$null
if ($LASTEXITCODE -eq 0) { Ok "ADOMD.NET ready" } else { Write-Warning "ADOMD.NET is not working yet (needed only for the live server). See README > Troubleshooting." }

# ---------------------------------------------------------------- 5. shortcut --
Step "5/5  Desktop shortcut"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Bookings Assistant.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $PSScriptRoot "run_app.bat"
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Ask questions about bookings data"
$shortcut.Save()
Ok "Created 'Bookings Assistant' on the desktop"

# ---------------------------------------------------------------- done --
Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Next: start the app, open Settings (in the app's menu), create an admin password,"
Write-Host "then enter the Claude API key and the bookings server details."
Write-Host "Later, start the app with the 'Bookings Assistant' shortcut on the desktop."
if (-not $NoStart) {
    $answer = Read-Host "`nStart the app now? (Y/n)"
    if ($answer -notmatch "^[nN]") { Start-Process (Join-Path $PSScriptRoot "run_app.bat") -WorkingDirectory $PSScriptRoot }
}
