# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

Set-StrictMode -Version Latest

function Read-SbomJsonArray {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    try {
        $payload = Get-Content `
            -LiteralPath $Path `
            -Raw `
            -Encoding UTF8 `
            -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "$Context is invalid JSON (${Path}): $($_.Exception.Message)"
    }
    if ($payload -isnot [System.Array] -or $payload.Count -eq 0) {
        throw "$Context must be a non-empty JSON array: $Path"
    }
    return @($payload)
}

function Get-SbomNormalizedDependencyName {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("python", "node")]
        [string]$Ecosystem,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $normalized = $Name.Trim().ToLowerInvariant()
    if ($Ecosystem -ceq "python") {
        return [regex]::Replace($normalized, '[-_.]+', '-')
    }
    return $normalized
}

function Get-SbomReportIdentitySet {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Report,

        [Parameter(Mandatory = $true)]
        [ValidateSet("python", "node")]
        [string]$Ecosystem
    )

    if ($Report.Count -eq 0) {
        throw "$Ecosystem dependency report must not be empty."
    }
    $identities = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($item in $Report) {
        if ($null -eq $item -or
            -not $item.PSObject.Properties["Name"] -or
            -not $item.PSObject.Properties["Version"]) {
            throw "$Ecosystem dependency report contains an item without Name and Version."
        }
        $name = [string]$item.Name
        $version = [string]$item.Version
        if ([string]::IsNullOrWhiteSpace($name) -or
            [string]::IsNullOrWhiteSpace($version)) {
            throw "$Ecosystem dependency report contains an empty Name or Version."
        }
        $identity = (
            "$Ecosystem`:" +
            "$(Get-SbomNormalizedDependencyName -Ecosystem $Ecosystem -Name $name)@" +
            $version.Trim()
        )
        if (-not $identities.Add($identity)) {
            throw "$Ecosystem dependency report contains a duplicate identity: $identity"
        }
    }
    return $identities
}

function Get-SbomComponentIdentitySet {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Components
    )

    if ($Components.Count -eq 0) {
        throw "SBOM must contain dependency components."
    }
    $identities = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($component in $Components) {
        if ($null -eq $component -or
            -not $component.PSObject.Properties["purl"]) {
            continue
        }
        $purl = [string]$component.purl
        if ($purl -notmatch '^pkg:(?:pypi|npm)/') {
            continue
        }
        $match = [regex]::Match(
            $purl,
            '^pkg:(?<type>pypi|npm)/(?<name>.+)@(?<version>[^?#]+)(?:\?[^#]*)?(?:#.*)?$',
            [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
        )
        if (-not $match.Success) {
            throw "SBOM contains a malformed Python or Node package URL: $purl"
        }
        if (-not $component.PSObject.Properties["name"] -or
            -not $component.PSObject.Properties["version"]) {
            throw "SBOM component with package URL lacks name or version: $purl"
        }

        try {
            $purlName = [System.Uri]::UnescapeDataString(
                $match.Groups["name"].Value
            )
            $purlVersion = [System.Uri]::UnescapeDataString(
                $match.Groups["version"].Value
            )
        }
        catch {
            throw "SBOM component has invalid package URL escaping: $purl"
        }
        $ecosystem = if ($match.Groups["type"].Value -ceq "pypi") {
            "python"
        }
        else {
            "node"
        }
        $normalizedPurlName = Get-SbomNormalizedDependencyName `
            -Ecosystem $ecosystem `
            -Name $purlName
        $normalizedComponentName = Get-SbomNormalizedDependencyName `
            -Ecosystem $ecosystem `
            -Name ([string]$component.name)
        if ($normalizedComponentName -cne $normalizedPurlName -or
            ([string]$component.version).Trim() -cne $purlVersion) {
            throw "SBOM component fields disagree with its package URL: $purl"
        }
        [void]$identities.Add(
            "$ecosystem`:$normalizedPurlName@$purlVersion"
        )
    }
    if ($identities.Count -eq 0) {
        throw "SBOM contains no parseable Python or Node package URLs."
    }
    return $identities
}

function Assert-SbomDependencyCoverage {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Components,

        [Parameter(Mandatory = $true)]
        [object[]]$PythonReport,

        [Parameter(Mandatory = $true)]
        [object[]]$NodeReport
    )

    $sbomIdentities = Get-SbomComponentIdentitySet -Components $Components
    $requiredIdentities = @(
        Get-SbomReportIdentitySet -Report $PythonReport -Ecosystem "python"
        Get-SbomReportIdentitySet -Report $NodeReport -Ecosystem "node"
    )
    foreach ($requiredIdentity in $requiredIdentities) {
        if (-not $sbomIdentities.Contains([string]$requiredIdentity)) {
            throw "SBOM is missing locked active dependency: $requiredIdentity"
        }
    }
}
