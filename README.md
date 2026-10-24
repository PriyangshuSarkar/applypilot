# ApplyPilot

A personal job-search tool. It finds LinkedIn jobs, looks up company contacts, drafts a short cold email with a **local LLM** (Ollama), and sends it through the **Gmail API** with strict caps.

```
LinkedIn search -> job + JD -> company contacts (GetProspect list + Mailmeteor email lookup)
  -> grounded draft (Ollama, from profile.yaml + resume only) -> validate -> Gmail send
```

> Use responsibly. LinkedIn is accessed read-only, and cold emailing is subject to the laws and the platforms' terms that apply to you. This is a personal tool, not a bulk mailer. Nothing is sent unless you pass `--live`.

## Requirements
- Python 3.11+, macOS (the scripts use `caffeinate`/`osascript`)
- [Brave](https://brave.com) logged in to LinkedIn, with the *Email Finder - GetProspect* extension
- [Ollama](https://ollama.com) with a model such as `gemma4:12b` or `qwen3.5:9b`
- `pdftotext` (poppler) to read your resume
- A Google Cloud OAuth *desktop* client (`credentials.json`) with the Gmail API enabled

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium
cp config.example.yaml config.yaml      # search, caps, paths
cp profile.example.yaml profile.yaml    # your facts; drafts may only use these
# put credentials.json in the project root; token.json is created on first send
.venv/bin/python -m applypilot.cli preflight
```
Brave blocks remote debugging on its real data directory, so ApplyPilot runs a **copy** of your profile in `~/.applypilot/brave-profile` (port 9222). Re-copy it when sessions expire.

## Usage
```bash
.venv/bin/python -m applypilot.cli run --jobs 5          # dry run of the whole flow, sends nothing
.venv/bin/python -m applypilot.cli send --test-to you@example.com   # send drafts only to yourself, prefixed [TEST]
.venv/bin/python -m applypilot.cli run --jobs 5 --live   # really sends
./run.sh                                                 # unattended live run (JOBS=10 by default); ./run.sh --dry to preview
touch STOP                                               # halts a run before the next email
```
Individual steps: `collect` (jobs + contacts -> `output/contacts.json`), `draft` (-> `output/emails.json`, review/edit by hand), `send`, `preflight`.

## Safety
- `dry_run: true` by default; live sending needs `--live`.
- Every draft passes `validate_draft` (no placeholders, no ungrounded or blended numbers) before sending.
- Caps per run, per day and per company, random delays between sends, dedupe via the SQLite store, and a `STOP` file.
- Stops on any captcha, block or security checkpoint; never tries to bypass one.

## Layout
| Path | Purpose |
|---|---|
| `applypilot/cli.py` | typer commands and orchestration |
| `scrape.py`, `browser.py`, `linkedin.py`, `mailmeteor.py` | browser/network code (selectors isolated in `scrape.py`) |
| `llm.py`, `emails.py`, `resume.py`, `validate.py` | drafting and checks |
| `gmail.py` | Gmail API sending |
| `store.py`, `jsonstore.py`, `records.py`, `filters.py`, `config.py` | state, models, selection, config |
| `tests/` | `.venv/bin/pytest -q` |

## Private files (gitignored, never commit)
`config.yaml`, `profile.yaml`, `credentials.json`, `token.json`, `*.db`, `resume.pdf`, `output/`, `logs/`.
