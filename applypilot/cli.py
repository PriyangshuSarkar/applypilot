import random
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from playwright.sync_api import sync_playwright

from applypilot import gmail, jsonstore, llm, scrape
from applypilot.browser import connect, launch_brave
from applypilot.config import Config, Profile, load_config, load_profile
from applypilot.emails import Recipient, assemble_body, greeting_names
from applypilot.filters import has_sendable, remaining_budget, title_excluded
from applypilot.linkedin import build_search_url
from applypilot.resume import load_resume_text
from applypilot.store import Store
from applypilot.validate import Draft, blended_numbers, subject_too_similar, ungrounded_numbers, validate_draft

app = typer.Typer(no_args_is_help=True)
CONTACTS = Path("output/contacts.json")
EMAILS = Path("output/emails.json")


@app.callback()
def main() -> None:
    """ApplyPilot."""


# --- step 1: LinkedIn -> contacts.json -------------------------------------------------------------

def collect_step(cfg: Config, store: Store, n: int, out: Path, reveal: bool, cap: int | None) -> None:
    """With reveal: keep going until `n` companies have a sendable email (bounded by max_jobs_examined).
    Without reveal: just look at `n` new jobs."""
    done = {r["job_id"]: r for r in jsonstore.load(out)}
    limit = cfg.run.max_jobs_examined or 2 * n
    ready = sum(1 for j in done.values() if has_sendable(j, store.already_emailed)) if reveal else 0
    if reveal:
        typer.echo(f"{ready} companies already queued with emails; target {n}, will examine at most {limit} new jobs")
    launch_brave(cfg.browser)
    with sync_playwright() as pw:
        browser = connect(pw, cfg.browser)
        ctx = browser.contexts[0]
        search = ctx.new_page()
        search.goto(build_search_url(cfg.search.queries[0], cfg.search))
        search.wait_for_timeout(6000)
        examined = 0
        try:
            scrape.guard(search)
            ids = scrape.collect_job_ids(search, limit * 3)  # extra: handled / excluded jobs are skipped
            typer.echo(f"{len(ids)} jobs on the results page")
            for jid in ids:
                if (reveal and ready >= n) or examined >= (limit if reveal else n):
                    break
                url = f"https://www.linkedin.com/jobs/view/{jid}/"
                if store.job_seen(url):
                    typer.echo(f"skip {jid} (already handled in an earlier run)")
                    continue
                if jid in done and not (reveal and not any(c["email"] for c in done[jid]["contacts"])):
                    typer.echo(f"skip {jid} (already collected, waiting to be emailed)")
                    continue
                job = scrape.read_job(search, jid)
                typer.echo(f"{jid} {job['title']} @ {job['company']}")
                bad = title_excluded(job["title"], cfg.search.exclude_title_words)
                if bad:
                    typer.echo(f"  skip: title contains '{bad}'")
                    store.mark_job(job["url"], job["title"], job["company"])
                    scrape.pause()
                    continue
                examined += 1
                res = (scrape.read_company_contacts(ctx, job["company_url"], job["company"], reveal, cap)
                       if job["company_url"] else {"contacts": [], "revealed_now": 0, "note": "no company page"})
                job["contacts"] = res["contacts"]
                if res["note"]:
                    typer.echo(f"  note: {res['note']}")
                job["collected_at"] = datetime.now(timezone.utc).isoformat()
                done[jid] = job
                jsonstore.save(out, list(done.values()))
                with_email = sum(1 for c in job["contacts"] if c["email"])
                typer.echo(f"  {len(job['contacts'])} contacts, {with_email} with email, {res['revealed_now']} revealed now")
                if reveal and has_sendable(job, store.already_emailed):
                    ready += 1
                    typer.echo(f"  -> {ready}/{n} companies ready")
                scrape.pause()
        except scrape.Checkpoint as e:
            typer.echo(f"STOPPED: LinkedIn checkpoint at {e}. Resolve it manually.", err=True)
            raise typer.Exit(1)
        finally:
            browser.close()


# --- step 2: contacts.json + resume -> emails.json (LLM) -------------------------------------------

def draft_step(cfg: Config, profile: Profile, store: Store, contacts: Path, out: Path) -> None:
    resume = load_resume_text(cfg.email.resume_path)
    links = " | ".join(f"{k.capitalize()}: {v}" for k, v in profile.links.items())
    signature = f"{cfg.email.sender_name}\n{profile.headline}\n{links}"
    results = jsonstore.load(out)  # keep earlier drafts (and any manual edits) untouched
    have = {r["job_id"] for r in results}
    for job in jsonstore.load(contacts):
        if job["job_id"] in have:
            continue
        people = [Recipient(c["name"], c["email"]) for c in job["contacts"]
                  if c.get("selected") and c["email"] and not store.already_emailed(c["email"])]
        if not people:
            typer.echo(f"skip {job['company']}: nobody left to email; clearing it")
            store.mark_job(job["url"], job["title"], job["company"])
            jsonstore.remove_job(contacts, job["job_id"])
            continue
        feedback, core, problems = None, None, []
        for attempt in range(1, cfg.llm.max_attempts + 1):
            try:
                core = llm.draft_core(cfg, resume, job, feedback)
            except ValueError:
                feedback = ["reply must be exactly: SUBJECT: <subject> then BODY: <body>"]
                typer.echo(f"{job['company']}: attempt {attempt} -> unparsable reply")
                continue
            full = assemble_body(core.body, greeting_names(people), cfg.email.opt_out_line, signature)
            problems = validate_draft(Draft(core.subject, full), job["company"], cfg.email.opt_out_line)
            bad = ungrounded_numbers(core.subject + " " + core.body, resume)
            if bad:
                problems.append(f"numbers not in resume: {', '.join(bad)}")
            blended = blended_numbers(core.subject + ". " + core.body, resume)
            if blended:
                problems.append("a sentence merges numbers from different resume bullets (one achievement per "
                                "sentence): " + " | ".join(blended))
            clash = subject_too_similar(core.subject, [r["subject"] for r in results])
            if clash:
                problems.append(f"subject too similar to another email's subject ({clash!r}); write a clearly different one")
            typer.echo(f"{job['company']}: attempt {attempt} -> {'ok' if not problems else problems}")
            if not problems:
                break
            feedback = problems
        if core is None:
            typer.echo(f"skip {job['company']}: model never produced a parsable draft (left in contacts.json)")
            continue
        results.append({
            "job_id": job["job_id"], "job_title": job["title"], "company": job["company"], "job_url": job["url"],
            "to": [p.email for p in people], "to_names": [p.name for p in people], "cc": [],
            "subject": core.subject,
            "body": assemble_body(core.body, greeting_names(people), cfg.email.opt_out_line, signature),
            "attachment": str(Path(cfg.email.resume_path).expanduser()),
            "model": cfg.llm.model, "problems": problems,
            "status": "draft" if not problems else "needs_review",
        })
        jsonstore.save(out, results)
    jsonstore.save(out, results)
    typer.echo(f"{len(results)} drafts in {out}")


# --- step 3: emails.json -> Gmail, clearing entries as they succeed --------------------------------

def send_step(cfg: Config, store: Store, emails: Path, contacts: Path, live: bool, test_to: str | None = None) -> None:
    drafts = jsonstore.load(emails)
    service = gmail.get_service() if (live or test_to) else None
    sent_run = failures = 0
    for d in drafts:
        label = f"{d['company']} -> {', '.join(d['to'])}"
        if Path("STOP").exists():
            typer.echo("STOP file found; halting.")
            break
        if d["status"] != "draft":
            typer.echo(f"skip {label}: status {d['status']} (needs review)")
            continue
        problems = validate_draft(Draft(d["subject"], d["body"]), d["company"], cfg.email.opt_out_line)
        if problems:
            typer.echo(f"skip {label}: {problems}")
            continue
        if test_to:
            msg = gmail.build_message([test_to], [], f"[TEST] {d['subject']}", d["body"], d["attachment"])
            typer.echo(f"TEST sent to {test_to}: {d['subject']} (id {gmail.send(service, msg)}) [would go to {label}]")
            continue
        fresh = [e for e in d["to"] if not store.already_emailed(e)]
        if not fresh:
            typer.echo(f"skip {label}: everyone already emailed")
            continue
        room = remaining_budget(cfg.limits.max_emails_per_run, cfg.limits.max_emails_per_day, sent_run, store.sent_today())
        if len(fresh) > room:
            typer.echo(f"skip {label}: needs {len(fresh)} sends, only {room} left under the caps")
            continue
        if not live:
            typer.echo(f"DRY RUN would send to {fresh} (cc {d['cc']}): {d['subject']}")
            continue
        try:
            msg = gmail.build_message(fresh, d["cc"], d["subject"], d["body"], d["attachment"])
            msg_id = gmail.send(service, msg)
        except Exception as e:  # keep the entry so it can be retried; stop if it keeps failing
            failures += 1
            typer.echo(f"FAILED {label}: {e} (entry kept)", err=True)
            if failures >= 2:
                typer.echo("two failures in a row; stopping.", err=True)
                break
            continue
        failures = 0
        typer.echo(f"SENT {fresh}: {d['subject']} (id {msg_id})")
        for e in fresh:
            store.record_email(e, d["job_url"], d["subject"], dry_run=False)
        store.mark_job(d["job_url"], d["job_title"], d["company"])
        jsonstore.remove_job(emails, d["job_id"])  # success -> clear from both files
        jsonstore.remove_job(contacts, d["job_id"])
        sent_run += len(fresh)
        time.sleep(random.uniform(*cfg.limits.delay_seconds))


# --- commands --------------------------------------------------------------------------------------

@app.command()
def collect(jobs: int = typer.Option(None, help="New jobs to process (default: config run.jobs_per_run)"),
            out: Path = CONTACTS,
            reveal: bool = typer.Option(False, help="Click 'Reveal and save' (spends GetProspect credits)"),
            max_reveals: int = typer.Option(None, help="Per-company reveal cap (default: config)")) -> None:
    """Step 1: search LinkedIn, read each JD, list GetProspect contacts, save JSON."""
    cfg = load_config()
    cap = max_reveals if max_reveals is not None else cfg.extension.max_reveals_per_company
    collect_step(cfg, Store(), jobs or cfg.run.jobs_per_run, out, reveal, cap)


@app.command()
def draft(contacts: Path = CONTACTS, out: Path = EMAILS,
          model: str = typer.Option(None, help="Override llm.model (e.g. qwen3.5:9b)")) -> None:
    """Step 2: build review-only emails with the local LLM (starts and stops it). Sends nothing."""
    cfg = load_config()
    if model:
        cfg.llm.model = model
    proc = llm.start_llm(cfg)
    try:
        draft_step(cfg, load_profile(), Store(), contacts, out)
    finally:
        llm.stop_llm(cfg, proc)


@app.command()
def send(emails: Path = EMAILS, contacts: Path = CONTACTS,
         test_to: str = typer.Option(None, help="Send every draft ONLY to this address, subject prefixed [TEST]"),
         live: bool = typer.Option(False, help="Really send (default: just print the plan)")) -> None:
    """Step 3: send drafts via Gmail. Default prints a plan; --test-to sends to yourself; --live sends for real."""
    send_step(load_config(), Store(), emails, contacts, live, test_to)


@app.command()
def preflight() -> None:
    """Check everything an unattended run needs, and fail early (before anything is spent or sent)."""
    import shutil
    import subprocess

    cfg = load_config()
    problems = []
    if not Path(cfg.browser.brave_path).exists():
        problems.append(f"Brave not found at {cfg.browser.brave_path}")
    if not Path(cfg.browser.user_data_dir).expanduser().exists():
        problems.append(f"Brave profile copy missing: {cfg.browser.user_data_dir}")
    if not Path(cfg.email.resume_path).expanduser().exists():
        problems.append(f"resume not found: {cfg.email.resume_path}")
    if not Path("profile.yaml").exists():
        problems.append("profile.yaml missing")
    for tool in ("ollama", "pdftotext"):
        if not shutil.which(tool):
            problems.append(f"`{tool}` not installed")
    if shutil.which("ollama"):
        listed = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
        if cfg.llm.model not in listed:
            problems.append(f"model {cfg.llm.model} not pulled (ollama pull {cfg.llm.model})")
    if not Path("credentials.json").exists():
        problems.append("credentials.json missing (Google OAuth client)")
    else:
        try:
            gmail.get_service()  # refreshes the token, or opens the consent page now rather than mid-run
        except Exception as e:
            problems.append(f"Gmail auth failed ({e}); delete token.json and run again")
    if problems:
        for p in problems:
            typer.echo(f"PREFLIGHT FAILED: {p}", err=True)
        raise typer.Exit(1)
    typer.echo("preflight ok")


@app.command()
def run(jobs: int = typer.Option(None, help="New jobs this run (default: config run.jobs_per_run)"),
        reveal: bool = typer.Option(True, "--reveal/--no-reveal", help="Spend GetProspect credits to reveal emails"),
        live: bool = typer.Option(False, help="Really send the emails (default: stop with a dry-run plan)"),
        test_to: str = typer.Option(None, help="Run everything, but send every email ONLY to this address ([TEST])")) -> None:
    """Whole flow: collect -> start LLM -> draft -> stop LLM -> send, clearing entries as emails succeed."""
    cfg, store = load_config(), Store()
    n = jobs or cfg.run.jobs_per_run
    cap = cfg.extension.max_reveals_per_company
    typer.echo(f"== 1/3 collect {n} new jobs (reveal={reveal}, cap {cap}/company)")
    try:
        collect_step(cfg, store, n, CONTACTS, reveal, cap)
    except typer.Exit:  # e.g. LinkedIn checkpoint: still draft/send whatever was collected so far
        typer.echo("collect stopped early; continuing with what was collected.", err=True)
    if Path("STOP").exists():
        raise typer.Exit()
    typer.echo(f"== 2/3 draft emails with {cfg.llm.model}")
    proc = llm.start_llm(cfg)
    try:
        draft_step(cfg, load_profile(), store, CONTACTS, EMAILS)
    finally:
        llm.stop_llm(cfg, proc)
        typer.echo("LLM stopped (model unloaded).")
    mode = f"TEST copies to {test_to}" if test_to else ("LIVE" if live else "dry run; pass --live to really send")
    typer.echo(f"== 3/3 send ({mode})")
    send_step(cfg, store, EMAILS, CONTACTS, live and not test_to, test_to)
    left = len(jsonstore.load(EMAILS))
    typer.echo(f"done. {left} entries remain in {EMAILS} (needs review / not sent)." if left else "done. All entries sent and cleared.")


if __name__ == "__main__":
    app()
