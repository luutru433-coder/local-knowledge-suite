# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Sbom,

    [Parameter(Mandatory = $true)]
    [string]$PythonReport,

    [Parameter(Mandatory = $true)]
    [string]$NodeReport
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Sbom-Policy.ps1")

foreach ($evidencePath in @($Sbom, $PythonReport, $NodeReport)) {
    if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
        throw "SBOM dependency evidence is missing: $evidencePath"
    }
}
try {
    $sbomPayload = Get-Content -LiteralPath $Sbom -Raw -Encoding UTF8 |
        ConvertFrom-Json
}
catch {
    throw "SBOM dependency evidence is invalid JSON: $($_.Exception.Message)"
}
[object[]]$pythonPayload = @(
    Read-SbomJsonArray `
        -Path $PythonReport `
        -Context "Python dependency report"
)
[object[]]$nodePayload = @(
    Read-SbomJsonArray `
        -Path $NodeReport `
        -Context "Node dependency report"
)
if (-not $sbomPayload.PSObject.Properties["components"]) {
    throw "SBOM dependency evidence has no components array."
}
Assert-SbomDependencyCoverage `
    -Components @($sbomPayload.components) `
    -PythonReport $pythonPayload `
    -NodeReport $nodePayload

Write-Output (
    "SBOM contains every dependency from the exact Python and active Windows " +
    "Node license inventories."
)
