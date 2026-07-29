# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

Set-StrictMode -Version Latest

$script:StrictSemVerPattern = (
    '^(0|[1-9]\d*)\.' +
    '(0|[1-9]\d*)\.' +
    '(0|[1-9]\d*)' +
    '(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)' +
    '(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?' +
    '(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
)
$script:CanonicalPdfiumIjgLicensePath = (
    "pypdfium2-5.12.1/licenses/data/windows_x64/" +
    "BUILD_LICENSES/libjpeg_turbo.ijg"
)

function Test-StrictSemVer {
    param([AllowNull()][string]$Version)

    return (
        -not [string]::IsNullOrWhiteSpace($Version) -and
        $Version -cmatch $script:StrictSemVerPattern
    )
}

function Get-RequiredReleaseContractPaths {
    return @(
        ".agents/plugins/marketplace.json",
        ".gitattributes",
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
        ".github/workflows/pages.yml",
        ".github/workflows/release.yml",
        ".gitignore",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "PRIVACY.md",
        "README.md",
        "README.vi.md",
        "SECURITY.md",
        "SUPPORT.md",
        "THIRD_PARTY_NOTICES.md",
        "docs/RELEASE_CHECKLIST.md",
        "docs/RELEASE_NOTES_PREAMBLE.md",
        "docs-site/package.json",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "plugins/local-knowledge-suite/.codex-plugin/plugin.json",
        "plugins/local-knowledge-suite/.mcp.json",
        "plugins/local-knowledge-suite/LICENSE",
        "plugins/local-knowledge-suite/README.md",
        "plugins/local-knowledge-suite/THIRD_PARTY_NOTICES.md",
        "plugins/local-knowledge-suite/runtime/pyproject.toml",
        "plugins/local-knowledge-suite/runtime/uv.lock",
        "plugins/local-knowledge-suite/skills/company-knowledge-base/SKILL.md",
        "plugins/local-knowledge-suite/skills/manage-local-knowledge/SKILL.md",
        "plugins/local-knowledge-suite/skills/memorizer/SKILL.md",
        "tools/release/Deterministic-Zip.ps1",
        "tools/release/Export-PdfiumNotices.ps1",
        "tools/release/Export-PortalRuntimeNotices.ps1",
        "tools/release/expected-node-licenses.json",
        "tools/release/expected-python-licenses.json",
        "tools/release/New-Release.ps1",
        "tools/release/Normalize-CycloneDxSbom.ps1",
        "tools/release/Release-Policy.ps1",
        "tools/release/Sbom-Policy.ps1",
        "tools/release/node_license_report.py",
        "tools/release/python_license_report.py",
        "tools/release/test_node_license_report.py",
        "tools/release/Test-DependencyLicenses.ps1",
        "tools/release/Test-DeterministicZip.ps1",
        "tools/release/Test-LicenseGateSelfTest.ps1",
        "tools/release/Test-McpHandshake.ps1",
        "tools/release/Test-Release.ps1",
        "tools/release/Test-ReleaseArtifacts.ps1",
        "tools/release/Test-ReleasePolicySelfTest.ps1",
        "tools/release/Test-ReleaseProvenance.ps1",
        "tools/release/Test-ReleaseProvenanceSelfTest.ps1",
        "tools/release/Test-SbomDependencyCoverage.ps1",
        "tools/release/Test-SbomDependencyCoverageSelfTest.ps1",
        "tools/release/Test-ThirdPartyLicenseManifest.ps1",
        "tools/release/Test-ThirdPartyLicenseManifestSelfTest.ps1",
        "tools/release/Test-VendoredInstall.ps1",
        "tools/release/third-party-license-manifest.json",
        "tools/release/Write-ReleaseChecksums.ps1",
        "web/package.json"
    )
}

function Get-OrdinalSortedUnique {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Values,
        [Parameter(Mandatory = $true)][string]$Context,
        [switch]$RejectExactDuplicates
    )

    $exactValues = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::Ordinal
    )
    $caseFoldedValues = New-Object 'System.Collections.Generic.Dictionary[string,string]' (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($value in $Values) {
        if ($null -eq $value) {
            throw "$Context contains a null value."
        }
        if ($caseFoldedValues.ContainsKey($value)) {
            $canonical = $caseFoldedValues[$value]
            if ($canonical -cne $value) {
                throw (
                    "$Context contains a case-only collision: " +
                    "'$canonical' and '$value'."
                )
            }
        }
        else {
            $caseFoldedValues.Add($value, $value)
        }
        if (-not $exactValues.Add($value) -and $RejectExactDuplicates) {
            throw "$Context contains a duplicate value: '$value'."
        }
    }

    [string[]]$sortedValues = @($exactValues)
    [System.Array]::Sort($sortedValues, [System.StringComparer]::Ordinal)
    return $sortedValues
}

function Test-OrdinalContains {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Values,
        [Parameter(Mandatory = $true)][string]$Value
    )

    foreach ($candidate in $Values) {
        if ($candidate -ceq $Value) {
            return $true
        }
    }
    return $false
}

function Assert-ExactOrdinalSet {
    param(
        [Parameter(Mandatory = $true)][string[]]$Actual,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Context
    )

    [string[]]$actualSorted = @(
        Get-OrdinalSortedUnique `
            -Values $Actual `
            -Context "$Context actual set" `
            -RejectExactDuplicates
    )
    [string[]]$expectedSorted = @(
        Get-OrdinalSortedUnique `
            -Values $Expected `
            -Context "$Context expected set" `
            -RejectExactDuplicates
    )
    if (($actualSorted -join "`n") -cne ($expectedSorted -join "`n")) {
        throw (
            "$Context must match the exact case-sensitive canonical set. " +
            "Expected: $($expectedSorted -join ', '); " +
            "actual: $($actualSorted -join ', ')."
        )
    }
}

function Assert-NoReparseTraversal {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $pathRoot = [System.IO.Path]::GetPathRoot($fullPath)
    if ([string]::IsNullOrWhiteSpace($pathRoot)) {
        throw "$Label does not have a filesystem root: $Path"
    }
    $cursor = $pathRoot
    $relative = $fullPath.Substring($pathRoot.Length)
    foreach ($segment in $relative -split "[\\/]") {
        if ([string]::IsNullOrWhiteSpace($segment)) {
            continue
        }
        $cursor = Join-Path $cursor $segment
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($null -ne $item -and
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label crosses a junction or symbolic link: $cursor"
        }
    }
    return $fullPath
}

function Get-ForbiddenReleasePathReason {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $normalized = $RelativePath.Replace("\", "/").TrimStart("/")
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return "empty path"
    }
    if ([System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '^[A-Za-z]:[\\/]') {
        return "absolute path"
    }
    $segments = @($normalized -split "/")
    if ($segments -contains "..") {
        return "parent traversal"
    }
    if ($normalized -match '(?i)(^|/)(?:\.git|\.ckb|\.memorizer|\.local-sources|node_modules|\.venv|__pycache__|\.uv-cache|\.pytest_cache|\.ruff_cache|\.mypy_cache)(?:/|$)' -or
        $normalized -match '(?i)^(?:artifacts|release)(?:/|$)') {
        return "private or derived directory"
    }
    if ($normalized -match '(?i)(^|/)\.env(?:\.[^/]*)?$') {
        return "environment file"
    }
    if ($normalized -match '(?i)(^|/)(?:\.npmrc|\.pypirc|\.netrc|_netrc|pip\.conf|pip\.ini|\.yarnrc(?:\.yml)?|nuget\.config)$') {
        return "package-manager credential configuration"
    }
    if ($normalized -match '(?i)(^|/)\.codex/config\.toml$') {
        return "machine-local Codex configuration"
    }
    if ($normalized -match '(?i)(^|/)\.local-knowledge/(?:company\.toml|project\.toml|vendor-lock\.json|backups(?:/|$)|memory-snapshot(?:/|$))') {
        return "machine-local Local Knowledge state"
    }
    if ($normalized -match '(?i)^knowledge(?:/|$)') {
        return "top-level canonical company knowledge"
    }
    if ($normalized -match '(?i)(^|/)(?:credentials(?:\.[^/]*)?\.json|service-account[^/]*\.json|secrets?\.json)$') {
        return "credential file"
    }
    if ($normalized -match '(?i)\.(?:pem|key|pfx|p12|jks|keystore|kdbx)$') {
        return "key-store or private-key file"
    }
    if ($normalized -match '(?i)\.(?:db|db-wal|db-shm|sqlite|sqlite3)$') {
        return "local database"
    }
    if ($normalized -match '(?i)\.(?:pdf|doc|docx|xls|xlsx|ppt|pptx|eml|msg|rtf|odt|ods|odp)$') {
        return "binary or customer document"
    }
    if (-not (Test-IsReleaseTextPath -Path $normalized)) {
        return "unreviewed or binary file type"
    }
    return $null
}

function Assert-ReleasePathsSafe {
    param(
        [Parameter(Mandatory = $true)][string[]]$Paths,
        [string]$Context = "release"
    )

    $problems = New-Object System.Collections.Generic.List[string]
    foreach ($path in $Paths) {
        $reason = Get-ForbiddenReleasePathReason -RelativePath $path
        if ($null -ne $reason) {
            $problems.Add("${path}: $reason")
        }
    }
    if ($problems.Count -gt 0) {
        throw "Forbidden paths found in ${Context}:`n - $($problems -join "`n - ")"
    }
}

function Test-IsReleaseTextPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $normalized = $Path.Replace("\", "/")
    if ($normalized -ceq $script:CanonicalPdfiumIjgLicensePath -or
        $normalized -ceq (
            "THIRD_PARTY_LICENSES/" +
            $script:CanonicalPdfiumIjgLicensePath
        )) {
        return $true
    }
    $name = [System.IO.Path]::GetFileName($Path)
    if ($name -in @(
        "CODEOWNERS", "COPYING", "Dockerfile", "LICENSE", "Makefile", "NOTICE"
    )) {
        return $true
    }
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    return $extension -in @(
        ".bat", ".cfg", ".cjs", ".cmd", ".conf", ".css", ".csv", ".editorconfig",
        ".gitattributes", ".gitignore", ".gql", ".graphql", ".html", ".ini", ".js",
        ".json", ".jsx", ".lock", ".map", ".md", ".mjs", ".mts", ".npmignore",
        ".properties", ".ps1", ".psd1", ".psm1", ".py", ".sh", ".sql", ".svg",
        ".toml", ".ts", ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml"
    )
}

function Get-ForbiddenContentFindings {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
        [string[]]$SensitiveRoots = @()
    )

    $findings = New-Object System.Collections.Generic.List[string]
    $privateKeyMarker = (
        "-----BEGIN " +
        "(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----"
    )
    $fineGrainedGitHubPrefix = "github" + "_pat_"
    $pgpPrivateKeyMarker = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"
    $patterns = [ordered]@{
        "private key material" = $privateKeyMarker
        "GitHub token" = "(?i)\b(?:gh[pousr]_[A-Za-z0-9]{32,}|$([Regex]::Escape($fineGrainedGitHubPrefix))[A-Za-z0-9_-]{20,})\b"
        "GitLab token" = '(?i)\bglpat-[0-9A-Za-z_-]{20,}\b'
        "AWS access key" = '\bAKIA[0-9A-Z]{16}\b'
        "Google API key" = '\bAIza[0-9A-Za-z_-]{32,}\b'
        "Slack token" = '\bxox[baprs]-[0-9A-Za-z-]{20,}\b'
        "Stripe live secret" = '\bsk_live_[0-9A-Za-z]{20,}\b'
        "OpenAI secret key" = '\bsk-(?:proj-|svcacct-)?[0-9A-Za-z_-]{32,}\b'
        "PyPI token" = '\bpypi-[0-9A-Za-z_-]{20,}\b'
        "npm token" = '(?im)^\s*(?:(?://[^/\r\n]+/?:)?_authToken|NPM_TOKEN|NODE_AUTH_TOKEN)\s*=\s*[^\s;#]{8,}\s*$'
        "encoded package credential" = '(?im)^\s*(?:_auth|_password)\s*=\s*[0-9A-Za-z+/=_-]{8,}\s*$'
        "PGP private key material" = $pgpPrivateKeyMarker
    }
    foreach ($item in $patterns.GetEnumerator()) {
        if ($Text -match $item.Value) {
            $findings.Add($item.Key)
        }
    }

    $roots = @($SensitiveRoots)
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $roots += $env:USERPROFILE
    }
    $textVariants = New-Object System.Collections.Generic.List[string]
    $textVariants.Add($Text)
    $collapsed = $Text
    while ($collapsed.Contains("\\")) {
        $collapsed = $collapsed.Replace("\\", "\")
    }
    if ($collapsed -cne $Text) {
        $textVariants.Add($collapsed)
    }
    foreach ($candidate in @($textVariants)) {
        try {
            $decoded = [System.Uri]::UnescapeDataString($candidate)
            if ($decoded -cne $candidate) {
                $textVariants.Add($decoded)
            }
        }
        catch {
            # Invalid percent escapes cannot form a valid encoded private path.
        }
    }

    foreach ($root in @($roots | Where-Object { $_ } | Sort-Object -Unique)) {
        $normalizedRoot = [System.IO.Path]::GetFullPath($root).TrimEnd("\", "/")
        $rootVariants = @(
            $normalizedRoot,
            $normalizedRoot.Replace("\", "/")
        )
        $matched = $false
        foreach ($candidate in @($textVariants | Select-Object -Unique)) {
            foreach ($rootVariant in @($rootVariants | Select-Object -Unique)) {
                if ($candidate -match [Regex]::Escape($rootVariant)) {
                    $matched = $true
                    break
                }
            }
            if ($matched) {
                break
            }
        }
        if ($matched) {
            $findings.Add("absolute private path")
            break
        }
    }
    return @($findings | Sort-Object -Unique)
}

function Assert-ReleaseTextSafe {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$Label,
        [string[]]$SensitiveRoots = @()
    )

    $findings = @(Get-ForbiddenContentFindings -Text $Text -SensitiveRoots $SensitiveRoots)
    if ($findings.Count -gt 0) {
        throw "Forbidden content in ${Label}: $($findings -join ', ')."
    }
}
