# StormHaven: shared context for every teammate's AI agent
**Read this fully before doing anything.** It's the source of truth for goals and rules; details live in `docs/`. Keep it current: if a decision changes, update this file in the same PR.

## 1. The challenge
HackOHI/O 2026, AEP "AI Outage Concierge" (24 h). A storm is coming; build an AI assistant answering four **customer** questions for an anonymized location:
1. **Will I lose power?** Band + confidence + reasons.
2. **How long?** A RANGE (never a single time) that updates with damage, crews and access, and separates model estimates from confirmed utility info.
3. **What should I do?** Safety + actions by risk, duration and DECLARED needs (opt-in only, never inferred).
4. **Do I get alerts?** Documented rules, timing, escalations, and pre-storm / outage-confirmed / estimate-updated / restored messages.

Plus trust: plain language, confidence, assumptions, missing data, privacy, honest fallback.
**Judging values:** customer impact, utility modernization, operational realism, responsible AI. Focused and credible beats broad.
**Judges' data guide:** What is damaged? Who depends on it? What work fixes it? With limited crews and critical customers, what goes first and how long? State crew size (2–8). Compare restoring everyone in 2 d / 3 d / 1 wk. Labor hours × 4.5 = person-hours.
**Requirement:** judges must be able to change at least one scenario input and see the answer change.

## 2. Product direction (decided; don't drift)
- **Consumer-first, phone-first.** The final deliverable is a **~3-minute ad-style video**, so polish of the customer golden path beats new features.
- **Customers identify themselves with the premise ID from their bill**, plus an optional "use my location" that snaps to the nearest neighborhood transformer. **Never addresses:** we deliberately never read the customer file. The map zooms to *their* neighborhood.
- **No operator knobs for customers.** Crew size is a stated assumption, not a control. Scenario inputs live in a collapsible **"What if…?"** section in customer words:
  - "What if the storm is worse than forecast?" (severity)
  - "What if roads are blocked?" (road access)
  - "What if AEP brings in extra crews?" (crews)
- **Operator console: frozen** (exists, read-only, not required). The utility-side planner reaches customers as **one sentence**: `restoration.storm_context`, e.g. "In our replay of the Feb 2025 storm with 20 crews, 9 in 10 affected homes had power back within about 3 days."
- **Golden path for the video:**
  1. A storm-warning text on a real phone.
  2. Open the app and enter the premise ID; the map zooms to the neighborhood.
  3. Risk band and why.
  4. The range, timeline and storm context, plus one "What if roads are blocked?" change.
  5. Ticking "medical device" changes the advice and shows a human escalation.
  6. A chat question, plus the 911 safety answer.
  7. "Estimate updated" and "power restored" texts.
  8. A 20-second trust beat: real AEP data, backtest chart, "the AI never makes up numbers", privacy.
- **Feature freeze at hour 18.** After that: fixes, video, rehearsal.

## 3. Architecture
- **Backend (FastAPI, `backend/app/`):** deterministic engines compute every number.
  - `engines/risk.py`: P(out) from the damage history of the upline equipment, scaled by storm severity
  - `engines/restoration.py`: Monte Carlo range; queue calibrated on the storm replay; value-vs-effort priority; `storm_context`
  - `engines/guidance.py` + `content/guidance_library.yaml` (EN/ES)
  - `engines/alerts.py` + `content/message_templates.yaml` (EN/ES; one shared rounding rule with the on-screen range)
  - `engines/planner.py` + `planner_routes.py`: replays a real storm, gives the restoration curve and crews needed for 2 d / 3 d / 1 wk
- **AI:** **Amazon Nova Lite on Bedrock (us-east-2) + Guardrail (deliberate choice).** Nova only routes the question to an answer category and may request one validated what-if; Python renders every fact. **The LLM never computes or writes outage numbers.** Offline fallback; a fixed 911 message is added in code.
- **Endpoints:** `/api/health`, `/api/concierge`, `/api/map`, `/api/weather` (context only), `/api/chat`, `/api/notify` (SNS; dry-run unless configured), `/api/planner/*`, `/api/console/*`, `/api/locate` (Abby, in progress).
- **Frontend:** React + Vite, Plotly `scattermap` (no key), dark mode, heatmap, EN/ES, the three-column answer (Confirmed / Our estimate / What you can do), timeline, chat.
- **All assumptions** are in `config/assumptions.yaml`, explained in `docs/ASSUMPTIONS.md`. Judge Q&A answers: `docs/QA_PREP.md`.

## 4. Data
- Real AEP data (Roanoke, VA area) is committed **compressed** in `data/archives/`. **`make data`** builds `data/raw/` and `data/processed/` (~40 s). Never commit those folders. Without `make data`, a fake Columbus network loads (`/api/health` → `synthetic_data: true`).
- **Privacy:**
  - The customer file (addresses, life-support flags) is never read or committed.
  - Homes appear only at transformer level.
  - Facility locations never leave the backend.
  - Every customer-facing string passes `core/privacy.scrub_text`.
  - Never paste premise IDs, coordinates or device IDs into docs, prompts or slides.

## 5. Numbers to use consistently
- **Risk backtest** (leave-one-storm-out, 4.2M pairs):
  - **Brier score:** 0.0097 vs 0.0113 baseline.
  - **Calibration:** good from 0–80%; 80%+ came true ~half the time (disclosed in the app).
  - **Feb 2025:** predicted 18.7% out vs actual 22.5%.
  - We **kept the simpler model** (v1 with features didn't win).
- **Repair work:** a medium three-phase pole = **26.3 person-hours** (guide example: 27). Storm history: 15,278 person-hours.
- **Feb 2025 replay:** 26,424 customers out, 11,800 person-hours.
  - **With 20 crews × 3:** 50% back ~16 h, 90% ~3 days, all ~8 days.
  - **To restore everyone:** 2 days needs **291 people**, 3 days **180**, 1 week **75**.
  - **Customer engine agreement:** the typical home's best guess is 15 h vs the replay's 16 h.
- Charts: `docs/figures/` (`make figures`). Weather credit: "Weather data by Open-Meteo.com".

## 6. Ownership (edit only your own files; ask the gatekeeper for shared ones)
| person | owns |
|---|---|
| **Akshat** (pitch owner) | `pipelines/03,04,05,07,09,10,_rates.py`, `engines/risk.py`, `restoration.py`, `planner.py`, `planner_routes.py`, `config/assumptions.yaml`, `docs/ASSUMPTIONS.md`, `QA_PREP.md`, `AGENT_CONTEXT.md`, `tests/test_model.py`, `test_planner.py`, `conftest.py`, video script |
| **Jaid** | `backend/app/ai/*`, `schemas.py`, `main.py`, `Makefile`, `requirements.txt`, `.env.example`, deploy, `notify` SNS setup, `tests/test_chat.py`, `test_bedrock_client.py` |
| **Abby** | `pipelines/02,06,08`, `core/data_loader.py`, `core/topology.py`, `map_layers.py`, new `locate.py`, `frontend/src/onboarding/`, `console.py`, `frontend/src/console/`, `notify/router.py`, `docs/DATA_NOTES.md`, `API_CONTRACT.md`; video production lead after hour 14 |
| **Nandan** | `frontend/src/*` (not `onboarding/`, `console/`), content YAMLs, `engines/guidance.py`, `docs/DEMO_SCRIPT.md`, slides/end cards |
Gatekeepers: `main.py` / `schemas.py` / `Makefile` → Jaid · `assumptions.yaml` → Akshat · `App.jsx` → Nandan. A `schemas.py` change gets announced in chat and documented in `API_CONTRACT.md` in the same PR.

## 7. Current tasks
- **Akshat:**
  - ✅ customer range calibrated on the replay
  - ✅ `storm_context` logic (activates when the schema field exists)
  - ✅ `QA_PREP.md`
  - next: the video script/storyboard (crews + Repaired_D are now stated assumptions; mentors unavailable)
- **Jaid:**
  - add `storm_context: Optional[str] = None` to `RestorationResponse`
  - **live SMS to a real phone**
  - Nova tuned to the video's chat questions, plus a red-team pass
  - deploy only if a public URL is required
- **Abby:**
  - `GET /api/locate?premise_id=` → `{valid, map_point_id, center, zoom}`, plus optional location snap
  - `<Onboarding onComplete={...}>`: premise ID → opt-in needs → alerts sign-up
  - video production lead after hour 14
- **Nandan:**
  - mobile-first golden path
  - mount `<Onboarding/>`; map zooms to the customer's neighborhood
  - **"What if…?" section** (no crew-size control)
  - show `restoration.storm_context` and "work behind each step"
  - camera-friendly "what changed" moments; end cards

## 8. Rules for agents
- **Run `git pull` before starting and before every commit.** Small commits, own files only. If Git reports "diverged" or a conflict, stop and tell the human. Never force-push.
- **Never commit:** `data/raw/`, `data/processed/`, `.env`, keys, ARNs, phone numbers, the phone-photo PDFs in `docs/`.
- **Before pushing:** `make test`, then `cd frontend && npm test && npm run build`. Both must pass.
- **Don't change engine math, numbers or assumptions** without Akshat. No new frameworks.
- **The LLM never computes numbers.** Ranges only. Needs are opt-in. Scrub all customer text. Keep confirmed / estimate / actions separate.
- **To run:** `make setup` (once) → `make data` → `make api` + `make web` → http://localhost:5173. Restart `make api` after `make data`.
- **When unsure, re-read section 2:** consumer-first, polish over breadth, credibility over flash.

My name is: ____ . My task right now is: ____ .
