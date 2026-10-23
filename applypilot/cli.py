import json
import random
from collections import deque
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from playwright.sync_api import sync_playwright

from applypilot import gmail, jsonstore, llm, mailmeteor, scrape
from applypilot.browser import connect, launch_brave
from applypilot.config import Config, Profile, load_config, load_profile
from applypilot.emails import Recipient, assemble_body, greeting_names
from applypilot.filters import fill_emails, has_sendable, pick_contacts, remaining_budget, title_excluded
from applypilot.linkedin import build_search_url
from applypilot.resume import load_resume_text
from applypilot.store import Store
from applypilot.validate import Draft, blended_numbers, subject_too_similar, ungrounded_numbers, validate_draft

app = typer.Typer(no_args_is_help=True)
CONTACTS = Path("output/contacts.json")
EMAILS = Path("output/emails.json")
RUNS_LOG = Path("logs/runs.jsonl")  # one JSON summary line per `run`; the per-run text logs are written by run.sh
_tag = "cli"


def say(msg: str, err: bool = False, tag: str | None = None) -> None:
    """One log line: `HH:MM:SS [step] message`."""
    typer.echo(f"{datetime.now():%H:%M:%S} [{tag or _tag}] {msg}", err=err)


def set_step(name: str) -> None:
    global _tag
    _tag = name


@app.callback()
def main() -> None:
    """ApplyPilot."""


# --- step 1: LinkedIn -> contacts.json -------------------------------------------------------------

def collect_step(cfg: Config, store: Store, n: int, out: Path, lookup: bool, cap: int | None, stats: dict | None = None) -> dict:
    """With lookup: keep going until `n` companies have a sendable email (bounded by max_jobs_examined).
    Without lookup: just list `n` new jobs' contacts (no emails). Returns counts for the run summary.

    Pipelined: scraping a job (job page + GetProspect employee list, no lookups) is separate from looking its
    contacts up. While a Mailmeteor lookup waits for its timer, the next job is scraped one step ahead."""
    set_step("collect")
    stats = {} if stats is None else stats
    stats.update(examined=0, lookups=0, ready=0)
    dropped = jsonstore.prune(out, cfg.run.keep_days)
    if dropped:
        say(f"dropped {dropped} job(s) older than {cfg.run.keep_days} days from {out}")
    done = {r["job_id"]: r for r in jsonstore.load(out)}
    limit = cfg.run.max_jobs_examined or 2 * n
    queued = sum(1 for j in done.values() if has_sendable(j, store.already_emailed)) if lookup else 0
    sent = store.sent_today() if lookup else 0  # one email per company, so emails sent today count toward the goal
    ready = queued + sent
    if lookup:
        say(f"daily goal {n}: {sent} emailed today + {queued} queued; will examine at most {limit} new jobs")
    launch_brave(cfg.browser)
    with sync_playwright() as pw:
        browser = connect(pw, cfg.browser)
        ctx = browser.contexts[0]
        search = ctx.new_page()
        search.goto(build_search_url(cfg.search.queries[0], cfg.search))
        scrape.wait_for(search, scrape.CARD)
        examined = 0
        finder = mailmeteor.Finder(ctx, store, cfg.mailmeteor)
        try:
            scrape.guard(search)
            ids = scrape.collect_job_ids(search, limit * 3)  # extra: handled / excluded jobs are skipped
            say(f"{len(ids)} jobs on the results page")
            queue = deque(ids)
            ahead: list[dict] = []  # at most one job scraped while a lookup timer runs
            want = cfg.mailmeteor.max_attempts_per_company  # worthwhile (HR / head) profiles needed to try a company

            def enough(batch: list[dict]) -> bool:
                seen.extend(c for c in batch if c["tier"] < 2)
                return len(seen) >= want

            def fetch() -> dict | None:
                """Scrape the next job worth examining: job page + employee list. No Mailmeteor lookups."""
                nonlocal seen
                while queue:
                    jid = queue.popleft()
                    url = f"https://www.linkedin.com/jobs/view/{jid}/"
                    if store.job_seen(url):
                        say(f"skip {jid} (already handled in an earlier run)")
                        continue
                    if jid in done:
                        state = "emailed" if done[jid].get("sent_at") else "drafted" if done[jid].get("drafted_at") else "collected"
                        say(f"skip {jid} (already {state})")
                        continue
                    job = scrape.read_job(search, jid)
                    say(f"{jid} {job['title']} @ {job['company']}")
                    bad = title_excluded(job["title"], cfg.search.exclude_title_words)
                    if bad:
                        say(f"  skip: title contains '{bad}'")
                        store.mark_job(job["url"], job["title"], job["company"])
                        continue
                    seen = []
                    res = (scrape.read_company_contacts(ctx, job["company_url"], job["company"], enough if lookup else None)
                           if job["company_url"] else {"contacts": [], "note": "no company page"})
                    job["contacts"] = res["contacts"]
                    if res["note"]:
                        say(f"  note: {res['note']}")
                    return job
                return None

            seen: list[dict] = []

            def prefetch() -> bool:
                """Called while a lookup waits for its timer: scrape the next job. False when there's nothing to do."""
                if ahead or (lookup and ready >= n) or examined >= (limit if lookup else n) - 1:
                    return False
                job = fetch()
                if job is None:
                    return False
                ahead.append(job)
                return True

            finder.idle = prefetch if lookup else None
            while not ((lookup and ready >= n) or examined >= (limit if lookup else n)):
                job = ahead.pop() if ahead else fetch()
                if job is None:
                    break
                examined += 1
                stats["examined"] = examined
                blocked = None
                if lookup:
                    cands = sorted((c for c in job["contacts"] if c["tier"] < 2), key=lambda c: c["tier"])  # HR, then heads
                    attempts = [0]

                    def look(c: dict) -> bool:
                        live = finder.lookup(c)
                        if live:
                            attempts[0] += 1
                            say(f"{c['name']} ({c['headline']}): {c['email'] or 'no email'} [{c['email_status']}]", tag="lookup")
                        return live
                    try:
                        for c in fill_emails(cands, look, cap, cfg.mailmeteor.max_attempts_per_company):
                            c["selected"] = True
                    except mailmeteor.Blocked as e:
                        blocked = str(e)
                else:
                    for c in pick_contacts(job["contacts"], cap):
                        c["selected"] = True
                total = len(job["contacts"])
                job["contacts"] = [c for c in job["contacts"] if c.get("selected") and (c["email"] or not lookup)]  # only keepers
                job["collected_at"] = datetime.now(timezone.utc).isoformat()
                say(f"  {job['company']}: {total} listed, {len(job['contacts'])} kept with email")
                if blocked:
                    say(f"STOPPED email lookups: {blocked}", err=True)
                    break
                if lookup and not job["contacts"]:
                    if any(c.get("email_status") == "timeout" for c in cands):
                        continue  # a lookup timed out: leave the job unmarked so a later run can retry it
                    store.mark_job(job["url"], job["title"], job["company"])  # nobody findable: don't redo it next run
                    continue
                done[job["job_id"]] = job
                jsonstore.save(out, list(done.values()))
                if lookup and has_sendable(job, store.already_emailed):
                    ready += 1
                    stats["ready"] = ready
                    say(f"  -> {ready}/{n} companies ready")
        except scrape.Checkpoint as e:
            say(f"STOPPED: LinkedIn checkpoint at {e}. Resolve it manually.", err=True)
            raise typer.Exit(1)
        finally:
            stats["lookups"] = finder.used
            stats["ready"] = ready
            browser.close()
    return stats


# --- step 2: contacts.json + resume -> emails.json (LLM) -------------------------------------------

def draft_step(cfg: Config, profile: Profile, store: Store, contacts: Path, out: Path) -> int:
    """Returns the number of new drafts."""
    set_step("draft")
    resume = load_resume_text(cfg.email.resume_path)
    links = " | ".join(f"{k.capitalize()}: {v}" for k, v in profile.links.items())
    signature = f"{cfg.email.sender_name}\n{profile.headline}\n{links}"
    results = jsonstore.load(out)  # keep earlier drafts (and any manual edits) untouched
    before = len(results)
    have = {r["job_id"] for r in results}
    for job in jsonstore.load(contacts):
        if job["job_id"] in have or job.get("drafted_at") or job.get("sent_at") or job.get("skipped"):
            continue  # already drafted / sent / skipped: never build or send it twice
        people = [Recipient(c["name"], c["email"]) for c in job["contacts"]
                  if c.get("selected") and c["email"] and not store.already_emailed(c["email"])]
        if not people:
            say(f"skip {job['company']}: nobody left to email")
            store.mark_job(job["url"], job["title"], job["company"])
            jsonstore.update_job(contacts, job["job_id"], skipped="everyone already emailed")
            continue
        feedback, core, problems = None, None, []
        for attempt in range(1, cfg.llm.max_attempts + 1):
            try:
                core = llm.draft_core(cfg, resume, job, feedback)
            except ValueError:
                feedback = ["reply must be exactly: SUBJECT: <subject> then BODY: <body>"]
                say(f"{job['company']}: attempt {attempt} -> unparsable reply")
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
            say(f"{job['company']}: attempt {attempt} -> {'ok' if not problems else problems}")
            if not problems:
                break
            feedback = problems
        if core is None:
            say(f"skip {job['company']}: model never produced a parsable draft (left in contacts.json)")
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
        jsonstore.update_job(contacts, job["job_id"], drafted_at=jsonstore.now())  # marker: subject + body are built
    jsonstore.save(out, results)
    say(f"{len(results)} drafts in {out} ({len(results) - before} new)")
    return len(results) - before


# --- step 3: emails.json -> Gmail, clearing entries as they succeed --------------------------------

def send_step(cfg: Config, store: Store, emails: Path, contacts: Path, live: bool, test_to: str | None = None) -> int:
    """Returns the number of recipients emailed."""
    set_step("send")
    drafts = jsonstore.load(emails)
    service = gmail.get_service() if (live or test_to) else None
    sent_run = failures = 0
    for d in drafts:
        label = f"{d['company']} -> {', '.join(d['to'])}"
        if Path("STOP").exists():
            say("STOP file found; halting.")
            break
        if d["status"] != "draft":
            say(f"skip {label}: status {d['status']} (needs review)")
            continue
        problems = validate_draft(Draft(d["subject"], d["body"]), d["company"], cfg.email.opt_out_line)
        if problems:
            say(f"skip {label}: {problems}")
            continue
        if test_to:
            msg = gmail.build_message([test_to], [], f"[TEST] {d['subject']}", d["body"], d["attachment"])
            say(f"TEST sent to {test_to}: {d['subject']} (id {gmail.send(service, msg)}) [would go to {label}]")
            continue
        fresh = [e for e in d["to"] if not store.already_emailed(e)]
        if not fresh:
            say(f"skip {label}: everyone already emailed")
            continue
        room = remaining_budget(cfg.limits.max_emails_per_run, cfg.limits.max_emails_per_day, sent_run, store.sent_today())
        if len(fresh) > room:
            say(f"skip {label}: needs {len(fresh)} sends, only {room} left under the caps")
            continue
        if not live:
            say(f"DRY RUN would send to {fresh} (cc {d['cc']}): {d['subject']}")
            continue
        try:
            msg = gmail.build_message(fresh, d["cc"], d["subject"], d["body"], d["attachment"])
            msg_id = gmail.send(service, msg)
        except Exception as e:  # keep the entry so it can be retried; stop if it keeps failing
            failures += 1
            say(f"FAILED {label}: {e} (entry kept)", err=True)
            if failures >= 2:
                say("two failures in a row; stopping.", err=True)
                break
            continue
        failures = 0
        say(f"SENT {fresh}: {d['subject']} (id {msg_id})")
        for e in fresh:
            store.record_email(e, d["job_url"], d["subject"], dry_run=False)
        store.mark_job(d["job_url"], d["job_title"], d["company"])
        jsonstore.remove_job(emails, d["job_id"])  # sent: off the send queue ...
        jsonstore.update_job(contacts, d["job_id"], sent_at=jsonstore.now())  # ... but kept (marked) in contacts.json for keep_days
        sent_run += len(fresh)
        time.sleep(random.uniform(*cfg.limits.delay_seconds))
    return sent_run


# --- commands --------------------------------------------------------------------------------------

@app.command()
def collect(jobs: int = typer.Option(None, help="New jobs to process (default: config run.jobs_per_run)"),
            out: Path = CONTACTS,
            lookup: bool = typer.Option(False, help="Find each selected contact's email via Mailmeteor (free, throttled)"),
            max_lookups: int = typer.Option(None, help="Per-company lookup cap (default: config)")) -> None:
    """Step 1: search LinkedIn, read each JD, list GetProspect contacts (+ Mailmeteor emails), save JSON."""
    cfg = load_config()
    cap = max_lookups if max_lookups is not None else cfg.mailmeteor.max_lookups_per_company
    collect_step(cfg, Store(), jobs or cfg.run.jobs_per_run, out, lookup, cap)


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
            say(f"PREFLIGHT FAILED: {p}", err=True)
        raise typer.Exit(1)
    say("preflight ok")


@app.command()
def run(jobs: int = typer.Option(None, help="New jobs this run (default: config run.jobs_per_run)"),
        lookup: bool = typer.Option(True, "--lookup/--no-lookup", help="Find contacts' emails via Mailmeteor"),
        live: bool = typer.Option(False, help="Really send the emails (default: stop with a dry-run plan)"),
        test_to: str = typer.Option(None, help="Run everything, but send every email ONLY to this address ([TEST])")) -> None:
    """Whole flow: collect -> start LLM -> draft -> stop LLM -> send, clearing entries as emails succeed."""
    cfg, store = load_config(), Store()
    n = jobs or cfg.run.jobs_per_run
    cap = cfg.mailmeteor.max_lookups_per_company
    started = datetime.now(timezone.utc)
    summary = {"started": started.isoformat(timespec="seconds"), "target": n, "live": bool(live and not test_to)}
    stats: dict = {}
    say(f"== 1/3 collect {n} new jobs (lookup={lookup}, cap {cap}/company)", tag="run")
    try:
        collect_step(cfg, store, n, CONTACTS, lookup, cap, stats)
    except typer.Exit:  # e.g. LinkedIn checkpoint: still draft/send whatever was collected so far
        say("collect stopped early; continuing with what was collected.", err=True)
    if Path("STOP").exists():
        raise typer.Exit()
    say(f"== 2/3 draft emails with {cfg.llm.model}", tag="run")
    proc = llm.start_llm(cfg)
    try:
        summary["drafted"] = draft_step(cfg, load_profile(), store, CONTACTS, EMAILS)
    finally:
        llm.stop_llm(cfg, proc)
        say("LLM stopped (model unloaded).")
    mode = f"TEST copies to {test_to}" if test_to else ("LIVE" if live else "dry run; pass --live to really send")
    say(f"== 3/3 send ({mode})", tag="run")
    summary["sent"] = send_step(cfg, store, EMAILS, CONTACTS, live and not test_to, test_to)
    left = len(jsonstore.load(EMAILS))
    summary.update(stats, left=left, seconds=int((datetime.now(timezone.utc) - started).total_seconds()))
    RUNS_LOG.parent.mkdir(exist_ok=True)
    with RUNS_LOG.open("a") as f:
        f.write(json.dumps(summary) + "\n")
    say(f"summary: {json.dumps(summary)}", tag="run")
    say(f"done. {left} entries remain in {EMAILS} (needs review / not sent)." if left else "done. All entries sent and cleared.", tag="run")


if __name__ == "__main__":
    app()
