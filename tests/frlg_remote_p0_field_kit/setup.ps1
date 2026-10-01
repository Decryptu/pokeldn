$ErrorActionPreference = "Stop"

$sourceRoot = Join-Path $PSScriptRoot "source"
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot "requirements.txt"))) {
    throw "The source folder is missing. Extract the complete field-test package first."
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Install Python 3.13 x64 with the Windows Python launcher, then rerun setup.ps1."
}

Push-Location $sourceRoot
try {
    & py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python 3.13 virtual environment." }
    $python = Join-Path $sourceRoot ".venv\Scripts\python.exe"
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Could not update pip." }
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install PokeLDN runtime requirements." }
    & $python -m pip install "pytest==9.1.1" "esptool==5.4.0"
    if ($LASTEXITCODE -ne 0) { throw "Could not install the field-test utilities." }
    Write-Host "Field-test environment is ready at $python"
}
finally {
    Pop-Location
}
