# ApplyPilot: Human-in-the-loop Job Application Agent

An agent that drives a real browser, fills ATS job forms from a grounded profile, and **stops at a review screen** so the user approves before submit.

## Goals
- Genuinely usable for my own job search.
- Resume-grade: measurable accuracy, guardrails, audit log, public repo with benchmarks.

## Non-goals
- No mass-apply / spam. No LinkedIn / Indeed / Naukri automation (ToS + bans).
- No fire-and-forget submit. Human approval is always required.
- No fabricated answers: anything not in the profile is flagged, never guessed.

## Scope: supported sites (MVP)
Greenhouse, Lever (then Ashby, Workable).

## Architecture
```
Profile (YAML/JSON, source of truth)
        |
Job URL -> Scraper/Parser -> Job model (title, JD, questions)
        |
   Tailor: pick relevant bullets, draft cover note (LLM, grounded in profile)
        |
   Form agent (Playwright + Claude tool use)
     - detect fields -> map to profile -> fill
     - unknown/low-confidence -> flag for user
        |
   Review gate (UI): diff of every answer, approve / edit / abort
        |
   Submit (only after approval) -> Postgres audit log
```

## Tech stack
- TypeScript, Node.js (or Bun)
- Playwright (own browser profile; optional attach to real Chrome via CDP)
- Claude API with tool use (model per `claude-api` skill at build time)
- PostgreSQL + Prisma (applications, answers, runs, status)
- Small review UI (React + Tailwind) served locally
- Vitest for tests; GitHub Actions CI; Docker compose for DB

## Data model (initial)
- `Profile`: static file, not in DB (facts, experience bullets, links, salary/notice-period policy)
- `Job`: url, company, title, description, ats, fetchedAt
- `Application`: jobId, status (drafted/approved/submitted/failed), tailoredResumePath, coverNote
- `Answer`: applicationId, fieldLabel, fieldType, value, source (profile|generated|user), confidence
- `Run`: applicationId, tokens, cost, durationMs, trace

## Guardrails
- Grounding: every answer cites a profile key, or is marked `generated` and requires review.
- Hard-block fields: salary, work authorization, demographic/EEO, and anything legal need explicit user answer unless the profile has a policy for them.
- Approval gate before submit; dry-run mode default.
- Rate limit and per-site allowlist; CAPTCHA -> pause and hand to user.
- Full audit log of what was submitted.

## Evaluation (the resume differentiator)
- Benchmark: N saved ATS form snapshots (HTML fixtures) with expected field mappings.
- Metrics: field detection recall, fill accuracy, flag precision (should-flag vs. flagged), cost and latency per form.
- Compare approaches: DOM heuristics vs. LLM mapping vs. hybrid. Report in README.

## Milestones
1. **M0 Setup** (day 1): repo, TS config, lint, Husky, CI, docker compose Postgres, Prisma schema.
2. **M1 Profile + Job parsing**: profile schema + validation; fetch and parse Greenhouse/Lever job pages.
3. **M2 Form filling, dry run**: Playwright detects fields, maps to profile, fills, screenshots, never submits.
4. **M3 Review gate**: local UI showing answers with source and confidence; approve/edit/abort.
5. **M4 Tailoring**: JD-to-profile matching, bullet selection, cover note, resume variant.
6. **M5 Submit + tracking**: gated submit, audit log, status dashboard.
7. **M6 Eval harness**: fixtures, metrics, comparison report.
8. **M7 Polish**: README with architecture diagram and benchmarks, demo GIF, tradeoffs write-up, Docker one-command demo.

## Risks
- Form variability, so fixtures plus a hybrid approach.
- LLM nondeterminism, so temperature 0, structured outputs, and eval repeats.
- Site anti-bot, so stay on ATS-hosted forms, human in the loop.
- Privacy: profile and resumes stay local; never commit them (gitignore).

## Open questions
- Attach to my real Chrome (logged-in sessions) vs. a clean Playwright profile?
- Local-only UI vs. CLI-only first?
- Which companies/ATS do I actually apply to most (drives fixture choice)?
