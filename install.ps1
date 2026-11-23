# Install (or update) the toolkit on Windows. Nothing to install first: no Miniforge or conda, no admin
# rights. Double-click install-windows.bat, or in PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File install.ps1 bats          (or: birds, images, "birds bats", all)
#
# It gets uv (a small program that fetches Python and packages), which gets Python 3.11, and puts
# everything in %LOCALAPPDATA%\ceh-biomonitoring (or $env:CEHBIO_HOME). The `cehbio` command then works in
# any new terminal. R users can do the same from R with cehbio::cehbio_install(): it uses the same folder.
param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Pipelines)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Known = "birds", "bats", "images", "validation", "reports", "all"
$Pipelines = @($Pipelines | ForEach-Object { $_ -split "[ ,]+" } | Where-Object { $_ })
foreach ($p in $Pipelines) { if ($Known -notcontains $p) { throw "Unknown pipeline '$p'. Choose from: $($Known -join ', ')" } }
$Extras = (@("reports") + $Pipelines | Select-Object -Unique) -join ","

$Home_ = if ($env:CEHBIO_HOME) { $env:CEHBIO_HOME } else { Join-Path $env:LOCALAPPDATA "ceh-biomonitoring" }
New-Item -ItemType Directory -Force (Join-Path $Home_ "uv") | Out-Null
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Home_ "python"
$env:UV_NO_MODIFY_PATH = "1"
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:UV_NATIVE_TLS = "1"                       # Windows' own certificates: works behind organisation networks

$Uv = Join-Path $Home_ "uv\uv.exe"
if (-not (Test-Path $Uv)) {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { $Uv = $found.Source }
    else {
        Write-Host "Getting uv (once) ..."
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
        $zip = Join-Path $env:TEMP "cehbio-uv.zip"
        $un = Join-Path $env:TEMP ("cehbio-uv-" + [guid]::NewGuid())
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
        Expand-Archive $zip $un -Force
        Copy-Item (Get-ChildItem $un -Recurse -Filter uv.exe | Select-Object -First 1).FullName $Uv
        Remove-Item $zip, $un -Recurse -Force
    }
}
& $Uv --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "This computer won't run uv ($Uv). If programs in your user folder are blocked, ask IT to allow it." }

$Env_ = Join-Path $Home_ "env"
$Py = Join-Path $Env_ "Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Making the toolkit's Python environment (once) ..."
    & $Uv venv --seed --python 3.11 $Env_
    if ($LASTEXITCODE -ne 0) { throw "The Python environment wasn't made: see the messages above." }
}

# from this folder if it's a copy of the repository, otherwise the newest on GitHub
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = @("ceh-biomonitoring[$Extras] @ https://github.com/NERC-CEH/ceh-biomonitoring/archive/refs/heads/main.zip")
if ($Here -and (Test-Path (Join-Path $Here "pyproject.toml"))) { $Source = @("$Here[$Extras]") }      # a copy, so the downloaded folder can be deleted afterwards
Write-Host "Installing: $Extras (the first time takes a while: the models' packages are large)"
& $Uv pip install --python $Py --upgrade @Source
if ($LASTEXITCODE -ne 0) { throw "The install didn't finish: see the messages above, then run it again." }
& $Py -m ceh_biomonitoring.reporting.getquarto | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "(Quarto, for Word and PDF reports, will be fetched when first needed)" }

# the `cehbio` command, in your own PATH (no admin rights needed)
if (-not $env:CEHBIO_NO_COMMAND) {
    $Bin = Join-Path $env:USERPROFILE ".local\bin"
    New-Item -ItemType Directory -Force $Bin | Out-Null
    Set-Content -Path (Join-Path $Bin "cehbio.cmd") -Encoding ascii -Value "@echo off`r`n`"$Py`" -m ceh_biomonitoring %*"
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $UserPath) { $UserPath = "" }
    if (($UserPath -split ";") -notcontains $Bin) {
        [Environment]::SetEnvironmentVariable("Path", ($UserPath.TrimEnd(";") + ";" + $Bin).TrimStart(";"), "User")
    }
}

Write-Host ""
& $Py -m ceh_biomonitoring.cli pipelines
Write-Host "Done. Open a NEW terminal (e.g. Windows PowerShell) and try:  cehbio check"
