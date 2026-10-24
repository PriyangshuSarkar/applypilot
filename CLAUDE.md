# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# ApplyPilot

Python tool that finds LinkedIn jobs, gets company contacts via a Brave email-finder extension, drafts a grounded cold email with a local LLM (Ollama), and sends it via the Gmail API with caps. Personal job search tool.

## Status
- Done: `config.py`, `store.py`, `filters.py`, `validate.py`, `linkedin.py` (URL builder), `browser.py` (Brave CDP launch), `scrape.py` (jobs, JD, GetProspect contacts), `cli.py` (`collect`, dry run, writes `output/contacts.json`).
- Emails come from Mailmeteor, not GetProspect credits: GetProspect's side panel is only used to list a company's employees (free) and read each row's LinkedIn URL; `mailmeteor.py` then looks up the email for the selected contacts (HR first, cap `mailmeteor.max_lookups_per_company`). Results are cached by LinkedIn URL in the store (`lookups` table). Only `valid`/`risky` results are used; `unknown`/none are saved but never emailed. The GetProspect reveal code was removed.
- `draft` command (`llm.py`, `emails.py`, `resume.py`): builds review-only emails into `output/emails.json` (one LLM call per job; one email per company, all selected contacts in `to`). The model writes only the hook + support paragraphs; code adds the greeting, closing ask (names role + company), opt-out and signature. Drafts are rejected for placeholders, ungrounded numbers, or a sentence mixing numbers from different resume bullets (`blended_numbers`). Sends nothing.
- `send` command (`gmail.py`, native Gmail API via OAuth, never Playwright): default prints a plan; `--test-to ADDR` sends every draft only to that address with a `[TEST]` prefix; `--live` really sends (re-validates, dedupes, enforces caps, delays, `STOP` file). Needs `credentials.json` (Google Cloud OAuth desktop client); `token.json` is created on first auth.

- `run` command = whole flow: `collect` (Mailmeteor lookup on by default) -> start Ollama -> `draft` -> unload/stop Ollama -> `send`. Sends only with `--live`. After each successful send the job leaves `output/emails.json`, is marked `sent_at` in `output/contacts.json` (kept for `run.keep_days`, default 7, then pruned) and is recorded in the SQLite store. `contacts.json` only holds contacts whose email was found; jobs carry `drafted_at` / `sent_at` / `skipped` markers so `collect`, `draft` and `send` never redo a job. `draft` keeps existing entries in `emails.json` (manual edits survive) and only drafts new jobs. Failures and `needs_review` entries stay in the files.

## Commands
```
./run.sh                                                      # unattended LIVE run (10 companies); ./run.sh --dry to only print the plan
.venv/bin/python -m applypilot.cli preflight                 # check everything an unattended run needs
.venv/bin/python -m applypilot.cli run --jobs 5              # dry run of the whole flow (no email sent)
.venv/bin/python -m applypilot.cli run --jobs 5 --live       # really sends
```
Individual steps:
```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup (no uv installed)
.venv/bin/pytest -q                                          # tests
.venv/bin/pytest tests/test_emails.py::test_name -q          # single test (no linter configured)
.venv/bin/python -m applypilot.cli collect --jobs 2          # read-only: jobs + JD + contact list -> output/contacts.json
.venv/bin/python -m applypilot.cli collect --jobs 1 --lookup --max-lookups 3   # Mailmeteor email lookups (free, throttled)
.venv/bin/python -m applypilot.cli send --test-to me@example.com   # test send to yourself first
.venv/bin/python -m applypilot.cli draft                     # contacts.json -> output/emails.json (local LLM, review only)
```

## Architecture
- `cli.py` (typer) holds the orchestration: `collect_step` -> `draft_step` -> `send_step`; `collect`/`draft`/`send` commands each wrap one step, and `run` chains them. `preflight` checks everything an unattended run needs; `run.sh` wraps `preflight` + `run` with a lock dir (`output/.run.lock`), a 15s abort window, logging to `logs/`, and cleanup of the automation Brave.
- State lives in two places: JSON queues in `output/` (`contacts.json` -> `emails.json`, handled via `jsonstore.py` with atomic writes and `remove_job`) and the SQLite `Store` (permanent record of processed/emailed jobs). A job leaves the JSON queues only after a successful send, so files are resumable and hand-editable.
- `records.py` defines the pydantic data models (`JobInfo`, `ContactInfo`, `EmailDraft`, `JobRecord`).

## Layout
- `applypilot/config.py`: pydantic models for `config.yaml` / `profile.yaml`
- `applypilot/store.py`: SQLite (`jobs`, `emails_sent`); dry-run sends never count as emailed
- `applypilot/filters.py`: contact selection (role allowlist, dedupe, per-company cap) and send budget
- `applypilot/validate.py`: draft checks run before every send
- `config.example.yaml`, `profile.example.yaml`: copy to `config.yaml` / `profile.yaml` (gitignored)

## Safety rules (do not weaken)
- `dry_run: true` is the default. Never send email unless the user explicitly runs `--send` or sets `dry_run: false`.
- Every draft must pass `validate_draft` before sending; never bypass it.
- Respect caps (`max_emails_per_run`, `max_emails_per_day`, `max_contacts_per_company`) and the random delay between sends. A `STOP` file in the project root must halt a run.
- LinkedIn is read-only: no connection requests, messages, or posting. Stop immediately on a captcha or security checkpoint; never try to bypass it.
- Only email contacts whose role matches `contacts.role_allowlist`; always dedupe via `Store.already_emailed`.
- Email content must be grounded in `profile.yaml` only; no invented experience or claims.
- Never commit or print secrets/personal data: `config.yaml`, `profile.yaml`, `credentials.json`, `token.json`, `*.db`, `resume.pdf` are gitignored.
- Test live sends first against the user's own address, with `jobs_per_run: 2`.

## Environment notes
- Brave profile "Personal" is `Profile 1` (profile "Default" is a separate work profile; never touch it).
- Brave 155 blocks CDP on its real data dir, so we run a **copy** of Profile 1 in `~/.applypilot/brave-profile` on port 9222 (logins carried over). Re-copy if sessions expire. Your normal Brave can stay open.
- GetProspect extension id `bhbcbkonalnjkflmdkdodieehnmmeknp`: click `#gp-open-panel-button` on a company page, then open the `sidepanel.html?tabId=...` URL from `http://127.0.0.1:9222/json` in a tab and click "View employees". Listing is free. Never click "Reveal and save" (spends credits; the code for it was removed).
- Mailmeteor LinkedIn Email Finder (`mailmeteor.com/tools/linkedin-email-finder`) is a web form driven with Playwright; keep the delays/caps in `mailmeteor:` config, and stop the run on any block/error/captcha (`Blocked`); never retry or bypass.
- `output/` holds scraped personal data and is gitignored.
- Ollama is installed with `gemma4:12b` (default) and `qwen3.5:9b`. Both run on the `mlx` runner: no JSON-schema output, and hidden thinking is on by default, so `llm.py` sends `think:false` and parses a `SUBJECT:/BODY:` text format. Resume PDF path is `email.resume_path` in `config.yaml`; text is extracted with `pdftotext`.
- Keep all DOM selectors isolated in `scrape.py` so breakage is local.

## Conventions
- Python >= 3.11, type hints, pydantic for config/data. Keep logic pure and testable; keep browser/network code thin.
- Add unit tests for any pure logic in `tests/`; browser parsing gets saved HTML fixtures, not live calls.
- Don't commit unless asked.
