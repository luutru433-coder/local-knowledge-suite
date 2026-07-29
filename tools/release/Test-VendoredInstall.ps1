# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [string]$RepositoryRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot "..\.."
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
$pluginRoot = Join-Path $root "plugins\local-knowledge-suite"
$installer = Join-Path $pluginRoot "scripts\Install-LocalKnowledgeVendor.ps1"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Vendored installer is missing: $installer"
}

$managedSkillNames = @(
    "manage-local-knowledge",
    "memorizer",
    "company-knowledge-base"
)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function New-SmokeProject {
    param([string]$Path, [string]$ProjectId)

    New-Item -ItemType Directory -Path (Join-Path $Path ".local-knowledge") -Force |
        Out-Null
    [System.IO.File]::WriteAllText(
        (Join-Path $Path ".local-knowledge\project.toml"),
        @"
schema_version = 2
project_id = "$ProjectId"
profile = "memory-only"
install_mode = "vendored"
"@,
        $utf8NoBom
    )
}

function Assert-OperationFails {
    param(
        [string]$Label,
        [scriptblock]$Operation,
        [string]$MessagePattern
    )

    $failed = $false
    try {
        & $Operation | Out-Null
    }
    catch {
        $failed = $true
        if ($_.Exception.Message.IndexOf(
            $MessagePattern,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -lt 0) {
            throw "$Label failed for the wrong reason: $($_.Exception.Message)"
        }
    }
    if (-not $failed) {
        throw "$Label unexpectedly succeeded."
    }
}

function Get-DirectoryFingerprint {
    param([string]$Path)

    $base = [System.IO.Path]::GetFullPath($Path).TrimEnd("\") + "\"
    $rows = @()
    foreach ($file in Get-ChildItem -LiteralPath $Path -Recurse -Force -File |
        Sort-Object FullName) {
        $relative = $file.FullName.Substring($base.Length).Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        $rows += "$relative=$hash"
    }
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($rows -join "`n")
        return -join @(
            $sha256.ComputeHash($bytes) |
                ForEach-Object { $_.ToString("x2") }
        )
    }
    finally {
        $sha256.Dispose()
    }
}

function Set-PluginVersion {
    param([string]$SourceRoot, [string]$Version)

    $manifestPath = Join-Path $SourceRoot ".codex-plugin\plugin.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $manifest.version = $Version
    [System.IO.File]::WriteAllText(
        $manifestPath,
        (($manifest | ConvertTo-Json -Depth 10) + "`n"),
        $utf8NoBom
    )
}

function New-SentinelApplication {
    param([string]$Path)

    New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force |
        Out-Null
    $typeName = "LocalKnowledgeSentinel" + [Guid]::NewGuid().ToString("N")
    $source = @"
using System;
using System.IO;

public static class $typeName
{
    public static int Main(string[] args)
    {
        string sentinel = Environment.GetEnvironmentVariable(
            "LOCAL_KNOWLEDGE_EXECUTABLE_SENTINEL"
        );
        if (!String.IsNullOrWhiteSpace(sentinel))
        {
            File.AppendAllText(
                sentinel,
                Path.GetFileName(Environment.GetCommandLineArgs()[0]) +
                    Environment.NewLine
            );
        }
        return 91;
    }
}
"@
    Add-Type `
        -TypeDefinition $source `
        -Language CSharp `
        -OutputAssembly $Path `
        -OutputType ConsoleApplication |
        Out-Null
}

function Write-McpJsonLine {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    [byte[]]$payload = $utf8NoBom.GetBytes($Message + "`n")
    $Process.StandardInput.BaseStream.Write($payload, 0, $payload.Length)
    $Process.StandardInput.BaseStream.Flush()
}

function Read-McpJsonResponse {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedId,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$ObservedLines,

        [int]$TimeoutMilliseconds = 30000
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($stopwatch.ElapsedMilliseconds -lt $TimeoutMilliseconds) {
        $remaining = [Math]::Max(
            1,
            $TimeoutMilliseconds - [int]$stopwatch.ElapsedMilliseconds
        )
        $readTask = $Process.StandardOutput.ReadLineAsync()
        if (-not $readTask.Wait($remaining)) {
            throw (
                "Timed out waiting for plugin MCP response id $ExpectedId. " +
                "Observed: $($ObservedLines -join [Environment]::NewLine)"
            )
        }
        $line = $readTask.Result
        if ($null -eq $line) {
            throw (
                "Plugin MCP stdout closed before response id $ExpectedId. " +
                "Observed: $($ObservedLines -join [Environment]::NewLine)"
            )
        }
        $trimmed = ([string]$line).Trim()
        $trimmed = $trimmed.TrimStart([char]0xFEFF).Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        $ObservedLines.Add($trimmed) | Out-Null
        try {
            $response = $trimmed | ConvertFrom-Json
        }
        catch {
            throw "Plugin MCP emitted non-JSON stdout: $trimmed"
        }
        $idProperty = $response.PSObject.Properties["id"]
        if ($null -ne $idProperty -and [string]$idProperty.Value -eq $ExpectedId) {
            return $response
        }
    }
    throw (
        "Timed out waiting for plugin MCP response id $ExpectedId. " +
        "Observed: $($ObservedLines -join [Environment]::NewLine)"
    )
}

$temporaryBase = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
).TrimEnd("\")
$smokeRoot = Join-Path $temporaryBase (
    "local-knowledge-vendor-smoke-" + [Guid]::NewGuid().ToString("N")
)
$smokePath = [System.IO.Path]::GetFullPath($smokeRoot)
$smokeLocalAppData = [System.IO.Path]::GetFullPath(
    (Join-Path $temporaryBase (
        "lkv-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
    ))
)
$temporaryPrefix = $temporaryBase + "\"
if (-not $smokePath.StartsWith(
    $temporaryPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
) -or -not $smokeLocalAppData.StartsWith(
    $temporaryPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Vendored smoke root escaped the temporary directory."
}

$originalLocalAppData = $env:LOCALAPPDATA
$originalUvCache = $env:UV_CACHE_DIR
$originalPath = $env:Path
$originalExecutableSentinel = $env:LOCAL_KNOWLEDGE_EXECUTABLE_SENTINEL
$originalModuleSentinel = $env:LOCAL_KNOWLEDGE_MODULE_SENTINEL
try {
    New-Item -ItemType Directory -Path $smokePath | Out-Null
    $env:LOCALAPPDATA = $smokeLocalAppData
    $workspaceUvCache = Join-Path $root ".uv-cache"
    if (Test-Path -LiteralPath $workspaceUvCache -PathType Container) {
        $env:UV_CACHE_DIR = $workspaceUvCache
    }

    $projectPath = Join-Path $smokePath "project"
    New-SmokeProject `
        -Path $projectPath `
        -ProjectId "00000000-0000-4000-8000-000000000001"

    $sentinelPath = Join-Path $projectPath "project-executable-invoked.txt"
    $fakeUvPath = Join-Path $projectPath "uv.exe"
    $fakeCmdPath = Join-Path $projectPath "cmd.exe"
    $fakePowerShellPath = Join-Path $projectPath "powershell.exe"
    $fakePythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
    $setupUvPath = @(
        Get-Command "uv" -All -CommandType Application -ErrorAction Stop
    )[0].Source
    & $setupUvPath venv `
        --no-project `
        --no-config `
        --no-cache `
        --no-python-downloads `
        --python 3.12 `
        (Join-Path $projectPath ".venv") |
        Out-Null
    if ($LASTEXITCODE -ne 0 -or
        -not (Test-Path -LiteralPath $fakePythonPath -PathType Leaf)) {
        throw "Sentinel smoke could not create its project-local Python environment."
    }
    $siteCustomizePath = Join-Path (
        $projectPath
    ) ".venv\Lib\site-packages\sitecustomize.py"
    [System.IO.File]::WriteAllText(
        $siteCustomizePath,
        @"
import os
import pathlib

sentinel = os.environ.get("LOCAL_KNOWLEDGE_EXECUTABLE_SENTINEL")
if sentinel:
    pathlib.Path(sentinel).write_text("project .venv python.exe", encoding="utf-8")
"@,
        $utf8NoBom
    )
    New-SentinelApplication -Path $fakeUvPath
    Copy-Item -LiteralPath $fakeUvPath -Destination $fakeCmdPath
    Copy-Item -LiteralPath $fakeUvPath -Destination $fakePowerShellPath
    $env:LOCAL_KNOWLEDGE_EXECUTABLE_SENTINEL = $sentinelPath
    $env:Path = $projectPath + [System.IO.Path]::PathSeparator + $originalPath
    $firstUvCandidate = @(
        Get-Command "uv" -All -CommandType Application -ErrorAction Stop
    )[0].Source
    if (-not $firstUvCandidate.Equals(
        $fakeUvPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Sentinel smoke did not place the project-controlled uv.exe first on PATH."
    }

    $unrelatedSkill = Join-Path $projectPath ".agents\skills\unrelated-skill"
    New-Item -ItemType Directory -Path $unrelatedSkill -Force | Out-Null
    $unrelatedSkillPath = Join-Path $unrelatedSkill "SKILL.md"
    [System.IO.File]::WriteAllText(
        $unrelatedSkillPath,
        "---`nname: unrelated-skill`ndescription: Preserve this user skill.`n---`n",
        $utf8NoBom
    )
    $unrelatedSkillBefore = [System.IO.File]::ReadAllBytes($unrelatedSkillPath)

    Push-Location $projectPath
    try {
        & $installer -Action Install -ProjectRoot $projectPath -PluginRoot $pluginRoot
    }
    finally {
        Pop-Location
    }
    if (Test-Path -LiteralPath $sentinelPath) {
        throw (
            "Install invoked a project-controlled uv or .venv Python executable: " +
            (Get-Content -LiteralPath $sentinelPath -Raw -Encoding UTF8)
        )
    }
    $env:Path = $originalPath

    $vendoredRoot = Join-Path $projectPath "tools\local-knowledge-suite"
    $vendoredInstaller = Join-Path (
        $vendoredRoot
    ) "scripts\Install-LocalKnowledgeVendor.ps1"
    if (-not (Test-Path -LiteralPath $vendoredInstaller -PathType Leaf)) {
        throw "Install did not copy the vendored installer."
    }

    $repositorySkillRoot = Join-Path $projectPath ".agents\skills"
    foreach ($skillName in $managedSkillNames) {
        $skillPath = Join-Path $repositorySkillRoot $skillName
        $skillItem = Get-Item -LiteralPath $skillPath -Force
        if (-not $skillItem.PSIsContainer -or
            ($skillItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-Path -LiteralPath (Join-Path $skillPath "SKILL.md") -PathType Leaf)) {
            throw "Install did not materialize a real repository skill: $skillName"
        }
    }
    if (-not [System.Linq.Enumerable]::SequenceEqual(
        [byte[]]$unrelatedSkillBefore,
        [byte[]][System.IO.File]::ReadAllBytes($unrelatedSkillPath)
    )) {
        throw "Install changed an unrelated repository skill."
    }

    $lockPath = Join-Path $projectPath ".local-knowledge\vendor-lock.json"
    $lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($lock.schema_version -ne 2 -or
        $lock.plugin_name -cne "local-knowledge-suite" -or
        (@($lock.managed_skills | Sort-Object) -join ",") -cne
        (@($managedSkillNames | Sort-Object) -join ",")) {
        throw "Vendored smoke produced an invalid vendor lock."
    }

    $configPath = Join-Path $projectPath ".codex\config.toml"
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
    if ($config -notmatch '(?m)^\[mcp_servers\.local-knowledge\]\s*$' -or
        $config -notmatch '(?m)^command = "[A-Za-z]:\\\\[^"]*\\uv\.exe"\s*$' -or
        $config -match '(?m)^command = "uv"\s*$' -or
        $config -notmatch '(?m)^cwd = "\.\."\s*$' -or
        $config.IndexOf(
            '"--project", "tools\\local-knowledge-suite\\runtime"',
            [System.StringComparison]::Ordinal
        ) -lt 0 -or
        $config.IndexOf(
            '"--no-config", "--no-env-file"',
            [System.StringComparison]::Ordinal
        ) -lt 0 -or
        $config -notmatch '"--python", "[A-Za-z]:\\\\[^"]*\\python\.exe"' -or
        $config.Contains($projectPath.Replace("\", "\\")) -or
        $config -match '(?m)^\s*\[\[skills\.config\]\]\s*$') {
        throw "Vendored smoke produced an invalid MCP-only Codex config."
    }

    $configuredUvMatch = [Regex]::Match(
        $config,
        '(?m)^command = "([^"]+)"\s*$'
    )
    $configuredPythonMatch = [Regex]::Match(
        $config,
        '"--python", "([^"]+)"'
    )
    if (-not $configuredUvMatch.Success -or -not $configuredPythonMatch.Success) {
        throw "Vendored MCP config omitted its pinned executable paths."
    }
    $configuredUvPath = $configuredUvMatch.Groups[1].Value.Replace("\\", "\")
    $configuredPythonPath = (
        $configuredPythonMatch.Groups[1].Value.Replace("\\", "\")
    )
    $moduleSentinelPath = Join-Path $projectPath "module-shadow-invoked.txt"
    $shadowPackageRoot = Join-Path $projectPath "local_knowledge"
    New-Item -ItemType Directory -Path $shadowPackageRoot -Force | Out-Null
    [System.IO.File]::WriteAllText(
        (Join-Path $shadowPackageRoot "__init__.py"),
        "",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $shadowPackageRoot "mcp.py"),
        @"
import os
import pathlib

sentinel = os.environ.get("LOCAL_KNOWLEDGE_MODULE_SENTINEL")
if sentinel:
    pathlib.Path(sentinel).write_text("project module shadowed runtime", encoding="utf-8")
raise SystemExit(91)
"@,
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $shadowPackageRoot "cli.py"),
        @"
import os
import pathlib

sentinel = os.environ.get("LOCAL_KNOWLEDGE_MODULE_SENTINEL")
if sentinel:
    pathlib.Path(sentinel).write_text("project CLI module shadowed runtime", encoding="utf-8")
raise SystemExit(92)
"@,
        $utf8NoBom
    )
    $env:LOCAL_KNOWLEDGE_MODULE_SENTINEL = $moduleSentinelPath
    $mcpArguments = @(
        "run",
        "--no-config",
        "--no-env-file",
        "--project",
        (Join-Path $pluginRoot "runtime"),
        "--frozen",
        "--no-python-downloads",
        "--python",
        $configuredPythonPath
    )
    if ($config -match '"--module", "local_knowledge\.mcp"') {
        $mcpArguments += @("--module", "local_knowledge.mcp")
    }
    else {
        $mcpArguments += @("--", "python", "-I", "-m", "local_knowledge.mcp")
    }
    Push-Location $projectPath
    try {
        & $configuredUvPath @mcpArguments
        $mcpExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if (Test-Path -LiteralPath $moduleSentinelPath) {
        throw "Vendored MCP imported a project-controlled local_knowledge package."
    }
    if ($mcpExitCode -ne 0) {
        throw "Vendored MCP isolated runtime smoke failed with exit code $mcpExitCode."
    }
    if ($config -notmatch (
            '"--", "python", "-I", "-m", "local_knowledge\.mcp"'
        )) {
        throw "Vendored MCP config did not require isolated Python module execution."
    }

    $env:Path = $projectPath + [System.IO.Path]::PathSeparator + $originalPath
    $projectMarker = Join-Path $projectPath ".local-knowledge\project.toml"
    $disabledProjectMarker = $projectMarker + ".disabled"
    Move-Item -LiteralPath $projectMarker -Destination $disabledProjectMarker
    Push-Location $projectPath
    try {
        & (Join-Path $pluginRoot "scripts\Invoke-LocalKnowledge.ps1") `
            -Tool local-knowledge `
            -ToolArguments @("--help") |
            Out-Null
    }
    finally {
        Pop-Location
        $env:Path = $originalPath
        Move-Item -LiteralPath $disabledProjectMarker -Destination $projectMarker
    }
    if ((Test-Path -LiteralPath $sentinelPath) -or
        (Test-Path -LiteralPath $moduleSentinelPath)) {
        throw (
            "Invoke-LocalKnowledge used a project-controlled uv, .venv Python, " +
            "or local_knowledge CLI module."
        )
    }

    $pluginMcpPath = Join-Path $pluginRoot ".mcp.json"
    $pluginMcp = Get-Content -LiteralPath $pluginMcpPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $mcpServerProperties = @($pluginMcp.mcpServers.PSObject.Properties)
    if ($mcpServerProperties.Count -ne 1 -or
        $mcpServerProperties[0].Name -cne "local-knowledge") {
        throw "Plugin MCP manifest must define exactly local-knowledge."
    }
    $mcpServer = $pluginMcp.mcpServers."local-knowledge"
    if ($mcpServer.command -cne "cmd.exe" -or
        @($mcpServer.args).Count -ne 4 -or
        $mcpServer.args[0] -cne "/d" -or
        $mcpServer.args[1] -cne "/s" -or
        $mcpServer.args[2] -cne "/c" -or
        $mcpServer.args[3] -notmatch
            '%SystemRoot%\\System32\\WindowsPowerShell\\v1\.0\\powershell\.exe' -or
        $mcpServer.args[3] -notmatch
            'Invoke-LocalKnowledge\.ps1" -Tool mcp') {
        throw "Plugin MCP manifest did not use the trusted Windows launcher contract."
    }

    $env:Path = $projectPath + [System.IO.Path]::PathSeparator + $originalPath
    try {
        $firstCmdCandidate = @(
            Get-Command "cmd.exe" -All -CommandType Application -ErrorAction Stop
        )[0].Source
        $firstPowerShellCandidate = @(
            Get-Command "powershell.exe" -All -CommandType Application -ErrorAction Stop
        )[0].Source
        if (-not $firstCmdCandidate.Equals(
                $fakeCmdPath,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            -not $firstPowerShellCandidate.Equals(
                $fakePowerShellPath,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            throw "MCP launcher sentinel executables were not first on PATH."
        }

        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = [string]$mcpServer.command
        $startInfo.WorkingDirectory = $pluginRoot
        $startInfo.Arguments = (
            "/d /s /c " + [string]$mcpServer.args[3]
        )
        $startInfo.UseShellExecute = $false
        $startInfo.RedirectStandardInput = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        foreach ($encodingProperty in @(
            "StandardInputEncoding",
            "StandardOutputEncoding",
            "StandardErrorEncoding"
        )) {
            if ($null -ne $startInfo.PSObject.Properties[$encodingProperty]) {
                $startInfo.$encodingProperty = $utf8NoBom
            }
        }
        $mcpProcess = New-Object System.Diagnostics.Process
        $mcpProcess.StartInfo = $startInfo
        $mcpStderrTask = $null
        $mcpObservedLines = New-Object "System.Collections.Generic.List[string]"
        $previousConsoleInputEncoding = [Console]::InputEncoding
        [Console]::InputEncoding = $utf8NoBom
        $mcpMessages = @(
            [ordered]@{
                jsonrpc = "2.0"
                id = 1
                method = "initialize"
                params = [ordered]@{
                    protocolVersion = "2025-06-18"
                    capabilities = @{}
                    clientInfo = [ordered]@{
                        name = "vendored-launcher-smoke"
                        version = "1.0"
                    }
                }
            },
            [ordered]@{
                jsonrpc = "2.0"
                method = "notifications/initialized"
                params = @{}
            },
            [ordered]@{
                jsonrpc = "2.0"
                id = 2
                method = "tools/list"
                params = @{}
            }
        )
        try {
            [void]$mcpProcess.Start()
            $mcpStderrTask = $mcpProcess.StandardError.ReadToEndAsync()

            Write-McpJsonLine `
                -Process $mcpProcess `
                -Message ($mcpMessages[0] | ConvertTo-Json -Depth 8 -Compress)
            $initializeResponse = Read-McpJsonResponse `
                -Process $mcpProcess `
                -ExpectedId "1" `
                -ObservedLines $mcpObservedLines

            Write-McpJsonLine `
                -Process $mcpProcess `
                -Message ($mcpMessages[1] | ConvertTo-Json -Depth 8 -Compress)
            Write-McpJsonLine `
                -Process $mcpProcess `
                -Message ($mcpMessages[2] | ConvertTo-Json -Depth 8 -Compress)
            $toolsResponse = Read-McpJsonResponse `
                -Process $mcpProcess `
                -ExpectedId "2" `
                -ObservedLines $mcpObservedLines

            $mcpProcess.StandardInput.Close()
            if (-not $mcpProcess.WaitForExit(120000)) {
                throw "Plugin MCP launcher handshake timed out after 120 seconds."
            }
            $mcpProcess.WaitForExit()
            $mcpStderr = if (
                $null -ne $mcpStderrTask -and
                $mcpStderrTask.Wait(5000)
            ) {
                [string]$mcpStderrTask.Result
            }
            else {
                ""
            }
            if ($mcpProcess.ExitCode -ne 0) {
                throw (
                    "Plugin MCP launcher exited with code $($mcpProcess.ExitCode). " +
                    "stderr: $mcpStderr"
                )
            }

            $initializeResultProperty = $initializeResponse.PSObject.Properties["result"]
            $serverInfoProperty = if ($null -ne $initializeResultProperty) {
                $initializeResultProperty.Value.PSObject.Properties["serverInfo"]
            }
            else {
                $null
            }
            if ($null -eq $serverInfoProperty) {
                throw (
                    "Plugin MCP initialize response was invalid. " +
                    ($initializeResponse | ConvertTo-Json -Depth 10 -Compress)
                )
            }
            $toolsResultProperty = $toolsResponse.PSObject.Properties["result"]
            $toolsProperty = if ($null -ne $toolsResultProperty) {
                $toolsResultProperty.Value.PSObject.Properties["tools"]
            }
            else {
                $null
            }
            if ($null -eq $toolsProperty) {
                throw (
                    "Plugin MCP tools/list response was invalid. " +
                    ($toolsResponse | ConvertTo-Json -Depth 10 -Compress)
                )
            }
            $expectedToolNames = @(
                "bootstrap_workspace",
                "capture_memory",
                "knowledge_status",
                "recall_context"
            )
            $actualToolNames = @(
                $toolsProperty.Value |
                    ForEach-Object { [string]$_.name } |
                    Sort-Object
            )
            if (($actualToolNames -join "`n") -cne
                    (($expectedToolNames | Sort-Object) -join "`n")) {
                throw (
                    "Plugin MCP handshake did not expose exactly four tools. " +
                    "stdout: $($mcpObservedLines -join [Environment]::NewLine); " +
                    "stderr: $mcpStderr"
                )
            }
        }
        catch {
            $primaryError = $_.Exception.Message
            try {
                if (-not $mcpProcess.HasExited) {
                    $mcpProcess.StandardInput.Close()
                    $mcpProcess.WaitForExit(2000) | Out-Null
                }
            }
            catch {
            }
            $mcpStderr = if (
                $null -ne $mcpStderrTask -and
                $mcpStderrTask.Wait(2000)
            ) {
                ([string]$mcpStderrTask.Result).Trim()
            }
            else {
                ""
            }
            if ([string]::IsNullOrWhiteSpace($mcpStderr)) {
                throw $primaryError
            }
            throw "$primaryError`nPlugin MCP stderr:`n$mcpStderr"
        }
        finally {
            try {
                if (-not $mcpProcess.HasExited) {
                    $mcpProcess.StandardInput.Close()
                    if (-not $mcpProcess.WaitForExit(2000)) {
                        $mcpProcess.Kill()
                        $mcpProcess.WaitForExit()
                    }
                }
            }
            catch {
            }
            $mcpProcess.Dispose()
            [Console]::InputEncoding = $previousConsoleInputEncoding
        }
    }
    finally {
        $env:Path = $originalPath
    }
    if ((Test-Path -LiteralPath $sentinelPath) -or
        (Test-Path -LiteralPath $moduleSentinelPath)) {
        throw (
            "Plugin MCP launcher invoked a project-controlled cmd, PowerShell, " +
            "uv, .venv Python, or local_knowledge module."
        )
    }

    & $vendoredInstaller `
        -Action Verify `
        -ProjectRoot $projectPath `
        -PluginRoot $vendoredRoot

    $trustedConfigBytes = [System.IO.File]::ReadAllBytes($configPath)
    $bareUvConfig = [Regex]::Replace(
        $config,
        '(?m)^command = ".*"\s*$',
        'command = "uv"'
    )
    [System.IO.File]::WriteAllText($configPath, $bareUvConfig, $utf8NoBom)
    Assert-OperationFails `
        -Label "Bare uv command verification" `
        -MessagePattern "trusted absolute external uv.exe" `
        -Operation {
            & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
                -PluginRoot $vendoredRoot
        }
    [System.IO.File]::WriteAllBytes($configPath, $trustedConfigBytes)

    $projectUvConfig = [Regex]::Replace(
        $config,
        '(?m)^command = ".*"\s*$',
        ('command = "' + $fakeUvPath.Replace("\", "\\") + '"')
    )
    [System.IO.File]::WriteAllText($configPath, $projectUvConfig, $utf8NoBom)
    Assert-OperationFails `
        -Label "Project-controlled uv command verification" `
        -MessagePattern "trusted absolute external uv.exe" `
        -Operation {
            & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
                -PluginRoot $vendoredRoot
        }
    [System.IO.File]::WriteAllBytes($configPath, $trustedConfigBytes)
    if (Test-Path -LiteralPath $sentinelPath) {
        throw "Verification invoked a rejected project-controlled executable."
    }
    & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
        -PluginRoot $vendoredRoot

    $tamperedSkillFile = Join-Path $repositorySkillRoot "memorizer\SKILL.md"
    $originalSkillBytes = [System.IO.File]::ReadAllBytes($tamperedSkillFile)
    [System.IO.File]::AppendAllText(
        $tamperedSkillFile,
        "`nTampered.`n",
        $utf8NoBom
    )
    Assert-OperationFails `
        -Label "Modified managed skill verification" `
        -MessagePattern "changed:SKILL.md" `
        -Operation {
            & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
                -PluginRoot $vendoredRoot
        }
    [System.IO.File]::WriteAllBytes($tamperedSkillFile, $originalSkillBytes)

    $extraSkillFile = Join-Path $repositorySkillRoot "memorizer\extra.txt"
    [System.IO.File]::WriteAllText($extraSkillFile, "extra", $utf8NoBom)
    Assert-OperationFails `
        -Label "Extra managed skill file verification" `
        -MessagePattern "extra:extra.txt" `
        -Operation {
            & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
                -PluginRoot $vendoredRoot
        }
    Remove-Item -LiteralPath $extraSkillFile -Force

    $extraSkillDirectory = Join-Path $repositorySkillRoot "memorizer\empty-extra"
    New-Item -ItemType Directory -Path $extraSkillDirectory | Out-Null
    Assert-OperationFails `
        -Label "Extra managed skill directory verification" `
        -MessagePattern "extra-directory:empty-extra" `
        -Operation {
            & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
                -PluginRoot $vendoredRoot
        }
    Remove-Item -LiteralPath $extraSkillDirectory -Force

    $missingSkillBackup = Join-Path $projectPath "missing-skill-file.bak"
    Move-Item -LiteralPath $tamperedSkillFile -Destination $missingSkillBackup
    Assert-OperationFails `
        -Label "Missing managed skill file verification" `
        -MessagePattern "missing:SKILL.md" `
        -Operation {
            & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
                -PluginRoot $vendoredRoot
        }
    Move-Item -LiteralPath $missingSkillBackup -Destination $tamperedSkillFile
    & $vendoredInstaller -Action Verify -ProjectRoot $projectPath `
        -PluginRoot $vendoredRoot

    $collisionProject = Join-Path $smokePath "collision-project"
    New-SmokeProject `
        -Path $collisionProject `
        -ProjectId "00000000-0000-4000-8000-000000000002"
    $collisionSkill = Join-Path $collisionProject ".agents\skills\memorizer"
    New-Item -ItemType Directory -Path $collisionSkill -Force | Out-Null
    $collisionFile = Join-Path $collisionSkill "SKILL.md"
    [System.IO.File]::WriteAllText(
        $collisionFile,
        "user-owned skill",
        $utf8NoBom
    )
    $collisionBytes = [System.IO.File]::ReadAllBytes($collisionFile)
    Assert-OperationFails `
        -Label "Pre-existing managed-name skill install" `
        -MessagePattern "will not overwrite" `
        -Operation {
            & $installer -Action Install -ProjectRoot $collisionProject `
                -PluginRoot $pluginRoot
        }
    if ((Test-Path -LiteralPath (
            Join-Path $collisionProject "tools\local-knowledge-suite"
        )) -or
        -not [System.Linq.Enumerable]::SequenceEqual(
            [byte[]]$collisionBytes,
            [byte[]][System.IO.File]::ReadAllBytes($collisionFile)
        )) {
        throw "Collision-safe install changed project state."
    }

    $upgradeSource = Join-Path $smokePath "upgrade-source-1.0.1"
    Copy-Item -LiteralPath $vendoredRoot -Destination $upgradeSource -Recurse
    Set-PluginVersion -SourceRoot $upgradeSource -Version "1.0.1"
    $upgradeInstaller = Join-Path (
        $upgradeSource
    ) "scripts\Install-LocalKnowledgeVendor.ps1"
    & $upgradeInstaller -Action Upgrade -ProjectRoot $projectPath `
        -PluginRoot $upgradeSource

    $upgradedLock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($upgradedLock.version -cne "1.0.1") {
        throw "Upgrade did not install the requested source version."
    }
    if (-not [System.Linq.Enumerable]::SequenceEqual(
        [byte[]]$unrelatedSkillBefore,
        [byte[]][System.IO.File]::ReadAllBytes($unrelatedSkillPath)
    )) {
        throw "Upgrade changed an unrelated repository skill."
    }
    $backupStates = @(
        Get-ChildItem -LiteralPath (
            Join-Path $env:LOCALAPPDATA "LocalKnowledgeSuite\vendor-backups"
        ) -Recurse -Force -Filter "backup-state.json" -File
    )
    if ($backupStates.Count -ne 1) {
        throw "Successful upgrade did not create exactly one complete backup."
    }
    $backupRoot = Split-Path -Parent $backupStates[0].FullName
    foreach ($skillName in $managedSkillNames) {
        if (-not (Test-Path -LiteralPath (
                Join-Path $backupRoot "skills\$skillName\SKILL.md"
            ) -PathType Leaf)) {
            throw "Upgrade backup omitted managed skill: $skillName"
        }
    }
    & (Join-Path $vendoredRoot "scripts\Install-LocalKnowledgeVendor.ps1") `
        -Action Verify -ProjectRoot $projectPath -PluginRoot $vendoredRoot

    $rollbackSource = Join-Path $smokePath "upgrade-source-1.0.2"
    Copy-Item -LiteralPath $vendoredRoot -Destination $rollbackSource -Recurse
    Set-PluginVersion -SourceRoot $rollbackSource -Version "1.0.2"
    $validConfigBytes = [System.IO.File]::ReadAllBytes($configPath)
    [System.IO.File]::AppendAllText(
        $configPath,
        "`n# BEGIN local-knowledge-suite vendored (managed)`n",
        $utf8NoBom
    )
    $vendorBeforeRollback = Get-DirectoryFingerprint -Path $vendoredRoot
    $skillsBeforeRollback = Get-DirectoryFingerprint -Path $repositorySkillRoot
    $lockBeforeRollback = [System.IO.File]::ReadAllBytes($lockPath)
    $configBeforeRollback = [System.IO.File]::ReadAllBytes($configPath)
    Assert-OperationFails `
        -Label "Atomic upgrade rollback" `
        -MessagePattern "incomplete or duplicate" `
        -Operation {
            & (Join-Path $rollbackSource "scripts\Install-LocalKnowledgeVendor.ps1") `
                -Action Upgrade -ProjectRoot $projectPath -PluginRoot $rollbackSource
        }
    if ((Get-DirectoryFingerprint -Path $vendoredRoot) -cne $vendorBeforeRollback -or
        (Get-DirectoryFingerprint -Path $repositorySkillRoot) -cne
            $skillsBeforeRollback -or
        -not [System.Linq.Enumerable]::SequenceEqual(
            [byte[]]$lockBeforeRollback,
            [byte[]][System.IO.File]::ReadAllBytes($lockPath)
        ) -or
        -not [System.Linq.Enumerable]::SequenceEqual(
            [byte[]]$configBeforeRollback,
            [byte[]][System.IO.File]::ReadAllBytes($configPath)
        )) {
        throw "Failed upgrade did not restore vendor, skills, lock, and config exactly."
    }
    [System.IO.File]::WriteAllBytes($configPath, $validConfigBytes)
    & (Join-Path $vendoredRoot "scripts\Install-LocalKnowledgeVendor.ps1") `
        -Action Verify -ProjectRoot $projectPath -PluginRoot $vendoredRoot

    if (Test-Path -LiteralPath $sentinelPath) {
        throw "Vendored lifecycle invoked a project-controlled executable."
    }
    Write-Output (
        "Vendored installer smoke passed install, discovery layout, four-tool " +
        "MCP handshake, cmd/PowerShell/uv/Python/module isolation, verify tamper " +
        "checks, collision safety, upgrade backup, and rollback."
    )
}
finally {
    $env:LOCALAPPDATA = $originalLocalAppData
    $env:UV_CACHE_DIR = $originalUvCache
    $env:Path = $originalPath
    $env:LOCAL_KNOWLEDGE_EXECUTABLE_SENTINEL = $originalExecutableSentinel
    $env:LOCAL_KNOWLEDGE_MODULE_SENTINEL = $originalModuleSentinel
    if (Test-Path -LiteralPath $smokePath) {
        Remove-Item -LiteralPath $smokePath -Recurse -Force
    }
    if (Test-Path -LiteralPath $smokeLocalAppData) {
        Remove-Item -LiteralPath $smokeLocalAppData -Recurse -Force
    }
}
