# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Deterministic-Zip.ps1")

function Assert-True {
    param([bool]$Condition, [string]$Message)

    if (-not $Condition) {
        throw $Message
    }
}

function Remove-TestJunction {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) {
        return
    }
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
        throw "Refusing to remove a non-junction self-test path: $Path"
    }
    [System.IO.Directory]::Delete([System.IO.Path]::GetFullPath($Path))
}

$testRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("local-knowledge-deterministic-zip-{0}" -f [System.Guid]::NewGuid().ToString("N"))
$treeOne = Join-Path $testRoot "tree-one"
$treeTwo = Join-Path $testRoot "tree-two"
$archiveOne = Join-Path $testRoot "one.zip"
$archiveTwo = Join-Path $testRoot "two.zip"
$tamperedArchive = Join-Path $testRoot "tampered.zip"
$symlinkArchive = Join-Path $testRoot "symlink-mode.zip"
$junctionRoot = Join-Path $testRoot "junction-source"
$junctionArchive = Join-Path $testRoot "junction-source.zip"

try {
    foreach ($tree in @($treeOne, $treeTwo)) {
        New-Item -ItemType Directory -Path (Join-Path $tree "nested") -Force | Out-Null
    }

    $fixtures = [ordered]@{
        "z-last.txt" = [byte[]](90, 10)
        "nested/alpha.txt" = [byte[]](65, 108, 112, 104, 97, 10)
        "nested/binary.dat" = [byte[]](0, 1, 2, 127, 128, 255)
    }
    foreach ($relative in @($fixtures.Keys)) {
        $path = Join-Path $treeOne $relative.Replace("/", "\")
        [System.IO.File]::WriteAllBytes($path, $fixtures[$relative])
        [System.IO.File]::SetLastWriteTimeUtc(
            $path,
            [System.DateTime]::new(2024, 1, 1, 1, 2, 3, [System.DateTimeKind]::Utc)
        )
    }
    $reverseFixtureKeys = @($fixtures.Keys)
    [System.Array]::Reverse($reverseFixtureKeys)
    foreach ($relative in $reverseFixtureKeys) {
        $path = Join-Path $treeTwo $relative.Replace("/", "\")
        [System.IO.File]::WriteAllBytes($path, $fixtures[$relative])
        [System.IO.File]::SetLastWriteTimeUtc(
            $path,
            [System.DateTime]::new(2026, 7, 25, 12, 34, 56, [System.DateTimeKind]::Utc)
        )
    }

    New-DeterministicZipArchive -SourceDirectory $treeOne -DestinationPath $archiveOne
    New-DeterministicZipArchive -SourceDirectory $treeTwo -DestinationPath $archiveTwo

    $hashOne = (Get-FileHash -LiteralPath $archiveOne -Algorithm SHA256).Hash
    $hashTwo = (Get-FileHash -LiteralPath $archiveTwo -Algorithm SHA256).Hash
    Assert-True ($hashOne -ceq $hashTwo) (
        "Equivalent source trees produced different ZIP hashes: $hashOne vs $hashTwo"
    )
    Assert-DeterministicZipMatchesSource `
        -SourceDirectory $treeOne `
        -ArchivePath $archiveOne
    Copy-Item -LiteralPath $archiveOne -Destination $tamperedArchive
    $trailer = [Text.Encoding]::UTF8.GetBytes("unscanned ZIP trailer")
    $tamperedStream = [System.IO.File]::Open(
        $tamperedArchive,
        [System.IO.FileMode]::Append,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        $tamperedStream.Write($trailer, 0, $trailer.Length)
    }
    finally {
        $tamperedStream.Dispose()
    }
    $tamperedRejected = $false
    try {
        Assert-DeterministicZipMatchesSource `
            -SourceDirectory $treeOne `
            -ArchivePath $tamperedArchive
    }
    catch {
        $tamperedRejected = $_.Exception.Message.IndexOf(
            "not byte-identical",
            [System.StringComparison]::Ordinal
        ) -ge 0
    }
    Assert-True $tamperedRejected (
        "A ZIP with an appended unscanned trailer passed deterministic verification."
    )
    Copy-Item -LiteralPath $archiveOne -Destination $symlinkArchive
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $symlinkStream = [System.IO.File]::Open(
        $symlinkArchive,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    try {
        $symlinkZip = [System.IO.Compression.ZipArchive]::new(
            $symlinkStream,
            [System.IO.Compression.ZipArchiveMode]::Update,
            $false
        )
        try {
            $symlinkEntry = $symlinkZip.GetEntry("nested/alpha.txt")
            $symlinkEntry.ExternalAttributes = [int]-1577123840 # 0120777 << 16
        }
        finally {
            $symlinkZip.Dispose()
        }
    }
    finally {
        $symlinkStream.Dispose()
    }
    $symlinkModeRejected = $false
    try {
        Assert-DeterministicZipMatchesSource `
            -SourceDirectory $treeOne `
            -ArchivePath $symlinkArchive
    }
    catch {
        $symlinkModeRejected = $_.Exception.Message.IndexOf(
            "not byte-identical",
            [System.StringComparison]::Ordinal
        ) -ge 0
    }
    Assert-True $symlinkModeRejected (
        "A ZIP carrying a Unix symlink mode passed deterministic verification."
    )

    try {
        New-Item `
            -ItemType Junction `
            -Path $junctionRoot `
            -Target $treeOne `
            -ErrorAction Stop |
            Out-Null
        $junctionRejected = $false
        try {
            New-DeterministicZipArchive `
                -SourceDirectory $junctionRoot `
                -DestinationPath $junctionArchive
        }
        catch {
            $junctionRejected = $_.Exception.Message.IndexOf(
                "junction or symbolic link",
                [System.StringComparison]::Ordinal
            ) -ge 0
        }
        Assert-True $junctionRejected (
            "A junction used as the deterministic ZIP source root was accepted."
        )
    }
    finally {
        Remove-TestJunction -Path $junctionRoot
    }
    Assert-True (Test-Path -LiteralPath $treeOne -PathType Container) (
        "Removing the junction self-test path also removed its target."
    )

    $readStream = [System.IO.File]::OpenRead($archiveOne)
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $readStream,
            [System.IO.Compression.ZipArchiveMode]::Read,
            $false
        )
        try {
            [string[]]$actualEntries = @($archive.Entries | ForEach-Object { $_.FullName })
            [string[]]$expectedEntries = @(
                "nested/alpha.txt",
                "nested/binary.dat",
                "z-last.txt"
            )
            Assert-True (
                ($actualEntries -join "`n") -ceq ($expectedEntries -join "`n")
            ) "Deterministic ZIP entries were not ordinal-sorted with portable separators."

            foreach ($entry in $archive.Entries) {
                Assert-True (-not $entry.FullName.Contains("\")) (
                    "ZIP entry used a non-portable separator: $($entry.FullName)"
                )
                Assert-True (
                    $entry.LastWriteTime.Year -eq 1980 -and
                    $entry.LastWriteTime.Month -eq 1 -and
                    $entry.LastWriteTime.Day -eq 1 -and
                    $entry.LastWriteTime.Hour -eq 0 -and
                    $entry.LastWriteTime.Minute -eq 0 -and
                    $entry.LastWriteTime.Second -eq 0
                ) "ZIP entry did not use the fixed legal ZIP timestamp: $($entry.FullName)"
                Assert-True ($entry.ExternalAttributes -eq [int]-2119958528) (
                    "ZIP entry did not use fixed regular-file mode 0644: $($entry.FullName)"
                )
            }
        }
        finally {
            $archive.Dispose()
        }
    }
    finally {
        $readStream.Dispose()
    }

    Write-Output (
        "Deterministic ZIP self-test passed byte identity, trailer, symlink-mode, " +
        "and junction-root rejection, ordering, timestamp, and attributes."
    )
}
finally {
    Remove-TestJunction -Path $junctionRoot
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
