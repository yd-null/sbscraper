# sbscraper

`sbscraper` is a CLI wrapper for scraping Structure Builder reports:

- `-pwrid`: fetch reports by PWRID
- `-fuel`: fetch fuel tank reports by Site ID
- `-coord`: extract address/lat/lon from a folder of PDF reports into CSV

## Config

On first run, `sbscraper` prompts for your username and password, then creates `config.json` next to the executing program path (`sys.argv[0]` semantics). For `python main.py ...`, this is next to `main.py`; for `sbscraper.exe ...`, this is next to `sbscraper.exe`.

You can still create/edit it manually if needed. Template:

```json
{
  "username": "your_username",
  "password": "your_password"
}
```

If credentials are missing or `config.json` is invalid JSON, the app prompts again and rewrites the file.

## CLI usage

```bash
python main.py -pwrid <PWRID...>
python main.py -fuel <SITE_ID...>
python main.py -coord <PDF_DIRECTORY> [--output sites.csv]
```

## Windows executable

Run from Command Prompt or PowerShell in the folder containing `sbscraper.exe`:

```powershell
.\sbscraper.exe -pwrid <PWRID...>
.\sbscraper.exe -fuel <SITE_ID...>
.\sbscraper.exe -coord <PDF_DIRECTORY> [--output sites.csv]
```

## Output

- PDF reports are saved under `output/`
- Coordinate extraction writes CSV to `sites.csv` by default (or `--output` path)
