# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")

$temporary = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("local-knowledge-third-party-manifest-" + [Guid]::NewGuid().ToString("N"))
$tree = Join-Path $temporary "THIRD_PARTY_LICENSES"
$manifestPath = Join-Path $temporary "third-party-license-manifest.json"
$verifier = Join-Path $PSScriptRoot "Test-ThirdPartyLicenseManifest.ps1"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$ijgRelative = (
    "pypdfium2-5.12.1/licenses/data/windows_x64/" +
    "BUILD_LICENSES/libjpeg_turbo.ijg"
)

function Write-Utf8Fixture {
    param([string]$Path, [string]$Text)

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Get-FixtureHash {
    param([string]$Path)

    return (
        Get-FileHash -LiteralPath $Path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}

function Write-ManifestFixture {
    param(
        [object[]]$Entries,
        [switch]$ExtraRootField
    )

    $payload = [ordered]@{
        schema_version = 1
        pypdfium2_version = "5.12.1"
        entries = $Entries
    }
    if ($ExtraRootField) {
        $payload["unexpected"] = $true
    }
    [System.IO.File]::WriteAllText(
        $manifestPath,
        (($payload | ConvertTo-Json -Depth 8) + "`n"),
        $utf8NoBom
    )
}

function Assert-VerifierRejects {
    param([string]$ExpectedText)

    $rejected = $false
    try {
        & $verifier `
            -ThirdPartyRoot $tree `
            -ManifestPath $manifestPath |
            Out-Null
    }
    catch {
        $rejected = $true
        if ($_.Exception.Message.IndexOf(
            $ExpectedText,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -lt 0) {
            throw (
                "Third-party manifest verifier rejected for the wrong reason. " +
                "Expected '$ExpectedText'; got '$($_.Exception.Message)'."
            )
        }
    }
    if (-not $rejected) {
        throw (
            "Third-party manifest verifier accepted a fixture that must be " +
            "rejected: $ExpectedText"
        )
    }
}

try {
    New-Item -ItemType Directory -Path $tree -Force | Out-Null
    $portalRelative = "portal-runtime/MANIFEST.json"
    $portalPath = Join-Path $tree $portalRelative.Replace("/", "\")
    $ijgPath = Join-Path $tree $ijgRelative.Replace("/", "\")
    Write-Utf8Fixture -Path $portalPath -Text "{}`n"
    Write-Utf8Fixture -Path $ijgPath -Text "Synthetic IJG license fixture.`n"
    $validEntries = @(
        [ordered]@{
            path = $portalRelative
            sha256 = Get-FixtureHash -Path $portalPath
        },
        [ordered]@{
            path = $ijgRelative
            sha256 = Get-FixtureHash -Path $ijgPath
        }
    )
    Write-ManifestFixture -Entries $validEntries
    & $verifier `
        -ThirdPartyRoot $tree `
        -ManifestPath $manifestPath |
        Out-Null

    if ($null -ne (
        Get-ForbiddenReleasePathReason -RelativePath $ijgRelative
    ) -or
        $null -ne (
            Get-ForbiddenReleasePathReason -RelativePath (
                "THIRD_PARTY_LICENSES/$ijgRelative"
            )
        )) {
        throw "The exact canonical IJG notice path was not allowlisted."
    }
    if ($null -eq (
        Get-ForbiddenReleasePathReason -RelativePath (
            "pypdfium2-5.12.1/licenses/data/windows_x64/" +
            "BUILD_LICENSES/arbitrary.ijg"
        )
    )) {
        throw "An arbitrary IJG path was incorrectly allowlisted."
    }

    $unexpectedPath = Join-Path $tree "portal-runtime\unexpected.txt"
    Write-Utf8Fixture -Path $unexpectedPath -Text "unexpected"
    Assert-VerifierRejects -ExpectedText "exact case-sensitive canonical set"
    Remove-Item -LiteralPath $unexpectedPath -Force

    Write-Utf8Fixture -Path $ijgPath -Text "tampered"
    Assert-VerifierRejects -ExpectedText "SHA-256 changed"
    Write-Utf8Fixture -Path $ijgPath -Text "Synthetic IJG license fixture.`n"

    Write-ManifestFixture -Entries @(
        $validEntries[1],
        $validEntries[0]
    )
    Assert-VerifierRejects -ExpectedText "strictly ordered"

    Write-ManifestFixture -Entries @(
        [ordered]@{
            path = "portal-runtime/MANIFEST.JSON"
            sha256 = $validEntries[0].sha256
        },
        $validEntries[0],
        $validEntries[1]
    )
    Assert-VerifierRejects -ExpectedText "case-only path collision"

    Write-ManifestFixture -Entries $validEntries -ExtraRootField
    Assert-VerifierRejects -ExpectedText "fields"

    Write-ManifestFixture -Entries @(
        [ordered]@{
            path = $portalRelative
            sha256 = $validEntries[0].sha256
            unexpected = $true
        },
        $validEntries[1]
    )
    Assert-VerifierRejects -ExpectedText "fields"

    Write-Output (
        "Third-party license manifest self-test passed exact-tree, hash, " +
        "schema, ordinal-order, case-collision, and narrow IJG-path gates."
    )
}
finally {
    $temporaryFull = [System.IO.Path]::GetFullPath($temporary)
    $tempRoot = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    ).TrimEnd("\") + "\"
    if (-not $temporaryFull.StartsWith(
        $tempRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to clean a self-test path outside the temp directory."
    }
    if (Test-Path -LiteralPath $temporaryFull) {
        Remove-Item -LiteralPath $temporaryFull -Recurse -Force
    }
}
