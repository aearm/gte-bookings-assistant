<# : Windows part, hidden from PowerShell
@echo off
rem Bookings Assistant installer - double-click it. Nothing to answer, no admin rights.
rem Downloaded on its own: it fetches the latest version from GitHub into
rem "%LOCALAPPDATA%\Programs\Bookings Assistant". In an app folder (a release zip, unzipped, or a clone):
rem it sets up that folder. Either way it installs everything the app needs (install\setup_windows.ps1),
rem starts it with Windows and opens it in the browser. Run it again to repair an installation (new
rem versions come from the app, on its Settings page). Options: -NoAutostart, -NoStart, -Classic.
rem For a second copy (e.g. to test): set BA_DIR, BA_TASK and BA_PORT; BA_ZIP installs a package on disk.
set "BA_SELF=%~f0"
set "BA_ARGS=%*"
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ((Get-Content -LiteralPath $env:BA_SELF -Raw) -replace '(?s)^.*?\n#\x3E', '')"
if errorlevel 1 (
    pause
    exit /b 1
)
echo.
echo This window closes by itself in 20 seconds.
"%SystemRoot%\System32\timeout.exe" /t 20 >nul
exit /b 0
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # much faster downloads in Windows PowerShell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = 'aearm/gte-bookings-assistant'
$Here = Split-Path $env:BA_SELF -Parent
$Target = if ($env:BA_DIR) { $env:BA_DIR }
          elseif (Test-Path (Join-Path $Here 'install\setup_windows.ps1')) { $Here }   # in an app folder: that one
          else { Join-Path $env:LOCALAPPDATA 'Programs\Bookings Assistant' }
$setup = @{}
foreach ($option in "$env:BA_ARGS" -split '\s+') {
    if ($option -in '-NoStart', '-NoAutostart', '-Classic') { $setup[$option.TrimStart('-')] = $true }
}
# the setup script of an app folder (in install\ since 2.0.1, before that next to the app)
function Find-Setup($folder) {
    foreach ($rel in 'install\setup_windows.ps1', 'setup_windows.ps1') {
        $path = Join-Path $folder $rel
        if (Test-Path $path) { return $path }
    }
}
if ($env:BA_TASK) { $setup.TaskName = $env:BA_TASK }
if ($env:BA_PORT) { $setup.Port = [int]$env:BA_PORT }

Write-Host 'Bookings Assistant - installer' -ForegroundColor White
try {
    if (Find-Setup $Target) {
        Write-Host "Already installed in $Target - setting it up again and starting it."
    } else {
        if (Test-Path $Target) { throw "The folder $Target exists but holds no Bookings Assistant. Move it away, then run this again." }
        if ($env:BA_ZIP) {
            $zip = $env:BA_ZIP
        } else {
            Write-Host 'Looking for the latest version on GitHub...'
            $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ 'User-Agent' = 'bookings-assistant-installer' }
            $asset = $release.assets | Where-Object { $_.name -like 'bookings-assistant-*.zip' } | Select-Object -First 1
            if (-not $asset) { throw "The latest version ($($release.tag_name)) has no install package." }
            $zip = Join-Path $env:TEMP $asset.name
            Write-Host "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)..."
            Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
        }
        $parent = Split-Path $Target
        New-Item -ItemType Directory -Force $parent | Out-Null
        $unpacked = Join-Path $parent '.bookings-assistant-unpacking'   # same drive as the target, so it can be moved
        Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host 'Unpacking...'
        Expand-Archive $zip -DestinationPath $unpacked
        $root = Get-ChildItem $unpacked -Directory | Where-Object { Find-Setup $_.FullName } | Select-Object -First 1
        if (-not $root) { throw 'The package holds no app (its setup script is missing).' }
        Move-Item $root.FullName $Target
        Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
        if (-not $env:BA_ZIP) { Remove-Item $zip -Force }
        Write-Host "Installed in $Target"
    }
} catch {
    Write-Host "`nInstalling stopped: $_" -ForegroundColor Red
    Write-Host 'Check the internet connection, then double-click the installer again.'
    exit 1
}
& (Find-Setup $Target) @setup
exit $LASTEXITCODE
