# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonReport,

    [Parameter(Mandatory = $true)]
    [string[]]$NodeReport,

    [string]$ThirdPartyNotices,

    [string]$ExpectedPythonReport,

    [string]$ExpectedNodeReport
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ThirdPartyNotices)) {
    $ThirdPartyNotices = Join-Path $PSScriptRoot "..\..\THIRD_PARTY_NOTICES.md"
}
if ([string]::IsNullOrWhiteSpace($ExpectedPythonReport)) {
    $ExpectedPythonReport = Join-Path $PSScriptRoot "expected-python-licenses.json"
}
if ([string]::IsNullOrWhiteSpace($ExpectedNodeReport)) {
    $ExpectedNodeReport = Join-Path $PSScriptRoot "expected-node-licenses.json"
}
$NodeReport = @(
    $NodeReport |
        ForEach-Object { $_ -split "," } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
)

foreach ($path in (
    @($PythonReport) +
    @($NodeReport) +
    @($ThirdPartyNotices) +
    @($ExpectedPythonReport) +
    @($ExpectedNodeReport)
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "License input is missing: $path"
    }
}

$allowedLicenseIds = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($identifier in @(
    "0BSD",
    "Apache-2.0",
    "BlueOak-1.0.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC0-1.0",
    "ISC",
    "MIT",
    "MIT-0",
    "MIT-CMU",
    "MPL-2.0",
    "PSF-2.0",
    "Zlib"
)) {
    [void]$allowedLicenseIds.Add($identifier)
}

function Assert-AllowedLicenseExpression {
    param(
        [Parameter(Mandatory = $true)][string]$Dependency,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Expression
    )

    if ([string]::IsNullOrWhiteSpace($Expression)) {
        throw "$Dependency has an empty license expression."
    }
    $tokenMatches = [Regex]::Matches(
        $Expression,
        '\(|\)|AND|OR|WITH|[0-9A-Za-z][0-9A-Za-z.+-]*'
    )
    $tokens = @($tokenMatches | ForEach-Object { $_.Value })
    $compact = [Regex]::Replace($Expression, '\s+', '')
    if (($tokens -join "") -cne $compact) {
        throw "$Dependency has an invalid or unnormalized license expression: $Expression"
    }

    $depth = 0
    $expectOperand = $true
    foreach ($token in $tokens) {
        if ($expectOperand) {
            if ($token -eq "(") {
                $depth++
                continue
            }
            if ($token -in @(")", "AND", "OR", "WITH")) {
                throw "$Dependency has malformed license syntax: $Expression"
            }
            if (-not $allowedLicenseIds.Contains($token)) {
                throw "$Dependency uses a license outside the explicit allowlist: $token"
            }
            $expectOperand = $false
            continue
        }

        if ($token -eq ")") {
            if ($depth -le 0) {
                throw "$Dependency has unbalanced license parentheses: $Expression"
            }
            $depth--
            continue
        }
        if ($token -in @("AND", "OR")) {
            $expectOperand = $true
            continue
        }
        if ($token -eq "WITH") {
            throw "$Dependency uses an unreviewed SPDX exception: $Expression"
        }
        throw "$Dependency has malformed license syntax: $Expression"
    }
    if ($expectOperand -or $depth -ne 0) {
        throw "$Dependency has an incomplete license expression: $Expression"
    }
}

function Read-LicenseArray {
    param([string]$Path, [string]$Ecosystem)

    try {
        $payload = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "$Ecosystem dependency license report is not valid JSON (${Path}): $($_.Exception.Message)"
    }
    if ($payload -isnot [System.Array] -or @($payload).Count -eq 0) {
        throw "$Ecosystem dependency license report must be a non-empty normalized JSON array: $Path"
    }
    return @($payload)
}

function Assert-NormalizedLicenseReport {
    param(
        [Parameter(Mandatory = $true)][object[]]$Items,
        [Parameter(Mandatory = $true)][string]$Ecosystem,
        [Parameter(Mandatory = $true)][string[]]$AllowedFields
    )

    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($item in $Items) {
        $actualFields = @($item.PSObject.Properties.Name | Sort-Object)
        if (($actualFields -join "`n") -cne (($AllowedFields | Sort-Object) -join "`n")) {
            throw (
                "$Ecosystem dependency license report has unexpected or missing fields: " +
                ($actualFields -join ", ")
            )
        }
        $name = [string]$item.Name
        $version = [string]$item.Version
        $license = [string]$item.License
        if ([string]::IsNullOrWhiteSpace($name) -or
            [string]::IsNullOrWhiteSpace($version) -or
            [string]::IsNullOrWhiteSpace($license)) {
            throw "$Ecosystem dependency license report contains an empty identity or license."
        }
        $identity = "$($name.Trim())@$($version.Trim())"
        if (-not $seen.Add($identity)) {
            throw "$Ecosystem dependency license report contains a duplicate identity: $identity"
        }
        if ($Ecosystem -ceq "Python") {
            if ([string]::IsNullOrWhiteSpace([string]$item.Source)) {
                throw "Python dependency license report contains an empty evidence source: $identity"
            }
            if ([string]$item.Source -cnotin @(
                "License-Expression",
                "License",
                "Classifier",
                "License file"
            )) {
                throw (
                    "Python dependency license report contains an unreviewed " +
                    "evidence source for ${identity}: $($item.Source)"
                )
            }
        }
        elseif ($item.Private -isnot [bool]) {
            throw "Node dependency license report has a non-boolean Private field: $identity"
        }
    }
}

function Assert-ExactLicenseReportMatch {
    param(
        [Parameter(Mandatory = $true)][object[]]$Candidate,
        [Parameter(Mandatory = $true)][object[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Ecosystem,
        [Parameter(Mandatory = $true)][string[]]$Fields
    )

    if ($Candidate.Count -ne $Expected.Count) {
        throw (
            "$Ecosystem dependency license report does not exactly match the " +
            "reviewed inventory: expected $($Expected.Count) entries, found " +
            "$($Candidate.Count)."
        )
    }
    for ($index = 0; $index -lt $Expected.Count; $index++) {
        $candidateItem = $Candidate[$index]
        $expectedItem = $Expected[$index]
        foreach ($field in $Fields) {
            $candidateValue = $candidateItem.$field
            $expectedValue = $expectedItem.$field
            $matches = if ($expectedValue -is [bool]) {
                $candidateValue -is [bool] -and $candidateValue -eq $expectedValue
            }
            else {
                [string]$candidateValue -ceq [string]$expectedValue
            }
            if (-not $matches) {
                $candidateIdentity = "$($candidateItem.Name)@$($candidateItem.Version)"
                $expectedIdentity = "$($expectedItem.Name)@$($expectedItem.Version)"
                throw (
                    "$Ecosystem dependency license report does not exactly match " +
                    "the reviewed inventory at entry $index, field ${field}: " +
                    "expected ${expectedIdentity}, found ${candidateIdentity}."
                )
            }
        }
    }
}

$problems = New-Object System.Collections.Generic.List[string]
$expectedPythonItems = @(
    Read-LicenseArray -Path $ExpectedPythonReport -Ecosystem "Expected Python"
)
Assert-NormalizedLicenseReport `
    -Items $expectedPythonItems `
    -Ecosystem "Python" `
    -AllowedFields @("Name", "Version", "License", "Source")
$pythonItems = @(Read-LicenseArray -Path $PythonReport -Ecosystem "Python")
Assert-NormalizedLicenseReport `
    -Items $pythonItems `
    -Ecosystem "Python" `
    -AllowedFields @("Name", "Version", "License", "Source")
Assert-ExactLicenseReportMatch `
    -Candidate $pythonItems `
    -Expected $expectedPythonItems `
    -Ecosystem "Python" `
    -Fields @("Name", "Version", "License", "Source")
foreach ($item in $pythonItems) {
    $name = [string]$item.Name
    $version = [string]$item.Version
    $license = [string]$item.License
    if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($version)) {
        $problems.Add("python report contains a dependency without name/version")
        continue
    }
    try {
        Assert-AllowedLicenseExpression -Dependency "python:${name}@${version}" -Expression $license
    }
    catch {
        $problems.Add($_.Exception.Message)
    }
}
$requiredBuildInventory = [ordered]@{
    "editables" = "0.5"
    "hatchling" = "1.28.0"
    "packaging" = "26.2"
    "pathspec" = "1.1.1"
    "pluggy" = "1.6.0"
    "trove-classifiers" = "2026.6.1.19"
}
foreach ($entry in $requiredBuildInventory.GetEnumerator()) {
    $matches = @(
        $pythonItems |
            Where-Object {
                [string]$_.Name -ieq [string]$entry.Key -and
                [string]$_.Version -ceq [string]$entry.Value
            }
    )
    if ($matches.Count -ne 1) {
        $problems.Add(
            "python report must contain exact PEP 517 build dependency " +
            "$($entry.Key)@$($entry.Value) once"
        )
    }
}

$expectedNodeItems = @(
    Read-LicenseArray -Path $ExpectedNodeReport -Ecosystem "Expected Node"
)
Assert-NormalizedLicenseReport `
    -Items $expectedNodeItems `
    -Ecosystem "Node" `
    -AllowedFields @("Name", "Version", "License", "Private")
foreach ($path in $NodeReport) {
    $nodeItems = @(Read-LicenseArray -Path $path -Ecosystem "Node")
    Assert-NormalizedLicenseReport `
        -Items $nodeItems `
        -Ecosystem "Node" `
        -AllowedFields @("Name", "Version", "License", "Private")
    Assert-ExactLicenseReportMatch `
        -Candidate $nodeItems `
        -Expected $expectedNodeItems `
        -Ecosystem "Node" `
        -Fields @("Name", "Version", "License", "Private")
    foreach ($item in $nodeItems) {
        $name = [string]$item.Name
        $version = [string]$item.Version
        $license = [string]$item.License
        $isFirstPartyWorkspace = (
            $name -in @(
                "@local-knowledge-suite/portal",
                "@local-knowledge-suite/docs"
            ) -and
            [bool]$item.Private
        )
        if ($isFirstPartyWorkspace) {
            continue
        }
        if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($version)) {
            $problems.Add("node report contains a dependency without name/version")
            continue
        }
        try {
            Assert-AllowedLicenseExpression -Dependency "node:${name}@${version}" -Expression $license
        }
        catch {
            $problems.Add($_.Exception.Message)
        }
    }
}

if ($problems.Count -gt 0) {
    throw "Dependency license policy failed closed:`n - $($problems -join "`n - ")"
}

$notices = Get-Content -LiteralPath $ThirdPartyNotices -Raw -Encoding UTF8
foreach ($requiredNotice in @(
    "pypdfium2",
    "PDFium",
    "editables",
    "Hatchling",
    "pathspec",
    "React DOM",
    "Rollup",
    "hash-verified",
    "Explicit release allowlist",
    "MPL-2.0 is allowed",
    "file-level copyleft"
)) {
    if ($notices -notmatch [Regex]::Escape($requiredNotice)) {
        throw "THIRD_PARTY_NOTICES.md must document: $requiredNotice"
    }
}

Write-Output (
    "Dependency licenses passed the explicit fail-closed allowlist " +
    "(including reviewed MPL-2.0)."
)
