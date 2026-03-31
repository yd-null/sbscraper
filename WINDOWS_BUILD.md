# Windows deploy

You do not need Python on target Windows systems.

## Build in CI (recommended)

Use the GitHub Actions workflow at `.github/workflows/windows-onefile-exe.yml`.

- Trigger manually from **Actions -> Build Windows Onedir EXE -> Run workflow**.

The workflow produces an artifact named `sbscraper-windows-onedir` with:

- `sbscraper/` (contains `sbscraper.exe` and runtime files)

## Auto-release on tags

Push a tag like `v1.0.0` to trigger `.github/workflows/windows-release.yml`.

That workflow builds a Windows app folder and publishes a GitHub Release with:

- `sbscraper-windows.zip`

## Deploy on Windows machines

1. Extract `sbscraper-windows.zip` (or download the `sbscraper-windows-onedir` artifact).
2. Run `sbscraper.exe` from inside the `sbscraper` folder.
3. On first run, the app prompts for credentials and creates `config.json` next to `sbscraper.exe` (not in the current working directory).

## Run examples

```powershell
.\sbscraper.exe -pwrid 12345 67890
.\sbscraper.exe -fuel 1001 1002
.\sbscraper.exe -coord .\pdfs --output sites.csv
```
