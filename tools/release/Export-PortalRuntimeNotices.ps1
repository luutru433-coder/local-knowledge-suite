# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,

    [string]$RepositoryRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
$destination = [System.IO.Path]::GetFullPath($DestinationRoot)
$portalDestination = Join-Path $destination "portal-runtime"
if (Test-Path -LiteralPath $portalDestination) {
    throw "Portal runtime notice destination already exists: $portalDestination"
}

$components = @(
    [ordered]@{
        name = "react"
        version = "19.2.7"
        package_root = "web\node_modules\react"
        license_source = "LICENSE"
        license_file = "react-19.2.7-LICENSE.txt"
        license_sha256 = "da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93"
        embedded_reason = "React production runtime"
    },
    [ordered]@{
        name = "react-dom"
        version = "19.2.7"
        package_root = "web\node_modules\react-dom"
        license_source = "LICENSE"
        license_file = "react-dom-19.2.7-LICENSE.txt"
        license_sha256 = "da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93"
        embedded_reason = "React DOM production runtime"
    },
    [ordered]@{
        name = "scheduler"
        version = "0.27.0"
        package_root = "node_modules\.pnpm\scheduler@0.27.0\node_modules\scheduler"
        license_source = "LICENSE"
        license_file = "scheduler-0.27.0-LICENSE.txt"
        license_sha256 = "da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93"
        embedded_reason = "React scheduler production runtime"
    },
    [ordered]@{
        name = "vite"
        version = "8.1.5"
        package_root = "web\node_modules\vite"
        license_source = "LICENSE.md"
        license_file = "vite-8.1.5-LICENSE.md"
        license_sha256 = "b1d741c26b53de1bbc0d4d7d3365b79888f9fe511527544a8a7b8e24dec43147"
        embedded_reason = "Vite module-preload runtime and bundled build helpers"
    },
    [ordered]@{
        name = "rollup"
        version = "4.62.2"
        package_root = "node_modules\.pnpm\rollup@4.62.2\node_modules\rollup"
        license_source = "LICENSE.md"
        license_file = "rollup-4.62.2-LICENSE.md"
        license_sha256 = "fa1bd040c5bdeefe65b3821cebf474f2733ce65df13089bd151dda1778e62fe8"
        embedded_reason = "Rollup-generated production bundle helpers"
    }
)

$rootPrefix = $root.TrimEnd("\") + "\"
$manifestEntries = New-Object System.Collections.Generic.List[object]
New-Item -ItemType Directory -Path $portalDestination -Force | Out-Null
foreach ($component in $components) {
    $packageRoot = (
        Resolve-Path -LiteralPath (Join-Path $root $component.package_root) -ErrorAction Stop
    ).Path
    if (-not $packageRoot.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Portal notice package escaped the repository: $($component.name)"
    }
    $packageJsonPath = Join-Path $packageRoot "package.json"
    $package = Get-Content -LiteralPath $packageJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$package.name -cne [string]$component.name -or
        [string]$package.version -cne [string]$component.version) {
        throw (
            "Portal notice package identity changed: expected " +
            "$($component.name)@$($component.version), found " +
            "$($package.name)@$($package.version)."
        )
    }
    $licenseSource = Join-Path $packageRoot $component.license_source
    if (-not (Test-Path -LiteralPath $licenseSource -PathType Leaf)) {
        throw "Portal runtime license is missing: $licenseSource"
    }
    $actualHash = (
        Get-FileHash -LiteralPath $licenseSource -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actualHash -cne [string]$component.license_sha256) {
        throw (
            "Portal runtime license changed for $($component.name)@$($component.version). " +
            "Review the exact upstream text before updating its expected hash."
        )
    }
    Copy-Item -LiteralPath $licenseSource -Destination (
        Join-Path $portalDestination $component.license_file
    )
    $manifestEntries.Add([pscustomobject][ordered]@{
        name = [string]$component.name
        version = [string]$component.version
        license = [string]$package.license
        embedded_reason = [string]$component.embedded_reason
        file = [string]$component.license_file
        sha256 = $actualHash
    })
}

$manifest = [pscustomobject][ordered]@{
    schema_version = 1
    scope = "third-party runtime code embedded in the shipped portal bundle"
    components = @($manifestEntries | ForEach-Object { $_ })
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    (Join-Path $portalDestination "MANIFEST.json"),
    (($manifest | ConvertTo-Json -Depth 8 -Compress) + "`n"),
    $utf8NoBom
)
Write-Output "Exported exact portal runtime notices to $portalDestination"
