$ErrorActionPreference = "Stop"
$sumPath = Join-Path $PSScriptRoot "firmware\SHA256SUMS"
if (-not (Test-Path -LiteralPath $sumPath)) { throw "Firmware SHA256SUMS is missing." }

foreach ($line in Get-Content -LiteralPath $sumPath) {
    if ($line -match '^([0-9a-fA-F]{64})\s+(.+)$') {
        $expected = $Matches[1].ToUpperInvariant()
        $name = $Matches[2].Trim()
        $path = Join-Path (Join-Path $PSScriptRoot "firmware") $name
        if (-not (Test-Path -LiteralPath $path)) { throw "Missing firmware release asset: $name" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($actual -ne $expected) { throw "SHA-256 mismatch for $name" }
        Write-Host "$name SHA-256 OK: $actual"
    }
}
