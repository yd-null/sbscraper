# sbscraper

`sbscraper` is a CLI wrapper for scraping Structure Builder reports:

- `-p`, `--pwrid`: fetch reports by PWRID
- `-b`, `--battery`: export battery strings by PWRID into CSV
- `-f`, `--fuel`: fetch fuel tank reports by Site ID
- `-c`, `--coord`: extract address/lat/lon from a folder of PDF reports into CSV

## Config

On first run, `sbscraper` prompts for your username and password, then creates a per-user `config.json`. On Windows this is `%LOCALAPPDATA%\sbscraper\config.json`. Existing credentials stored next to the executable are copied there automatically on the next run.

You can still create/edit it manually if needed. Template:

```json
{
  "username": "your_username",
  "password": "your_password"
}
```

If credentials are missing or `config.json` is invalid JSON, the app prompts again and rewrites the file.

If Structure Builder rejects the saved password, the app explains that the password may need to be reset or changed in a web browser and offers to update the password stored in `config.json`. It retries the login once after an update.

## CLI usage

```bash
python main.py -v
python main.py --version
python main.py -p <PWRID...>
python main.py -b <PWRID...> [-o <DIRECTORY>]
python main.py --pwrid --battery <PWRID...> [--output <DIRECTORY>]
python main.py -f <SITE_ID...> [-o <DIRECTORY>]
python main.py -c <PDF_DIRECTORY> [-o <DIRECTORY>]
```

## Windows executable

Run from Command Prompt or PowerShell in the folder containing `sbscraper.exe`:

```powershell
.\sbscraper.exe -p <PWRID...>
.\sbscraper.exe -b <PWRID...> [-o <DIRECTORY>]
.\sbscraper.exe --pwrid --battery <PWRID...> [--output <DIRECTORY>]
.\sbscraper.exe -f <SITE_ID...> [-o <DIRECTORY>]
.\sbscraper.exe -c <PDF_DIRECTORY> [-o <DIRECTORY>]
```

Tagged GitHub releases can also be installed without administrator privileges
after the package is accepted into the WinGet community repository:

```powershell
winget install yd-null.sbscraper --scope user
sbscraper --version
```

## Output

On Windows, the default base directory is `%LOCALAPPDATA%\sbscraper`, beside `config.json`. On macOS and Linux, the default base is the current working directory.

- PDF reports are saved under `<base>/output/`
- Battery extraction writes `<base>/csv/battery_report.csv`
- Coordinate extraction writes `<base>/csv/sites.csv`

Use `-o <DIRECTORY>` or `--output <DIRECTORY>` to override the base directory for every mode. The old single-dash word options and CSV filename form of `--output` are no longer supported.
