# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Release-Policy.ps1")

function Assert-True {
    param([bool]$Condition, [string]$Message)

    if (-not $Condition) {
        throw $Message
    }
}

foreach ($version in @(
    "0.0.0",
    "1.0.0",
    "1.0.0-alpha.1",
    "1.0.0-rc.1+build.5"
)) {
    Assert-True (Test-StrictSemVer -Version $version) "Valid SemVer was rejected: $version"
}
foreach ($version in @(
    "v1.0.0",
    "01.0.0",
    "1.01.0",
    "1.0.01",
    "1.0",
    "1.0.0-01",
    "1.0.0-alpha..1",
    "1.0.0+"
)) {
    Assert-True (-not (Test-StrictSemVer -Version $version)) "Invalid SemVer was accepted: $version"
}

Assert-ExactOrdinalSet `
    -Actual @("SHA256SUMS", "THIRD_PARTY_NOTICES.md") `
    -Expected @("THIRD_PARTY_NOTICES.md", "SHA256SUMS") `
    -Context "Canonical-name positive self-test"
$caseVariantRejected = $false
try {
    Assert-ExactOrdinalSet `
        -Actual @("SHA256SUMS", "third_party_notices.md") `
        -Expected @("SHA256SUMS", "THIRD_PARTY_NOTICES.md") `
        -Context "Canonical-name negative self-test"
}
catch {
    $caseVariantRejected = $true
}
Assert-True $caseVariantRejected "A lowercase release-asset rename was accepted."

$caseCollisionRejected = $false
try {
    Get-OrdinalSortedUnique `
        -Values @("docs/README.md", "docs/readme.md") `
        -Context "Case-collision negative self-test" |
        Out-Null
}
catch {
    $caseCollisionRejected = $true
}
Assert-True $caseCollisionRejected "A case-only path collision was accepted."

$requiredContractPaths = @(Get-RequiredReleaseContractPaths)
Assert-True (
    Test-OrdinalContains -Values $requiredContractPaths -Value "README.md"
) "The canonical README contract path was not found."
Assert-True (
    -not (Test-OrdinalContains -Values $requiredContractPaths -Value "readme.md")
) "A case-mismatched required contract path was accepted."

Assert-True (
    $null -eq (Get-ForbiddenReleasePathReason -RelativePath "plugins/local-knowledge-suite/LICENSE")
) "A safe plugin path was rejected."
foreach ($path in @(
    ".gitattributes",
    ".gitignore",
    "CODEOWNERS",
    "web/app.js.map",
    "scripts/install.cmd",
    "scripts/install.sh"
)) {
    Assert-True (
        $null -eq (Get-ForbiddenReleasePathReason -RelativePath $path)
    ) "A reviewed text path was rejected: $path"
}
foreach ($path in @(
    ".env",
    "config/.env.production",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "_netrc",
    "config/pip.conf",
    "config/pip.ini",
    ".yarnrc.yml",
    "NuGet.Config",
    ".codex/config.toml",
    ".local-knowledge/company.toml",
    ".local-knowledge/project.toml",
    ".local-knowledge/vendor-lock.json",
    ".local-knowledge/backups/state.json",
    ".local-knowledge/memory-snapshot/memory.json",
    "customer/credentials.json",
    "customer/service-account-prod.json",
    "customer/private.pem",
    "customer/company.pdf",
    "customer/financials.xlsx",
    "customer/payload.bin",
    ".ckb/knowledge.db",
    ".memorizer/memory.json",
    "knowledge/reference/customer-policy.md"
)) {
    Assert-True (
        $null -ne (Get-ForbiddenReleasePathReason -RelativePath $path)
    ) "A forbidden release path was accepted: $path"
}

$safeText = "Local Knowledge Suite release policy"
Assert-True (
    @(Get-ForbiddenContentFindings -Text $safeText).Count -eq 0
) "Safe text was rejected."
$githubToken = ("github" + "_pat_" + ("A" * 30))
$gitLabToken = ("gl" + "pat-" + ("A" * 24))
$privateKey = "-----BEGIN " + "PRIVATE KEY-----"
$encryptedPrivateKey = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"
$dsaPrivateKey = "-----BEGIN " + "DSA PRIVATE KEY-----"
$pgpPrivateKey = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"
$awsKey = "AKIA" + ("A" * 16)
$npmToken = "_auth" + "Token=opaque-release-credential"
$encodedPackageCredential = "_auth" + "=b3BhcXVlLXJlbGVhc2UtY3JlZGVudGlhbA=="
$pypiToken = "pypi-" + ("A" * 30)
foreach ($secret in @(
    $githubToken,
    $gitLabToken,
    $privateKey,
    $encryptedPrivateKey,
    $dsaPrivateKey,
    $pgpPrivateKey,
    $awsKey,
    $npmToken,
    $encodedPackageCredential,
    $pypiToken
)) {
    Assert-True (
        @(Get-ForbiddenContentFindings -Text $secret).Count -gt 0
    ) "A synthetic secret fixture was accepted."
}
if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
    $nativePrivatePath = Join-Path $env:USERPROFILE "private.txt"
    $forwardPrivatePath = $nativePrivatePath.Replace("\", "/")
    $jsonPrivatePath = $nativePrivatePath.Replace("\", "\\")
    $fileUriPrivatePath = "file:///" + $forwardPrivatePath
    $encodedPrivatePath = [System.Uri]::EscapeDataString($forwardPrivatePath)
    foreach ($privatePath in @(
        $nativePrivatePath,
        $forwardPrivatePath,
        $jsonPrivatePath,
        $fileUriPrivatePath,
        $encodedPrivatePath
    )) {
        Assert-True (
            @(Get-ForbiddenContentFindings -Text $privatePath).Count -gt 0
        ) "A current user profile path spelling was not rejected: $privatePath"
    }
}

$windowsPowerShellViolations = New-Object System.Collections.Generic.List[string]
foreach ($script in Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.ps1" -File -Recurse) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $script.FullName,
        [ref]$tokens,
        [ref]$errors
    )
    $unsupportedCalls = @(
        $ast.FindAll({
            param($node)

            $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and
                $node.Member.Value -eq "Contains" -and
                $node.Arguments.Count -gt 1 -and
                $node.Arguments[1].Extent.Text -match '\bStringComparison\b'
        }, $true)
    )
    foreach ($call in $unsupportedCalls) {
        $windowsPowerShellViolations.Add(
            "$($script.Name):$($call.Extent.StartLineNumber)"
        )
    }
}
Assert-True (
    $windowsPowerShellViolations.Count -eq 0
) (
    "Windows PowerShell 5.1 does not support string.Contains(value, StringComparison): " +
    ($windowsPowerShellViolations -join ", ")
)

& (Join-Path $PSScriptRoot "Test-ReleaseProvenanceSelfTest.ps1")
& (Join-Path $PSScriptRoot "Test-DeterministicZip.ps1")
& (Join-Path $PSScriptRoot "Test-ThirdPartyLicenseManifestSelfTest.ps1")
& (Join-Path $PSScriptRoot "Test-SbomDependencyCoverageSelfTest.ps1")

Write-Output (
    "Release policy self-test passed strict SemVer, path denylist, secret detection, " +
    "Windows PowerShell 5.1 compatibility, release provenance, and deterministic " +
    "ZIP, third-party license manifest, and SBOM dependency verification."
)
