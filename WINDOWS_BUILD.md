# Windows onefile deploy

You do not need Python on target Windows systems.

## Build in CI (recommended)

Use the GitHub Actions workflow at `.github/workflows/windows-onefile-exe.yml`.

- Trigger manually from **Actions -> Build Windows Onefile EXE -> Run workflow**.

The workflow produces an artifact named `sbscraper-windows-onefile` with:

- `sbscraper.exe`
- `config.example.json`

## Auto-release on tags

Push a tag like `v1.0.0` to trigger `.github/workflows/windows-release.yml`.

That workflow builds `sbscraper.exe` and publishes a GitHub Release with:

- `sbscraper.exe`
- `config.example.json`

## Deploy on Windows machines

1. Copy `sbscraper.exe` to the target machine.
2. Copy `config.example.json` beside it and rename to `config.json`.
3. Fill in credentials in `config.json`.

## Run examples

```powershell
.\sbscraper.exe -pwrid 12345 67890
.\sbscraper.exe -fuel 1001 1002
.\sbscraper.exe -coord .\pdfs --output sites.csv
```
