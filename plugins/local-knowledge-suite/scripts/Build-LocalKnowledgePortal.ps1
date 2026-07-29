# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [string]$RepositoryRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\..\.."
}

if ($env:OS -ne "Windows_NT") {
    throw "The Local Knowledge portal release helper supports native Windows only."
}

$repository = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
$pluginRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$webRoot = Join-Path $repository "web"
$packageJson = Join-Path $webRoot "package.json"
$pnpmLock = Join-Path $repository "pnpm-lock.yaml"
$distRoot = Join-Path $webRoot "dist"
$portalTarget = Join-Path $pluginRoot "runtime\src\local_knowledge\portal"
$runtimePrefix = (Join-Path $pluginRoot "runtime").TrimEnd("\") + "\"

if (-not (Test-Path -LiteralPath $packageJson -PathType Leaf)) {
    throw "Portal package is missing: $packageJson"
}
if (-not (Test-Path -LiteralPath $pnpmLock -PathType Leaf)) {
    throw "Portal lockfile is missing: $pnpmLock"
}
if (-not $portalTarget.StartsWith($runtimePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Portal target escaped the plugin runtime."
}

$pnpm = @(
    Get-Command "pnpm" -All -CommandType Application -ErrorAction Stop
)[0]
$pnpmPath = [string]$pnpm.Source
if (-not (Test-Path -LiteralPath $pnpmPath -PathType Leaf)) {
    throw "Resolved pnpm application is missing: $pnpmPath"
}
& $pnpmPath --dir $repository install --frozen-lockfile
if ($LASTEXITCODE -ne 0) {
    throw "pnpm install failed with code $LASTEXITCODE."
}
& $pnpmPath --dir $repository --filter "@local-knowledge-suite/portal" build
if ($LASTEXITCODE -ne 0) {
    throw "Portal build failed with code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath (Join-Path $distRoot "index.html") -PathType Leaf)) {
    throw "Portal build did not produce dist\index.html."
}

$stage = Join-Path $pluginRoot (".portal-stage-" + [Guid]::NewGuid().ToString("N"))
$backup = Join-Path $pluginRoot (".portal-backup-" + [Guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath $distRoot -Recurse -File) {
        $relative = $file.FullName.Substring($distRoot.TrimEnd("\").Length + 1)
        $destination = Join-Path $stage $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }
    if (-not (Test-Path -LiteralPath (Join-Path $stage "index.html") -PathType Leaf)) {
        throw "Staged portal is incomplete."
    }

    if (Test-Path -LiteralPath $portalTarget) {
        Move-Item -LiteralPath $portalTarget -Destination $backup
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $portalTarget) -Force | Out-Null
    Move-Item -LiteralPath $stage -Destination $portalTarget
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force
    }
    Write-Output "Packaged portal assets at $portalTarget"
}
catch {
    if ((-not (Test-Path -LiteralPath $portalTarget)) -and (Test-Path -LiteralPath $backup)) {
        Move-Item -LiteralPath $backup -Destination $portalTarget
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force
    }
}
