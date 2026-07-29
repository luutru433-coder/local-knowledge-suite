# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$TagName
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
if ([string]::IsNullOrWhiteSpace($TagName)) {
    $TagName = $env:GITHUB_REF_NAME
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
if ([string]::IsNullOrWhiteSpace($TagName) -or -not $TagName.StartsWith("v")) {
    throw "Release provenance requires a v-prefixed tag."
}
$version = $TagName.Substring(1)
if (-not (Test-StrictSemVer -Version $version)) {
    throw "Release tag does not contain strict SemVer 2.0.0: $TagName"
}

function Invoke-GitCapture {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $result = @(& git -C $root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed:`n$($result -join "`n")"
    }
    return @($result | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
}

$tagRef = "refs/tags/$TagName"
$tagType = @(Invoke-GitCapture -Arguments @("cat-file", "-t", $tagRef))
if ($tagType.Count -ne 1 -or $tagType[0] -cne "tag") {
    throw "Release tag must be an annotated tag object, not a lightweight tag: $TagName"
}

$tagCommit = @(Invoke-GitCapture -Arguments @("rev-parse", "--verify", "$tagRef^{commit}"))
if ($tagCommit.Count -ne 1 -or $tagCommit[0] -notmatch '^[0-9a-f]{40,64}$') {
    throw "Annotated release tag does not resolve to one commit: $TagName"
}
$mainCommit = @(Invoke-GitCapture -Arguments @("rev-parse", "--verify", "refs/remotes/origin/main^{commit}"))
if ($mainCommit.Count -ne 1) {
    throw "origin/main is unavailable; fetch it before provenance validation."
}

if ($tagCommit[0] -cne $mainCommit[0]) {
    throw (
        "Tagged commit must exactly match the current origin/main head. " +
        "Tag: $($tagCommit[0]); origin/main: $($mainCommit[0])."
    )
}
if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_SHA)) {
    $eventSha = $env:GITHUB_SHA.Trim()
    if ($eventSha -notmatch '^[0-9a-fA-F]{40,64}$') {
        throw "GitHub event SHA is not a full Git object ID."
    }
    try {
        $eventCommit = @(
            Invoke-GitCapture -Arguments @(
                "rev-parse",
                "--verify",
                "$eventSha^{commit}"
            )
        )
    }
    catch {
        throw "GitHub event SHA does not resolve to a commit."
    }
    if ($eventCommit.Count -ne 1 -or
        $eventCommit[0] -notmatch '^[0-9a-f]{40,64}$') {
        throw "GitHub event SHA does not resolve to one commit."
    }
    if ($tagCommit[0] -cne $eventCommit[0]) {
        throw "GitHub event SHA does not match the annotated tag target."
    }
}

Write-Output (
    "Release provenance passed: annotated $TagName exactly matches " +
    "origin/main at $($tagCommit[0])."
)
