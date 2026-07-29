# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

function Assert-DeterministicZipPathNotReparse {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $pathRoot = [System.IO.Path]::GetPathRoot($fullPath)
    if ([string]::IsNullOrWhiteSpace($pathRoot)) {
        throw "$Label does not have a filesystem root: $Path"
    }
    $cursor = $pathRoot
    foreach ($segment in $fullPath.Substring($pathRoot.Length) -split "[\\/]") {
        if ([string]::IsNullOrWhiteSpace($segment)) {
            continue
        }
        $cursor = Join-Path $cursor $segment
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($null -ne $item -and
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label crosses a junction or symbolic link: $cursor"
        }
    }
    return $fullPath
}

function New-DeterministicZipArchive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDirectory,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    Assert-DeterministicZipPathNotReparse `
        -Path $SourceDirectory `
        -Label "Deterministic ZIP source" |
        Out-Null
    $resolvedSource = (Resolve-Path -LiteralPath $SourceDirectory -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolvedSource -PathType Container)) {
        throw "Deterministic ZIP source is not a directory: $SourceDirectory"
    }

    $sourceRoot = [System.IO.Path]::GetFullPath($resolvedSource)
    $sourcePrefix = $sourceRoot
    if (-not $sourcePrefix.EndsWith([string][System.IO.Path]::DirectorySeparatorChar) -and
        -not $sourcePrefix.EndsWith([string][System.IO.Path]::AltDirectorySeparatorChar)) {
        $sourcePrefix += [System.IO.Path]::DirectorySeparatorChar
    }

    $destination = [System.IO.Path]::GetFullPath($DestinationPath)
    if ($destination.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Deterministic ZIP destination must be outside its source directory."
    }
    $destinationDirectory = [System.IO.Path]::GetDirectoryName($destination)
    if ([string]::IsNullOrWhiteSpace($destinationDirectory)) {
        throw "Deterministic ZIP destination must have a parent directory."
    }
    Assert-DeterministicZipPathNotReparse `
        -Path $destinationDirectory `
        -Label "Deterministic ZIP destination" |
        Out-Null
    [System.IO.Directory]::CreateDirectory($destinationDirectory) | Out-Null
    Assert-DeterministicZipPathNotReparse `
        -Path $destinationDirectory `
        -Label "Created deterministic ZIP destination" |
        Out-Null

    $sourceItems = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force)
    foreach ($item in $sourceItems) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Deterministic ZIP source cannot contain a reparse point: $($item.FullName)"
        }
    }

    [string[]]$entryNames = @(
        $sourceItems |
            Where-Object { -not $_.PSIsContainer } |
            ForEach-Object {
                $fullName = [System.IO.Path]::GetFullPath($_.FullName)
                if (-not $fullName.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Deterministic ZIP source entry escaped its source directory: $fullName"
                }
                $relative = $fullName.Substring($sourcePrefix.Length).Replace("\", "/")
                if ([string]::IsNullOrWhiteSpace($relative) -or
                    $relative.StartsWith("/", [System.StringComparison]::Ordinal) -or
                    $relative.Contains("\")) {
                    throw "Deterministic ZIP source produced an invalid entry path: $relative"
                }
                $relative
            }
    )
    [System.Array]::Sort($entryNames, [System.StringComparer]::Ordinal)

    # Stored entries avoid runtime-specific Deflate output while preserving a
    # standards-compliant ZIP container. All regular files use Unix mode 0644.
    $fixedTimestamp = [System.DateTimeOffset]::new(
        1980,
        1,
        1,
        0,
        0,
        0,
        [System.TimeSpan]::Zero
    )
    $fixedExternalAttributes = [int]-2119958528 # 0100644 << 16 (0x81A40000)
    $temporaryPath = Join-Path (
        $destinationDirectory
    ) (".deterministic-zip-{0}.tmp" -f [System.Guid]::NewGuid().ToString("N"))

    try {
        $archiveStream = [System.IO.File]::Open(
            $temporaryPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        try {
            $archive = [System.IO.Compression.ZipArchive]::new(
                $archiveStream,
                [System.IO.Compression.ZipArchiveMode]::Create,
                $false
            )
            try {
                foreach ($entryName in $entryNames) {
                    $entry = $archive.CreateEntry(
                        $entryName,
                        [System.IO.Compression.CompressionLevel]::NoCompression
                    )
                    $entry.LastWriteTime = $fixedTimestamp
                    $entry.ExternalAttributes = $fixedExternalAttributes

                    $platformRelative = $entryName.Replace(
                        "/",
                        [string][System.IO.Path]::DirectorySeparatorChar
                    )
                    $sourcePath = Join-Path $sourceRoot $platformRelative
                    $sourceStream = [System.IO.File]::Open(
                        $sourcePath,
                        [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::Read,
                        [System.IO.FileShare]::Read
                    )
                    try {
                        $entryStream = $entry.Open()
                        try {
                            $sourceStream.CopyTo($entryStream, 81920)
                        }
                        finally {
                            $entryStream.Dispose()
                        }
                    }
                    finally {
                        $sourceStream.Dispose()
                    }
                }
            }
            finally {
                $archive.Dispose()
            }
        }
        finally {
            $archiveStream.Dispose()
        }

        if ([System.IO.File]::Exists($destination)) {
            [System.IO.File]::Delete($destination)
        }
        [System.IO.File]::Move($temporaryPath, $destination)
    }
    finally {
        if ([System.IO.File]::Exists($temporaryPath)) {
            [System.IO.File]::Delete($temporaryPath)
        }
    }
}

function Assert-DeterministicZipMatchesSource {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDirectory,

        [Parameter(Mandatory = $true)]
        [string]$ArchivePath
    )

    $archive = (Resolve-Path -LiteralPath $ArchivePath -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        throw "Deterministic ZIP verification target is not a file: $ArchivePath"
    }
    $archiveDirectory = [System.IO.Path]::GetDirectoryName($archive)
    $rebuilt = Join-Path $archiveDirectory (
        ".deterministic-verify-{0}.tmp" -f [System.Guid]::NewGuid().ToString("N")
    )
    try {
        New-DeterministicZipArchive `
            -SourceDirectory $SourceDirectory `
            -DestinationPath $rebuilt
        $actualInfo = Get-Item -LiteralPath $archive -Force
        $rebuiltInfo = Get-Item -LiteralPath $rebuilt -Force
        $actualHash = (
            Get-FileHash -LiteralPath $archive -Algorithm SHA256
        ).Hash
        $rebuiltHash = (
            Get-FileHash -LiteralPath $rebuilt -Algorithm SHA256
        ).Hash
        if ($actualInfo.Length -ne $rebuiltInfo.Length -or
            $actualHash -cne $rebuiltHash) {
            throw (
                "ZIP is not byte-identical to the canonical deterministic " +
                "archive for its verified source tree: $archive"
            )
        }
    }
    finally {
        if (Test-Path -LiteralPath $rebuilt) {
            Remove-Item -LiteralPath $rebuilt -Force
        }
    }
}
