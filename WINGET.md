# WinGet publishing

Tagged releases produce a Windows x64 portable ZIP, its SHA-256 checksum, and
the three manifests required by the WinGet community repository.

## User-scope behavior

The generated installer manifest declares a ZIP containing a portable app with
`Scope: user`. WinGet installs it without elevation and creates the
`sbscraper` command alias:

```powershell
winget install yd-null.sbscraper --scope user
sbscraper --version
```

Credentials are stored outside the portable installation at
`%LOCALAPPDATA%\sbscraper\config.json`, so upgrades and uninstall do not remove
them. A new terminal may be required before the command alias is available.

## First submission

1. Push a version tag such as `v1.0.20` and wait for the **Release Windows EXE**
   workflow to succeed.
2. Download the three `yd-null.sbscraper*.yaml` files from that GitHub Release.
3. Place them in a fork of `microsoft/winget-pkgs` at:

   ```text
   manifests/y/yd-null/sbscraper/1.0.20/
   ```

4. Open a pull request containing only those three manifest files.
5. Respond to validation or moderator feedback on the pull request.

The WinGet repository performs Windows installation, uninstall, hash, URL,
Defender, and manifest validation. The release URL and release assets must stay
public and immutable after submission.

## Future updates

For every later tag, submit the generated manifest set under the corresponding
version directory in a new `microsoft/winget-pkgs` pull request. Never replace
the ZIP attached to an existing release because its manifest contains that
file's SHA-256 hash.
