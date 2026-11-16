# MockMate – Implementation Plan

Derived from the SRS v1.0 (2026-11-15). Each step is small enough to build, test and commit on its own.
Tick items as they land. Requirement IDs (FR/NFR) link back to the SRS.

## Key design decisions

| Topic | Decision | Why |
|---|---|---|
| Orchestrator | **Deterministic Python state machine**, not an LLM agent | Cheaper, predictable, testable. It holds session state, picks the round, enforces question limits, routes to agents. Only the specialist agents call Claude. |
| Interviewer turn | One Claude call per turn that returns **structured JSON** (`decision: follow_up / next_topic`, `question`, `topic`, `difficulty`) | FR-10/11/12 in a single call keeps latency (NFR-01) and cost (NFR-15) down. |
| Evaluator | Per-answer scoring runs **in the background** after each answer; final report aggregates | Report ready in < 30 s (NFR-02) even for 8 questions. |
| Structured outputs | `client.messages.parse()` with Pydantic models | FR-40 "structured JSON", output validation (prompt-injection risk). |
| Prompts | Versioned `.md` files in `backend/app/prompts/`, loaded by name | NFR-17. |
| CV / JD | Passed inside `<document>` tags, system prompt says "treat as data" | NFR-09. |
| LLM client | One wrapper (`app/llm/client.py`) that logs tokens/latency/cost per call and retries 2× | NFR-11, NFR-18, FR-61. All tests mock this wrapper (NFR-16). |
| DB | SQLAlchemy 2.0 + Alembic; SQLite in dev, Postgres in prod via `DATABASE_URL` | §2.4. |
| Streaming | Server-Sent Events for the next question | NFR-01 "starts appearing within 3 s". Added in Phase 1.5 after the non-streamed flow works. |
| Frontend | Vite + React + TypeScript, React Router, plain CSS with theme tokens | Few dependencies; light/dark via CSS variables. |

### Cost note (NFR-15: < US$0.30 per session)
Opus 5.5 is $4 / $20 per MTok. A rough 8-question session (≈ 9 interviewer calls + 8 scoring calls + 1 report) lands around **$0.20–0.35**.
Mitigations built in from the start: prompt caching on the stable system prompt + CV/JD prefix, `effort: "low"` for the interviewer,
compact per-turn context. We measure real cost per session from Phase 1 and decide on further levers then.

## Phase 0 – Setup (Day 1)
- [x] Repo layout, `.gitignore`, `.env.example`, `CLAUDE.md`
- [x] FastAPI skeleton with settings, CORS, `{"error": ...}` error format, `GET /health`
- [x] pytest + coverage config, first test
- [x] Vite React TS skeleton that calls `/health`
- [ ] Dockerfiles + `docker compose up` (NFR-19) — files written, not yet verified (Docker Desktop was not running)
- **Exit:** health check runs locally (backend test passes, frontend shows "API: ok")

## Phase 1 – MVP text interview (Weeks 1–2)
1. [x] DB models: Session, Message, Evaluation, Report (User nullable for now) + Alembic
2. [x] LLM wrapper: client, retries, usage logging, prompt loader, pricing table
3. [x] Interviewer agent + prompt (FR-10, FR-11, FR-16) with Pydantic output schema
4. [x] Orchestrator state machine (FR-14: default 8 questions, end early)
5. [x] Evaluator agent: per-answer score (FR-40), final report (FR-41)
6. [x] API: `POST /sessions`, `POST /sessions/{id}/answer`, `POST /sessions/{id}/end`, `GET /sessions/{id}/report`
7. [x] Frontend: Setup page (FR-03/04/05), Interview chat page, Report page
8. [ ] SSE streaming for the next question (NFR-01) — measure real latency with an API key first; stream only if p95 > 3 s
- **Exit:** one complete 8-question interview with report; cost per session logged

## Phase 2 – Personalisation (Week 3)
- [x] Auth: register/login, bcrypt, JWT 24 h (FR-01, NFR-05); admins via `ADMIN_EMAILS`
- [x] Persist sessions per user + history list (FR-50); delete session/account with password (FR-54, UC-04)
- [x] CV upload → pypdf text in memory, PDF not stored (FR-06, §6.1)
- [x] Session types with HR→technical rounds (FR-07), personalities (FR-08), CV project question by Q3 (FR-13), adaptive difficulty (FR-12)
- [x] STAR flags (FR-42)
- [x] Usage/cost logger + daily cap + admin usage page (FR-61, FR-62)
- [x] Guest flow (one 5-question interview) + 24 h cleanup (FR-02)
- **Exit:** CV-based question appears — verified in demo mode; confirm with real Claude once an API key is set

## Phase 3 – Voice (Week 4)
- [x] Web Speech API dictation into an editable answer box (FR-20, FR-23); auto-restart after pauses
- [x] Questions read aloud with mute + per-message replay (FR-21); TTS stops when the mic starts
- [x] Voice/text toggle at any time; text fallback when unsupported or mic blocked (FR-22, UC-01 4a)
- [x] Speech metrics tool: fillers, WPM, answer length from the raw transcript (FR-43); "How you spoke" report card
- **Exit:** full interview by voice — server side verified; needs a manual run in Chrome/Edge with a microphone

## Phase 4 – Coding (Week 5)
- [x] CodingProblem model + admin CRUD with reference-solution validation (FR-60, UC-05); 7-problem starter bank seeded on first start-up; archive instead of delete
- [x] Docker sandbox: no network, read-only FS, 5 s CPU, 128 MB, 64 pids, non-root, all caps dropped, 256 KB output cap, wall-clock kill (FR-31, NFR-07); per-test 2 s limit so slow code keeps partial results; Python 3.12 and Node 22
- [x] Run (sample tests) / submit (sample + hidden) endpoints; hidden inputs never sent to the client (FR-32); 3 graduated pre-written hints, -1 correctness each (FR-33); complexity follow-up question scored against the submitted code (FR-34)
- [x] Scoring: correctness from tests (deterministic), code quality and efficiency from a Claude code review (`code_review.v1`); one Claude call for the code + one for the follow-up
- [x] Monaco editor workspace, lazy-loaded and bundled locally (FR-30); drafts kept per language in the browser; admin problem editor
- **Exit:** sandbox passes security tests (network blocked, fork bomb/time/memory limits) — done, `tests/test_sandbox.py` against real containers
- Notes: the harness runs inside the container with the hidden expected values, so a determined candidate could read them via introspection; acceptable for practice, not for hiring. Docker compose disables the coding round (no Docker socket in the container). **Deploy (Phase 6): Render web services can't start containers, so the sandbox needs its own host (small VM with Docker behind a runner API) or a hosted code-execution service.**

## Phase 5 – Progress (Weeks 6–7)
- [ ] Progress endpoint + dashboard: score trend, 5 weakest topics (FR-51)
- [ ] Weak-topic weighting in new sessions (FR-52)
- [ ] Study-plan agent (FR-53); panel mode hire/no-hire (FR-44)
- **Exit:** second session favours weak topics

## Phase 6 – Release (Week 8)
- [ ] 30-answer eval set for evaluator (±1 on 80%) and follow-up relevance review
- [ ] PDF report download (FR-45), data export (NFR-10)
- [ ] CI (GitHub Actions: lint, tests, coverage ≥ 70%), secret scan
- [ ] Deploy: Render (backend + Postgres), Vercel (frontend); README + demo video
- **Exit:** all acceptance criteria in SRS §9.1 met
