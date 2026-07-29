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
$runtime = Join-Path $root "plugins\local-knowledge-suite\runtime"
$uv = Get-Command "uv" -CommandType Application -ErrorAction Stop
$messages = @(
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"release-smoke","version":"1.0.0"}}}',
    '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
    '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
)

function Get-ObservedOutput {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$Lines
    )

    if ($Lines.Count -eq 0) {
        return "(no stdout lines)"
    }
    $text = $Lines -join [Environment]::NewLine
    if ($text.Length -gt 4000) {
        return $text.Substring(0, 4000) + "... (truncated)"
    }
    return $text
}

function Read-JsonRpcResponse {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedId,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$ObservedLines,

        [int]$TimeoutMilliseconds = 15000
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($stopwatch.ElapsedMilliseconds -lt $TimeoutMilliseconds) {
        $remaining = [Math]::Max(
            1,
            $TimeoutMilliseconds - [int]$stopwatch.ElapsedMilliseconds
        )
        $readTask = $Process.StandardOutput.ReadLineAsync()
        if (-not $readTask.Wait($remaining)) {
            $observed = Get-ObservedOutput -Lines $ObservedLines
            throw "Timed out waiting for MCP response id $ExpectedId. Observed: $observed"
        }
        $line = $readTask.Result
        if ($null -eq $line) {
            $observed = Get-ObservedOutput -Lines $ObservedLines
            throw "MCP stdout closed before response id $ExpectedId. Observed: $observed"
        }

        $trimmed = ([string]$line).Trim()
        $trimmed = $trimmed.TrimStart([char]0xFEFF).Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        $ObservedLines.Add($trimmed) | Out-Null
        if (-not $trimmed.StartsWith("{", [System.StringComparison]::Ordinal)) {
            continue
        }
        try {
            $response = $trimmed | ConvertFrom-Json
        }
        catch {
            throw "MCP returned invalid JSON: $trimmed"
        }
        $idProperty = $response.PSObject.Properties["id"]
        if ($null -ne $idProperty -and [string]$idProperty.Value -eq $ExpectedId) {
            return $response
        }
    }
    $observed = Get-ObservedOutput -Lines $ObservedLines
    throw "Timed out waiting for MCP response id $ExpectedId. Observed: $observed"
}

function Write-JsonRpcMessage {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,

        [Parameter(Mandatory = $true)]
        [string]$Message,

        [Parameter(Mandatory = $true)]
        [System.Text.Encoding]$Encoding
    )

    # Windows PowerShell 5.1 can select a host-dependent encoding for the
    # redirected StreamWriter. MCP stdio requires UTF-8 JSON Lines, so write
    # deterministic no-BOM bytes directly to the pipe.
    [byte[]]$payload = $Encoding.GetBytes($Message + "`n")
    $Process.StandardInput.BaseStream.Write($payload, 0, $payload.Length)
    $Process.StandardInput.BaseStream.Flush()
}

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $uv.Source
$startInfo.Arguments = "run --project `"$runtime`" --frozen --python 3.12 python -m local_knowledge.mcp"
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($encodingProperty in @(
    "StandardInputEncoding",
    "StandardOutputEncoding",
    "StandardErrorEncoding"
)) {
    if ($null -ne $startInfo.PSObject.Properties[$encodingProperty]) {
        $startInfo.$encodingProperty = $utf8
    }
}

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo
$observedLines = New-Object "System.Collections.Generic.List[string]"
$stderrTask = $null
$previousConsoleInputEncoding = [Console]::InputEncoding
[Console]::InputEncoding = $utf8

try {
    if (-not $process.Start()) {
        throw "Failed to start the MCP process."
    }
    $stderrTask = $process.StandardError.ReadToEndAsync()

    # MCP requires a real handshake: wait for initialize before notifying the
    # server and requesting its tools. Sending all three messages in one pipe
    # races the server and can lose the initialize response on slower runners.
    Write-JsonRpcMessage -Process $process -Message $messages[0] -Encoding $utf8
    $initialize = Read-JsonRpcResponse `
        -Process $process `
        -ExpectedId "1" `
        -ObservedLines $observedLines

    Write-JsonRpcMessage -Process $process -Message $messages[1] -Encoding $utf8
    Write-JsonRpcMessage -Process $process -Message $messages[2] -Encoding $utf8
    $toolsList = Read-JsonRpcResponse `
        -Process $process `
        -ExpectedId "2" `
        -ObservedLines $observedLines

    $process.StandardInput.Close()
    if (-not $process.WaitForExit(15000)) {
        throw "MCP process did not exit after stdin was closed."
    }
    $process.WaitForExit()
    $stderrText = if ($null -ne $stderrTask -and $stderrTask.Wait(5000)) {
        [string]$stderrTask.Result
    }
    else {
        ""
    }
    if ($process.ExitCode -ne 0) {
        throw "MCP process failed with exit code $($process.ExitCode). $stderrText"
    }

    if (-not $initialize.result.serverInfo) {
        $initializeJson = $initialize | ConvertTo-Json -Compress -Depth 10
        throw "MCP initialize response is invalid: $initializeJson"
    }
    if ($null -eq $toolsList.result.tools) {
        $toolsJson = $toolsList | ConvertTo-Json -Compress -Depth 10
        throw "MCP tools/list response is invalid: $toolsJson"
    }
    $actualNames = @($toolsList.result.tools | ForEach-Object { [string]$_.name } | Sort-Object)
    $expectedNames = @("bootstrap_workspace", "capture_memory", "knowledge_status", "recall_context") | Sort-Object
    if (($actualNames -join ",") -ne ($expectedNames -join ",")) {
        throw "MCP tools differ from the public contract. Expected $($expectedNames -join ', '); got $($actualNames -join ', ')."
    }
    Write-Output "MCP handshake passed with exactly four public tools."
}
catch {
    $primaryError = $_.Exception.Message
    try {
        if (-not $process.HasExited) {
            $process.StandardInput.Close()
            $process.WaitForExit(2000) | Out-Null
        }
    }
    catch {
        # The original handshake error remains authoritative.
    }
    $stderrText = if ($null -ne $stderrTask -and $stderrTask.Wait(2000)) {
        ([string]$stderrTask.Result).Trim()
    }
    else {
        ""
    }
    if ([string]::IsNullOrWhiteSpace($stderrText)) {
        throw $primaryError
    }
    throw "$primaryError`nMCP stderr:`n$stderrText"
}
finally {
    if ($null -ne $process) {
        try {
            if (-not $process.HasExited) {
                $process.StandardInput.Close()
                if (-not $process.WaitForExit(2000)) {
                    $process.Kill()
                    $process.WaitForExit()
                }
            }
        }
        catch {
            # Preserve the original validation error.
        }
        $process.Dispose()
    }
    [Console]::InputEncoding = $previousConsoleInputEncoding
}
