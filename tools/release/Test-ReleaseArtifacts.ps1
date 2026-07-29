# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$Version = "1.0.0",
    [string]$OutputDirectory,
    [switch]$RequireSbom
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")
. (Join-Path $PSScriptRoot "Deterministic-Zip.ps1")
. (Join-Path $PSScriptRoot "Sbom-Policy.ps1")

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
if (-not (Test-StrictSemVer -Version $Version)) {
    throw "Artifact version must use strict SemVer 2.0.0."
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $root "artifacts"
}
$output = (Resolve-Path -LiteralPath $OutputDirectory -ErrorAction Stop).Path
$bundleName = "local-knowledge-suite-v$Version.zip"
$licenseName = "local-knowledge-suite-v$Version-third-party-licenses.zip"
$sbomName = "local-knowledge-suite-v$Version-sbom.cdx.json"
$stageName = "staged-product-v$Version"
$bundle = Join-Path $output $bundleName
$licenses = Join-Path $output $licenseName
$sums = Join-Path $output "SHA256SUMS"
$notices = Join-Path $output "THIRD_PARTY_NOTICES.md"
$stage = Join-Path $output $stageName
$sbom = Join-Path $output $sbomName

function Assert-StagedSourceMatchesHead {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$StageRoot,
        [Parameter(Mandatory = $true)][string[]]$StageFiles
    )

    $head = @(& git -C $RepositoryRoot rev-parse --verify "HEAD^{commit}")
    if ($LASTEXITCODE -ne 0 -or
        $head.Count -ne 1 -or
        $head[0] -notmatch '^[0-9a-f]{40,64}$') {
        throw "Artifact verification requires one committed HEAD."
    }
    $treeOutput = @(& git -C $RepositoryRoot ls-tree -r $head[0])
    if ($LASTEXITCODE -ne 0) {
        throw "Artifact verification could not read the HEAD tree."
    }
    $treePaths = New-Object System.Collections.Generic.List[string]
    foreach ($entry in $treeOutput) {
        $match = [Regex]::Match(
            [string]$entry,
            '^([0-9]{6}) (blob|commit) ([0-9a-f]{40,64})\t(.+)$'
        )
        if (-not $match.Success -or
            $match.Groups[1].Value -notin @("100644", "100755") -or
            $match.Groups[2].Value -cne "blob") {
            throw "HEAD contains an unsupported, quoted, symlink, or submodule entry: $entry"
        }
        $relative = $match.Groups[4].Value.Replace("\", "/")
        if ($relative.StartsWith(
            "THIRD_PARTY_LICENSES/",
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "HEAD must not pre-populate generated THIRD_PARTY_LICENSES."
        }
        $treePaths.Add($relative)
    }
    [string[]]$expectedSourcePaths = @(
        Get-OrdinalSortedUnique `
            -Values @($treePaths) `
            -Context "checked-out HEAD source paths" `
            -RejectExactDuplicates
    )
    [string[]]$actualSourcePaths = @(
        Get-OrdinalSortedUnique `
            -Values @(
                $StageFiles |
                    Where-Object {
                        -not $_.StartsWith(
                            "THIRD_PARTY_LICENSES/",
                            [System.StringComparison]::OrdinalIgnoreCase
                        )
                    }
            ) `
            -Context "staged source paths" `
            -RejectExactDuplicates
    )
    if (($actualSourcePaths -join "`n") -cne ($expectedSourcePaths -join "`n")) {
        throw "Staged source paths do not exactly match the checked-out HEAD tree."
    }

    $tempBase = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    ).TrimEnd("\", "/")
    $verificationRoot = Join-Path $tempBase (
        "local-knowledge-head-verify-" + [Guid]::NewGuid().ToString("N")
    )
    $verificationRoot = [System.IO.Path]::GetFullPath($verificationRoot)
    $tempPrefix = $tempBase + [System.IO.Path]::DirectorySeparatorChar
    if (-not $verificationRoot.StartsWith(
        $tempPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "HEAD verification workspace escaped the temporary directory."
    }
    $snapshotArchive = Join-Path $verificationRoot "head.zip"
    $snapshotRoot = Join-Path $verificationRoot "head"
    try {
        New-Item -ItemType Directory -Path $verificationRoot -ErrorAction Stop |
            Out-Null
        & git -C $RepositoryRoot archive `
            --format=zip `
            "--output=$snapshotArchive" `
            $head[0]
        if ($LASTEXITCODE -ne 0) {
            throw "Could not archive the checked-out HEAD for artifact comparison."
        }
        Expand-Archive -LiteralPath $snapshotArchive -DestinationPath $snapshotRoot
        $snapshotPrefix = $snapshotRoot.TrimEnd("\") + "\"
        [string[]]$snapshotPaths = @(
            Get-OrdinalSortedUnique `
                -Values @(
                    Get-ChildItem -LiteralPath $snapshotRoot -Recurse -File |
                        ForEach-Object {
                            $_.FullName.Substring($snapshotPrefix.Length).Replace("\", "/")
                        }
                ) `
                -Context "archived HEAD snapshot paths" `
                -RejectExactDuplicates
        )
        if (($snapshotPaths -join "`n") -cne ($expectedSourcePaths -join "`n")) {
            throw "Git archive entries do not exactly match the checked-out HEAD tree."
        }
        foreach ($relative in $expectedSourcePaths) {
            $snapshotHash = (
                Get-FileHash -LiteralPath (
                    Join-Path $snapshotRoot $relative
                ) -Algorithm SHA256
            ).Hash
            $stageHash = (
                Get-FileHash -LiteralPath (
                    Join-Path $StageRoot $relative
                ) -Algorithm SHA256
            ).Hash
            if ($snapshotHash -cne $stageHash) {
                throw "Staged source differs from checked-out HEAD: $relative"
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $verificationRoot) {
            Remove-Item -LiteralPath $verificationRoot -Recurse -Force
        }
    }
}

$requiredAssetNames = @(
    $bundleName,
    $licenseName,
    "THIRD_PARTY_NOTICES.md",
    "SHA256SUMS"
)
if ($RequireSbom) {
    $requiredAssetNames += @(
        $sbomName,
        "python-licenses.json",
        "node-licenses.json"
    )
}
foreach ($name in $requiredAssetNames) {
    $path = Join-Path $output $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required release artifact is missing: $path"
    }
}
if (-not (Test-Path -LiteralPath $stage -PathType Container)) {
    throw "Shipped-product staging directory is missing: $stage"
}

$actualAssetNames = @(
    Get-ChildItem -LiteralPath $output -File |
        ForEach-Object { $_.Name }
)
Assert-ExactOrdinalSet `
    -Actual $actualAssetNames `
    -Expected $requiredAssetNames `
    -Context "Top-level release assets"

$expectedHashes = New-Object 'System.Collections.Generic.Dictionary[string,string]' (
    [System.StringComparer]::Ordinal
)
foreach ($line in Get-Content -LiteralPath $sums -Encoding UTF8) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    if ($line -notmatch '^([0-9a-f]{64})\s{2}([^\\/]+)$') {
        throw "SHA256SUMS contains an invalid line: $line"
    }
    if ($expectedHashes.ContainsKey($Matches[2])) {
        throw "SHA256SUMS contains a duplicate asset: $($Matches[2])"
    }
    $expectedHashes[$Matches[2]] = $Matches[1]
}
$publishedNames = @($actualAssetNames | Where-Object { $_ -cne "SHA256SUMS" })
Assert-ExactOrdinalSet `
    -Actual @($expectedHashes.Keys) `
    -Expected $publishedNames `
    -Context "SHA256SUMS coverage"
foreach ($name in $publishedNames) {
    $path = Join-Path $output $name
    $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -cne $expectedHashes[$name]) {
        throw "SHA-256 mismatch for $name."
    }
}

$rootNoticeHash = (Get-FileHash -LiteralPath (Join-Path $root "THIRD_PARTY_NOTICES.md") -Algorithm SHA256).Hash
$artifactNoticeHash = (Get-FileHash -LiteralPath $notices -Algorithm SHA256).Hash
if ($rootNoticeHash -cne $artifactNoticeHash) {
    throw "Published THIRD_PARTY_NOTICES.md is not byte-equivalent to the repository source."
}

$stagePrefix = $stage.TrimEnd("\") + "\"
$stagedFiles = @(
    Get-OrdinalSortedUnique `
        -Values @(
            Get-ChildItem -LiteralPath $stage -Recurse -File |
                ForEach-Object {
                    $_.FullName.Substring($stagePrefix.Length).Replace("\", "/")
                }
        ) `
        -Context "shipped-product staging tree" `
        -RejectExactDuplicates
)
Assert-ReleasePathsSafe -Paths $stagedFiles -Context "shipped-product staging tree"
Assert-StagedSourceMatchesHead `
    -RepositoryRoot $root `
    -StageRoot $stage `
    -StageFiles $stagedFiles
$stagedManifestPath = Join-Path $stage "plugins\local-knowledge-suite\.codex-plugin\plugin.json"
if (-not (Test-Path -LiteralPath $stagedManifestPath -PathType Leaf)) {
    throw "Shipped plugin manifest is missing."
}
$stagedManifest = (
    Get-Content -LiteralPath $stagedManifestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
)
if ([string]$stagedManifest.version -cne $Version) {
    throw "Shipped plugin manifest version does not match the artifact version."
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$sha256 = [Security.Cryptography.SHA256]::Create()
try {
    $mainArchive = [System.IO.Compression.ZipFile]::OpenRead($bundle)
    try {
        $mainEntries = @(
            $mainArchive.Entries |
                Where-Object { -not [string]::IsNullOrEmpty($_.Name) } |
                Sort-Object FullName
        )
        $mainPaths = @(
            Get-OrdinalSortedUnique `
                -Values @(
                    $mainEntries |
                        ForEach-Object { $_.FullName.Replace("\", "/") }
                ) `
                -Context "main release archive entries" `
                -RejectExactDuplicates
        )
        Assert-ReleasePathsSafe -Paths $mainPaths -Context "main release archive"
        if (($mainPaths -join "`n") -cne ($stagedFiles -join "`n")) {
            throw "Main archive entries do not exactly match the shipped-product staging tree."
        }
        foreach ($entry in $mainEntries) {
            $relative = $entry.FullName.Replace("\", "/")
            $source = Join-Path $stage $relative
            $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
            $stream = $entry.Open()
            try {
                $entryHash = (-join @($sha256.ComputeHash($stream) | ForEach-Object { $_.ToString("x2") }))
            }
            finally {
                $stream.Dispose()
            }
            if ($entryHash -cne $sourceHash) {
                throw "Archive entry differs from staging: $relative"
            }
            if (Test-IsReleaseTextPath -Path $relative) {
                $textStream = $entry.Open()
                try {
                    $reader = New-Object System.IO.StreamReader($textStream, [Text.Encoding]::UTF8, $true)
                    try {
                        $text = $reader.ReadToEnd()
                    }
                    finally {
                        $reader.Dispose()
                    }
                }
                finally {
                    if ($null -ne $textStream) {
                        $textStream.Dispose()
                    }
                }
                Assert-ReleaseTextSafe -Text $text -Label "archive:$relative" -SensitiveRoots @($root)
            }
        }
        foreach ($requiredSource in @(
            @(Get-RequiredReleaseContractPaths) +
            @("tests/portable/test_workspace_lifecycle.py")
        )) {
            if (-not (Test-OrdinalContains `
                -Values $mainPaths `
                -Value $requiredSource)) {
                throw "Full-source release bundle is missing: $requiredSource"
            }
        }
    }
    finally {
        $mainArchive.Dispose()
    }

    $thirdPartyRoot = Join-Path $stage "THIRD_PARTY_LICENSES"
    & (Join-Path $PSScriptRoot "Test-ThirdPartyLicenseManifest.ps1") `
        -ThirdPartyRoot $thirdPartyRoot |
        Out-Null
    $thirdPartyPrefix = $thirdPartyRoot.TrimEnd("\") + "\"
    $thirdPartyFiles = @(
        Get-OrdinalSortedUnique `
            -Values @(
                Get-ChildItem -LiteralPath $thirdPartyRoot -Recurse -File |
                    ForEach-Object {
                        $_.FullName.Substring($thirdPartyPrefix.Length).Replace("\", "/")
                    }
            ) `
            -Context "staged third-party license files" `
            -RejectExactDuplicates
    )
    $portalManifestPath = Join-Path $thirdPartyRoot "portal-runtime\MANIFEST.json"
    if (-not (Test-Path -LiteralPath $portalManifestPath -PathType Leaf)) {
        throw "Portal runtime notice manifest is missing."
    }
    try {
        $portalManifest = (
            Get-Content -LiteralPath $portalManifestPath -Raw -Encoding UTF8 |
                ConvertFrom-Json
        )
    }
    catch {
        throw "Portal runtime notice manifest is invalid JSON: $($_.Exception.Message)"
    }
    if ($portalManifest.schema_version -ne 1 -or
        @($portalManifest.components).Count -ne 5) {
        throw "Portal runtime notice manifest has an unsupported schema or component count."
    }
    $expectedPortalNotices = @(
        [pscustomobject]@{
            name = "react"
            version = "19.2.7"
            file = "react-19.2.7-LICENSE.txt"
            sha256 = "da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93"
            marker = "Copyright (c) Meta Platforms, Inc. and affiliates."
        },
        [pscustomobject]@{
            name = "react-dom"
            version = "19.2.7"
            file = "react-dom-19.2.7-LICENSE.txt"
            sha256 = "da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93"
            marker = "Copyright (c) Meta Platforms, Inc. and affiliates."
        },
        [pscustomobject]@{
            name = "scheduler"
            version = "0.27.0"
            file = "scheduler-0.27.0-LICENSE.txt"
            sha256 = "da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93"
            marker = "Copyright (c) Meta Platforms, Inc. and affiliates."
        },
        [pscustomobject]@{
            name = "vite"
            version = "8.1.5"
            file = "vite-8.1.5-LICENSE.md"
            sha256 = "b1d741c26b53de1bbc0d4d7d3365b79888f9fe511527544a8a7b8e24dec43147"
            marker = "Copyright (c) 2019-present, VoidZero Inc. and Vite contributors"
        },
        [pscustomobject]@{
            name = "rollup"
            version = "4.62.2"
            file = "rollup-4.62.2-LICENSE.md"
            sha256 = "fa1bd040c5bdeefe65b3821cebf474f2733ce65df13089bd151dda1778e62fe8"
            marker = "Copyright (c) 2017"
        }
    )
    $actualPortalIdentities = @(
        $portalManifest.components |
            ForEach-Object { "$($_.name)@$($_.version)" } |
            Sort-Object
    )
    $expectedPortalIdentities = @(
        $expectedPortalNotices |
            ForEach-Object { "$($_.name)@$($_.version)" } |
            Sort-Object
    )
    if (($actualPortalIdentities -join "`n") -cne
        ($expectedPortalIdentities -join "`n")) {
        throw "Portal runtime notice identities do not match the shipped bundle contract."
    }
    foreach ($expectedNotice in $expectedPortalNotices) {
        $matches = @(
            $portalManifest.components |
                Where-Object {
                    $_.name -ceq $expectedNotice.name -and
                    $_.version -ceq $expectedNotice.version
                }
        )
        if ($matches.Count -ne 1) {
            throw "Portal runtime notice must appear exactly once: $($expectedNotice.name)"
        }
        $actualNotice = $matches[0]
        if ($actualNotice.license -cne "MIT" -or
            $actualNotice.file -cne $expectedNotice.file -or
            $actualNotice.sha256 -cne $expectedNotice.sha256) {
            throw "Portal runtime notice metadata changed: $($expectedNotice.name)"
        }
        $licensePath = Join-Path (
            Join-Path $thirdPartyRoot "portal-runtime"
        ) $expectedNotice.file
        if (-not (Test-Path -LiteralPath $licensePath -PathType Leaf)) {
            throw "Portal runtime license file is missing: $($expectedNotice.file)"
        }
        $licenseHash = (
            Get-FileHash -LiteralPath $licensePath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if ($licenseHash -cne $expectedNotice.sha256) {
            throw "Portal runtime license hash changed: $($expectedNotice.file)"
        }
        $licenseText = Get-Content -LiteralPath $licensePath -Raw -Encoding UTF8
        if ($licenseText.IndexOf(
            $expectedNotice.marker,
            [System.StringComparison]::Ordinal
        ) -lt 0) {
            throw "Portal runtime copyright marker is missing: $($expectedNotice.name)"
        }
    }
    $licenseArchive = [System.IO.Compression.ZipFile]::OpenRead($licenses)
    try {
        $licenseEntries = @(
            $licenseArchive.Entries |
                Where-Object { -not [string]::IsNullOrEmpty($_.Name) } |
                Sort-Object FullName
        )
        $licensePaths = @(
            Get-OrdinalSortedUnique `
                -Values @(
                    $licenseEntries |
                        ForEach-Object { $_.FullName.Replace("\", "/") }
                ) `
                -Context "third-party license archive entries" `
                -RejectExactDuplicates
        )
        Assert-ReleasePathsSafe -Paths $licensePaths -Context "third-party license archive"
        if (($licensePaths -join "`n") -cne ($thirdPartyFiles -join "`n")) {
            throw "Third-party license archive does not exactly match shipped notices."
        }
        foreach ($entry in $licenseEntries) {
            $relative = $entry.FullName.Replace("\", "/")
            $sourceHash = (
                Get-FileHash -LiteralPath (Join-Path $thirdPartyRoot $relative) -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            $stream = $entry.Open()
            try {
                $entryHash = (-join @($sha256.ComputeHash($stream) | ForEach-Object { $_.ToString("x2") }))
            }
            finally {
                $stream.Dispose()
            }
            if ($entryHash -cne $sourceHash) {
                throw "Third-party archive entry differs from staging: $relative"
            }
        }
    }
    finally {
        $licenseArchive.Dispose()
    }
}
finally {
    $sha256.Dispose()
}

Assert-DeterministicZipMatchesSource `
    -SourceDirectory $stage `
    -ArchivePath $bundle
Assert-DeterministicZipMatchesSource `
    -SourceDirectory (Join-Path $stage "THIRD_PARTY_LICENSES") `
    -ArchivePath $licenses

if ($RequireSbom) {
    & (Join-Path $PSScriptRoot "Test-DependencyLicenses.ps1") `
        -PythonReport (Join-Path $output "python-licenses.json") `
        -NodeReport (Join-Path $output "node-licenses.json") `
        -ThirdPartyNotices $notices |
        Out-Null
    & (Join-Path $PSScriptRoot "Test-SbomDependencyCoverage.ps1") `
        -Sbom $sbom `
        -PythonReport (Join-Path $output "python-licenses.json") `
        -NodeReport (Join-Path $output "node-licenses.json") |
        Out-Null
}

foreach ($name in @(
    "THIRD_PARTY_NOTICES.md",
    "python-licenses.json",
    "node-licenses.json",
    $sbomName
)) {
    $path = Join-Path $output $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        continue
    }
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    Assert-ReleaseTextSafe -Text $text -Label "release-asset:$name" -SensitiveRoots @($root)
}

foreach ($name in @("node-licenses.json")) {
    $path = Join-Path $output $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        continue
    }
    $payload = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($payload -isnot [System.Array] -or @($payload).Count -eq 0) {
        throw "Node license report is not normalized: $name"
    }
    foreach ($item in @($payload)) {
        $unknownFields = @(
            $item.PSObject.Properties.Name |
                Where-Object { $_ -notin @("Name", "Version", "License", "Private") }
        )
        if ($unknownFields.Count -gt 0) {
            throw "Node license report retained machine-local fields in ${name}: $($unknownFields -join ', ')"
        }
    }
}

if ($RequireSbom) {
    $payload = Get-Content -LiteralPath $sbom -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($payload.bomFormat -cne "CycloneDX") {
        throw "SBOM does not declare CycloneDX format."
    }
    if ([string]$payload.specVersion -notmatch '^1\.(?:4|5|6|7)$') {
        throw "SBOM has an unsupported or missing CycloneDX specVersion."
    }
    if (@($payload.components).Count -eq 0) {
        throw "SBOM must contain dependency components."
    }
    if ($payload.metadata.component.name -cne "local-knowledge-suite" -or
        $payload.metadata.component.version -cne $Version -or
        $payload.metadata.component.type -cne "application") {
        throw "SBOM product metadata does not match local-knowledge-suite $Version."
    }

    function Get-NormalizedDependencyName {
        param([Parameter(Mandatory = $true)][string]$Name)

        return [regex]::Replace(
            $Name.Trim().ToLowerInvariant(),
            '[-_.]+',
            '-'
        )
    }

    function Test-DependencyIdentityPresent {
        param(
            [Parameter(Mandatory = $true)]
            [object[]]$Items,

            [Parameter(Mandatory = $true)]
            [string]$Name,

            [Parameter(Mandatory = $true)]
            [string]$Version
        )

        $normalizedName = Get-NormalizedDependencyName -Name $Name
        foreach ($item in $Items) {
            if ($null -eq $item -or
                -not $item.PSObject.Properties["Name"] -or
                -not $item.PSObject.Properties["Version"]) {
                continue
            }
            if ((Get-NormalizedDependencyName -Name ([string]$item.Name)) -ceq
                $normalizedName -and [string]$item.Version -ceq $Version) {
                return $true
            }
        }
        return $false
    }

    $runtimeProjectPath = Join-Path $stage "plugins\local-knowledge-suite\runtime\pyproject.toml"
    $runtimeLockPath = Join-Path $stage "plugins\local-knowledge-suite\runtime\uv.lock"
    $webPackagePath = Join-Path $stage "web\package.json"
    $nodeLockPath = Join-Path $stage "pnpm-lock.yaml"
    foreach ($manifestPath in @(
        $runtimeProjectPath,
        $runtimeLockPath,
        $webPackagePath,
        $nodeLockPath
    )) {
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            throw "Dependency evidence source is missing from the shipped product: $manifestPath"
        }
    }

    $runtimeProject = Get-Content -LiteralPath $runtimeProjectPath -Raw -Encoding UTF8
    $projectBlock = [regex]::Match(
        $runtimeProject,
        '(?ms)^\[project\]\s*(.*?)(?=^\[|\z)'
    )
    $dependencyBlock = [regex]::Match(
        $projectBlock.Groups[1].Value,
        '(?ms)^dependencies\s*=\s*\[(.*?)^\]\s*$'
    )
    if (-not $projectBlock.Success -or -not $dependencyBlock.Success) {
        throw "Could not parse direct runtime dependencies from the shipped pyproject.toml."
    }
    $pythonDependencySpecs = @(
        [regex]::Matches(
            $dependencyBlock.Groups[1].Value,
            '(?m)^\s*"([^"]+)",?\s*$'
        ) |
            ForEach-Object { $_.Groups[1].Value }
    )
    if ($pythonDependencySpecs.Count -eq 0) {
        throw "The shipped runtime must declare direct Python dependencies."
    }

    $expectedDependencies = New-Object System.Collections.Generic.List[object]
    foreach ($spec in $pythonDependencySpecs) {
        if ($spec -notmatch '^(?<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?<version>[^,;\s]+)$') {
            throw "Direct Python dependency is not an exact, marker-free pin: $spec"
        }
        $expectedDependencies.Add([pscustomobject]@{
            Ecosystem = "python"
            Name = $Matches["name"]
            Version = $Matches["version"]
        })
    }

    $webPackage = Get-Content -LiteralPath $webPackagePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $nodeDependencies = @($webPackage.dependencies.PSObject.Properties)
    if ($nodeDependencies.Count -eq 0) {
        throw "The shipped portal must declare direct Node runtime dependencies."
    }
    foreach ($dependency in $nodeDependencies) {
        $nodeVersion = [string]$dependency.Value
        if (-not (Test-StrictSemVer -Version $nodeVersion)) {
            throw "Direct Node runtime dependency is not an exact SemVer pin: $($dependency.Name)@$nodeVersion"
        }
        $expectedDependencies.Add([pscustomobject]@{
            Ecosystem = "node"
            Name = [string]$dependency.Name
            Version = $nodeVersion
        })
    }

    $identityKeys = @(
        $expectedDependencies |
            ForEach-Object {
                "$($_.Ecosystem):$(Get-NormalizedDependencyName -Name $_.Name)@$($_.Version)"
            }
    )
    if (($identityKeys | Sort-Object -Unique).Count -ne $identityKeys.Count) {
        throw "Direct dependency manifests contain a duplicate identity."
    }

    $runtimeLock = Get-Content -LiteralPath $runtimeLockPath -Raw -Encoding UTF8
    $lockedPython = @(
        [regex]::Matches(
            $runtimeLock,
            '(?ms)^\[\[package\]\]\r?\nname = "([^"]+)"\r?\nversion = "([^"]+)"'
        ) |
            ForEach-Object {
                [pscustomobject]@{
                    Name = $_.Groups[1].Value
                    Version = $_.Groups[2].Value
                }
            }
    )
    $nodeLock = Get-Content -LiteralPath $nodeLockPath -Raw -Encoding UTF8
    $packagesBlock = [regex]::Match(
        $nodeLock,
        '(?ms)^packages:\s*\r?\n(.*?)(?=^[^\s]|\z)'
    )
    if (-not $packagesBlock.Success) {
        throw "Could not parse the packages section from pnpm-lock.yaml."
    }
    $lockedNodeIdentitySet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($entryMatch in [regex]::Matches(
        $packagesBlock.Groups[1].Value,
        '(?m)^  (.+):\s*$'
    )) {
        $lockKey = $entryMatch.Groups[1].Value.Trim()
        if ($lockKey.Length -ge 2 -and
            $lockKey[0] -eq "'" -and
            $lockKey[$lockKey.Length - 1] -eq "'") {
            $lockKey = $lockKey.Substring(1, $lockKey.Length - 2).Replace("''", "'")
        }
        elseif ($lockKey.Length -ge 2 -and
            $lockKey[0] -eq '"' -and
            $lockKey[$lockKey.Length - 1] -eq '"') {
            $lockKey = $lockKey.Substring(1, $lockKey.Length - 2)
        }
        $baseIdentity = $lockKey.Split("(")[0]
        $separator = $baseIdentity.LastIndexOf("@", [System.StringComparison]::Ordinal)
        if ($separator -le 0) {
            continue
        }
        $lockedName = $baseIdentity.Substring(0, $separator)
        $lockedVersion = $baseIdentity.Substring($separator + 1)
        if ([string]::IsNullOrWhiteSpace($lockedVersion) -or $lockedVersion.Contains(":")) {
            continue
        }
        [void]$lockedNodeIdentitySet.Add(
            "$(Get-NormalizedDependencyName -Name $lockedName)@$lockedVersion"
        )
    }
    if ($lockedNodeIdentitySet.Count -eq 0) {
        throw "pnpm-lock.yaml contains no parseable package identities."
    }
    [object[]]$pythonReport = @(
        Read-SbomJsonArray `
            -Path (Join-Path $output "python-licenses.json") `
            -Context "Python dependency report"
    )
    [object[]]$nodeReport = @(
        Read-SbomJsonArray `
            -Path (Join-Path $output "node-licenses.json") `
            -Context "Node dependency report"
    )
    $reportedNodeIdentitySet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($item in $nodeReport) {
        $reportedIdentity = (
            "$(Get-NormalizedDependencyName -Name ([string]$item.Name))@" +
            "$([string]$item.Version)"
        )
        if (-not $reportedNodeIdentitySet.Add($reportedIdentity)) {
            throw "Node license report contains a duplicate identity: $reportedIdentity"
        }
        if (-not $lockedNodeIdentitySet.Contains($reportedIdentity)) {
            throw "Node license report contains an identity absent from pnpm-lock.yaml: $reportedIdentity"
        }
    }
    foreach ($requiredNodeIdentity in @(
        "react@19.2.7",
        "react-dom@19.2.7",
        "rollup@4.62.2",
        "scheduler@0.27.0",
        "vite@8.1.5"
    )) {
        if (-not $reportedNodeIdentitySet.Contains($requiredNodeIdentity)) {
            throw "Node license report is missing shipped portal bundle dependency: $requiredNodeIdentity"
        }
    }
    $sbomComponents = @(
        $payload.components |
            ForEach-Object {
                [pscustomobject]@{
                    Name = [string]$_.name
                    Version = [string]$_.version
                }
            }
    )

    foreach ($dependency in $expectedDependencies) {
        $identity = "$($dependency.Name)@$($dependency.Version)"
        if ($dependency.Ecosystem -ceq "python") {
            if (-not (Test-DependencyIdentityPresent `
                -Items $lockedPython `
                -Name $dependency.Name `
                -Version $dependency.Version)) {
                throw "Direct runtime dependency is missing from uv.lock: $identity"
            }
            if (-not (Test-DependencyIdentityPresent `
                -Items $pythonReport `
                -Name $dependency.Name `
                -Version $dependency.Version)) {
                throw "Direct runtime dependency is missing from the Python license report: $identity"
            }
        }
        else {
            $plainLockKey = "  $identity`:"
            $quotedLockKey = "  '$identity':"
            if ($nodeLock.IndexOf(
                $plainLockKey,
                [System.StringComparison]::Ordinal
            ) -lt 0 -and $nodeLock.IndexOf(
                $quotedLockKey,
                [System.StringComparison]::Ordinal
            ) -lt 0) {
                throw "Direct portal dependency is missing from pnpm-lock.yaml: $identity"
            }
            if (-not (Test-DependencyIdentityPresent `
                -Items $nodeReport `
                -Name $dependency.Name `
                -Version $dependency.Version)) {
                throw "Direct portal dependency is missing from the Node license report: $identity"
            }
        }
        if (-not (Test-DependencyIdentityPresent `
            -Items $sbomComponents `
            -Name $dependency.Name `
            -Version $dependency.Version)) {
            throw "Direct shipped dependency is missing from the SBOM: $identity"
        }
    }
}

Write-Output "Release artifacts passed exact coverage, staged-product, archive, notice, path, and dependency-evidence SBOM checks."
