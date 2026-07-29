# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $root "artifacts"
}
$output = (Resolve-Path -LiteralPath $OutputDirectory -ErrorAction Stop).Path
$artifactsRoot = [System.IO.Path]::GetFullPath((Join-Path $root "artifacts"))
$artifactsPrefix = $artifactsRoot.TrimEnd("\") + "\"
if ($output -ne $artifactsRoot -and
    -not $output.StartsWith($artifactsPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must be the repository artifacts directory or one of its children."
}

$checksumPath = Join-Path $output "SHA256SUMS"
$publishedFiles = @(
    Get-ChildItem -LiteralPath $output -File |
        Where-Object { $_.Name -cne "SHA256SUMS" } |
        Sort-Object Name
)
if ($publishedFiles.Count -eq 0) {
    throw "No release assets exist for checksum generation."
}

$lines = @(
    $publishedFiles |
        ForEach-Object {
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $($_.Name)"
        }
)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    $checksumPath,
    (($lines -join "`n") + "`n"),
    $utf8NoBom
)
Write-Output "SHA256SUMS now covers all $($publishedFiles.Count) published release assets."
