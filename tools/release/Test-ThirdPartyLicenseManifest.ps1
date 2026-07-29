# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ThirdPartyRoot,

    [string]$ManifestPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $PSScriptRoot "third-party-license-manifest.json"
}

function Assert-ExactJsonFields {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Object -isnot [pscustomobject]) {
        throw "$Label must be a JSON object."
    }
    $actual = @(
        $Object.PSObject.Properties |
            ForEach-Object { [string]$_.Name }
    )
    Assert-ExactOrdinalSet `
        -Actual $actual `
        -Expected $Expected `
        -Context "$Label fields"
}

function Assert-NoCaseCollision {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$ExistingPaths,
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($existing in $ExistingPaths) {
        if ([System.StringComparer]::OrdinalIgnoreCase.Equals(
            $existing,
            $Candidate
        )) {
            if ($existing -ceq $Candidate) {
                throw "$Label contains duplicate path: $Candidate"
            }
            throw (
                "$Label contains a case-only path collision: " +
                "$existing and $Candidate"
            )
        }
    }
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Third-party license manifest is missing: $ManifestPath"
}
if (-not (Test-Path -LiteralPath $ThirdPartyRoot -PathType Container)) {
    throw "Third-party license tree is missing: $ThirdPartyRoot"
}

$manifestFullPath = Assert-NoReparseTraversal `
    -Path (Resolve-Path -LiteralPath $ManifestPath -ErrorAction Stop).Path `
    -Label "Third-party license manifest"
$treeFullPath = Assert-NoReparseTraversal `
    -Path (Resolve-Path -LiteralPath $ThirdPartyRoot -ErrorAction Stop).Path `
    -Label "Third-party license tree"

try {
    $manifest = (
        Get-Content -LiteralPath $manifestFullPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
    )
}
catch {
    throw "Third-party license manifest is invalid JSON: $($_.Exception.Message)"
}

Assert-ExactJsonFields `
    -Object $manifest `
    -Expected @("schema_version", "pypdfium2_version", "entries") `
    -Label "Third-party license manifest"
if ($manifest.schema_version -isnot [int] -or
    [int]$manifest.schema_version -ne 1) {
    throw "Third-party license manifest schema_version must be integer 1."
}
if ($manifest.pypdfium2_version -isnot [string] -or
    -not (Test-StrictSemVer -Version $manifest.pypdfium2_version)) {
    throw "Third-party license manifest has an invalid pypdfium2_version."
}
if ($manifest.entries -isnot [System.Array] -or
    @($manifest.entries).Count -eq 0) {
    throw "Third-party license manifest entries must be a non-empty JSON array."
}

$pdfiumPrefix = "pypdfium2-$($manifest.pypdfium2_version)/"
$manifestPaths = New-Object System.Collections.Generic.List[string]
$hashByPath = @{}
$previousPath = $null
foreach ($entry in @($manifest.entries)) {
    Assert-ExactJsonFields `
        -Object $entry `
        -Expected @("path", "sha256") `
        -Label "Third-party license manifest entry"
    if ($entry.path -isnot [string] -or
        [string]::IsNullOrWhiteSpace($entry.path)) {
        throw "Third-party license manifest entry path must be a non-empty string."
    }
    if ($entry.sha256 -isnot [string] -or
        [string]$entry.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw (
            "Third-party license manifest SHA-256 must be 64 lowercase " +
            "hexadecimal characters: $($entry.path)"
        )
    }

    $relative = [string]$entry.path
    if ($relative.IndexOf("\", [System.StringComparison]::Ordinal) -ge 0 -or
        $relative.StartsWith("/", [System.StringComparison]::Ordinal) -or
        $relative.EndsWith("/", [System.StringComparison]::Ordinal) -or
        @($relative -split "/") -contains "" -or
        @($relative -split "/") -contains "." -or
        @($relative -split "/") -contains "..") {
        throw "Third-party license manifest path is not canonical: $relative"
    }
    if (-not $relative.StartsWith(
        "portal-runtime/",
        [System.StringComparison]::Ordinal
    ) -and
        -not $relative.StartsWith(
            $pdfiumPrefix,
            [System.StringComparison]::Ordinal
        )) {
        throw (
            "Third-party license manifest path is outside the locked " +
            "portal/PDFium namespaces: $relative"
        )
    }
    $forbiddenReason = Get-ForbiddenReleasePathReason -RelativePath $relative
    if ($null -ne $forbiddenReason) {
        throw (
            "Third-party license manifest path is forbidden: " +
            "$relative ($forbiddenReason)"
        )
    }
    if ($null -ne $previousPath -and
        [System.StringComparer]::Ordinal.Compare(
            $previousPath,
            $relative
        ) -ge 0) {
        throw (
            "Third-party license manifest paths must be strictly ordered " +
            "with ordinal comparison: $previousPath then $relative"
        )
    }
    Assert-NoCaseCollision `
        -ExistingPaths @($manifestPaths) `
        -Candidate $relative `
        -Label "Third-party license manifest"
    $manifestPaths.Add($relative)
    $hashByPath[$relative] = [string]$entry.sha256
    $previousPath = $relative
}

$treePaths = New-Object System.Collections.Generic.List[string]
$directories = New-Object System.Collections.Generic.Queue[System.IO.DirectoryInfo]
$directories.Enqueue((Get-Item -LiteralPath $treeFullPath -Force))
$treePrefix = $treeFullPath.TrimEnd("\") + "\"
while ($directories.Count -gt 0) {
    $directory = $directories.Dequeue()
    foreach ($item in Get-ChildItem -LiteralPath $directory.FullName -Force) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Third-party license tree contains a junction or symbolic link: $($item.FullName)"
        }
        if ($item.PSIsContainer) {
            $directories.Enqueue($item)
            continue
        }
        if (-not $item.FullName.StartsWith(
            $treePrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Third-party license file escaped its tree root: $($item.FullName)"
        }
        $relative = $item.FullName.Substring($treePrefix.Length).Replace("\", "/")
        Assert-NoCaseCollision `
            -ExistingPaths @($treePaths) `
            -Candidate $relative `
            -Label "Third-party license tree"
        $treePaths.Add($relative)
    }
}

Assert-ExactOrdinalSet `
    -Actual @($treePaths) `
    -Expected @($manifestPaths) `
    -Context "Third-party license tree"
foreach ($relative in @($manifestPaths)) {
    $path = Join-Path $treeFullPath $relative.Replace("/", "\")
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Third-party license file is missing: $relative"
    }
    $actualHash = (
        Get-FileHash -LiteralPath $path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actualHash -cne [string]$hashByPath[$relative]) {
        throw "Third-party license file SHA-256 changed: $relative"
    }
}

Write-Output (
    "Third-party license manifest verified $($manifestPaths.Count) exact " +
    "files and SHA-256 digests."
)
