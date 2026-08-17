# AI-Powered Excel Anomaly Detection Agent

An agent that continuously watches an Excel file of business metrics,
detects anomalies with statistics, explains them using business rules, and
emails an alert with a full report.

## Quick start

```bash
pip install -r requirements.txt

# 1. Create sample Excel files with fake data
python scripts/generate_sample_data.py
python scripts/generate_wide_sample.py
python scripts/generate_retail_sample.py

# 2. INTERACTIVE: the agent asks which data to watch, then runs
python main.py
#   -> "Which data should I watch?"  pick a number (or type a file path)
#   -> "Run once or keep watching?"  type 1 or 2
#   If the data/ folder is empty it offers to generate samples for you.

# 3. Non-interactive single pass (uses the file path in config.json)
python main.py --once

# 4. Run continuously on the configured file
python main.py --config config.json
```

## Auto mode (it figures out your file by itself)

Set `"auto": true` in `config.json` (it's on by default) and the agent will
**detect everything itself**:

- which worksheet has the data
- the date column and the date format
- long format (`Date | Metric | Value`) **or** wide format
  (`Date | MetricA | MetricB | ...`)
- metric names it didn't know about (registered automatically with guessed
  unit/priority)
- which detection method fits each metric based on how much history exists

So you can throw almost any normal business spreadsheet at it. Try the wide
sample:

```powershell
python scripts/generate_wide_sample.py
# point config.json excel_config.file_path at data/wide_metrics.xlsx
python main.py --once
```

It will log what it detected, e.g.:
`Auto-detected: sheet='Fruit Store', layout=wide, date_format=%d/%m/%Y %H:%M`

If auto mode still can't handle a file, set `"auto": false` and give it the
exact column names manually.

## Project structure

```
anomaly-detector/
├── main.py                     # entry point (CLI, interactive menu)
├── config.json                 # all settings (Excel path, metrics, SMTP, rules)
├── requirements.txt
├── modules/
│   ├── __init__.py
│   ├── auto_detect.py          # NEW: figures out sheets, columns, formats
│   ├── data_reader.py          # reads + cleans the Excel file
│   ├── anomaly_detector.py     # z-score / moving-average / threshold detection
│   ├── context_analyzer.py     # business rules (IF-THEN) that explain anomalies
│   ├── email_service.py        # composes + sends emails (with dry-run fallback)
│   └── monitor_loop.py         # heartbeat loop + alert decision logic
├── scripts/
│   ├── generate_sample_data.py # creates long-format data/business_metrics.xlsx
│   ├── generate_wide_sample.py # creates wide-format data/wide_metrics.xlsx
│   └── generate_retail_sample.py # creates currency-format data/retail_metrics.xlsx
├── data/
│   ├── business_metrics.xlsx   # long-format sample (generated)
│   ├── wide_metrics.xlsx       # wide-format sample (generated)
│   └── retail_metrics.xlsx     # currency/dd-mm-yyyy sample (generated)
├── logs/
│   ├── anomaly_detection.log   # agent log file
│   └── emails_sent/            # dry-run email copies (when no SMTP configured)
└── tests/                      # unit tests (python -m unittest discover -s tests)
```

## Configuration

Edit `config.json`. Key sections:

- `excel_config` — which file/sheet/columns to read
- `anomaly_detection` — detection method and thresholds
- `metrics` — per-metric priority, severity threshold, alert cooldown
- `email_config` — SMTP settings; leave `sender_password` unset for dry-run
- `monitoring` — check interval, timezone, business hours
- `business_rules` — IF-THEN rules that explain (or suppress) alerts

Rule conditions can reference: `metric`, `current_value`, `expected_value`,
`deviation_percent`, `z_score`, `severity`, `day`, `hour`, `is_weekend`,
`peak_hours`, `unit`.

## How it works (30-second version)

1. **Read** the newest rows from the Excel file.
2. **Detect** outliers: z-score (how far from the average), moving-average
   deviation, or fixed thresholds.
3. **Explain** via business rules (e.g. "weekend sales are usually lower").
4. **Decide** — skip if suppressed, below threshold, in cooldown, or outside
   business hours.
5. **Email** the report (or write it to `logs/emails_sent/` in dry-run mode).

## Running tests

```bash
python -m unittest discover -s tests -v
```

## Enabling real emails (Gmail)

1. Enable **2-Step Verification** at https://myaccount.google.com/security
2. Create an **App Password** (Security → 2-Step Verification → App passwords)
   — this is a 16-character code, *not* your normal Gmail password.
3. Set these environment variables (open a new terminal after `setx`):

```powershell
setx ANOMALY_SENDER_EMAIL   "your@gmail.com"
setx ANOMALY_SENDER_PASSWORD "your_16_char_app_password"
setx ANOMALY_RECIPIENTS     "you@example.com, manager@example.com"
```

The agent reads these at startup. `config.json` keeps placeholders only, so
no real password ever gets written into the project files.

For just one test run in the current terminal instead:

```powershell
$env:ANOMALY_SENDER_EMAIL = "your@gmail.com"
$env:ANOMALY_SENDER_PASSWORD = "your_16_char_app_password"
$env:ANOMALY_RECIPIENTS = "you@example.com"
```

Then:

```powershell
python main.py --once
```

Without these environment variables the agent stays in safe **dry-run mode**
and writes emails to `logs/emails_sent/` instead of sending them.

Other SMTP servers work too — override with `ANOMALY_SMTP_SERVER` and
`ANOMALY_SMTP_PORT`, or edit `config.json`.
