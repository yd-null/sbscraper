# sbscraper

`sbscraper` is a single CLI for three SBS workflows:

- `-pwrid`: fetch reports by PWRID
- `-fuel`: fetch fuel tank reports by Site ID
- `-coord`: extract address/lat/lon from a folder of PDF reports into CSV

## Requirements

- Python 3.13+
- Playwright Chromium (installed automatically in CI workflows)
- `config.json` with SBS credentials

## Config

Create `config.json` in the working directory (or next to the exe):

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

```console
python main.py -pwrid <PWRID...>
python main.py -fuel <SITE_ID...>
python main.py -coord <PDF_DIRECTORY> [--output sites.csv]
```

## Output

- PDF reports are saved under `output/`
- Coordinate extraction writes CSV to `sites.csv` by default (or `--output` path)
