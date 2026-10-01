param(
    [Parameter(Mandatory = $true)]
    [string]$JournalA,

    [Parameter(Mandatory = $true)]
    [string]$JournalB
)

$ErrorActionPreference = "Stop"
$sourceRoot = Join-Path $PSScriptRoot "source"
$python = Join-Path $sourceRoot ".venv\Scripts\python.exe"
$checker = Join-Path $sourceRoot "tools\frlg\validate_remote_p0_evidence.py"
if (-not (Test-Path -LiteralPath $python)) { throw "Run .\setup.ps1 first." }
Push-Location $sourceRoot
try {
    & $python $checker --a $JournalA --b $JournalB
    $p0ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $p0ExitCode
