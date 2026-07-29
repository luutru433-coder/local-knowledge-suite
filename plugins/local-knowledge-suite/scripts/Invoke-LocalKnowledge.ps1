# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [ValidateSet("local-knowledge", "memorizer", "ckb", "mcp")]
    [string]$Tool = "local-knowledge",

    [string]$Root,

    [string[]]$ToolArguments = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "Local Knowledge Suite supports native Windows only."
}

function Test-PathWithin {
    param([string]$Child, [string]$Parent)

    $parentPrefix = $Parent.TrimEnd("\") + "\"
    return $Child.StartsWith(
        $parentPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Test-PathAtOrWithin {
    param([string]$Child, [string]$Parent)

    $childPath = [System.IO.Path]::GetFullPath($Child).TrimEnd("\")
    $parentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd("\")
    return (
        $childPath.Equals(
            $parentPath,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        (Test-PathWithin -Child $childPath -Parent $parentPath)
    )
}

function Test-PathEntryExists {
    param([string]$Path)

    return $null -ne (
        Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    )
}

function Test-ProjectControlledAncestor {
    param([string]$Path)

    $cursor = if (Test-Path -LiteralPath $Path -PathType Container) {
        [System.IO.Path]::GetFullPath($Path)
    }
    else {
        Split-Path -Parent ([System.IO.Path]::GetFullPath($Path))
    }
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if ((Test-PathEntryExists -Path (Join-Path $cursor ".git")) -or
            (Test-PathEntryExists -Path (
                Join-Path $cursor ".local-knowledge\project.toml"
            )) -or
            (Test-PathEntryExists -Path (Join-Path $cursor ".memorizer")) -or
            (Test-PathEntryExists -Path (Join-Path $cursor ".ckb"))) {
            return $true
        }
        $parent = [System.IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) {
            break
        }
        if ($parent.FullName.Equals(
            $cursor,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            break
        }
        $cursor = $parent.FullName
    }
    return $false
}

function Assert-TrustedExecutablePath {
    param(
        [string]$Path,
        [string[]]$ControlledRoots,
        [string]$Label
    )

    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw "$Label must be an absolute Windows path."
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath -notmatch '^[A-Za-z]:\\') {
        throw "$Label must be on a local Windows drive."
    }
    foreach ($controlledRoot in $ControlledRoots) {
        if (-not [string]::IsNullOrWhiteSpace($controlledRoot) -and
            (Test-PathAtOrWithin -Child $fullPath -Parent $controlledRoot)) {
            throw "$Label must not be project or plugin controlled: $fullPath"
        }
    }
    $pathSegments = $fullPath.Substring(3) -split "[\\/]"
    if (@(
            $pathSegments |
                Where-Object { $_.Equals(
                    ".venv",
                    [System.StringComparison]::OrdinalIgnoreCase
                ) }
        ).Count -gt 0) {
        throw "$Label must not come from a .venv directory: $fullPath"
    }
    if (Test-ProjectControlledAncestor -Path $fullPath) {
        throw "$Label must not come from a project-controlled tree: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "$Label is not an executable file: $fullPath"
    }

    $pathRoot = [System.IO.Path]::GetPathRoot($fullPath).TrimEnd("\") + "\"
    $relative = $fullPath.Substring($pathRoot.Length)
    $cursor = $pathRoot
    foreach ($segment in ($relative -split "[\\/]")) {
        if ([string]::IsNullOrWhiteSpace($segment)) {
            continue
        }
        $cursor = Join-Path $cursor $segment
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label crosses a junction or symbolic link: $cursor"
        }
    }
    return $fullPath
}

function Resolve-TrustedUv {
    param([string[]]$ControlledRoots)

    $commands = @(
        Get-Command "uv" -All -CommandType Application -ErrorAction SilentlyContinue
    )
    $rejections = @()
    $seen = @{}
    foreach ($command in $commands) {
        $candidate = [string]$command.Source
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        try {
            $candidate = [System.IO.Path]::GetFullPath($candidate)
            if ($seen.ContainsKey($candidate)) {
                continue
            }
            $seen[$candidate] = $true
            $trusted = Assert-TrustedExecutablePath `
                -Path $candidate `
                -ControlledRoots $ControlledRoots `
                -Label "uv executable"
            if ([System.IO.Path]::GetExtension($trusted) -cne ".exe") {
                throw "uv executable must be a native .exe application: $trusted"
            }
            return $trusted
        }
        catch {
            $rejections += $_.Exception.Message
        }
    }
    $detail = if ($rejections.Count -gt 0) {
        " Rejected candidates: $($rejections -join '; ')"
    }
    else {
        ""
    }
    throw "No trusted external uv.exe application was found on PATH.$detail"
}

function Resolve-TrustedPython {
    param([string]$UvPath, [string[]]$ControlledRoots)

    $isolatedEnvironmentNames = @(
        "CONDA_PREFIX",
        "PYTHONHOME",
        "PYTHONPATH",
        "UV_CONFIG_FILE",
        "UV_PROJECT",
        "UV_PYTHON",
        "VIRTUAL_ENV"
    )
    $savedEnvironment = @{}
    $pythonOutput = @()
    $uvExitCode = $null
    try {
        foreach ($name in $isolatedEnvironmentNames) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable(
                $name,
                [EnvironmentVariableTarget]::Process
            )
            [Environment]::SetEnvironmentVariable(
                $name,
                $null,
                [EnvironmentVariableTarget]::Process
            )
        }
        $pythonOutput = @(
            & $UvPath python find `
                --no-project `
                --no-config `
                --system `
                --no-cache `
                --no-python-downloads `
                --resolve-links `
                --color never `
                3.12
        )
        $uvExitCode = $LASTEXITCODE
    }
    finally {
        foreach ($name in $isolatedEnvironmentNames) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $savedEnvironment[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
    }
    if ($uvExitCode -ne 0 -or $pythonOutput.Count -eq 0) {
        throw "Trusted uv could not resolve a system Python 3.12 interpreter."
    }
    $candidate = [string]$pythonOutput[$pythonOutput.Count - 1]
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        throw "Trusted uv returned an empty Python interpreter path."
    }
    $trusted = Assert-TrustedExecutablePath `
        -Path $candidate.Trim() `
        -ControlledRoots $ControlledRoots `
        -Label "Python 3.12 interpreter"
    if ([System.IO.Path]::GetExtension($trusted) -cne ".exe") {
        throw "Python 3.12 interpreter must be a native .exe application: $trusted"
    }
    return $trusted
}

$pluginRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = Join-Path $pluginRoot "runtime"
$runtimeLock = Join-Path $runtimeRoot "uv.lock"

if (-not (Test-Path -LiteralPath $runtimeLock -PathType Leaf)) {
    throw "Pinned runtime lock is missing: $runtimeLock"
}

$entryArguments = @()
$resolvedRoot = $null
if ($Tool -in @("memorizer", "ckb")) {
    if ([string]::IsNullOrWhiteSpace($Root)) {
        throw "-Root is required when -Tool is $Tool."
    }
    if (-not [System.IO.Path]::IsPathRooted($Root)) {
        throw "-Root must be an absolute Windows path."
    }
    $resolvedRoot = (Resolve-Path -LiteralPath $Root -ErrorAction Stop).Path
    $entryArguments += @("--root", $resolvedRoot)
}
elseif (-not [string]::IsNullOrWhiteSpace($Root)) {
    throw "Pass project or company roots inside -ToolArguments for the local-knowledge CLI."
}

$entryArguments += $ToolArguments
$controlledRoots = @(
    $pluginRoot,
    (Get-Location).Path
)
if ($null -ne $resolvedRoot) {
    $controlledRoots += $resolvedRoot
}
$trustedUvPath = Resolve-TrustedUv -ControlledRoots $controlledRoots
$trustedPythonPath = Resolve-TrustedPython `
    -UvPath $trustedUvPath `
    -ControlledRoots $controlledRoots
$module = switch ($Tool) {
    "local-knowledge" { "local_knowledge.cli" }
    "memorizer" { "local_knowledge.memorizer.cli" }
    "ckb" { "local_knowledge.ckb.cli" }
    "mcp" { "local_knowledge.mcp" }
}
$uvArguments = @(
    "run",
    "--no-config",
    "--no-env-file",
    "--project", $runtimeRoot,
    "--frozen",
    "--no-python-downloads",
    "--python", $trustedPythonPath,
    "--",
    "python",
    "-I",
    "-m",
    $module
) + $entryArguments

$previousPythonUtf8 = $env:PYTHONUTF8
$previousPythonIoEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    & $trustedUvPath @uvArguments
    $exitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
}

if ($exitCode -ne 0) {
    throw "$Tool exited with code $exitCode."
}
