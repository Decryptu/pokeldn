param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("host", "join")]
    [string]$Role,

    [Parameter(Mandatory = $true)]
    [string]$RadioPort,

    [Parameter(Mandatory = $true)]
    [string]$LanAddress,

    [int]$Port = 24873,
    [int]$Channel = 1,
    [string]$BridgeName,
    [string]$ConfigPath,
    [string]$LocalConfigPath,
    [string]$KeysPath,
    [switch]$NoLocalConfig,
    [switch]$VerboseOutput,
    [ValidateSet("link_player", "trainer_card", "party_0", "party_1", "party_2", "mail", "ribbons")]
    [string]$HoldPhase,
    [string]$ReleaseFile
)

$ErrorActionPreference = "Stop"
$sourceRoot = Join-Path $PSScriptRoot "source"
$python = Join-Path $sourceRoot ".venv\Scripts\python.exe"
$entry = Join-Path $sourceRoot "bin\frlg_remote_trade.py"
if (-not (Test-Path -LiteralPath $python)) { throw "Run .\setup.ps1 first." }
if ([string]::IsNullOrWhiteSpace($RadioPort)) { throw "Specify the local ESP32 serial port, such as COM5." }
if (($HoldPhase -and -not $ReleaseFile) -or ($ReleaseFile -and -not $HoldPhase)) {
    throw "-HoldPhase and -ReleaseFile must be supplied together."
}
if ($ReleaseFile) { $ReleaseFile = [System.IO.Path]::GetFullPath($ReleaseFile) }
if ($HoldPhase -and (Test-Path -LiteralPath $ReleaseFile)) {
    throw "The phase-gate release file already exists. Choose a fresh local path."
}
if ($NoLocalConfig -and $LocalConfigPath) {
    throw "-NoLocalConfig and -LocalConfigPath cannot be combined."
}

$p0Arguments = @($entry, $Role)
if ($Role -eq "host") {
    $p0Arguments += @("--listen", $LanAddress)
}
else {
    $p0Arguments += @("--connect", $LanAddress)
}
$p0Arguments += @("--port", "$Port", "--channel", "$Channel")
if ($BridgeName) { $p0Arguments += @("--bridge-name", $BridgeName) }
if ($ConfigPath) { $p0Arguments += @("--config", $ConfigPath) }
if ($LocalConfigPath) { $p0Arguments += @("--local-config", $LocalConfigPath) }
if ($NoLocalConfig) { $p0Arguments += "--no-local-config" }
if ($KeysPath) { $p0Arguments += @("--keys", $KeysPath) }
if ($VerboseOutput) { $p0Arguments += "--verbose" }
if ($HoldPhase) {
    $p0Arguments += @("--p0-test-hold-phase", $HoldPhase, "--p0-test-release-file", $ReleaseFile)
    Write-Host "P0 test gate: $HoldPhase will be held until this PC creates: $ReleaseFile"
}

$previousRadio = $env:POKELDN_RADIO
$previousData = $env:POKELDN_DATA
try {
    $radioSpec = if ($RadioPort.StartsWith("esp32:")) { $RadioPort } else { "esp32:$RadioPort" }
    $env:POKELDN_RADIO = $radioSpec
    Push-Location $sourceRoot
    try {
        & $python @p0Arguments
        $p0ExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($null -eq $previousRadio) { Remove-Item Env:POKELDN_RADIO -ErrorAction SilentlyContinue }
    else { $env:POKELDN_RADIO = $previousRadio }
    if ($null -eq $previousData) { Remove-Item Env:POKELDN_DATA -ErrorAction SilentlyContinue }
    else { $env:POKELDN_DATA = $previousData }
}

exit $p0ExitCode
