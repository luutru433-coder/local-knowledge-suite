# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$RepositoryRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
if (-not (Test-StrictSemVer -Version $Version)) {
    throw "SBOM version must use strict SemVer 2.0.0."
}
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "CycloneDX SBOM is missing: $Path"
}
try {
    $payload = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}
catch {
    throw "CycloneDX SBOM is invalid JSON: $($_.Exception.Message)"
}
if ($payload.bomFormat -cne "CycloneDX") {
    throw "SBOM generator did not emit CycloneDX."
}
if ([string]$payload.specVersion -notmatch '^1\.(?:4|5|6|7)$') {
    throw "SBOM generator emitted an unsupported CycloneDX specVersion."
}
if (@($payload.components).Count -eq 0) {
    throw "SBOM generator emitted no dependency components."
}

if (-not $payload.PSObject.Properties["metadata"]) {
    $payload | Add-Member -MemberType NoteProperty -Name metadata -Value ([pscustomobject]@{})
}
$product = [pscustomobject][ordered]@{
    type = "application"
    name = "local-knowledge-suite"
    version = $Version
}
$payload.metadata | Add-Member -MemberType NoteProperty -Name component -Value $product -Force
$normalized = ($payload | ConvertTo-Json -Depth 100) + "`n"
Assert-ReleaseTextSafe -Text $normalized -Label "CycloneDX SBOM" -SensitiveRoots @($root)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path,
    $normalized,
    $utf8NoBom
)
Write-Output "Normalized CycloneDX SBOM product metadata for local-knowledge-suite $Version."
