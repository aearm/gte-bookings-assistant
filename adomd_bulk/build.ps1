# Builds AdomdBulk.dll (the one-call reader for cube results used by ssas.py) from AdomdBulk.cs,
# with the C# compiler that comes with Windows' .NET Framework 4.x. Nothing to install.
# Run from any folder:  powershell -ExecutionPolicy Bypass -File adomd_bulk\build.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
if (-not (Test-Path $csc)) { throw "The .NET Framework 4 C# compiler (csc.exe) was not found." }

& $csc /nologo /target:library /optimize+ /platform:anycpu /reference:System.Data.dll `
    "/out:$(Join-Path $here 'AdomdBulk.dll')" (Join-Path $here 'AdomdBulk.cs')
if ($LASTEXITCODE -ne 0) { throw "Building AdomdBulk.dll failed." }
Write-Host "Built $(Join-Path $here 'AdomdBulk.dll')"
