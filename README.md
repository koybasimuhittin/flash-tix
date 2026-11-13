# FlashTix

A flash-sale event-ticketing system. When sales open, many buyers hit the same event's seats at the same moment: FlashTix holds seats atomically, never sells a seat twice, and generates PDF tickets in the background.

- **Three FastAPI services:** `auth` (accounts, JWT), `catalog` (events, seat layouts, Redis cache), `booking` (seat holds in Redis via Lua scripts, purchases, tickets).
- **nginx gateway:** one entry point, per-user rate limit, request ids.
- **React frontend.**
- **PostgreSQL + Redis.**
- **Background jobs:** `ticket-pdf` renders a ticket after every purchase; `daily-report` writes a CSV of each day's sales.

```
browser ──► gateway (nginx) ──┬─► auth-service ──────► Postgres authdb
            :8080             ├─► catalog-service ───► Postgres catalogdb, Redis (cache)
                              ├─► booking-service ───► Postgres bookingdb, Redis (holds)
                              │        │ booking.confirmed
                              │        ▼
                              │   ticket-pdf ──► storage  tickets/<id>.pdf
                              └─► frontend     daily-report ──► storage  reports/<date>.csv
```

## Run it locally

Everything runs in Docker Compose.

### Prerequisites

- Docker with Compose v2 (on macOS e.g. [Colima](https://github.com/abiosoft/colima): `colima start`; the default 2 CPU / 4 GiB is enough)
- `make`, `openssl`, `curl`
- Python 3.12+ on the host (the `make seed` / `smoke` / `oversell` scripts use only the standard library)

### Start

```bash
git clone https://github.com/koybasimuhittin/flash-tix.git
cd flash-tix
make up      # creates .env and JWT keys, builds every image, waits until all are healthy
make seed    # demo events; the 1000-seat flash sale opens 2 minutes after each run
make smoke   # end-to-end check (must end with "smoke test passed")
```

Open <http://localhost:8080>. Log in as the organizer `organizer@example.com` / `organizer-local-pass` (from `.env`), or register a customer in the UI.

| Command | What it does |
|---|---|
| `make up` / `make down` / `make clean` | start (and wait for health) / stop / stop and **delete all data** |
| `make seed` | demo events through the API; idempotent; re-arms the flash sale to open in 2 min |
| `make smoke` | holds and conflicts, purchase, ticket PDF, 20 concurrent buyers on one seat (exactly 1 wins), oversell check |
| `make oversell [strict=1]` | proof that no seat was sold twice and no event beyond its capacity |
| `make report [date=YYYY-MM-DD]` | write the daily sales report (default: yesterday, Istanbul time) |
| `make logs s=booking-service`, `make ps` | follow one service's logs / list containers |
| `make psql db=bookingdb` | psql as the Postgres superuser |
| `make db-check`, `make gateway-check` | verify database isolation / gateway routing and rate limit |
| `make help` | every target |

**Monolith mode:** `MONOLITH=1 make up` runs the same code as **one** process instead of three services, behind the same gateway (use `MONOLITH=1` with `down`/`logs` too). `make seed && make smoke` work unchanged.

### Tests and lint

```bash
make dev     # .venv with the shared library, all service dependencies, ruff, pytest
make lint    # ruff check + ruff format --check
make test    # pytest; database tests use the running stack (Postgres :5433, Redis :6380)
```

CI (GitHub Actions) runs lint and tests, the database and gateway checks, the frontend build and tests, and the full `make up → seed → smoke → report` chain on a fresh machine, once for the microservices and once for the monolith.

### Troubleshooting

- **Tickets never become ready / `Permission denied` in the ticket container logs:** your `flashtix_storage` volume was created by an older version as root. Run `make clean` (or `docker volume rm flashtix_storage`) once, then `make up`.
- **401 everywhere after switching branches or worktrees:** every service must use the same `secrets/` keys. Run `make down && make up` from one checkout.
- **Port 8080 / 5433 / 6380 / 8091 already in use:** stop the other program or another FlashTix stack (`make down`).
- **The build runs out of memory (Colima):** `colima stop && colima start --cpu 4 --memory 6`.

### Repository layout

```
services/   common (flashtix_common), auth, catalog, booking, monolith   (FastAPI, Python 3.12)
functions/  ticket_pdf, daily_report                                       (background jobs)
gateway/    nginx template          frontend/   React app
infra/      postgres init script    scripts/    seed, smoke, oversell, checks
```


## Frontend

The UI is a single-page app in `frontend/`: Vite, React 19, TypeScript and react-router, styled with Tailwind CSS v4 and shadcn/ui components (`src/components/ui/`). The design tokens are CSS variables at the top of `src/styles.css`.

| Route | Page |
|---|---|
| `/` | Upcoming events, with search and city filter |
| `/events/:id` | Sales countdown and seat map. Pick up to 6 seats → **Hold** → **Pay (mock)** |
| `/login`, `/register` | Accounts; the JWT is kept in `localStorage` |
| `/bookings` | My tickets. **Download ticket (PDF)** appears once the ticket is generated |
| `/organizer`, `/organizer/new` | Organizer only: sold / held / capacity per event, daily report CSV, create event |

### Run it

- **With the stack:** `make up` builds the `frontend` image (Node 22 build, nginx serve) and the gateway serves it at <http://localhost:8080>.
- **Live reload while editing:** keep the stack up and run `make fe-dev`. It opens <http://localhost:5173> and Vite proxies `/api` to the gateway on `:8080`.
- **Checks** (all three run in the CI `frontend` job):

  ```bash
  cd frontend
  npm ci
  npm run typecheck   # tsc --noEmit
  npm test            # vitest: seat states, clock offset, API error mapping
  npm run build       # production bundle in dist/
  ```

  Use Node 22 (or 24); vitest does not support Node 23. `frontend/.nvmrc` pins 22, so with nvm run `cd frontend && nvm use`.

Log in as the bootstrap organizer from `.env` (`organizer@example.com` / `organizer-local-pass` locally) to see the organizer pages. Register customers in the UI.

### How it talks to the backend

- **One entry point.** Every request goes to the nginx gateway as a relative `/api/...` URL, so the same build works locally and in GKE.
- **One wrapper.** `src/api.ts` is the only code that calls `fetch`.
  - It adds `Authorization: Bearer <token>`.
  - It turns `{"detail": {"code": ...}}` errors into an `ApiError` with a `code`.
  - It logs the user out when an authenticated request gets 401.
  - It shows the gateway's 429 as "slow down".
- **Polling, not WebSockets.**
  - The event page polls `GET /api/booking/events/{id}/availability` every 3 s. That endpoint reads Redis only.
  - The "My events" page sends **one** batch stats request every 5 s, so the per-user rate limit is never hit.
  - Polling pauses while the tab is hidden.
- **Server time for countdowns.** Each availability response carries `server_time`. The page keeps the offset from the local clock, measured at the midpoint of the round trip. The sales countdown and the hold timer therefore follow the server, even if the laptop clock is wrong.
- **Authenticated downloads.** Tickets and reports need the Authorization header, so a plain link would fail. Instead the page:
  1. fetches the file with the header,
  2. turns the response into a blob,
  3. creates an object URL,
  4. clicks a temporary link to save it.
