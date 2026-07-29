# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Sbom-Policy.ps1")

function Assert-Rejected {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $rejected = $false
    try {
        & $Action
    }
    catch {
        $rejected = $true
    }
    if (-not $rejected) {
        throw $Message
    }
}

function Write-JsonFixture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Json
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Json, $utf8NoBom)
}

$pythonReport = @(
    [pscustomobject]@{ Name = "Example_Python"; Version = "1.2.3" }
)
$nodeReport = @(
    [pscustomobject]@{ Name = "@scope/example"; Version = "4.5.6" }
)
$completeComponents = @(
    [pscustomobject]@{
        name = "example-python"
        version = "1.2.3"
        purl = "pkg:pypi/example-python@1.2.3"
    },
    [pscustomobject]@{
        name = "@scope/example"
        version = "4.5.6"
        purl = "pkg:npm/%40scope/example@4.5.6"
    }
)
Assert-SbomDependencyCoverage `
    -Components $completeComponents `
    -PythonReport $pythonReport `
    -NodeReport $nodeReport

Assert-Rejected -Message "An SBOM missing an active Node dependency was accepted." -Action {
    Assert-SbomDependencyCoverage `
        -Components @($completeComponents[0]) `
        -PythonReport $pythonReport `
        -NodeReport $nodeReport
}
Assert-Rejected -Message "A dependency under the wrong package ecosystem was accepted." -Action {
    $wrongEcosystem = @(
        $completeComponents[0],
        [pscustomobject]@{
            name = "@scope/example"
            version = "4.5.6"
            purl = "pkg:pypi/%40scope/example@4.5.6"
        }
    )
    Assert-SbomDependencyCoverage `
        -Components $wrongEcosystem `
        -PythonReport $pythonReport `
        -NodeReport $nodeReport
}
Assert-Rejected -Message "A component whose fields disagree with its purl was accepted." -Action {
    $spoofedComponent = @(
        $completeComponents[0],
        [pscustomobject]@{
            name = "@scope/not-example"
            version = "4.5.6"
            purl = "pkg:npm/%40scope/example@4.5.6"
        }
    )
    Assert-SbomDependencyCoverage `
        -Components $spoofedComponent `
        -PythonReport $pythonReport `
        -NodeReport $nodeReport
}

$temporary = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("local-knowledge-sbom-coverage-" + [Guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    $multipleItems = Join-Path $temporary "multiple-items.json"
    $singleItem = Join-Path $temporary "single-item.json"
    $emptyArray = Join-Path $temporary "empty-array.json"
    $rootObject = Join-Path $temporary "root-object.json"
    $malformed = Join-Path $temporary "malformed.json"

    Write-JsonFixture -Path $multipleItems -Json @'
[
  {"Name":"first","Version":"1.0.0"},
  {"Name":"second","Version":"2.0.0"}
]
'@
    Write-JsonFixture -Path $singleItem -Json @'
[{"Name":"only","Version":"1.0.0"}]
'@
    Write-JsonFixture -Path $emptyArray -Json '[]'
    Write-JsonFixture -Path $rootObject -Json '{"Name":"not-an-array"}'
    Write-JsonFixture -Path $malformed -Json '[{"Name":"truncated"}'

    [object[]]$multiplePayload = @(
        Read-SbomJsonArray `
            -Path $multipleItems `
            -Context "Fixture dependency report"
    )
    if ($multiplePayload.Count -ne 2 -or
        $multiplePayload[0].Name -cne "first" -or
        $multiplePayload[1].Name -cne "second") {
        throw "A file-backed JSON array was not flattened into dependency items."
    }

    [object[]]$singlePayload = @(
        Read-SbomJsonArray `
            -Path $singleItem `
            -Context "Fixture dependency report"
    )
    if ($singlePayload.Count -ne 1 -or
        $singlePayload[0].Name -cne "only") {
        throw "A single-item file-backed JSON array was not preserved."
    }

    Assert-Rejected -Message "An empty file-backed JSON array was accepted." -Action {
        Read-SbomJsonArray `
            -Path $emptyArray `
            -Context "Fixture dependency report"
    }
    Assert-Rejected -Message "A file-backed JSON object was accepted as an array." -Action {
        Read-SbomJsonArray `
            -Path $rootObject `
            -Context "Fixture dependency report"
    }
    Assert-Rejected -Message "Malformed file-backed JSON was accepted." -Action {
        Read-SbomJsonArray `
            -Path $malformed `
            -Context "Fixture dependency report"
    }

    Write-Output (
        "SBOM dependency coverage self-test passed in-memory coverage and " +
        "file-backed JSON array parsing."
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
