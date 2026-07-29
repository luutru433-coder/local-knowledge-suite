# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$provenanceScript = Join-Path $PSScriptRoot "Test-ReleaseProvenance.ps1"
if (-not (Test-Path -LiteralPath $provenanceScript -PathType Leaf)) {
    throw "Release provenance script is missing: $provenanceScript"
}
Get-Command "git" -CommandType Application -ErrorAction Stop | Out-Null

$tempBase = (
    Resolve-Path -LiteralPath ([System.IO.Path]::GetTempPath()) -ErrorAction Stop
).Path.TrimEnd("\", "/")
$testLeaf = (
    "local-knowledge-release-provenance-selftest-" +
    [Guid]::NewGuid().ToString("N")
)
$testRoot = [System.IO.Path]::GetFullPath((Join-Path $tempBase $testLeaf))
$testRootCreated = $false

function Assert-SafeTestRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $expectedPrefix = $tempBase + [System.IO.Path]::DirectorySeparatorChar
    $leaf = [System.IO.Path]::GetFileName($fullPath)
    if (-not $fullPath.StartsWith(
            $expectedPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        $leaf -cne $testLeaf -or
        $leaf -notmatch '^local-knowledge-release-provenance-selftest-[0-9a-f]{32}$') {
        throw "Refusing to use an unvalidated provenance self-test directory: $fullPath"
    }
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $exitCode = 0
    try {
        $ErrorActionPreference = "Continue"
        $result = @(& git -C $Repository @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw (
            "git $($Arguments -join ' ') failed in ${Repository}:`n" +
            ($result -join "`n")
        )
    }
    return @(
        $result |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ }
    )
}

function Get-GitCommit {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Revision
    )

    $commits = @(
        Invoke-Git -Repository $Repository -Arguments @(
            "rev-parse",
            "--verify",
            "$Revision^{commit}"
        )
    )
    if ($commits.Count -ne 1 -or $commits[0] -notmatch '^[0-9a-f]{40,64}$') {
        throw "Fixture revision did not resolve to one commit: $Revision"
    }
    return $commits[0]
}

function Invoke-ProvenanceWithSha {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$TagName,
        [AllowNull()][string]$GitHubSha
    )

    $originalSha = [Environment]::GetEnvironmentVariable(
        "GITHUB_SHA",
        [EnvironmentVariableTarget]::Process
    )
    try {
        [Environment]::SetEnvironmentVariable(
            "GITHUB_SHA",
            $GitHubSha,
            [EnvironmentVariableTarget]::Process
        )
        return @(
            & $provenanceScript `
                -RepositoryRoot $Repository `
                -TagName $TagName
        )
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            "GITHUB_SHA",
            $originalSha,
            [EnvironmentVariableTarget]::Process
        )
    }
}

function Assert-ProvenanceRejected {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$TagName,
        [Parameter(Mandatory = $true)][string]$GitHubSha,
        [Parameter(Mandatory = $true)][string]$ExpectedMessage,
        [Parameter(Mandatory = $true)][string]$CaseName
    )

    $failure = $null
    try {
        Invoke-ProvenanceWithSha `
            -Repository $Repository `
            -TagName $TagName `
            -GitHubSha $GitHubSha | Out-Null
    }
    catch {
        $failure = $_.Exception
    }
    if ($null -eq $failure) {
        throw "Provenance self-test expected rejection: $CaseName"
    }
    if ($failure.Message.IndexOf(
            $ExpectedMessage,
            [System.StringComparison]::Ordinal
        ) -lt 0) {
        throw (
            "Provenance self-test rejected '$CaseName' for the wrong reason. " +
            "Expected '$ExpectedMessage'; received '$($failure.Message)'."
        )
    }
    Write-Output "PASS: $CaseName"
}

function Assert-ProvenanceAccepted {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$TagName,
        [Parameter(Mandatory = $true)][string]$GitHubSha,
        [Parameter(Mandatory = $true)][string]$CaseName
    )

    $output = @(
        Invoke-ProvenanceWithSha `
            -Repository $Repository `
            -TagName $TagName `
            -GitHubSha $GitHubSha
    )
    if (($output -join "`n").IndexOf(
            "Release provenance passed:",
            [System.StringComparison]::Ordinal
        ) -lt 0) {
        throw "Provenance self-test produced no success result: $CaseName"
    }
    Write-Output "PASS: $CaseName"
}

Assert-SafeTestRoot -Path $testRoot
if (Test-Path -LiteralPath $testRoot) {
    throw "Unique provenance self-test directory already exists: $testRoot"
}

try {
    New-Item -ItemType Directory -Path $testRoot -ErrorAction Stop | Out-Null
    $testRootCreated = $true
    $origin = Join-Path $testRoot "origin.git"
    $work = Join-Path $testRoot "work"

    Invoke-Git -Repository $testRoot -Arguments @("init", "--bare", $origin) |
        Out-Null
    Invoke-Git -Repository $testRoot -Arguments @("init", $work) | Out-Null
    Invoke-Git -Repository $work -Arguments @("config", "user.name", "Release Self Test") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @(
        "config",
        "user.email",
        "release-self-test@example.invalid"
    ) | Out-Null
    Invoke-Git -Repository $work -Arguments @("config", "commit.gpgSign", "false") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @("config", "tag.gpgSign", "false") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @("config", "core.autocrlf", "false") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @("checkout", "-b", "main") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @("remote", "add", "origin", $origin) |
        Out-Null

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $fixturePath = Join-Path $work "fixture.txt"
    [System.IO.File]::WriteAllText($fixturePath, "main-one`n", $utf8NoBom)
    Invoke-Git -Repository $work -Arguments @("add", "--", "fixture.txt") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @(
        "commit",
        "--no-gpg-sign",
        "--no-verify",
        "-m",
        "main one"
    ) | Out-Null
    $oldMainCommit = Get-GitCommit -Repository $work -Revision "HEAD"

    [System.IO.File]::WriteAllText($fixturePath, "main-two`n", $utf8NoBom)
    Invoke-Git -Repository $work -Arguments @("add", "--", "fixture.txt") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @(
        "commit",
        "--no-gpg-sign",
        "--no-verify",
        "-m",
        "main two"
    ) | Out-Null
    $currentMainCommit = Get-GitCommit -Repository $work -Revision "HEAD"
    Invoke-Git -Repository $work -Arguments @(
        "push",
        "--no-verify",
        "origin",
        "refs/heads/main:refs/heads/main"
    ) | Out-Null
    Invoke-Git -Repository $work -Arguments @(
        "fetch",
        "--no-tags",
        "origin",
        "+refs/heads/main:refs/remotes/origin/main"
    ) | Out-Null

    Invoke-Git -Repository $work -Arguments @(
        "tag",
        "v1.0.0",
        $currentMainCommit
    ) | Out-Null
    Invoke-Git -Repository $work -Arguments @(
        "tag",
        "-a",
        "-m",
        "old main fixture",
        "v1.0.2",
        $oldMainCommit
    ) | Out-Null
    Invoke-Git -Repository $work -Arguments @(
        "tag",
        "-a",
        "-m",
        "current main fixture",
        "v1.0.3",
        $currentMainCommit
    ) | Out-Null
    $currentTagObjects = @(
        Invoke-Git -Repository $work -Arguments @(
            "rev-parse",
            "--verify",
            "refs/tags/v1.0.3"
        )
    )
    if ($currentTagObjects.Count -ne 1 -or
        $currentTagObjects[0] -notmatch '^[0-9a-f]{40,64}$') {
        throw "Annotated fixture tag did not resolve to one tag object."
    }
    $currentTagObject = $currentTagObjects[0]
    $currentTagTypes = @(
        Invoke-Git -Repository $work -Arguments @(
            "cat-file",
            "-t",
            $currentTagObject
        )
    )
    if ($currentTagTypes.Count -ne 1 -or
        $currentTagTypes[0] -cne "tag" -or
        $currentTagObject -ceq $currentMainCommit) {
        throw "Annotated fixture tag did not create a distinct tag object."
    }

    Invoke-Git -Repository $work -Arguments @(
        "checkout",
        "-b",
        "off-main",
        $currentMainCommit
    ) | Out-Null
    $offMainPath = Join-Path $work "off-main.txt"
    [System.IO.File]::WriteAllText($offMainPath, "off-main`n", $utf8NoBom)
    Invoke-Git -Repository $work -Arguments @("add", "--", "off-main.txt") |
        Out-Null
    Invoke-Git -Repository $work -Arguments @(
        "commit",
        "--no-gpg-sign",
        "--no-verify",
        "-m",
        "off main"
    ) | Out-Null
    $offMainCommit = Get-GitCommit -Repository $work -Revision "HEAD"
    Invoke-Git -Repository $work -Arguments @(
        "tag",
        "-a",
        "-m",
        "off main fixture",
        "v1.0.1",
        $offMainCommit
    ) | Out-Null
    Invoke-Git -Repository $work -Arguments @("checkout", "main") | Out-Null

    Assert-ProvenanceRejected `
        -Repository $work `
        -TagName "v1.0.0" `
        -GitHubSha $currentMainCommit `
        -ExpectedMessage "annotated tag object" `
        -CaseName "lightweight tag is rejected"
    Assert-ProvenanceRejected `
        -Repository $work `
        -TagName "v1.0.1" `
        -GitHubSha $currentMainCommit `
        -ExpectedMessage "exactly match the current origin/main head" `
        -CaseName "off-main annotated tag is rejected"
    Assert-ProvenanceRejected `
        -Repository $work `
        -TagName "v1.0.2" `
        -GitHubSha $oldMainCommit `
        -ExpectedMessage "exactly match the current origin/main head" `
        -CaseName "old main ancestor annotated tag is rejected"
    Assert-ProvenanceAccepted `
        -Repository $work `
        -TagName "v1.0.3" `
        -GitHubSha $currentMainCommit `
        -CaseName "current origin/main annotated tag is accepted"
    Assert-ProvenanceAccepted `
        -Repository $work `
        -TagName "v1.0.3" `
        -GitHubSha $currentTagObject `
        -CaseName "annotated tag-object GitHub SHA is peeled and accepted"
    Assert-ProvenanceRejected `
        -Repository $work `
        -TagName "v1.0.3" `
        -GitHubSha $oldMainCommit `
        -ExpectedMessage "GitHub event SHA does not match" `
        -CaseName "mismatched GitHub commit SHA is rejected"
}
finally {
    if ($testRootCreated) {
        Assert-SafeTestRoot -Path $testRoot
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}

Write-Output (
    "Release provenance self-test passed lightweight, off-main, old-main, " +
    "exact-current-main, annotated tag-object SHA, and GitHub commit mismatch cases."
)
