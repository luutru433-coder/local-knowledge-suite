# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$Version = "1.0.0",
    [string]$OutputDirectory,
    [switch]$SkipVerification
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")
. (Join-Path $PSScriptRoot "Deterministic-Zip.ps1")

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
$repositoryCandidate = [System.IO.Path]::GetFullPath($RepositoryRoot)
Assert-NoReparseTraversal `
    -Path $repositoryCandidate `
    -Label "Repository root" |
    Out-Null
$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
$eventShaInput = [string]$env:GITHUB_SHA
$eventRefTypeInput = [string]$env:GITHUB_REF_TYPE
$eventRefNameInput = [string]$env:GITHUB_REF_NAME
$artifactsRoot = [System.IO.Path]::GetFullPath((Join-Path $root "artifacts"))
Assert-NoReparseTraversal `
    -Path $artifactsRoot `
    -Label "Artifacts directory" |
    Out-Null
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = $artifactsRoot
}
$output = [System.IO.Path]::GetFullPath($OutputDirectory)
Assert-NoReparseTraversal `
    -Path $output `
    -Label "Release output directory" |
    Out-Null
$artifactsPrefix = $artifactsRoot.TrimEnd("\") + "\"
if ($output -ne $artifactsRoot -and
    -not $output.StartsWith($artifactsPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must be the repository artifacts directory or one of its children."
}
if (-not (Test-StrictSemVer -Version $Version)) {
    throw "Version is not strict SemVer 2.0.0: $Version"
}
if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME -cne "v$Version") {
    throw "Git tag $($env:GITHUB_REF_NAME) does not match plugin version v$Version."
}

$workingTreeStatus = @(
    & git -C $root status --porcelain=v1 --untracked-files=all
)
if ($LASTEXITCODE -ne 0) {
    throw "git status failed before release packaging."
}
if ($workingTreeStatus.Count -gt 0) {
    throw (
        "Release packaging requires a clean committed worktree so tests and " +
        "the archived HEAD describe the same source:`n" +
        ($workingTreeStatus -join "`n")
    )
}

if (-not $SkipVerification) {
    & (Join-Path $PSScriptRoot "Test-Release.ps1") -RepositoryRoot $root -ExpectedVersion $Version
}

$headOutput = @(& git -C $root rev-parse --verify "HEAD^{commit}")
if ($LASTEXITCODE -ne 0) {
    throw "Release packaging requires one committed HEAD."
}
$headCommit = @(
    $headOutput |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { $_ }
)
if ($headCommit.Count -ne 1 -or $headCommit[0] -notmatch '^[0-9a-f]{40,64}$') {
    throw "Release HEAD did not resolve to exactly one commit."
}
if (-not [string]::IsNullOrWhiteSpace($eventShaInput)) {
    $eventShaInput = $eventShaInput.Trim()
    if ($eventShaInput -notmatch '^[0-9a-fA-F]{40,64}$') {
        throw "GitHub event SHA is not a full Git object ID."
    }
    $eventCommit = @(
        & git -C $root rev-parse --verify "$eventShaInput^{commit}"
    )
    if ($LASTEXITCODE -ne 0 -or
        $eventCommit.Count -ne 1 -or
        $eventCommit[0] -notmatch '^[0-9a-f]{40,64}$') {
        throw "GitHub event SHA does not peel to exactly one commit."
    }
    if ($eventCommit[0] -cne $headCommit[0]) {
        throw "Release HEAD changed after checkout and no longer matches the GitHub event."
    }
}
if ($eventRefTypeInput -ceq "tag") {
    if ([string]::IsNullOrWhiteSpace($eventShaInput) -or
        $eventRefNameInput -cne "v$Version") {
        throw "Tag release context is incomplete or does not match the product version."
    }
    $tagRef = "refs/tags/$eventRefNameInput"
    $tagType = @(& git -C $root cat-file -t $tagRef)
    if ($LASTEXITCODE -ne 0 -or
        $tagType.Count -ne 1 -or
        $tagType[0] -cne "tag") {
        throw "Release packaging requires the local event tag to be annotated."
    }
    $tagCommit = @(& git -C $root rev-parse --verify "$tagRef^{commit}")
    if ($LASTEXITCODE -ne 0 -or
        $tagCommit.Count -ne 1 -or
        $tagCommit[0] -cne $headCommit[0]) {
        throw "Annotated event tag does not target the exact release HEAD."
    }
}

$treeOutput = @(& git -C $root ls-tree -r $headCommit[0])
if ($LASTEXITCODE -ne 0) {
    throw "git ls-tree failed with exit code $LASTEXITCODE."
}
$releaseFiles = New-Object System.Collections.Generic.List[string]
foreach ($entry in $treeOutput) {
    $match = [Regex]::Match(
        [string]$entry,
        '^([0-9]{6}) (blob|commit) ([0-9a-f]{40,64})\t(.+)$'
    )
    if (-not $match.Success) {
        throw "Release tree contains an unsupported or quoted path entry: $entry"
    }
    if ($match.Groups[1].Value -notin @("100644", "100755") -or
        $match.Groups[2].Value -cne "blob") {
        throw "Release tree contains a symlink, submodule, or special entry: $entry"
    }
    $releaseFiles.Add($match.Groups[4].Value.Replace("\", "/"))
}
$releaseFiles = @(
    Get-OrdinalSortedUnique `
        -Values @($releaseFiles) `
        -Context "tracked full-source bundle" `
        -RejectExactDuplicates
)
if ($releaseFiles.Count -eq 0) {
    throw "Release packaging requires committed source files."
}
Assert-ReleasePathsSafe -Paths $releaseFiles -Context "tracked full-source bundle"

foreach ($requiredContractPath in Get-RequiredReleaseContractPaths) {
    if (-not (Test-OrdinalContains `
        -Values $releaseFiles `
        -Value $requiredContractPath)) {
        throw "Full-source release is missing required contract file: $requiredContractPath"
    }
}
if (@($releaseFiles | Where-Object { $_.StartsWith("tests/", [System.StringComparison]::Ordinal) }).Count -eq 0) {
    throw "Full-source release must include the test suite."
}

New-Item -ItemType Directory -Path $output -Force | Out-Null
Assert-NoReparseTraversal `
    -Path $output `
    -Label "Created release output directory" |
    Out-Null
$zipName = "local-knowledge-suite-v$Version.zip"
$zipPath = Join-Path $output $zipName
$licenseZipName = "local-knowledge-suite-v$Version-third-party-licenses.zip"
$licenseZipPath = Join-Path $output $licenseZipName
$noticeCopy = Join-Path $output "THIRD_PARTY_NOTICES.md"
$stage = Join-Path $output "staged-product-v$Version"
$snapshotArchive = Join-Path $output ".source-snapshot-v$Version.zip"
$stagePath = [System.IO.Path]::GetFullPath($stage)
Assert-NoReparseTraversal `
    -Path $stagePath `
    -Label "Release staging directory" |
    Out-Null
if (-not $stagePath.StartsWith($artifactsPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Staging directory escaped the repository artifacts directory."
}
if (Test-Path -LiteralPath $stagePath) {
    Remove-Item -LiteralPath $stagePath -Recurse -Force
}
if (Test-Path -LiteralPath $snapshotArchive) {
    Remove-Item -LiteralPath $snapshotArchive -Force
}

try {
    & git -C $root archive `
        --format=zip `
        "--output=$snapshotArchive" `
        $headCommit[0]
    if ($LASTEXITCODE -ne 0 -or
        -not (Test-Path -LiteralPath $snapshotArchive -PathType Leaf)) {
        throw "git archive failed to materialize the committed release snapshot."
    }
    Expand-Archive -LiteralPath $snapshotArchive -DestinationPath $stagePath
    Assert-NoReparseTraversal `
        -Path $stagePath `
        -Label "Materialized release staging directory" |
        Out-Null
    $snapshotFiles = @(
        Get-OrdinalSortedUnique `
            -Values @(
                Get-ChildItem -LiteralPath $stagePath -Recurse -File |
                    ForEach-Object {
                        $_.FullName.Substring($stagePath.TrimEnd("\").Length + 1).Replace("\", "/")
                    }
            ) `
            -Context "materialized committed release snapshot" `
            -RejectExactDuplicates
    )
    if (($snapshotFiles -join "`n") -cne ($releaseFiles -join "`n")) {
        throw "Committed release snapshot entries differ from the HEAD tree."
    }

    $thirdPartyRoot = Join-Path $stagePath "THIRD_PARTY_LICENSES"
    & (Join-Path $PSScriptRoot "Export-PdfiumNotices.ps1") `
        -RepositoryRoot $root `
        -DestinationRoot $thirdPartyRoot
    & (Join-Path $PSScriptRoot "Export-PortalRuntimeNotices.ps1") `
        -RepositoryRoot $root `
        -DestinationRoot $thirdPartyRoot
    & (Join-Path $PSScriptRoot "Test-ThirdPartyLicenseManifest.ps1") `
        -ThirdPartyRoot $thirdPartyRoot `
        -ManifestPath (
            Join-Path $stagePath "tools\release\third-party-license-manifest.json"
        ) |
        Out-Null

    $stagedFiles = @(
        Get-OrdinalSortedUnique `
            -Values @(
                Get-ChildItem -LiteralPath $stagePath -Recurse -File |
                    ForEach-Object {
                        $_.FullName.Substring($stagePath.TrimEnd("\").Length + 1).Replace("\", "/")
                    }
            ) `
            -Context "staged full-source product" `
            -RejectExactDuplicates
    )
    Assert-ReleasePathsSafe -Paths $stagedFiles -Context "staged full-source product"
    foreach ($relative in $stagedFiles) {
        if (-not (Test-IsReleaseTextPath -Path $relative)) {
            continue
        }
        $text = Get-Content -LiteralPath (Join-Path $stagePath $relative) -Raw -Encoding UTF8
        Assert-ReleaseTextSafe -Text $text -Label "staged:$relative" -SensitiveRoots @($root)
    }

    foreach ($oldPath in @($zipPath, $licenseZipPath, $noticeCopy)) {
        if (Test-Path -LiteralPath $oldPath) {
            Remove-Item -LiteralPath $oldPath -Force
        }
    }
    New-DeterministicZipArchive -SourceDirectory $stagePath -DestinationPath $zipPath
    New-DeterministicZipArchive -SourceDirectory $thirdPartyRoot -DestinationPath $licenseZipPath
    Copy-Item -LiteralPath (
        Join-Path $stagePath "THIRD_PARTY_NOTICES.md"
    ) -Destination $noticeCopy -Force

    Write-Output "Created full-source release bundle: $zipPath"
    Write-Output "Created exact upstream notices: $licenseZipPath"
    Write-Output "Retained shipped-product staging tree for SBOM: $stagePath"
    Write-Output "Copied third-party notices: $noticeCopy"
}
catch {
    if (Test-Path -LiteralPath $stagePath) {
        Remove-Item -LiteralPath $stagePath -Recurse -Force
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $snapshotArchive) {
        Remove-Item -LiteralPath $snapshotArchive -Force
    }
}
