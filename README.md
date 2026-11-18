# MockMate

AI mock interviews for students and graduates preparing for internship, junior and mid-level tech roles.
MockMate runs a realistic interview by text or voice, adapts to your answers, scores each one against a fixed
rubric, and gives you a report, a progress dashboard and a study plan.

Built with FastAPI, React and Claude (`claude-opus-5-5`). Specification: SRS v1.0; build log:
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Features

| Area | What you get | SRS |
|---|---|---|
| Interview | HR, technical, full (HR then technical) or coding interviews; 3 interviewer styles or a 3-person panel; follow-ups on vague answers; difficulty adapts to how you're doing | FR-03–FR-16, FR-44 |
| Personalisation | Paste the job description and upload your CV (PDF): questions match the role, and one is always about a project on your CV | FR-05, FR-06, FR-13 |
| Voice | Answer out loud (Chrome / Edge), hear the questions, edit the transcript before sending | FR-20–FR-23 |
| Coding round | Monaco editor, Python or JavaScript, sample tests, hidden tests, hints, complexity follow-up; code runs in an isolated Docker sandbox | FR-30–FR-34 |
| Feedback | Scores for correctness, clarity and depth, STAR check, model answers, delivery metrics (pace, filler words), panel hire / no-hire, PDF download | FR-40–FR-45 |
| Progress | Score trend, weakest topics (which new interviews revisit automatically), study plan | FR-50–FR-53 |
| Privacy | Guest mode, export all your data, delete your account; CV PDFs are never stored, only their text | FR-02, FR-54, NFR-10 |
| Admin | Usage and cost per day, daily spending cap, coding-problem manager | FR-60–FR-62 |

## How it works

```
React (Vite) ──HTTP/JSON──▶ FastAPI
                             ├─ Orchestrator (plain Python): rounds, difficulty, follow-up limits,
                             │  CV / weak-topic / panel rules. Never calls Claude itself.
                             ├─ Agents (Claude, structured output): interviewer, evaluator,
                             │  code reviewer, report, panel, study plan
                             ├─ Tools: CV parser, speech metrics, Docker code sandbox, PDF renderer
                             └─ SQLAlchemy + Alembic ─▶ SQLite (dev) / Postgres (prod)
```

- **One Claude call per interviewer turn** returns the decision (follow-up / new topic / redirect), the
  topic, the difficulty and the question as JSON. Answers are scored in the background, so the report is
  ready seconds after the last answer.
- **Prompts are versioned files** in [backend/app/prompts](backend/app/prompts); changing one means a new
  version file.
- **Untrusted text** (CV, job description, answers, code) is wrapped in tags and treated as data; attempts to
  instruct the model are redirected and earn no credit.
- **Cost control:** prompt caching, low reasoning effort where latency matters, a per-day spending cap, and
  token/cost logging for every call (see the Admin page).

## Run it locally

Requirements: Python 3.11+, Node 22, and Docker Desktop for the coding round.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt      # macOS/Linux: .venv/bin/pip
cp .env.example .env                                   # then edit it (see below)
.venv/Scripts/uvicorn app.main:app --reload            # http://localhost:8000, runs migrations on start

# Frontend (second terminal)
cd frontend
npm install
npm run dev                                            # http://localhost:5173
```

**No API key yet?** Set `USE_FAKE_LLM=true` in `backend/.env` for demo mode: canned questions and placeholder
scores, no cost. Everything else (voice, coding sandbox, PDF, dashboard) works normally.

**Whole stack in Docker:** `docker compose up --build`. The coding round is switched off there, because
running the sandbox from inside a container would mean giving it the host's Docker socket.

### Configuration (`backend/.env`)

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | - | Required unless `USE_FAKE_LLM=true`. Only ever set in the environment. |
| `JWT_SECRET` | dev value | Production refuses to start unless it's 32+ random characters. |
| `DATABASE_URL` | `sqlite:///./mockmate.db` | `postgres://…` / `postgresql://…` URLs work as given. |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list of frontend URLs. |
| `ADMIN_EMAILS` | `[]` | Accounts registered with these emails become admins. |
| `DAILY_COST_CAP_USD` | `5.0` | New interviews are refused once today's spend reaches it. |
| `SANDBOX_ENABLED` | `true` | Needs Docker on the same machine. |
| `USE_FAKE_LLM` | `false` | Demo mode. |

Frontend: `VITE_API_URL` (build time) points at the API, default `http://localhost:8000`.

## Tests and quality

```bash
cd backend
.venv/Scripts/python -m pytest --cov                   # 160+ tests, coverage gate 70% (currently ~97%)
.venv/Scripts/ruff check app tests evals
cd ../frontend && npm run lint && npm run build
```

- Claude is always mocked in tests; nothing in the suite calls the real API.
- `tests/test_sandbox.py` runs real containers to prove the sandbox blocks network access, file writes,
  infinite loops, memory and fork bombs and output floods. It skips itself when Docker isn't running.
- Set `TEST_DATABASE_URL=postgresql://user:pass@host/db` to run the whole suite on Postgres.
- [CI](.github/workflows/ci.yml) runs all of this on every push and pull request (tests on Postgres 16 with real
  sandbox containers), plus a gitleaks secret scan.

### Evaluating the AI

The tests check the plumbing; these check the judgement. Both call the real API, so they are never part of the
test suite and they ask for `--yes` first.

```bash
cd backend
.venv/Scripts/python -m evals.run_evaluator_eval        # 30 answers with reference scores; target: 80% within ±1
.venv/Scripts/python -m evals.run_followup_review       # 10 vague answers -> a checklist for a human reviewer
```

The reference scores in `evals/evaluator_set.jsonl` are a first draft; have a second person review them before
trusting the agreement number. Re-run both after any prompt change.

## Deploy

**Backend + database on Render.** In Render choose *New → Blueprint* and point it at this repository;
[render.yaml](render.yaml) creates the API (Docker) and a Postgres database, generates `JWT_SECRET`, and asks
for `ANTHROPIC_API_KEY`, `CORS_ORIGINS` (your Vercel URL as a JSON list) and `ADMIN_EMAILS`. Migrations run
when the service starts. `GET /health` is the health check.

**Frontend on Vercel.** Import the repository, set the root directory to `frontend` and the environment
variable `VITE_API_URL` to the Render API URL. [vercel.json](frontend/vercel.json) handles client-side routes
and security headers.

### Coding round in production

The sandbox starts a fresh Docker container per run, and Render web services can't do that, so `render.yaml`
sets `SANDBOX_ENABLED=false` and the setup page shows the coding round as unavailable. To offer it, run the
backend (or a small runner service built from `app/tools/sandbox.py`) on a VM with Docker, such as a small
cloud instance, or swap in a hosted code-execution service behind the same `Sandbox` interface.

## Project layout

```
backend/
  app/
    api/            HTTP routes (sessions, coding, users, auth, cv, admin, problems)
    agents/         Claude agents: interviewer, evaluator, study plan
    prompts/        versioned prompt files
    llm/            Claude client wrapper, pricing, demo/fake LLM
    tools/          CV parser, speech metrics, sandbox (+ in-container harness), PDF report
    orchestrator.py interview state machine;  coding.py coding round;  progress.py dashboard + weak topics
    data/           starter coding problems, fonts for the PDF
  alembic/          database migrations
  evals/            evaluator eval set and follow-up review
  tests/
frontend/src/
  pages/            setup, interview, coding workspace, report, progress, history, account, admin
  api.ts            typed API client;  speech.ts  voice hooks;  monaco.ts  bundled editor
```

## Known limitations

- Voice input uses the browser's speech recognition (Chrome and Edge; Chrome sends audio to Google to
  transcribe it). MockMate itself only receives text. Browsers often drop "um" and "uh", so filler counts are a
  lower bound.
- In the coding round, the hidden tests' expected answers are inside the sandbox container, so a determined
  candidate could read them. That's fine for practice, but not for real hiring decisions.
- Topics are free-text labels written by the interviewer; very different wordings of the same subject count as
  separate topics on the dashboard.
- Scores are AI-generated practice feedback, not a hiring decision.
