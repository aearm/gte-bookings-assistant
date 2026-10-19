<# : Windows part, hidden from PowerShell
@echo off
rem Bookings Assistant installer - double-click it. Nothing to answer, no admin rights.
rem Downloaded on its own: it fetches the latest version from GitHub into
rem "%LOCALAPPDATA%\Programs\Bookings Assistant". In an app folder (a release zip, unzipped, or a clone):
rem it sets up that folder. Either way it installs everything the app needs (install\setup_windows.ps1),
rem starts it with Windows and opens it in the browser. Run it again at any time: an installation older than
rem the latest release is brought up to it first (settings, dashboards and data kept), then repaired.
rem Options: -NoAutostart, -NoStart, -Classic.
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
if ($env:BA_TASK) { $setup.TaskName = $env:BA_TASK }
if ($env:BA_PORT) { $setup.Port = [int]$env:BA_PORT }

# the setup script of an app folder (in install\ since 2.0.1, before that next to the app)
function Find-Setup($folder) {
    foreach ($rel in 'install\setup_windows.ps1', 'setup_windows.ps1') {
        $path = Join-Path $folder $rel
        if (Test-Path $path) { return $path }
    }
}

function Read-Version($folder) {
    try { return [version]((Get-Content (Join-Path $folder 'VERSION') -Raw).Trim()) } catch { return [version]'0.0' }
}

# the latest release on GitHub: its version and its install package
function Get-Release {
    Write-Host 'Looking for the latest version on GitHub...'
    $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ 'User-Agent' = 'bookings-assistant-installer' }
    $asset = $release.assets | Where-Object { $_.name -like 'bookings-assistant-*.zip' } | Select-Object -First 1
    if (-not $asset) { throw "The latest version ($($release.tag_name)) has no install package." }
    return @{ Version = [version]$release.tag_name.TrimStart('v'); Asset = $asset }
}

# the package (BA_ZIP, else the release downloaded) unpacked next to the target - same drive, so it can be
# moved there: returns its app folder
function Get-Package($latest) {
    if ($env:BA_ZIP) {
        $zip = $env:BA_ZIP
    } else {
        $zip = Join-Path $env:TEMP $latest.Asset.name
        Write-Host "Downloading $($latest.Asset.name) ($([math]::Round($latest.Asset.size / 1MB, 1)) MB)..."
        Invoke-WebRequest $latest.Asset.browser_download_url -OutFile $zip -UseBasicParsing
    }
    $parent = Split-Path $Target
    New-Item -ItemType Directory -Force $parent | Out-Null
    $unpacked = Join-Path $parent '.bookings-assistant-unpacking'
    Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'Unpacking...'
    Expand-Archive $zip -DestinationPath $unpacked
    if (-not $env:BA_ZIP) { Remove-Item $zip -Force }
    $root = Get-ChildItem $unpacked -Directory | Where-Object { Find-Setup $_.FullName } | Select-Object -First 1
    if (-not $root) { throw 'The package holds no app (its setup script is missing).' }
    return $root.FullName
}

# the app running from this folder (its task, and every process it started), so its files can be replaced
function Stop-App($folder) {
    try { $task = (Get-Content (Join-Path $folder 'data\autostart.json') -Raw | ConvertFrom-Json).task } catch { $task = $null }
    if ($task) { Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue }
    $all = @(Get-CimInstance Win32_Process)
    $ids = New-Object System.Collections.Generic.HashSet[int]
    foreach ($p in $all) {
        if ($p.CommandLine -and $p.CommandLine -like "*$folder*" -and
            $p.CommandLine -match 'start_api\.py|start_server\.py|streamlit|run_app\.bat') { [void]$ids.Add([int]$p.ProcessId) }
    }
    do {
        $added = 0
        foreach ($p in $all) { if ($ids.Contains([int]$p.ParentProcessId) -and $ids.Add([int]$p.ProcessId)) { $added++ } }
    } while ($added -gt 0)
    foreach ($id in $ids) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    if ($ids.Count) { Start-Sleep -Seconds 2 }
}

# the new version's code put in place by its own updater (updates.py: what the Settings page does), which keeps
# settings, keys, dashboards, the data layer and data, saves the old code in data\backup and puts it back if
# a step fails
function Update-App($root, $version) {
    $python = Join-Path $Target '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'its Python environment (.venv) is missing' }
    Stop-App $Target
    $code = "import importlib.util, pathlib, sys; spec = importlib.util.spec_from_file_location('ba_updates', sys.argv[1]); " +
            "u = importlib.util.module_from_spec(spec); sys.modules['ba_updates'] = u; spec.loader.exec_module(u); " +
            "u.BASE = pathlib.Path(sys.argv[2]); u.apply(pathlib.Path(sys.argv[3]), sys.argv[4])"
    & $python -I -c $code (Join-Path $root 'updates.py') $Target $root "$version"
    if ($LASTEXITCODE -ne 0) { throw 'see the messages above; the installed version was put back' }
}

Write-Host 'Bookings Assistant - installer' -ForegroundColor White
try {
    if (Find-Setup $Target) {
        $installed = Read-Version $Target
        if (Test-Path (Join-Path $Target '.git')) {
            Write-Host "A developer copy in $Target (it is updated with git pull) - setting it up again and starting it."
        } else {
            $latest = $null
            if (-not $env:BA_ZIP) {
                try { $latest = Get-Release } catch { Write-Warning "GitHub could not be reached ($_)." }
            }
            if ($env:BA_ZIP -or ($latest -and $latest.Version -gt $installed)) {
                $root = Get-Package $latest
                $newest = Read-Version $root
                if ($newest -gt $installed) {
                    Write-Host "Updating $Target from version $installed to $newest (settings, dashboards and data are kept)..."
                    try {
                        Update-App $root $newest
                        Write-Host "Updated to version $newest"
                    } catch {
                        Write-Host "Updating stopped: $_" -ForegroundColor Yellow
                    }
                }
                Remove-Item (Split-Path $root -Parent) -Recurse -Force -ErrorAction SilentlyContinue
            }
            Write-Host "Version $(Read-Version $Target) is in $Target - setting it up and starting it."
        }
    } else {
        if (Test-Path $Target) { throw "The folder $Target exists but holds no Bookings Assistant. Move it away, then run this again." }
        $latest = if ($env:BA_ZIP) { $null } else { Get-Release }
        $root = Get-Package $latest
        Move-Item $root $Target
        Remove-Item (Split-Path $root -Parent) -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Installed version $(Read-Version $Target) in $Target"
    }
} catch {
    Write-Host "`nInstalling stopped: $_" -ForegroundColor Red
    Write-Host 'Check the internet connection, then double-click the installer again.'
    exit 1
}
& (Find-Setup $Target) @setup
exit $LASTEXITCODE
