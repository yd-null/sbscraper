param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$InstallerSha256,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$packageIdentifier = "yd-null.sbscraper"
$repositoryUrl = "https://github.com/yd-null/sbscraper"
$installerUrl = "$repositoryUrl/releases/download/v$Version/sbscraper-windows.zip"
$schemaBase = "https://aka.ms/winget-manifest"

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

@"
# yaml-language-server: `$schema=$schemaBase.version.1.12.0.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.12.0
"@ | Set-Content -Path "$OutputDirectory/$packageIdentifier.yaml" -Encoding utf8

@"
# yaml-language-server: `$schema=$schemaBase.defaultLocale.1.12.0.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
PackageLocale: en-US
Publisher: yd-null
PublisherUrl: https://github.com/yd-null
PublisherSupportUrl: $repositoryUrl/issues
Author: yd-null
PackageName: sbscraper
PackageUrl: $repositoryUrl
License: MIT
LicenseUrl: $repositoryUrl/blob/v$Version/LICENSE
Copyright: Copyright (c) 2026 yd-null
ShortDescription: Scrape Structure Builder reports and export related CSV data.
Moniker: sbscraper
Tags:
  - cli
  - reports
  - scraper
ReleaseNotesUrl: $repositoryUrl/releases/tag/v$Version
ManifestType: defaultLocale
ManifestVersion: 1.12.0
"@ | Set-Content -Path "$OutputDirectory/$packageIdentifier.locale.en-US.yaml" -Encoding utf8

@"
# yaml-language-server: `$schema=$schemaBase.installer.1.12.0.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
InstallerType: zip
NestedInstallerType: portable
Scope: user
UpgradeBehavior: install
Commands:
  - sbscraper
Installers:
  - Architecture: x64
    InstallerUrl: $installerUrl
    InstallerSha256: $InstallerSha256
    NestedInstallerFiles:
      - RelativeFilePath: sbscraper\sbscraper.exe
        PortableCommandAlias: sbscraper
ManifestType: installer
ManifestVersion: 1.12.0
"@ | Set-Content -Path "$OutputDirectory/$packageIdentifier.installer.yaml" -Encoding utf8
