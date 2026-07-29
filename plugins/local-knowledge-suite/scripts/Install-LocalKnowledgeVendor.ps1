# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Install", "Verify", "Upgrade")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [string]$PluginRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($PluginRoot)) {
    $PluginRoot = Join-Path $PSScriptRoot ".."
}

$managedStart = "# BEGIN local-knowledge-suite vendored (managed)"
$managedEnd = "# END local-knowledge-suite vendored (managed)"
$managedSkillNames = @(
    "manage-local-knowledge",
    "memorizer",
    "company-knowledge-base"
)
$excludedDirectories = @(
    ".git", ".venv", ".uv-cache", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "node_modules", "tests", "htmlcov"
)

function Resolve-ExistingDirectory {
    param([string]$Path, [string]$Label)

    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw "$Label must be an absolute Windows path."
    }
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "$Label is not a directory: $resolved"
    }
    return $resolved
}

function Test-PathWithin {
    param([string]$Child, [string]$Parent)

    $parentPrefix = $Parent.TrimEnd("\") + "\"
    return $Child.StartsWith($parentPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-PathAtOrWithin {
    param([string]$Child, [string]$Parent)

    $childPath = [System.IO.Path]::GetFullPath($Child).TrimEnd("\")
    $parentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd("\")
    return (
        $childPath.Equals($parentPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        (Test-PathWithin -Child $childPath -Parent $parentPath)
    )
}

function Test-PathEntryExists {
    param([string]$Path)

    return $null -ne (Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
}

function Assert-TrustedExecutablePath {
    param(
        [string]$Path,
        [string]$ProjectRoot,
        [string]$PluginRoot,
        [string]$Label
    )

    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw "$Label must be an absolute Windows path."
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath -notmatch '^[A-Za-z]:\\') {
        throw "$Label must be on a local Windows drive."
    }
    if (Test-PathAtOrWithin -Child $fullPath -Parent $ProjectRoot) {
        throw "$Label must not be controlled by ProjectRoot: $fullPath"
    }
    if (Test-PathAtOrWithin -Child $fullPath -Parent $PluginRoot) {
        throw "$Label must not be controlled by PluginRoot: $fullPath"
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
    param([string]$ProjectRoot, [string]$PluginRoot)

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
                -ProjectRoot $ProjectRoot `
                -PluginRoot $PluginRoot `
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
    param(
        [string]$UvPath,
        [string]$ProjectRoot,
        [string]$PluginRoot
    )

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
        -ProjectRoot $ProjectRoot `
        -PluginRoot $PluginRoot `
        -Label "Python 3.12 interpreter"
    if ([System.IO.Path]::GetExtension($trusted) -cne ".exe") {
        throw "Python 3.12 interpreter must be a native .exe application: $trusted"
    }
    return $trusted
}

function ConvertTo-TomlBasicStringValue {
    param([string]$Value, [string]$Label)

    if ($Value.IndexOf('"') -ge 0 -or $Value.IndexOf("`r") -ge 0 -or
        $Value.IndexOf("`n") -ge 0 -or $Value.IndexOf("`t") -ge 0) {
        throw "$Label contains characters that cannot be represented safely in managed TOML."
    }
    return $Value.Replace("\", "\\")
}

function Assert-NoReparseTraversal {
    param([string]$Root, [string]$Target, [string]$Label)

    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd("\")
    $targetPath = [System.IO.Path]::GetFullPath($Target)
    if (-not (Test-PathWithin -Child $targetPath -Parent $rootPath)) {
        throw "$Label escaped the project root."
    }
    $relative = $targetPath.Substring($rootPath.Length).TrimStart("\")
    $cursor = $rootPath
    foreach ($segment in ($relative -split "[\\/]")) {
        if ([string]::IsNullOrWhiteSpace($segment)) {
            continue
        }
        $cursor = Join-Path $cursor $segment
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label crosses a junction or symbolic link: $cursor"
            }
        }
    }
}

function Assert-NoReparseTree {
    param([string]$Root, [string]$Label)

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return
    }
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($Root)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label contains a junction or symbolic link: $($item.FullName)"
            }
            if ($item.PSIsContainer) {
                $pending.Push($item.FullName)
            }
        }
    }
}

function Get-RelativeSnapshotPath {
    param([string]$Base, [string]$File)

    $prefix = $Base.TrimEnd("\") + "\"
    if (-not $File.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Snapshot file escaped plugin root: $File"
    }
    return $File.Substring($prefix.Length)
}

function Get-SnapshotFiles {
    param([string]$SourceRoot)

    $result = @()
    foreach ($file in Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force -File) {
        $relative = Get-RelativeSnapshotPath -Base $SourceRoot -File $file.FullName
        $parts = $relative -split "[\\/]"
        if (@($parts | Where-Object { $_ -in $excludedDirectories -or $_.StartsWith(".pt-portable-") }).Count -gt 0) {
            continue
        }
        if ($file.Extension -in @(".pyc", ".pyo")) {
            continue
        }
        if ($parts[0] -eq "scripts" -and $file.Extension -ne ".ps1") {
            continue
        }
        if ($file.Name -eq ".coverage") {
            continue
        }
        $result += $file
    }
    return @($result | Sort-Object FullName)
}

function Get-SnapshotHashes {
    param([string]$SnapshotRoot)

    $hashes = [ordered]@{}
    foreach ($file in Get-SnapshotFiles -SourceRoot $SnapshotRoot) {
        $relative = (Get-RelativeSnapshotPath -Base $SnapshotRoot -File $file.FullName).Replace("\", "/")
        $hashes[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $hashes
}

function Copy-Snapshot {
    param([string]$SourceRoot, [string]$DestinationRoot)

    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    foreach ($file in Get-SnapshotFiles -SourceRoot $SourceRoot) {
        $relative = Get-RelativeSnapshotPath -Base $SourceRoot -File $file.FullName
        $destination = Join-Path $DestinationRoot $relative
        $destinationParent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }
}

function Get-TreeInventory {
    param([string]$Root, [string]$Label)

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "$Label is missing: $Root"
    }
    Assert-NoReparseTree -Root $Root -Label $Label
    $files = [ordered]@{}
    $directories = @()
    foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -Force) {
        $relative = (Get-RelativeSnapshotPath -Base $Root -File $item.FullName).Replace("\", "/")
        if ($item.PSIsContainer) {
            $directories += $relative
        }
        else {
            $files[$relative] = (
                Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256
            ).Hash.ToLowerInvariant()
        }
    }
    return [pscustomobject]@{
        files = $files
        directories = @($directories | Sort-Object)
    }
}

function Copy-ExactTree {
    param([string]$SourceRoot, [string]$DestinationRoot, [string]$Label)

    if (Test-PathEntryExists -Path $DestinationRoot) {
        throw "$Label destination already exists: $DestinationRoot"
    }
    $inventory = Get-TreeInventory -Root $SourceRoot -Label $Label
    New-Item -ItemType Directory -Path $DestinationRoot | Out-Null
    foreach ($relative in $inventory.directories) {
        New-Item -ItemType Directory -Path (
            Join-Path $DestinationRoot $relative.Replace("/", "\")
        ) | Out-Null
    }
    foreach ($relative in $inventory.files.Keys) {
        $destination = Join-Path $DestinationRoot $relative.Replace("/", "\")
        $destinationParent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        Copy-Item -LiteralPath (
            Join-Path $SourceRoot $relative.Replace("/", "\")
        ) -Destination $destination
    }
}

function Assert-TreeMatchesReference {
    param(
        [string]$ReferenceRoot,
        [string]$CandidateRoot,
        [string]$Label
    )

    $expected = Get-TreeInventory -Root $ReferenceRoot -Label "$Label source"
    $actual = Get-TreeInventory -Root $CandidateRoot -Label "$Label managed copy"
    $problems = @()
    foreach ($path in $expected.files.Keys) {
        if (-not $actual.files.Contains($path)) {
            $problems += "missing:$path"
        }
        elseif ($actual.files[$path] -ne $expected.files[$path]) {
            $problems += "changed:$path"
        }
    }
    foreach ($path in $actual.files.Keys) {
        if (-not $expected.files.Contains($path)) {
            $problems += "extra:$path"
        }
    }
    $expectedDirectories = @{}
    foreach ($path in $expected.directories) {
        $expectedDirectories[$path] = $true
    }
    $actualDirectories = @{}
    foreach ($path in $actual.directories) {
        $actualDirectories[$path] = $true
    }
    foreach ($path in $expectedDirectories.Keys) {
        if (-not $actualDirectories.ContainsKey($path)) {
            $problems += "missing-directory:$path"
        }
    }
    foreach ($path in $actualDirectories.Keys) {
        if (-not $expectedDirectories.ContainsKey($path)) {
            $problems += "extra-directory:$path"
        }
    }
    if ($problems.Count -gt 0) {
        throw "$Label differs from its locked vendored source: $($problems -join ', ')"
    }
}

function Write-Utf8Atomic {
    param([string]$Path, [string]$Content)

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = "$Path.tmp.$([Guid]::NewGuid().ToString('N'))"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    try {
        [System.IO.File]::WriteAllText($temporary, $Content, $encoding)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Read-VendorLock {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Vendor lock is missing: $Path"
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Vendor lock is invalid: $($_.Exception.Message)"
    }
}

function Assert-SnapshotMatchesLock {
    param(
        [string]$SnapshotRoot,
        [object]$Lock,
        [switch]$AllowLegacySchema
    )

    $supportedSchema = $Lock.schema_version -eq 2 -or (
        $AllowLegacySchema -and $Lock.schema_version -eq 1
    )
    if (-not $supportedSchema -or $Lock.plugin_name -ne "local-knowledge-suite") {
        throw "Unsupported vendor lock identity or schema."
    }
    $expected = @{}
    foreach ($property in $Lock.files.PSObject.Properties) {
        $expected[$property.Name] = [string]$property.Value
    }
    $actual = Get-SnapshotHashes -SnapshotRoot $SnapshotRoot
    $problems = @()
    foreach ($path in $expected.Keys) {
        if (-not $actual.Contains($path)) {
            $problems += "missing:$path"
        }
        elseif ($actual[$path] -ne $expected[$path]) {
            $problems += "changed:$path"
        }
    }
    foreach ($path in $actual.Keys) {
        if (-not $expected.ContainsKey($path)) {
            $problems += "extra:$path"
        }
    }
    if ($problems.Count -gt 0) {
        throw "Vendored snapshot differs from vendor-lock.json: $($problems -join ', ')"
    }
}

function Get-LockManagedSkillNames {
    param([object]$Lock)

    if ($null -eq $Lock.PSObject.Properties["managed_skills"]) {
        return @()
    }
    return @($Lock.managed_skills | ForEach-Object { [string]$_ })
}

function Assert-LockOwnsManagedSkills {
    param([object]$Lock)

    $actual = @(Get-LockManagedSkillNames -Lock $Lock | Sort-Object)
    $expected = @($managedSkillNames | Sort-Object)
    if (($actual -join "`n") -cne ($expected -join "`n")) {
        throw "Vendor lock does not declare exactly the three managed repository skills."
    }
}

function Assert-ManagedSkillCopies {
    param(
        [string]$SnapshotRoot,
        [string]$RepositorySkillRoot,
        [object]$Lock
    )

    Assert-LockOwnsManagedSkills -Lock $Lock
    foreach ($skillName in $managedSkillNames) {
        Assert-TreeMatchesReference `
            -ReferenceRoot (Join-Path $SnapshotRoot "skills\$skillName") `
            -CandidateRoot (Join-Path $RepositorySkillRoot $skillName) `
            -Label "Managed skill $skillName"
    }
}

function New-ManagedConfigBlock {
    param([string]$TrustedUvPath, [string]$TrustedPythonPath)

    $tomlUvPath = ConvertTo-TomlBasicStringValue `
        -Value $TrustedUvPath `
        -Label "uv executable path"
    $tomlPythonPath = ConvertTo-TomlBasicStringValue `
        -Value $TrustedPythonPath `
        -Label "Python interpreter path"
    return @"
$managedStart
[mcp_servers.local-knowledge]
command = "$tomlUvPath"
cwd = ".."
args = ["run", "--no-config", "--no-env-file", "--project", "tools\\local-knowledge-suite\\runtime", "--frozen", "--no-python-downloads", "--python", "$tomlPythonPath", "--", "python", "-I", "-m", "local_knowledge.mcp"]
startup_timeout_sec = 120
tool_timeout_sec = 300
default_tools_approval_mode = "writes"

[mcp_servers.local-knowledge.env]
PYTHONUTF8 = "1"
PYTHONIOENCODING = "utf-8"
$managedEnd
"@
}

function Get-ManagedConfigBlock {
    param([string]$Text)

    $escapedStart = [Regex]::Escape($managedStart)
    $escapedEnd = [Regex]::Escape($managedEnd)
    $startCount = [Regex]::Matches($Text, "(?m)^$escapedStart\s*$").Count
    $endCount = [Regex]::Matches($Text, "(?m)^$escapedEnd\s*$").Count
    if ($startCount -ne 1 -or $endCount -ne 1) {
        throw "Codex config must contain exactly one complete Local Knowledge managed block."
    }
    $match = [Regex]::Match($Text, "(?ms)^$escapedStart\s*\r?\n.*?^$escapedEnd\s*$")
    if (-not $match.Success) {
        throw "Codex config contains a malformed Local Knowledge managed block."
    }
    return $match.Value.Trim()
}

function Assert-ManagedConfigCommandTrust {
    param([string]$ConfigPath, [string]$TrustedUvPath)

    $text = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
    $block = Get-ManagedConfigBlock -Text $text
    $tomlUvPath = ConvertTo-TomlBasicStringValue `
        -Value $TrustedUvPath `
        -Label "uv executable path"
    $expectedCommand = 'command = "' + $tomlUvPath + '"'
    if ($block -notmatch (
            "(?m)^" + [Regex]::Escape($expectedCommand) + "\s*$"
        )) {
        throw (
            "Codex config must use the trusted absolute external uv.exe command: " +
            $TrustedUvPath
        )
    }
}

function Assert-ManagedConfigExact {
    param(
        [string]$ConfigPath,
        [string]$TrustedUvPath,
        [string]$TrustedPythonPath
    )

    $text = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
    $actual = (Get-ManagedConfigBlock -Text $text).Replace("`r`n", "`n")
    $expected = (
        New-ManagedConfigBlock `
            -TrustedUvPath $TrustedUvPath `
            -TrustedPythonPath $TrustedPythonPath
    ).Trim().Replace("`r`n", "`n")
    if (-not $actual.Equals($expected, [System.StringComparison]::Ordinal)) {
        throw "Codex config Local Knowledge managed block differs from the release contract."
    }
}

function Assert-CodexConfigToml {
    param([string]$ConfigPath, [string]$TrustedPythonPath)

    & $TrustedPythonPath -I -c `
        'import pathlib,sys,tomllib; assert sys.version_info[:2] == (3, 12); tomllib.loads(pathlib.Path(sys.argv[1]).read_bytes().decode())' `
        $ConfigPath
    if ($LASTEXITCODE -ne 0) {
        throw "Codex config is not valid TOML: $ConfigPath"
    }
}

function Merge-CodexConfig {
    param(
        [string]$ConfigPath,
        [string]$TrustedUvPath,
        [string]$TrustedPythonPath
    )

    $existing = if (Test-Path -LiteralPath $ConfigPath) {
        Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
    }
    else {
        ""
    }
    $escapedStart = [Regex]::Escape($managedStart)
    $escapedEnd = [Regex]::Escape($managedEnd)
    $startCount = [Regex]::Matches($existing, "(?m)^$escapedStart\s*$").Count
    $endCount = [Regex]::Matches($existing, "(?m)^$escapedEnd\s*$").Count
    if ($startCount -ne $endCount -or $startCount -gt 1) {
        throw "Codex config contains incomplete or duplicate Local Knowledge managed blocks."
    }
    $hasStart = $startCount -eq 1

    $block = New-ManagedConfigBlock `
        -TrustedUvPath $TrustedUvPath `
        -TrustedPythonPath $TrustedPythonPath
    if ($hasStart) {
        $escapedStart = [Regex]::Escape($managedStart)
        $escapedEnd = [Regex]::Escape($managedEnd)
        $pattern = "(?ms)^$escapedStart.*?^$escapedEnd\s*"
        $updated = [Regex]::Replace($existing, $pattern, $block.TrimEnd() + "`r`n")
    }
    else {
        if ($existing -match "(?m)^\s*\[mcp_servers\.local-knowledge\]\s*$") {
            throw "Codex config already defines mcp_servers.local-knowledge outside the managed block."
        }
        if ($existing -match "(?i)local-knowledge-suite[\\/]+skills[\\/]") {
            throw "Codex config already references Local Knowledge skills outside the managed block."
        }
        $separator = if ([string]::IsNullOrWhiteSpace($existing)) { "" } else { "`r`n`r`n" }
        $updated = $existing.TrimEnd() + $separator + $block.TrimEnd() + "`r`n"
    }
    Write-Utf8Atomic -Path $ConfigPath -Content $updated
}

if ($env:OS -ne "Windows_NT") {
    throw "Vendored Local Knowledge Suite supports native Windows only."
}

$project = Resolve-ExistingDirectory -Path $ProjectRoot -Label "ProjectRoot"
$source = Resolve-ExistingDirectory -Path $PluginRoot -Label "PluginRoot"
$projectManifest = Join-Path $project ".local-knowledge\project.toml"
$pluginManifest = Join-Path $source ".codex-plugin\plugin.json"
$runtimeLock = Join-Path $source "runtime\uv.lock"
$vendorRoot = Join-Path $project "tools\local-knowledge-suite"
$metadataRoot = Join-Path $project ".local-knowledge"
$vendorLock = Join-Path $metadataRoot "vendor-lock.json"
$codexConfig = Join-Path $project ".codex\config.toml"
$agentsRoot = Join-Path $project ".agents"
$repositorySkillRoot = Join-Path $agentsRoot "skills"

Assert-NoReparseTraversal -Root $project -Target $metadataRoot -Label "Local Knowledge metadata"
Assert-NoReparseTraversal -Root $project -Target $codexConfig -Label "Codex config"
Assert-NoReparseTraversal -Root $project -Target $vendorRoot -Label "Vendored runtime"
Assert-NoReparseTraversal -Root $project -Target $repositorySkillRoot -Label "Repository skills"
Assert-NoReparseTree -Root $source -Label "Source plugin"
foreach ($skillName in $managedSkillNames) {
    $sourceSkill = Join-Path $source "skills\$skillName"
    if (-not (Test-Path -LiteralPath $sourceSkill -PathType Container)) {
        throw "Source plugin skill is missing: $sourceSkill"
    }
    Assert-NoReparseTree -Root $sourceSkill -Label "Source skill $skillName"
    Assert-NoReparseTraversal `
        -Root $project `
        -Target (Join-Path $repositorySkillRoot $skillName) `
        -Label "Managed skill $skillName"
}

if (-not (Test-Path -LiteralPath $projectManifest -PathType Leaf)) {
    throw "Project manifest is missing. Run `local-knowledge project init --install-mode vendored` first."
}
$projectManifestText = Get-Content -LiteralPath $projectManifest -Raw -Encoding UTF8
if ($projectManifestText -notmatch '(?m)^\s*schema_version\s*=\s*2\s*$') {
    throw "Project manifest must use schema_version 2. Run `local-knowledge project migrate` first."
}
if ($projectManifestText -notmatch '(?m)^\s*install_mode\s*=\s*"vendored"\s*$') {
    throw "Project manifest install_mode must be vendored."
}
$profileMatch = [Regex]::Match(
    $projectManifestText,
    '(?m)^\s*profile\s*=\s*"(combined|memory-only|company-only)"\s*$'
)
if (-not $profileMatch.Success) {
    throw "Project manifest must define a supported profile."
}
$profile = $profileMatch.Groups[1].Value
$hasCompanyId = $projectManifestText -match '(?m)^\s*company_id\s*=\s*"[^"]+"\s*$'
if ($profile -in @("combined", "company-only") -and -not $hasCompanyId) {
    throw "Project profile $profile requires company_id."
}
if (-not (Test-Path -LiteralPath $pluginManifest -PathType Leaf)) {
    throw "Plugin manifest is missing: $pluginManifest"
}
if (-not (Test-Path -LiteralPath $runtimeLock -PathType Leaf)) {
    throw "Pinned runtime lock is missing: $runtimeLock"
}
if ($Action -ne "Verify" -and $source.Equals($vendorRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Install and Upgrade require a source plugin outside the project's vendor target."
}
if (-not (Test-PathWithin -Child $vendorRoot -Parent $project)) {
    throw "Resolved vendor target escaped the project root."
}
$trustedUvPath = Resolve-TrustedUv `
    -ProjectRoot $project `
    -PluginRoot $source
$trustedPythonPath = Resolve-TrustedPython `
    -UvPath $trustedUvPath `
    -ProjectRoot $project `
    -PluginRoot $source

if ($Action -eq "Verify") {
    if (-not (Test-Path -LiteralPath $vendorRoot -PathType Container)) {
        throw "Vendored snapshot is missing: $vendorRoot"
    }
    Assert-NoReparseTree -Root $vendorRoot -Label "Vendored runtime"
    $lock = Read-VendorLock -Path $vendorLock
    Assert-SnapshotMatchesLock -SnapshotRoot $vendorRoot -Lock $lock
    Assert-ManagedSkillCopies `
        -SnapshotRoot $vendorRoot `
        -RepositorySkillRoot $repositorySkillRoot `
        -Lock $lock
    if (-not (Test-Path -LiteralPath $codexConfig -PathType Leaf)) {
        throw "Project Codex config is missing: $codexConfig"
    }
    Assert-ManagedConfigCommandTrust `
        -ConfigPath $codexConfig `
        -TrustedUvPath $trustedUvPath
    Assert-ManagedConfigExact `
        -ConfigPath $codexConfig `
        -TrustedUvPath $trustedUvPath `
        -TrustedPythonPath $trustedPythonPath
    Assert-CodexConfigToml `
        -ConfigPath $codexConfig `
        -TrustedPythonPath $trustedPythonPath
    Write-Output "Verified Local Knowledge Suite $($lock.version) at $vendorRoot"
    return
}

if ($Action -eq "Install" -and (Test-Path -LiteralPath $vendorRoot)) {
    throw "Vendored snapshot already exists. Use -Action Verify or -Action Upgrade."
}
if ($Action -eq "Install") {
    foreach ($skillName in $managedSkillNames) {
        $managedSkill = Join-Path $repositorySkillRoot $skillName
        if (Test-PathEntryExists -Path $managedSkill) {
            throw "Install will not overwrite the pre-existing repository skill: $managedSkill"
        }
    }
}
if ($Action -eq "Upgrade") {
    if (-not (Test-Path -LiteralPath $vendorRoot -PathType Container)) {
        throw "Vendored snapshot is missing. Use -Action Install."
    }
    Assert-NoReparseTree -Root $vendorRoot -Label "Vendored runtime"
    $currentLock = Read-VendorLock -Path $vendorLock
    Assert-SnapshotMatchesLock -SnapshotRoot $vendorRoot -Lock $currentLock -AllowLegacySchema
    $currentManagedSkillNames = @(Get-LockManagedSkillNames -Lock $currentLock)
    if ($currentManagedSkillNames.Count -eq 0) {
        foreach ($skillName in $managedSkillNames) {
            $managedSkill = Join-Path $repositorySkillRoot $skillName
            if (Test-PathEntryExists -Path $managedSkill) {
                throw (
                    "Upgrade cannot claim the pre-existing repository skill because " +
                    "the current vendor lock does not own it: $managedSkill"
                )
            }
        }
    }
    else {
        Assert-LockOwnsManagedSkills -Lock $currentLock
        foreach ($skillName in $managedSkillNames) {
            $managedSkill = Join-Path $repositorySkillRoot $skillName
            if (Test-PathEntryExists -Path $managedSkill) {
                if (-not (Test-Path -LiteralPath $managedSkill -PathType Container)) {
                    throw "Managed skill path is not a directory: $managedSkill"
                }
                Assert-NoReparseTree -Root $managedSkill -Label "Managed skill $skillName"
            }
        }
    }
}

$plugin = Get-Content -LiteralPath $pluginManifest -Raw -Encoding UTF8 | ConvertFrom-Json
if ($plugin.name -ne "local-knowledge-suite" -or [string]::IsNullOrWhiteSpace([string]$plugin.version)) {
    throw "Source plugin manifest has an invalid name or version."
}

New-Item -ItemType Directory -Path $metadataRoot -Force | Out-Null
$transactionRoot = Join-Path $metadataRoot (
    ".vendor-stage-" + [Guid]::NewGuid().ToString("N")
)
$stagedVendor = Join-Path $transactionRoot "vendor"
$stagedSkillRoot = Join-Path $transactionRoot "skills"
$backup = $null
$mutationStarted = $false
$originalConfigExists = Test-Path -LiteralPath $codexConfig -PathType Leaf
$originalConfig = if ($originalConfigExists) {
    Get-Content -LiteralPath $codexConfig -Raw -Encoding UTF8
}
else {
    $null
}
$originalLockExists = Test-Path -LiteralPath $vendorLock -PathType Leaf
$originalLock = if ($originalLockExists) {
    Get-Content -LiteralPath $vendorLock -Raw -Encoding UTF8
}
else {
    $null
}
$agentsRootOriginallyExists = Test-Path -LiteralPath $agentsRoot -PathType Container
$repositorySkillRootOriginallyExists = (
    Test-Path -LiteralPath $repositorySkillRoot -PathType Container
)
$originalSkillExists = @{}
foreach ($skillName in $managedSkillNames) {
    $originalSkillExists[$skillName] = Test-Path -LiteralPath (
        Join-Path $repositorySkillRoot $skillName
    ) -PathType Container
}

try {
    Copy-Snapshot -SourceRoot $source -DestinationRoot $stagedVendor
    $stagedHashes = Get-SnapshotHashes -SnapshotRoot $stagedVendor
    if ($stagedHashes.Count -eq 0) {
        throw "Source plugin snapshot is empty."
    }
    foreach ($skillName in $managedSkillNames) {
        Copy-ExactTree `
            -SourceRoot (Join-Path $stagedVendor "skills\$skillName") `
            -DestinationRoot (Join-Path $stagedSkillRoot $skillName) `
            -Label "Staged skill $skillName"
        Assert-TreeMatchesReference `
            -ReferenceRoot (Join-Path $stagedVendor "skills\$skillName") `
            -CandidateRoot (Join-Path $stagedSkillRoot $skillName) `
            -Label "Staged skill $skillName"
    }

    $sameSnapshot = $false
    if ($Action -eq "Upgrade" -and $currentLock.version -eq $plugin.version) {
        $sameSnapshot = $true
        foreach ($key in $stagedHashes.Keys) {
            $property = $currentLock.files.PSObject.Properties[$key]
            if ($null -eq $property -or [string]$property.Value -ne $stagedHashes[$key]) {
                $sameSnapshot = $false
                break
            }
        }
        if ($currentLock.files.PSObject.Properties.Count -ne $stagedHashes.Count) {
            $sameSnapshot = $false
        }
        if (-not $sameSnapshot) {
            throw "Source files changed without a plugin version change. Bump the plugin version before Upgrade."
        }

        $installationAlreadyCurrent = $true
        try {
            Assert-ManagedSkillCopies `
                -SnapshotRoot $vendorRoot `
                -RepositorySkillRoot $repositorySkillRoot `
                -Lock $currentLock
            Assert-ManagedConfigCommandTrust `
                -ConfigPath $codexConfig `
                -TrustedUvPath $trustedUvPath
            Assert-ManagedConfigExact `
                -ConfigPath $codexConfig `
                -TrustedUvPath $trustedUvPath `
                -TrustedPythonPath $trustedPythonPath
        }
        catch {
            $installationAlreadyCurrent = $false
        }
        if ($installationAlreadyCurrent) {
            Write-Output "Vendored snapshot is already current at version $($plugin.version)."
            return
        }
    }

    if ($Action -eq "Upgrade") {
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            throw "LOCALAPPDATA is unavailable; cannot create the required upgrade backup."
        }
        $backupBase = Join-Path $env:LOCALAPPDATA "LocalKnowledgeSuite\vendor-backups"
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            $projectBytes = [Text.Encoding]::UTF8.GetBytes($project)
            $projectHash = $sha256.ComputeHash($projectBytes)
            $projectKey = (
                -join @($projectHash | ForEach-Object { $_.ToString("x2") })
            ).Substring(0, 16)
        }
        finally {
            $sha256.Dispose()
        }
        $backup = Join-Path $backupBase (
            "$projectKey\$($currentLock.version)-" +
            "$(Get-Date -Format 'yyyyMMdd-HHmmss')-" +
            [Guid]::NewGuid().ToString("N").Substring(0, 8)
        )
        $backupVendor = Join-Path $backup "vendor"
        Copy-Snapshot -SourceRoot $vendorRoot -DestinationRoot $backupVendor
        Assert-SnapshotMatchesLock `
            -SnapshotRoot $backupVendor `
            -Lock $currentLock `
            -AllowLegacySchema
        $backupSkillPresence = [ordered]@{}
        foreach ($skillName in $managedSkillNames) {
            $backupSkillPresence[$skillName] = [bool]$originalSkillExists[$skillName]
            if ($originalSkillExists[$skillName]) {
                Copy-ExactTree `
                    -SourceRoot (Join-Path $repositorySkillRoot $skillName) `
                    -DestinationRoot (Join-Path $backup "skills\$skillName") `
                    -Label "Backup skill $skillName"
            }
        }
        if ($originalConfigExists) {
            $backupConfig = Join-Path $backup ".codex\config.toml"
            New-Item -ItemType Directory -Path (Split-Path -Parent $backupConfig) -Force |
                Out-Null
            Copy-Item -LiteralPath $codexConfig -Destination $backupConfig
        }
        if ($originalLockExists) {
            $backupLock = Join-Path $backup ".local-knowledge\vendor-lock.json"
            New-Item -ItemType Directory -Path (Split-Path -Parent $backupLock) -Force |
                Out-Null
            Copy-Item -LiteralPath $vendorLock -Destination $backupLock
        }
        $backupState = [ordered]@{
            schema_version = 1
            project_root = $project
            vendor_version = [string]$currentLock.version
            config_existed = $originalConfigExists
            managed_skills = $backupSkillPresence
        }
        Write-Utf8Atomic `
            -Path (Join-Path $backup "backup-state.json") `
            -Content (($backupState | ConvertTo-Json -Depth 5) + "`n")
    }

    $mutationStarted = $true
    if (Test-PathEntryExists -Path $vendorRoot) {
        Remove-Item -LiteralPath $vendorRoot -Recurse -Force
    }
    foreach ($skillName in $managedSkillNames) {
        $managedSkill = Join-Path $repositorySkillRoot $skillName
        if (Test-PathEntryExists -Path $managedSkill) {
            Remove-Item -LiteralPath $managedSkill -Recurse -Force
        }
    }

    New-Item -ItemType Directory -Path (Split-Path -Parent $vendorRoot) -Force |
        Out-Null
    New-Item -ItemType Directory -Path $repositorySkillRoot -Force | Out-Null
    Move-Item -LiteralPath $stagedVendor -Destination $vendorRoot
    foreach ($skillName in $managedSkillNames) {
        Move-Item `
            -LiteralPath (Join-Path $stagedSkillRoot $skillName) `
            -Destination (Join-Path $repositorySkillRoot $skillName)
    }

    $lockPayload = [ordered]@{
        schema_version = 2
        plugin_name = "local-knowledge-suite"
        version = [string]$plugin.version
        managed_skills = $managedSkillNames
        files = $stagedHashes
    }
    Write-Utf8Atomic `
        -Path $vendorLock `
        -Content (($lockPayload | ConvertTo-Json -Depth 8) + "`n")
    Merge-CodexConfig `
        -ConfigPath $codexConfig `
        -TrustedUvPath $trustedUvPath `
        -TrustedPythonPath $trustedPythonPath

    $installedLock = Read-VendorLock -Path $vendorLock
    Assert-SnapshotMatchesLock -SnapshotRoot $vendorRoot -Lock $installedLock
    Assert-ManagedSkillCopies `
        -SnapshotRoot $vendorRoot `
        -RepositorySkillRoot $repositorySkillRoot `
        -Lock $installedLock
    Assert-ManagedConfigCommandTrust `
        -ConfigPath $codexConfig `
        -TrustedUvPath $trustedUvPath
    Assert-ManagedConfigExact `
        -ConfigPath $codexConfig `
        -TrustedUvPath $trustedUvPath `
        -TrustedPythonPath $trustedPythonPath
    Assert-CodexConfigToml `
        -ConfigPath $codexConfig `
        -TrustedPythonPath $trustedPythonPath

    $message = "$Action complete: Local Knowledge Suite $($plugin.version) at $vendorRoot"
    if ($backup) {
        $message += ". Previous snapshot and managed skills backed up to $backup"
    }
    Write-Output $message
}
catch {
    $failure = $_
    if ($mutationStarted) {
        $rollbackProblems = New-Object System.Collections.Generic.List[string]
        try {
            if (Test-PathEntryExists -Path $vendorRoot) {
                Remove-Item -LiteralPath $vendorRoot -Recurse -Force
            }
            if ($Action -eq "Upgrade") {
                Copy-Snapshot `
                    -SourceRoot (Join-Path $backup "vendor") `
                    -DestinationRoot $vendorRoot
            }
        }
        catch {
            $rollbackProblems.Add("vendor: $($_.Exception.Message)")
        }
        foreach ($skillName in $managedSkillNames) {
            try {
                $managedSkill = Join-Path $repositorySkillRoot $skillName
                if (Test-PathEntryExists -Path $managedSkill) {
                    Remove-Item -LiteralPath $managedSkill -Recurse -Force
                }
                if ($Action -eq "Upgrade" -and $originalSkillExists[$skillName]) {
                    Copy-ExactTree `
                        -SourceRoot (Join-Path $backup "skills\$skillName") `
                        -DestinationRoot $managedSkill `
                        -Label "Restored skill $skillName"
                }
            }
            catch {
                $rollbackProblems.Add("$skillName`: $($_.Exception.Message)")
            }
        }
        try {
            if ($originalLockExists) {
                Write-Utf8Atomic -Path $vendorLock -Content $originalLock
            }
            elseif (Test-PathEntryExists -Path $vendorLock) {
                Remove-Item -LiteralPath $vendorLock -Force
            }
        }
        catch {
            $rollbackProblems.Add("vendor lock: $($_.Exception.Message)")
        }
        try {
            if ($originalConfigExists) {
                Write-Utf8Atomic -Path $codexConfig -Content $originalConfig
            }
            elseif (Test-PathEntryExists -Path $codexConfig) {
                Remove-Item -LiteralPath $codexConfig -Force
            }
        }
        catch {
            $rollbackProblems.Add("Codex config: $($_.Exception.Message)")
        }
        try {
            if (-not $repositorySkillRootOriginallyExists -and
                (Test-Path -LiteralPath $repositorySkillRoot -PathType Container) -and
                @(Get-ChildItem -LiteralPath $repositorySkillRoot -Force).Count -eq 0) {
                Remove-Item -LiteralPath $repositorySkillRoot -Force
            }
            if (-not $agentsRootOriginallyExists -and
                (Test-Path -LiteralPath $agentsRoot -PathType Container) -and
                @(Get-ChildItem -LiteralPath $agentsRoot -Force).Count -eq 0) {
                Remove-Item -LiteralPath $agentsRoot -Force
            }
        }
        catch {
            $rollbackProblems.Add("empty skill parents: $($_.Exception.Message)")
        }
        if ($rollbackProblems.Count -gt 0) {
            throw (
                "Vendored operation failed and rollback was incomplete. " +
                "Original error: $($failure.Exception.Message). " +
                "Rollback errors: $($rollbackProblems -join '; ')"
            )
        }
    }
    throw $failure
}
finally {
    if (Test-PathEntryExists -Path $transactionRoot) {
        Remove-Item -LiteralPath $transactionRoot -Recurse -Force
    }
}
