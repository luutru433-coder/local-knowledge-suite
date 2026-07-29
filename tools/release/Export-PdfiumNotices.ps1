# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,

    [string]$RepositoryRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
if ($env:OS -ne "Windows_NT") {
    throw "PDFium notice export currently targets the Windows wheel only."
}

$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
$runtime = Join-Path $root "plugins\local-knowledge-suite\runtime"
$uv = Get-Command "uv" -CommandType Application -ErrorAction Stop
$python = @'
import importlib.metadata as metadata

dist = metadata.distribution('pypdfium2')
metadata_path = next(
    dist.locate_file(path)
    for path in dist.files
    if path.name == 'METADATA' and '.dist-info' in str(path)
)
print(str(dist.version) + '|' + str(metadata_path.parent))
'@
$result = @(
    & $uv.Source run --project $runtime --frozen --python 3.12 python -c $python
)
if ($LASTEXITCODE -ne 0 -or $result.Count -eq 0) {
    throw "Could not locate the installed pypdfium2 distribution."
}
$identity = ([string]$result[-1]).Trim().Split("|", 2)
if ($identity.Count -ne 2 -or [string]::IsNullOrWhiteSpace($identity[0])) {
    throw "pypdfium2 returned an invalid distribution identity."
}
$version = $identity[0]
$distInfo = (Resolve-Path -LiteralPath $identity[1] -ErrorAction Stop).Path
$licenseRoot = Join-Path $distInfo "licenses"
if (-not (Test-Path -LiteralPath $licenseRoot -PathType Container)) {
    throw "The pypdfium2 wheel does not contain its license directory: $licenseRoot"
}

$destination = [System.IO.Path]::GetFullPath(
    (Join-Path $DestinationRoot "pypdfium2-$version\licenses")
)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$sourcePrefix = $licenseRoot.TrimEnd("\") + "\"
foreach ($file in Get-ChildItem -LiteralPath $licenseRoot -Recurse -File) {
    if (-not $file.FullName.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Wheel license file escaped its source directory."
    }
    $relative = $file.FullName.Substring($sourcePrefix.Length)
    $target = Join-Path $destination $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
}

foreach ($required in @(
    "data\windows_x64\BUILD_LICENSES\pdfium.txt",
    "data\windows_x64\BUILD_LICENSES\pdfium-binaries.txt",
    "LICENSES\Apache-2.0.txt",
    "LICENSES\BSD-3-Clause.txt"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $destination $required) -PathType Leaf)) {
        throw "The pypdfium2 wheel is missing a required upstream notice: $required"
    }
}

Write-Output "Exported exact pypdfium2 $version wheel notices to $destination"
