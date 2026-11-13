# CLAUDE.md — FlashTix

FlashTix is a flash-sale event-ticketing system: three FastAPI services (auth, catalog, booking), an nginx gateway, a React frontend, PostgreSQL + Redis, and a worker service for background jobs (ticket PDFs, the daily sales report). See `README.md` for the architecture, how to run it and the `make` targets.

## Working mode
- The user works **solo** for now. **Claude writes the code** and explains it; the user reviews.
- **Sessions:** **master** (backend, assigns work, merges), **frontend** (UI work assigned by master), **reviewer** (reviews every PR). No subagents: master and frontend do the work themselves and send every PR to the reviewer.

## Rules
1. **Same code locally and wherever it is deployed.** Environment differences go through settings and adapters only (`EVENT_BACKEND`, `STORAGE_BACKEND`, URLs, credentials); no `if production:` forks.
2. **Explain choices.** A new component or dependency comes with its alternatives and the reason for the pick, in the PR description.
3. **Never commit secrets** (`.env`, `secrets/`).
4. **Never block the event loop:** bcrypt, PDF rendering and sync SDK calls go through a threadpool. Never hold a DB session across Redis, HTTP or sleep calls.
5. **Tests:** pytest from the repo root (`make test`). Database tests use the compose stack (Postgres `127.0.0.1:5433`, Redis `127.0.0.1:6380`) and skip without it, unless `REQUIRE_DB=1` (set in CI), where they fail.
6. **Apple Silicon:** images for amd64 hosts are built with `docker buildx build --platform linux/amd64`.
7. **Language:** reply in the user's language (Turkish or English). Code, comments, commit messages and docs are in English.
8. **Git workflow (no need to ask):**
   - One feature branch per task; atomic commits (Conventional Commits); push the branch and open a PR that links its issue (`Closes #N`).
   - Ask the `reviewer` session to review each PR. Merge only when it has the **`approved`** label (applied by the reviewer) **and** CI is green. `changes-requested` means fix, push, ask again. **New commits on an `approved` PR void the approval:** remove the label and ask for a re-review.
   - Stage files by explicit path, never `git add -A`.
   - Stacked PRs merge bottom-up; **retarget dependent PRs to `main` before deleting a merged branch** (deleting a base branch closes its PRs).
   - Never push directly to `main`, force-push to `main`, or rewrite its history.
9. **Explain what you build.** Every PR description has a **"How it works"** section for the user: what the code does, why, and how to explain it.

## Commands (`make help` lists them all)
```bash
make dev       # .venv with flashtix_common, all service dependencies, ruff, pytest
make up        # build + start everything, wait until healthy (gateway on http://localhost:8080)
make seed      # demo events (idempotent); re-arms the 1000-seat flash sale to open in 2 min
make smoke     # end-to-end: holds, purchase, ticket PDF, 20-buyer race, oversell check
make report    # daily sales report: make report [date=YYYY-MM-DD]
make oversell  # no seat sold twice, sold <= capacity per event; strict=1 after load tests
MONOLITH=1 make up   # same code as ONE process; use MONOLITH=1 for down/logs too
make logs s=booking-service | make ps | make down | make clean
make psql db=bookingdb | make db-check | make gateway-check
make test | make lint | make fmt | make fe-dev
```

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
