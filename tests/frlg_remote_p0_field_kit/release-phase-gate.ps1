param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $Path) {
    throw "The release file already exists: $Path"
}
$parent = Split-Path -Parent $Path
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
New-Item -ItemType File -Path $Path | Out-Null
Write-Host "Released the P0 phase gate: $Path"
