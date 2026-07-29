# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("local-knowledge-license-gate-" + [Guid]::NewGuid().ToString("N"))
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$gate = Join-Path $PSScriptRoot "Test-DependencyLicenses.ps1"
$notices = Join-Path $PSScriptRoot "..\..\THIRD_PARTY_NOTICES.md"

function Write-JsonFixture {
    param([string]$Path, [string]$Json)

    [System.IO.File]::WriteAllText($Path, $Json, $utf8NoBom)
}

function Assert-GateRejects {
    param(
        [string]$PythonReport,
        [string]$NodeReport,
        [string]$ExpectedText,
        [string]$ExpectedPythonReport,
        [string]$ExpectedNodeReport
    )

    if ([string]::IsNullOrWhiteSpace($ExpectedPythonReport)) {
        $ExpectedPythonReport = $PythonReport
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedNodeReport)) {
        $ExpectedNodeReport = $NodeReport
    }

    $rejected = $false
    try {
        & $gate `
            -PythonReport $PythonReport `
            -NodeReport $NodeReport `
            -ThirdPartyNotices $notices `
            -ExpectedPythonReport $ExpectedPythonReport `
            -ExpectedNodeReport $ExpectedNodeReport |
            Out-Null
    }
    catch {
        $rejected = $true
        if ($_.Exception.Message -notmatch [Regex]::Escape($ExpectedText)) {
            throw "License gate rejected for the wrong reason: $($_.Exception.Message)"
        }
    }
    if (-not $rejected) {
        throw "License gate accepted a fixture that must be rejected: $ExpectedText"
    }
}

try {
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    $allowedPython = Join-Path $temporary "python-allowed.json"
    $unknownPython = Join-Path $temporary "python-unknown.json"
    $allowedNode = Join-Path $temporary "node-allowed.json"
    $missingNode = Join-Path $temporary "node-missing.json"
    $gplNode = Join-Path $temporary "node-gpl.json"
    $customNode = Join-Path $temporary "node-custom.json"
    $malformedNode = Join-Path $temporary "node-malformed.json"
    $duplicatePython = Join-Path $temporary "python-duplicate.json"
    $missingPythonField = Join-Path $temporary "python-missing-field.json"
    $extraNodeField = Join-Path $temporary "node-extra-field.json"
    $invalidNodePrivate = Join-Path $temporary "node-invalid-private.json"
    $extraPythonIdentity = Join-Path $temporary "python-extra-identity.json"
    $truncatedNode = Join-Path $temporary "node-truncated.json"
    $arbitraryPythonSource = Join-Path $temporary "python-arbitrary-source.json"

    Write-JsonFixture $allowedPython @'
[
  {"Name":"editables","Version":"0.5","License":"MIT","Source":"Classifier"},
  {"Name":"hatchling","Version":"1.28.0","License":"MIT","Source":"License-Expression"},
  {"Name":"packaging","Version":"26.2","License":"Apache-2.0 OR BSD-2-Clause","Source":"License-Expression"},
  {"Name":"pathspec","Version":"1.1.1","License":"MPL-2.0","Source":"Classifier"},
  {"Name":"pluggy","Version":"1.6.0","License":"MIT","Source":"License"},
  {"Name":"trove-classifiers","Version":"2026.6.1.19","License":"Apache-2.0","Source":"Classifier"},
  {"Name":"mpl-example","Version":"1.0.0","License":"MPL-2.0","Source":"License-Expression"},
  {"Name":"dual-example","Version":"2.0.0","License":"Apache-2.0 OR BSD-3-Clause","Source":"License-Expression"}
]
'@
    Write-JsonFixture $unknownPython '[{"Name":"example","Version":"1.0.0","License":"UNKNOWN","Source":"License"}]'
    Write-JsonFixture $allowedNode @'
[
  {"Name":"example","Version":"1.0.0","License":"MIT","Private":false},
  {"Name":"blue-oak","Version":"2.0.0","License":"BlueOak-1.0.0","Private":false}
]
'@
    Write-JsonFixture $missingNode '[{"Name":"example","Version":"1.0.0","License":"","Private":false}]'
    Write-JsonFixture $gplNode '[{"Name":"example","Version":"1.0.0","License":"GPL-3.0-only","Private":false}]'
    Write-JsonFixture $customNode '[{"Name":"example","Version":"1.0.0","License":"LicenseRef-Proprietary","Private":false}]'
    Write-JsonFixture $malformedNode '[{"Name":"example","Version":"1.0.0","License":"MIT OR","Private":false}]'
    Write-JsonFixture $duplicatePython @'
[
  {"Name":"duplicate","Version":"1.0.0","License":"MIT","Source":"License"},
  {"Name":"duplicate","Version":"1.0.0","License":"MIT","Source":"License"}
]
'@
    Write-JsonFixture $missingPythonField '[{"Name":"example","Version":"1.0.0","License":"MIT"}]'
    Write-JsonFixture $extraNodeField '[{"Name":"example","Version":"1.0.0","License":"MIT","Private":false,"Path":"private"}]'
    Write-JsonFixture $invalidNodePrivate '[{"Name":"example","Version":"1.0.0","License":"MIT","Private":"false"}]'
    Write-JsonFixture $extraPythonIdentity @'
[
  {"Name":"editables","Version":"0.5","License":"MIT","Source":"Classifier"},
  {"Name":"hatchling","Version":"1.28.0","License":"MIT","Source":"License-Expression"},
  {"Name":"packaging","Version":"26.2","License":"Apache-2.0 OR BSD-2-Clause","Source":"License-Expression"},
  {"Name":"pathspec","Version":"1.1.1","License":"MPL-2.0","Source":"Classifier"},
  {"Name":"pluggy","Version":"1.6.0","License":"MIT","Source":"License"},
  {"Name":"trove-classifiers","Version":"2026.6.1.19","License":"Apache-2.0","Source":"Classifier"},
  {"Name":"mpl-example","Version":"1.0.0","License":"MPL-2.0","Source":"License-Expression"},
  {"Name":"dual-example","Version":"2.0.0","License":"Apache-2.0 OR BSD-3-Clause","Source":"License-Expression"},
  {"Name":"unlocked-extra","Version":"9.9.9","License":"MIT","Source":"License"}
]
'@
    Write-JsonFixture $truncatedNode @'
[
  {"Name":"example","Version":"1.0.0","License":"MIT","Private":false}
]
'@
    Write-JsonFixture $arbitraryPythonSource @'
[
  {"Name":"editables","Version":"0.5","License":"MIT","Source":"RegistryGuess"},
  {"Name":"hatchling","Version":"1.28.0","License":"MIT","Source":"License-Expression"},
  {"Name":"packaging","Version":"26.2","License":"Apache-2.0 OR BSD-2-Clause","Source":"License-Expression"},
  {"Name":"pathspec","Version":"1.1.1","License":"MPL-2.0","Source":"Classifier"},
  {"Name":"pluggy","Version":"1.6.0","License":"MIT","Source":"License"},
  {"Name":"trove-classifiers","Version":"2026.6.1.19","License":"Apache-2.0","Source":"Classifier"},
  {"Name":"mpl-example","Version":"1.0.0","License":"MPL-2.0","Source":"License-Expression"},
  {"Name":"dual-example","Version":"2.0.0","License":"Apache-2.0 OR BSD-3-Clause","Source":"License-Expression"}
]
'@

    & $gate `
        -PythonReport $allowedPython `
        -NodeReport $allowedNode `
        -ThirdPartyNotices $notices `
        -ExpectedPythonReport $allowedPython `
        -ExpectedNodeReport $allowedNode |
        Out-Null
    Assert-GateRejects $unknownPython $allowedNode "outside the explicit allowlist"
    Assert-GateRejects $allowedPython $missingNode "empty identity or license"
    Assert-GateRejects $allowedPython $gplNode "outside the explicit allowlist"
    Assert-GateRejects $allowedPython $customNode "outside the explicit allowlist"
    Assert-GateRejects $allowedPython $malformedNode "incomplete license expression"
    Assert-GateRejects $duplicatePython $allowedNode "duplicate identity"
    Assert-GateRejects $missingPythonField $allowedNode "unexpected or missing fields"
    Assert-GateRejects $allowedPython $extraNodeField "unexpected or missing fields"
    Assert-GateRejects $allowedPython $invalidNodePrivate "non-boolean Private"
    Assert-GateRejects `
        $extraPythonIdentity `
        $allowedNode `
        "does not exactly match the reviewed inventory" `
        $allowedPython `
        $allowedNode
    Assert-GateRejects `
        $allowedPython `
        $truncatedNode `
        "does not exactly match the reviewed inventory" `
        $allowedPython `
        $allowedNode
    Assert-GateRejects `
        $arbitraryPythonSource `
        $allowedNode `
        "unreviewed evidence source"
    Write-Output (
        "License gate self-test passed allowed MPL-2.0 and denied unknown, " +
        "forbidden, malformed, duplicate, non-normalized, incomplete, " +
        "extra, and unreviewed evidence."
    )
}
finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
