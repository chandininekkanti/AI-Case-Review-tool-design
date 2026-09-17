# Junior AI Investigator — Case Review Prototype

An AI-first triage tool for a fraud investigation queue. Instead of an
investigator opening each claim cold, the app pre-computes a risk
assessment for every case in the queue — a narrative summary, the specific
signals driving the score, a risk level, and a recommended next step — so
the investigator's morning starts with a ranked, explained queue instead of
50 blank case files.

## Quick start

```bash
cd case-review-tool
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

# Optional: enable real Claude reasoning (see "Reasoning modes" below).
# If you skip this, the app runs fully on the built-in mock reasoner.
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-... if you have one
export $(grep -v '^#' .env | xargs)   # or just `export ANTHROPIC_API_KEY=...`

uvicorn backend.main:app --app-dir . --reload --port 8008
```

Open **http://localhost:8008**. That's the whole app — no build step, no
database to provision, no separate frontend server.

Investigator actions (accept/reject, notes, chat) persist to
`case_store.json` in the project root, so they survive a server restart.
Delete that file to reset the demo to a clean state.

## Reasoning modes

The AI reasoning layer (`backend/ai_engine.py`) has two interchangeable
engines behind one interface:

- **Mock engine (default, no key needed).** A deterministic rule engine
  (`backend/scoring.py`) scores each case from its 10 signals and produces
  a ranked, weighted list of triggered indicators. A template layer turns
  that into readable narrative text and answers follow-up questions by
  looking up the relevant field on the case record. This is what runs out
  of the box — zero cost, zero API dependency, and fully explainable.
- **Claude engine (set `ANTHROPIC_API_KEY` to activate).** Calls the real
  Claude API to *narrate* the same, already-computed evidence packet, and
  to answer free-form follow-up questions grounded in the case record. If
  the API call fails for any reason, it falls back to the mock engine
  automatically rather than breaking the UI.

Critically, **the LLM is never asked to invent a risk score from scratch**.
`scoring.py` always computes the score and evidence deterministically from
the CSV first; the LLM's job is narrower — narrate and explain, not decide.
See the write-up for why this split is the main lever we use to keep the
system grounded and resistant to hallucination.

## What's built

- Loads all 50 cases from `data/sample_cases.csv`.
- Computes a 0–100 risk score, risk level (low/medium/high), and a
  confidence label for every case, with a full breakdown of which signals
  contributed and why.
- A ranked queue view (highest risk first) with search and risk filters.
- A case detail view: attributes, AI summary, weighted indicator list,
  recommended action, accept/reject controls, freeform notes, and a
  follow-up-question chat box grounded in that case's own data.
- A cross-case signal that a single-row view can't catch: **C1001 and
  C1031 share the exact same claim number** (`LTC-2034786`), which is
  flagged as a strong duplicate-submission indicator.

## Project structure

```
case-review-tool/
├── backend/
│   ├── main.py         FastAPI app + API routes, serves the frontend
│   ├── data_loader.py  CSV loading + cross-case signal (duplicate claim #)
│   ├── scoring.py       Deterministic, explainable rule engine
│   ├── ai_engine.py     Mock + Claude reasoning engines (shared interface)
│   └── store.py         JSON-file-backed investigator actions
├── frontend/
│   ├── index.html / app.js / styles.css   Vanilla JS console, no build step
├── data/
│   └── sample_cases.csv
├── case_store.json      Created at runtime (investigator actions)
├── requirements.txt
└── .env.example
```

## Assumptions

- Signal thresholds in `scoring.py` (e.g. "distance > 150mi is a strong
  flag") are documented, reasonable-sounding defaults for illustrative
  purposes — in production these would be learned from labeled fraud
  outcomes and would likely be peer-group- or care-type-specific rather
  than global constants.
- "Accept" means the investigator agrees with the AI's finding and is
  ready to act on the recommended next step; "Reject" means they're
  overriding the AI's call. Both are logged, which is the seed of a
  feedback loop for improving the model over time (see write-up).
- Single-investigator demo: there's no auth or per-user accounts, per the
  assignment's "don't build auth" constraint.
