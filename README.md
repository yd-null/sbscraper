# sbscraper

`sbscraper` is a CLI wrapper for scraping Structure Builder reports:

- `-pwrid`: fetch reports by PWRID
- `-fuel`: fetch fuel tank reports by Site ID
- `-coord`: extract address/lat/lon from a folder of PDF reports into CSV

## Config

Create `config.json` in the same working directory as the executable:

```json
{
  "username": "your_username",
  "password": "your_password"
}
```

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
