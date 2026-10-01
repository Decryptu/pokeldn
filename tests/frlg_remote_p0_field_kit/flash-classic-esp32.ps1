param(
    [Parameter(Mandatory = $true)]
    [string]$RadioPort
)

$ErrorActionPreference = "Stop"
$sourceRoot = Join-Path $PSScriptRoot "source"
$python = Join-Path $sourceRoot ".venv\Scripts\python.exe"
$firmware = Join-Path $PSScriptRoot "firmware\pokeldn-radio.bin"
if (-not (Test-Path -LiteralPath $python)) { throw "Run .\setup.ps1 first." }
if (-not (Test-Path -LiteralPath $firmware)) { throw "The classic ESP32 firmware file is missing." }

& $python -m esptool --chip esp32 -p $RadioPort -b 460800 --before default-reset --after hard-reset write-flash 0x0 $firmware
if ($LASTEXITCODE -ne 0) { throw "Firmware flash failed. Check the board model and serial port." }
