# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$ExpectedVersion = "1.0.0"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")
if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}

function Assert-ReleaseCondition {
    param([bool]$Condition, [string]$Message)

    if (-not $Condition) {
        throw $Message
    }
}

function Read-JsonFile {
    param([string]$Path)

    Assert-ReleaseCondition (Test-Path -LiteralPath $Path -PathType Leaf) "Required JSON file is missing: $Path"
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Invalid JSON in ${Path}: $($_.Exception.Message)"
    }
}

function Get-PublicationFiles {
    param([string]$Root)

    $output = @(& git -C $Root ls-files -co --exclude-standard)
    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed with exit code $LASTEXITCODE."
    }
    return @(
        Get-OrdinalSortedUnique `
            -Values @(
                $output |
                    ForEach-Object { $_.Trim().Replace("\", "/") } |
                    Where-Object { $_ }
            ) `
            -Context "Git publication set" `
            -RejectExactDuplicates
    )
}

function Get-YamlJobBlock {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$JobName,
        [Parameter(Mandatory = $true)][string]$WorkflowName
    )

    $escapedJob = [Regex]::Escape($JobName)
    $match = [Regex]::Match(
        $Text,
        "(?ms)^  ${escapedJob}:\s*\r?\n.*?(?=^  [0-9A-Za-z_-]+:\s*\r?\n|\z)"
    )
    Assert-ReleaseCondition $match.Success "$WorkflowName is missing the $JobName job."
    return $match.Value
}

function Get-WorkflowRunExpressionFindings {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$WorkflowName
    )

    $findings = New-Object System.Collections.Generic.List[string]
    $lines = @($Text -split "\r?\n")
    $runIndent = -1
    for ($index = 0; $index -lt $lines.Count; $index++) {
        $line = [string]$lines[$index]
        if ($runIndent -ge 0 -and -not [string]::IsNullOrWhiteSpace($line)) {
            $indent = ([Regex]::Match($line, '^\s*')).Value.Length
            if ($indent -le $runIndent) {
                $runIndent = -1
            }
            elseif ($line.Contains('${{')) {
                $findings.Add("${WorkflowName}:$($index + 1)")
                continue
            }
        }
        if ($runIndent -ge 0) {
            continue
        }
        $runMatch = [Regex]::Match($line, '^(\s*)run:\s*(.*)$')
        if (-not $runMatch.Success) {
            continue
        }
        if ($runMatch.Groups[2].Value.Contains('${{')) {
            $findings.Add("${WorkflowName}:$($index + 1)")
        }
        if ($runMatch.Groups[2].Value -match '^[>|][+-]?\s*$') {
            $runIndent = $runMatch.Groups[1].Value.Length
        }
    }
    return @($findings)
}

$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
$pluginRoot = Join-Path $root "plugins\local-knowledge-suite"
$pluginManifestPath = Join-Path $pluginRoot ".codex-plugin\plugin.json"
$marketplacePath = Join-Path $root ".agents\plugins\marketplace.json"
$runtimeProjectPath = Join-Path $pluginRoot "runtime\pyproject.toml"

Assert-ReleaseCondition (Test-StrictSemVer -Version $ExpectedVersion) "ExpectedVersion must use strict SemVer 2.0.0."
$plugin = Read-JsonFile $pluginManifestPath
Assert-ReleaseCondition ($plugin.name -eq "local-knowledge-suite") "Plugin name must be local-knowledge-suite."
Assert-ReleaseCondition (Test-StrictSemVer -Version ([string]$plugin.version)) "Plugin version must use strict SemVer 2.0.0."
Assert-ReleaseCondition ($plugin.version -eq $ExpectedVersion) "Plugin version must be $ExpectedVersion."
Assert-ReleaseCondition ([string]$plugin.license -eq "MIT") "Plugin license must be MIT."
Assert-ReleaseCondition ([string]$plugin.author.name -eq "John-IDK") "Plugin author must be John-IDK."
Assert-ReleaseCondition ([string]$plugin.author.url -eq "https://github.com/luutru433-coder") "Plugin author URL is not canonical."
Assert-ReleaseCondition ([string]$plugin.repository -eq "https://github.com/luutru433-coder/local-knowledge-suite") "Plugin repository URL is not canonical."
Assert-ReleaseCondition ([string]$plugin.homepage -eq "https://luutru433-coder.github.io/local-knowledge-suite/") "Plugin homepage URL is not canonical."
Assert-ReleaseCondition ([string]$plugin.interface.websiteURL -eq [string]$plugin.homepage) "Plugin websiteURL and homepage must match."
Assert-ReleaseCondition ([string]$plugin.interface.privacyPolicyURL -eq "https://luutru433-coder.github.io/local-knowledge-suite/en/privacy/") "Plugin privacy URL is not canonical."
Assert-ReleaseCondition ($plugin.skills -eq "./skills/") "Plugin skills path must be ./skills/."
Assert-ReleaseCondition ($plugin.mcpServers -eq "./.mcp.json") "Plugin MCP manifest path must be ./.mcp.json."
Assert-ReleaseCondition (-not $plugin.PSObject.Properties["apps"]) "Plugin declares apps without an app manifest."
Assert-ReleaseCondition (-not $plugin.PSObject.Properties["hooks"]) "Unsupported hooks field must not appear in plugin.json."

foreach ($assetProperty in @("composerIcon", "logo", "logoDark")) {
    $relativeAsset = [string]$plugin.interface.$assetProperty
    Assert-ReleaseCondition ($relativeAsset.StartsWith("./assets/", [System.StringComparison]::Ordinal)) "Plugin $assetProperty must be under ./assets/."
    $asset = (Resolve-Path -LiteralPath (Join-Path $pluginRoot $relativeAsset.Substring(2)) -ErrorAction Stop).Path
    $pluginPrefix = $pluginRoot.TrimEnd("\") + "\"
    Assert-ReleaseCondition ($asset.StartsWith($pluginPrefix, [System.StringComparison]::OrdinalIgnoreCase)) "Plugin asset escaped the plugin root: $relativeAsset"
}

$marketplace = Read-JsonFile $marketplacePath
Assert-ReleaseCondition ($marketplace.name -eq "john-idk") "Marketplace name must be john-idk."
Assert-ReleaseCondition ($marketplace.interface.displayName -eq "John-IDK") "Marketplace display name must be John-IDK."
$entry = @($marketplace.plugins | Where-Object { $_.name -eq "local-knowledge-suite" })
Assert-ReleaseCondition ($entry.Count -eq 1) "Marketplace must contain exactly one local-knowledge-suite entry."
Assert-ReleaseCondition ($entry[0].source.source -eq "local") "Marketplace plugin source type must be local."
Assert-ReleaseCondition ($entry[0].source.path -eq "./plugins/local-knowledge-suite") "Marketplace source path is invalid."
Assert-ReleaseCondition ($entry[0].policy.installation -eq "AVAILABLE") "Marketplace installation policy must be AVAILABLE."
Assert-ReleaseCondition ($entry[0].policy.authentication -eq "ON_INSTALL") "Marketplace authentication policy must be ON_INSTALL."
Assert-ReleaseCondition (-not $entry[0].policy.PSObject.Properties["products"]) "Marketplace must not add product gating."

$expectedSkills = @("company-knowledge-base", "manage-local-knowledge", "memorizer")
$actualSkills = @(
    Get-ChildItem -LiteralPath (Join-Path $pluginRoot "skills") -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "SKILL.md") -PathType Leaf } |
        ForEach-Object { $_.Name } |
        Sort-Object
)
Assert-ReleaseCondition (($actualSkills -join ",") -eq (($expectedSkills | Sort-Object) -join ",")) "Plugin must contain exactly the three supported skills."
foreach ($skillName in $expectedSkills) {
    $skillPath = Join-Path $pluginRoot "skills\$skillName\SKILL.md"
    $skillText = Get-Content -LiteralPath $skillPath -Raw -Encoding UTF8
    Assert-ReleaseCondition ($skillText -match "(?m)^---\s*$") "Skill frontmatter is missing: $skillName"
    Assert-ReleaseCondition ($skillText -match "(?m)^name:\s*$([Regex]::Escape($skillName))\s*$") "Skill name does not match its folder: $skillName"
    Assert-ReleaseCondition ($skillText -match "(?m)^description:\s*\S") "Skill description is missing: $skillName"
}

$rootPackage = Read-JsonFile (Join-Path $root "package.json")
$portalPackage = Read-JsonFile (Join-Path $root "web\package.json")
$docsPackage = Read-JsonFile (Join-Path $root "docs-site\package.json")
Assert-ReleaseCondition ($rootPackage.version -eq $ExpectedVersion) "Root package version must be $ExpectedVersion."
Assert-ReleaseCondition ($portalPackage.version -eq $ExpectedVersion) "Portal package version must be $ExpectedVersion."
Assert-ReleaseCondition ($docsPackage.version -eq $ExpectedVersion) "Documentation package version must be $ExpectedVersion."
foreach ($versionEntry in @(
    @("root package", [string]$rootPackage.version),
    @("portal package", [string]$portalPackage.version),
    @("documentation package", [string]$docsPackage.version)
)) {
    Assert-ReleaseCondition (Test-StrictSemVer -Version $versionEntry[1]) "$($versionEntry[0]) must use strict SemVer 2.0.0."
}
Assert-ReleaseCondition ($rootPackage.packageManager -eq "pnpm@11.9.0") "Root packageManager must be pnpm@11.9.0."
Assert-ReleaseCondition ($rootPackage.engines.node -eq ">=22.12.0 <23") "Node must be pinned to the Node 22 release line."
Assert-ReleaseCondition ($docsPackage.name -eq "@local-knowledge-suite/docs") "VitePress package name is invalid."

$releaseWorkflowPath = Join-Path $root ".github\workflows\release.yml"
$pagesWorkflowPath = Join-Path $root ".github\workflows\pages.yml"
$releaseNotesPreamblePath = Join-Path $root "docs\RELEASE_NOTES_PREAMBLE.md"
Assert-ReleaseCondition (Test-Path -LiteralPath $releaseWorkflowPath -PathType Leaf) "Release workflow is missing."
Assert-ReleaseCondition (Test-Path -LiteralPath $pagesWorkflowPath -PathType Leaf) "Pages workflow is missing."
Assert-ReleaseCondition (Test-Path -LiteralPath $releaseNotesPreamblePath -PathType Leaf) "Release notes preamble is missing."
$releaseWorkflow = Get-Content -LiteralPath $releaseWorkflowPath -Raw -Encoding UTF8
$pagesWorkflow = Get-Content -LiteralPath $pagesWorkflowPath -Raw -Encoding UTF8
$releaseNotesPreamble = Get-Content -LiteralPath $releaseNotesPreamblePath -Raw -Encoding UTF8
$releaseBuildJob = Get-YamlJobBlock -Text $releaseWorkflow -JobName "build" -WorkflowName "Release workflow"
$releasePublishJob = Get-YamlJobBlock -Text $releaseWorkflow -JobName "publish" -WorkflowName "Release workflow"
$pagesBuildJob = Get-YamlJobBlock -Text $pagesWorkflow -JobName "build" -WorkflowName "Pages workflow"
$pagesDeployJob = Get-YamlJobBlock -Text $pagesWorkflow -JobName "deploy" -WorkflowName "Pages workflow"

Assert-ReleaseCondition (
    $releaseWorkflow -match '(?m)^permissions:\s*\r?\n  contents:\s*read\s*$'
) "Release workflow default permission must be contents: read."
Assert-ReleaseCondition (
    $releaseBuildJob -match '(?m)^    permissions:\s*\r?\n      contents:\s*read\s*$'
) "Release build job must be read-only."
Assert-ReleaseCondition (
    $releaseBuildJob -notmatch '(?m)^\s+GH_TOKEN:'
) "Release build job must not receive GH_TOKEN."
Assert-ReleaseCondition (
    $releasePublishJob -match '(?m)^    needs:\s*build\s*$' -and
    $releasePublishJob -match '(?m)^    permissions:\s*\r?\n      contents:\s*write\s*$'
) "Release publish job must depend on build and own the only contents: write permission."
Assert-ReleaseCondition (
    $releasePublishJob -match 'actions/download-artifact@[0-9a-f]{40}' -and
    $releasePublishJob -match '(?m)^          persist-credentials:\s*false\s*$'
) "Release publish job must securely download evidence and avoid persisted Git credentials."
$releaseTokenLines = [Regex]::Matches(
    $releaseWorkflow,
    '(?m)^\s+GH_TOKEN:\s*\$\{\{\s*github\.token\s*\}\}\s*$'
)
Assert-ReleaseCondition (
    $releaseTokenLines.Count -eq 1 -and
    $releasePublishJob -match '(?m)^\s+GH_TOKEN:\s*\$\{\{\s*github\.token\s*\}\}\s*$'
) "GH_TOKEN must appear exactly once, inside the publish step."
$requiredReleaseDisclaimer = (
    "Annotated-tag/main-head binding and SHA-256 checks provide provenance and integrity only " +
    "against the trusted GitHub Release channel. They are not a cryptographic " +
    "signature or an independent attestation."
)
Assert-ReleaseCondition (
    $releaseNotesPreamble.IndexOf(
        $requiredReleaseDisclaimer,
        [System.StringComparison]::Ordinal
    ) -ge 0
) "Release notes preamble must contain the exact channel-trust and integrity disclaimer."
foreach ($requiredReleaseAsset in @(
    "full-source ZIP",
    "SHA256SUMS",
    "CycloneDX SBOM",
    "license inventories",
    "third-party notices"
)) {
    Assert-ReleaseCondition (
        $releaseNotesPreamble.IndexOf(
            $requiredReleaseAsset,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -ge 0
    ) "Release notes preamble is missing the asset summary: $requiredReleaseAsset"
}
Assert-ReleaseCondition (
    $releasePublishJob -match 'docs/RELEASE_NOTES_PREAMBLE\.md' -and
    $releasePublishJob -match 'releases/generate-notes' -and
    $releasePublishJob -match '(?m)^\s+--notes-file \$notesFile\s*$' -and
    $releasePublishJob -notmatch '(?m)^\s+--generate-notes\s*$' -and
    [Regex]::Matches(
        $releasePublishJob,
        'Release notes (?:preamble is missing|lost) the required integrity disclaimer'
    ).Count -eq 2
) "Release publish must compose generated notes with the reviewed preamble and gate the exact disclaimer."

Assert-ReleaseCondition (
    $pagesBuildJob -match '(?m)^    permissions:\s*\r?\n      contents:\s*read\s*$' -and
    $pagesBuildJob -notmatch '(?m)^\s+(?:pages|id-token):\s*write\s*$'
) "Pages build job must have contents: read only."
Assert-ReleaseCondition (
    $pagesDeployJob -match '(?m)^      pages:\s*write\s*$' -and
    $pagesDeployJob -match '(?m)^      id-token:\s*write\s*$'
) "Pages deploy job must own Pages and OIDC write permissions."

foreach ($workflowPath in Get-ChildItem -LiteralPath (Join-Path $root ".github\workflows") -Filter "*.yml" -File) {
    $workflowText = Get-Content -LiteralPath $workflowPath.FullName -Raw -Encoding UTF8
    $runExpressionFindings = @(
        Get-WorkflowRunExpressionFindings `
            -Text $workflowText `
            -WorkflowName $workflowPath.Name
    )
    Assert-ReleaseCondition (
        $runExpressionFindings.Count -eq 0
    ) (
        "GitHub expressions must enter run steps through env, never as shell source: " +
        ($runExpressionFindings -join ", ")
    )
    foreach ($line in $workflowText -split "\r?\n") {
        if ($line -notmatch '^\s*uses:\s*(\S+)') {
            continue
        }
        $action = $Matches[1]
        if ($action.StartsWith("./", [System.StringComparison]::Ordinal)) {
            continue
        }
        Assert-ReleaseCondition (
            $action -match '@[0-9a-f]{40}$'
        ) "GitHub Action must be pinned to a full commit SHA in $($workflowPath.Name): $action"
    }
}

Assert-ReleaseCondition (Test-Path -LiteralPath $runtimeProjectPath -PathType Leaf) "Runtime pyproject.toml is missing."
$runtimeProject = Get-Content -LiteralPath $runtimeProjectPath -Raw -Encoding UTF8
$runtimeVersionMatch = [Regex]::Match($runtimeProject, '(?m)^\s*version\s*=\s*"([^"]+)"\s*$')
Assert-ReleaseCondition $runtimeVersionMatch.Success "Runtime version is missing from pyproject.toml."
Assert-ReleaseCondition ($runtimeVersionMatch.Groups[1].Value -eq $ExpectedVersion) "Runtime version must be $ExpectedVersion."
Assert-ReleaseCondition (Test-StrictSemVer -Version $runtimeVersionMatch.Groups[1].Value) "Runtime version must use strict SemVer 2.0.0."
$runtimeInitPath = Join-Path $pluginRoot "runtime\src\local_knowledge\__init__.py"
$runtimeInit = Get-Content -LiteralPath $runtimeInitPath -Raw -Encoding UTF8
$runtimeInitVersion = [Regex]::Match(
    $runtimeInit,
    '(?m)^__version__\s*=\s*"([^"]+)"\s*$'
)
Assert-ReleaseCondition (
    $runtimeInitVersion.Success -and
    $runtimeInitVersion.Groups[1].Value -ceq $ExpectedVersion
) "Runtime __version__ must match the product version."
$ckbInit = Get-Content -LiteralPath (
    Join-Path $pluginRoot "runtime\src\local_knowledge\ckb\__init__.py"
) -Raw -Encoding UTF8
Assert-ReleaseCondition (
    $ckbInit -match '(?m)^from local_knowledge import __version__\s*$' -and
    $ckbInit -notmatch '(?m)^__version__\s*='
) "The CKB package must reuse the single runtime __version__."
Assert-ReleaseCondition ($runtimeProject -notmatch '(?i)\bPyMuPDF\b') "PyMuPDF must not be present in the public runtime."
Assert-ReleaseCondition (
    $runtimeProject -match '(?m)^requires\s*=\s*\["hatchling==1\.28\.0"\]\s*$' -and
    $runtimeProject -match '(?ms)^build\s*=\s*\[\s*"editables==0\.5",\s*"hatchling==1\.28\.0",\s*\]\s*$'
) "The inventoried build extra must exactly include Hatchling 1.28.0 and editables 0.5."
Assert-ReleaseCondition (
    $runtimeProject -notmatch '(?im)\bruff\b'
) "Unowned Ruff tooling must not expand the locked product graph."
$expectedBuildConstraints = @(
    "editables==0.5",
    "hatchling==1.28.0",
    "packaging==26.2",
    "pathspec==1.1.1",
    "pluggy==1.6.0",
    "trove-classifiers==2026.6.1.19"
)
$toolUvBlock = [Regex]::Match(
    $runtimeProject,
    '(?ms)^\[tool\.uv\]\s*(.*?)(?=^\[|\z)'
)
$constraintBlock = [Regex]::Match(
    $toolUvBlock.Groups[1].Value,
    '(?ms)^build-constraint-dependencies\s*=\s*\[(.*?)^\]\s*$'
)
$actualBuildConstraints = @(
    [Regex]::Matches(
        $constraintBlock.Groups[1].Value,
        '(?m)^\s*"([^"]+)",?\s*$'
    ) |
        ForEach-Object { $_.Groups[1].Value }
)
Assert-ReleaseCondition (
    $toolUvBlock.Success -and
    $constraintBlock.Success -and
    (($actualBuildConstraints | Sort-Object) -join "`n") -ceq
        (($expectedBuildConstraints | Sort-Object) -join "`n")
) "PEP 517 build constraints must exactly pin the reviewed Hatchling closure."
$runtimeLockPath = Join-Path $pluginRoot "runtime\uv.lock"
Assert-ReleaseCondition (Test-Path -LiteralPath $runtimeLockPath -PathType Leaf) "Runtime uv.lock is missing."
$runtimeLock = Get-Content -LiteralPath $runtimeLockPath -Raw -Encoding UTF8
Assert-ReleaseCondition ($runtimeLock -notmatch '(?im)^name\s*=\s*"pymupdf"\s*$') "Runtime lock still contains PyMuPDF."
Assert-ReleaseCondition ($runtimeLock -notmatch '(?im)^name\s*=\s*"ruff"\s*$') "Runtime lock still contains unowned Ruff tooling."
foreach ($buildConstraint in $expectedBuildConstraints) {
    $constraintParts = $buildConstraint -split "==", 2
    $buildDependency = $constraintParts[0]
    $buildVersion = $constraintParts[1]
    Assert-ReleaseCondition (
        $runtimeLock -match (
            "(?ms)^\[\[package\]\]\r?\n" +
            "name = `"$([Regex]::Escape($buildDependency))`"\r?\n" +
            "version = `"$([Regex]::Escape($buildVersion))`""
        )
    ) "Runtime lock is missing exact build dependency: $buildConstraint"
}
foreach ($workflow in @($releaseWorkflow, (Get-Content -LiteralPath (Join-Path $root ".github\workflows\ci.yml") -Raw -Encoding UTF8))) {
    Assert-ReleaseCondition (
        [Regex]::Matches($workflow, '--extra\s+build').Count -ge 3
    ) "CI and release must sync, test, and inventory the Hatchling build extra."
    Assert-ReleaseCondition (
        $workflow -match 'test_node_license_report\.py' -and
        $workflow -match 'node_license_report\.py' -and
        [Regex]::Matches($workflow, 'node-licenses\.json').Count -ge 2
    ) "CI and release must self-test, generate, and enforce the complete installed Node inventory."
    Assert-ReleaseCondition (
        [Regex]::Matches(
            $workflow,
            '(?m)^\s+syft-version:\s*v1\.33\.0\s*$'
        ).Count -eq 1
    ) "CI and release must pin the exact reviewed Syft version."
}

foreach ($packageManifest in @(
    "package.json",
    "web\package.json",
    "docs-site\package.json"
)) {
    $packageManifestPath = Join-Path $root $packageManifest
    $packagePayload = Get-Content -LiteralPath $packageManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $declaredNodeDependencies = @()
    foreach ($sectionName in @("dependencies", "devDependencies")) {
        if (-not $packagePayload.PSObject.Properties[$sectionName]) {
            continue
        }
        $declaredNodeDependencies += @($packagePayload.$sectionName.PSObject.Properties)
    }
    foreach ($dependency in $declaredNodeDependencies) {
        Assert-ReleaseCondition (
            Test-StrictSemVer -Version ([string]$dependency.Value)
        ) "$packageManifest must exactly pin $($dependency.Name); ranges and tags are not allowed."
    }
}
$pnpmLockText = Get-Content -LiteralPath (Join-Path $root "pnpm-lock.yaml") -Raw -Encoding UTF8
Assert-ReleaseCondition (
    $pnpmLockText -notmatch '(?i)license-checker-rseidelsohn'
) "The incomplete license-checker dependency and lock graph must not be shipped."
foreach ($nodeInventorySource in @(
    "tools\release\node_license_report.py",
    "tools\release\test_node_license_report.py"
)) {
    Assert-ReleaseCondition (
        Test-Path -LiteralPath (Join-Path $root $nodeInventorySource) -PathType Leaf
    ) "Deterministic Node inventory source is missing: $nodeInventorySource"
}

foreach ($requiredFile in @(
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "PRIVACY.md",
    "SECURITY.md",
    "SUPPORT.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml"
)) {
    Assert-ReleaseCondition (Test-Path -LiteralPath (Join-Path $root $requiredFile) -PathType Leaf) "Required release file is missing: $requiredFile"
}
Assert-ReleaseCondition (
    Test-Path -LiteralPath (Join-Path $root "docs-site\en\privacy\index.md") -PathType Leaf
) "The manifest privacyPolicyURL must resolve to docs-site/en/privacy/index.md."
foreach ($legalFile in @("LICENSE", "THIRD_PARTY_NOTICES.md")) {
    $rootLegalPath = Join-Path $root $legalFile
    $pluginLegalPath = Join-Path $pluginRoot $legalFile
    Assert-ReleaseCondition (Test-Path -LiteralPath $pluginLegalPath -PathType Leaf) "Plugin archive is missing $legalFile."
    $rootHash = (Get-FileHash -LiteralPath $rootLegalPath -Algorithm SHA256).Hash
    $pluginHash = (Get-FileHash -LiteralPath $pluginLegalPath -Algorithm SHA256).Hash
    Assert-ReleaseCondition ($pluginHash -eq $rootHash) "Plugin $legalFile must be byte-equivalent to the root copy."
}

$publicationFiles = @(Get-PublicationFiles -Root $root)
Assert-ReleaseCondition ($publicationFiles.Count -gt 0) "No publishable files were found."
Assert-ReleasePathsSafe -Paths $publicationFiles -Context "Git publication set"
$trackedFiles = @(
    & git -C $root ls-files
)
if ($LASTEXITCODE -ne 0) {
    throw "git ls-files failed while checking the committed release contract."
}
$trackedFiles = @(
    Get-OrdinalSortedUnique `
        -Values @(
            $trackedFiles |
                ForEach-Object { ([string]$_).Trim().Replace("\", "/") } |
                Where-Object { $_ }
        ) `
        -Context "committed release contract set" `
        -RejectExactDuplicates
)
foreach ($requiredContractPath in Get-RequiredReleaseContractPaths) {
    Assert-ReleaseCondition (
        Test-Path -LiteralPath (Join-Path $root $requiredContractPath) -PathType Leaf
    ) "Required release contract file is missing: $requiredContractPath"
    Assert-ReleaseCondition (
        Test-OrdinalContains `
            -Values $trackedFiles `
            -Value $requiredContractPath
    ) "Required release contract file is not committed: $requiredContractPath"
}

$placeholderCompany = "My" + "Company LLC"
$placeholderPattern = "(?i)" + [Regex]::Escape($placeholderCompany) + "|\[" + "TODO(?:\:|\])"
$contentProblems = New-Object System.Collections.Generic.List[string]
foreach ($relative in $publicationFiles) {
    $fullPath = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        continue
    }
    if (-not (Test-IsReleaseTextPath -Path $relative)) {
        continue
    }
    $text = Get-Content -LiteralPath $fullPath -Raw -Encoding UTF8
    foreach ($finding in @(Get-ForbiddenContentFindings -Text $text -SensitiveRoots @($root))) {
        $contentProblems.Add("${relative}: $finding")
    }
    if ($text -match '(?i)\blearn-company\b') {
        $contentProblems.Add("${relative}: private company identifier")
    }
    if ($text -match $placeholderPattern) {
        $contentProblems.Add("${relative}: placeholder metadata")
    }
}
Assert-ReleaseCondition ($contentProblems.Count -eq 0) ("Release hygiene checks failed:`n - " + ($contentProblems -join "`n - "))

$manifestFiles = @($publicationFiles | Where-Object { $_ -match '(^|/)(package\.json|pnpm-lock\.yaml)$' })
foreach ($relative in $manifestFiles) {
    $text = Get-Content -LiteralPath (Join-Path $root $relative) -Raw -Encoding UTF8
    Assert-ReleaseCondition ($text -notmatch '(?i)(?:"|:\s*)latest(?:"|\s|$)') "Unpinned latest dependency found in $relative."
}

$parseProblems = New-Object System.Collections.Generic.List[string]
foreach ($relative in @($publicationFiles | Where-Object { $_.EndsWith(".ps1", [System.StringComparison]::OrdinalIgnoreCase) })) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $root $relative),
        [ref]$tokens,
        [ref]$errors
    )
    foreach ($parseError in @($errors)) {
        $parseProblems.Add("${relative}: $($parseError.Message)")
    }
}
Assert-ReleaseCondition ($parseProblems.Count -eq 0) ("PowerShell syntax checks failed:`n - " + ($parseProblems -join "`n - "))

Write-Output "Release checks passed for Local Knowledge Suite $ExpectedVersion."
