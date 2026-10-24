# StormHaven team tasks (24 hours)

Hour 0 = kickoff. Times below are **hackathon hours**, not clock time. Write the real start time here: `h0 = ____`.

## CURRENT ASSIGNMENT (supersedes the role tables below, which are from hour 0)

| person | owns | now |
|---|---|---|
| **Akshat (+ Claude)** | model + planner: `pipelines/03,04,05,07,09,10,_rates.py`, `engines/risk.py`, `restoration.py`, `planner.py`, `planner_routes.py`, `config/assumptions.yaml`, `docs/ASSUMPTIONS.md`, `tests/test_model.py`, `test_planner.py`, `conftest.py` | ✅ repair work per record (structure drawings), ✅ storm planner + `/api/planner`, ✅ crew size 2–8, ✅ value/effort priority, ✅ slide charts (`make figures` → `docs/figures/`). Next: mentor numbers into config, pitch storyline + Q&A |
| **Jaid** | AWS + chat: `backend/app/ai/*`, `schemas.py`, `main.py`, deploy | Bedrock live test + Guardrail; planner as a second chat tool; App Runner + Vercel |
| **Abby** | data + console + notify: `pipelines/02,06,08`, `console.py`, `frontend/src/console/`, `notify/router.py`, `storage.py`, `docs/DATA_NOTES.md`, `API_CONTRACT.md` | **Storm restoration plan panel** in the console on `/api/planner/plan`; S3 startup download |
| **Nandan** | customer frontend + content: `frontend/src/*` (not `console/`), content YAMLs, `DEMO_SCRIPT.md`, slides | crew-size control (2–8); show the work behind each step; storm-level rename; mobile/PWA; slides around the 4 key questions using `docs/figures/` |

Gatekeepers for shared files: `main.py` / `schemas.py` / `Makefile` → Jaid · `assumptions.yaml` → Akshat · `App.jsx` → Nandan.
Rule: `git pull` before you commit; never commit `data/raw`, `data/processed`, `.env`, or the phone-photo PDFs in `docs/`.

## How we stay unblocked

Nobody waits on anybody, because two contracts are fixed at hour 1:

1. **API contract**: `backend/app/schemas.py` (documented in `docs/API_CONTRACT.md`). The frontend builds against it from hour 1 using the **synthetic backend**. `make api` works with no AEP data at all.
2. **Processed-file contract**: the docstring at the top of `backend/app/core/data_loader.py`. Jaid's pipelines write exactly these files to `data/processed/`. The engines read only these files. Akshat's modeling and Jaid's data work run in parallel, and when the files appear the API switches from synthetic to real on restart.

Labor is already real: `make pipelines` loads the AEP labor workbook on top of the synthetic network.

## Ownership

**Shared files.** Announce in team chat before touching them, keep the PR small, and tag the people affected:
- `backend/app/schemas.py`: the API contract. Frozen after hour 1. Any change needs a matching `docs/API_CONTRACT.md` update in the same PR.
- `config/assumptions.yaml`: every assumption. Any change needs a matching `docs/ASSUMPTIONS.md` update.
- `backend/app/service.py`: the engine order and the audit log.

| person | owns (exact paths) |
|---|---|
| **Akshat**: modeling | `backend/app/engines/risk.py`, `backend/app/engines/restoration.py` (math; Jaid co-owns sequencing), `pipelines/04_load_labor.py`, `pipelines/05_train_and_backtest.py`, `pipelines/03_build_labels.py` (co-owner: labels and smoothing), `docs/ASSUMPTIONS.md` |
| **Jaid**: data + geospatial | `pipelines/01_recon.py`, `pipelines/02_build_topology.py`, `pipelines/03_build_labels.py` (ARCOS matching), `pipelines/06_export_map_layers.py`, `backend/app/core/data_loader.py`, `backend/app/core/topology.py`, `backend/app/map_layers.py`, `docs/DATA_NOTES.md` |
| **Nandan**: backend, AWS, AI | `backend/app/main.py`, `backend/app/config.py`, `backend/app/engines/alerts.py` (logic; Abby owns copy), `backend/app/core/privacy.py`, `backend/app/core/audit.py`, `backend/app/ai/agent.py`, `backend/app/ai/bedrock_client.py`, `backend/app/ai/prompts.py`, `backend/app/notify/sns_sender.py`, `backend/tests/test_engines.py`, `requirements.txt`, `Makefile`, `.env.example`, `docs/API_CONTRACT.md` |
| **Abby**: product, UX, content | `frontend/**` (`src/App.jsx`, `src/components/OutageMap.jsx`, `ScenarioControls.jsx`, `ResultsPanel.jsx`, `StepTimeline.jsx`, `ChatPanel.jsx`, `src/api/client.js`, `src/styles.css`), `backend/app/engines/guidance.py`, `backend/app/content/guidance_library.yaml`, `backend/app/content/message_templates.yaml`, `docs/DEMO_SCRIPT.md` |

Anyone may add tests to `backend/tests/` for their own module. `.github/CODEOWNERS` mirrors this table.

---

## Akshat: modeling + pitch owner

**First 3 tasks**
1. Read `docs/ASSUMPTIONS.md` and `config/assumptions.yaml`. Ask an AEP mentor: (a) are the CU labor hours per person or per crew? (b) typical line-crew size? (c) are our repair recipes realistic? (Show them `restoration.repair_recipes`.)
2. Run `make pipelines`, open `data/processed/labor_hours.csv`, and sanity-check clock hours per damage type (hours × indirect multiplier ÷ crew size). Adjust recipes with Jaid if the structure-diagram PDF arrives.
3. Review the risk model now live on real data (ASSUMPTIONS.md "Risk", `pipelines/_rates.py`, `backtest.json`). Decide with the team how severity should be ranked (all 36 storms vs. major storms only) and whether to keep `severity_damping` = 0.8.

| block | tasks |
|---|---|
| **0–1** (all) | Schema freeze meeting. Agree the shared rules. Mentor questions above. |
| **1–3** | Tasks 1–3. Draft the pitch storyline (problem → 4 questions → trust layer → modernization). Stub the backtest slide layout. |
| **3–8** | As soon as Jaid's `nodes_base.csv` + ARCOS land: per-device `fail_prob` with empirical-Bayes smoothing in 03 (already sketched; tune the prior). Event severity distribution → `severity_k` fit. Calibrate `base_backlog_hours_per_crew` and `assessment_hours` against `durations.csv`. Keep the synthetic tests green. |
| **8–9** (all) | Integration checkpoint: one real premise end-to-end (see below). |
| **9–14** | `05_train_and_backtest.py`: leave-one-event-out calibration (Brier score + reliability table) and restoration P10–P90 coverage (fill the `coverage` TODO). ML v1 (logistic on path features: hist rate, path length, asset mix) **only if** it beats v0 on held-out events; hook it into `risk.py` behind the TODO, with the same response shape. |
| **14–18** separators | ✅ Estimate-updated message now uses the input that actually changed. ✅ Weather pipeline (07) and `/api/weather` done; see ASSUMPTIONS → Weather. Now: backtest + weather numbers into slides. **Nap h15:30–17:00.** |
| **18–20** | Red-team the math: severity 0/100, crews 1/500, every damage type at once, an unknown damage type. Check monotonicity (more crews ⇒ never slower). Fix bugs only. |
| **20** | 🧊 Feature freeze. |
| **20–24** | Own the slides and the 5-minute pitch. Rehearse with the demo driver ×3. Prepare Q&A answers for the 4 known simplifications in ASSUMPTIONS.md. |

## Jaid: data + geospatial

**First 3 tasks** (✅ done at setup: data loaded, recon run, 02/03/06 written for the real formats, DATA_NOTES filled, ID formats added to the scrubber)
1. Read `docs/DATA_NOTES.md` and re-run `make pipelines` on your machine. Spot-check 5 premises' upline paths against the GIS on a map.
2. QA the ARCOS attribution: open `data/processed/damage_attributed.csv` and look at the `line_to_protective_zone` records with the largest `dist_m`. Is the nearest-transformer rule sensible there?
3. Get mentor answers on the data questions in DATA_NOTES (`Repaired_D`, `Media`, life-support flags) and update DATA_NOTES.

| block | tasks |
|---|---|
| **0–1** (all) | Schema freeze. Confirm the processed-file contract in `data_loader.py` is achievable from what AEP sent. |
| **1–3** | Tasks 1–3. |
| **3–8** | `02_build_topology.py` → `edges.csv`, `nodes_base.csv` (radial check, premise coordinates). `03_build_labels.py` → ARCOS-to-device matching (equipment column, or nearest device on the same circuit; record the match rate), `DAMAGE_NAME_MAP` with Akshat, premise × event labels, `damage_mix.json`, `meta.json`. `06_export_map_layers.py` → `circuits.geojson` + `priority_nodes.csv`. |
| **8–9** (all) | Integration checkpoint (you drive the data side). |
| **9–14** | QA: match rates, premises with no path (must hit the fallback, not crash), map performance (simplify, cap point count, or aggregate). Step-restoration sequencing on real protective devices in `topology.py`/`restoration.py` (steps upstream-first, ETAs non-decreasing). Circuit-level lookup for "enter a location". |
| **14–18** separators | **Utility console tab** (with Nandan's endpoint): alert queue, active escalations, audit log, circuit restoration order. **Nap h14:00–15:30.** |
| **18–20** | Privacy red-team of the map layer (no facility coordinates, rounded premise coordinates, no internal-only fields). Edge-case data fixes. |
| **20** | 🧊 Feature freeze. |
| **20–24** | Data slide (sources, joins, match rates, gaps). Record the **backup demo video** by h22. |

## Nandan: backend, AWS, AI

**First 3 tasks**
1. AWS: confirm **Bedrock model access** for Amazon Nova Lite in `us-east-2` (the model ID is configured in `.env`). Configure the verified **Guardrail** (PII filters + denied topics: facility locations, employee contacts). Set up the **SNS SMS sandbox**: verify each teammate's phone, subscribe them to a topic, and set `SNS_TOPIC_ARN`. Add a budget alarm.
2. `cp .env.example .env`, then `make api` + `make test`. Confirm `/api/chat` works offline, then online with Bedrock (validated what-if tool → answer-category decision → deterministic rendering).
3. Deployment skeleton on the synthetic backend (App Runner or EC2 for the API, Amplify for the frontend) so a URL exists early.

| block | tasks |
|---|---|
| **0–1** (all) | Schema freeze (you chair it). Bedrock access request and SNS sandbox verification **in this hour**: approvals can take time. |
| **1–3** | Tasks 1–3. Validate chat history input (roles alternate, text only, length caps). |
| **3–8** | Privacy hardening: real ID regexes from Jaid in `privacy._INTERNAL_ID`; add a test that the LLM payload holds only allowlisted keys. Audit: add data version + model version per record. Review the alerts engine against `assumptions.yaml`. Wire `notify/sns_sender.py` to an endpoint (announce the schema change). |
| **8–9** (all) | Integration checkpoint (you drive the API side). |
| **9–14** | Deploy API + frontend. Processed data from a private S3 bucket at startup (never public). Optional: DynamoDB audit sink. LLM eval: 20 scripted questions (the 4 challenge questions, scenario changes, jailbreaks, "compute it yourself" bait); check that answers only restate tool numbers. |
| **14–18** separators | **Live SNS text** in the demo (pre-storm + outage-confirmed). Console endpoint for Jaid's utility tab (alert queue, escalations, audit tail). **Nap h14:00–15:30.** |
| **18–20** | Red-team: prompt injection, PII exfiltration, asking for hospital locations or employee contacts, asking the LLM to compute an ETA. Fix and add tests. |
| **20** | 🧊 Feature freeze. **Deployment freeze at h21.** |
| **20–24** | Demo laptop setup, offline fallback check, backup URL. Architecture slide. |

## Abby: product, UX, content

**First 3 tasks**
1. `make api` + `make web`, then click through the whole flow on the synthetic backend. List UX gaps against the MVD checklist below.
2. Verify every item in `guidance_library.yaml` against its cited source (Ready.gov, CDC, FoodSafety.gov, AEP) and add a `source` to any item missing one.
3. Draft `docs/DEMO_SCRIPT.md` timing with Akshat and decide the demo premise IDs.

| block | tasks |
|---|---|
| **0–1** (all) | Schema freeze: confirm the frontend needs nothing more from `ConciergeResponse`. |
| **1–3** | Tasks 1–3. Accessibility basics: labels, focus order, contrast, keyboard-only pass. |
| **3–8** | Guidance library curation (sources, reading level 6th–8th grade). EN/ES message templates (✅ all inserted words are now localized via `words:` in the template file; needs a native-speaker review). ChatPanel: suggested-question chips, loading state. Clear fallback and error states. Loading skeletons. |
| **8–9** (all) | Integration checkpoint (you drive the UI side). |
| **9–14** | ResultsPanel polish: a "what changed" highlight when a slider moves, better band/confidence visual, mobile layout. Quick usability test with someone outside the team. |
| **14–18** separators | **Spanish toggle** (`profile.language`), **step timeline** visual (`StepTimeline.jsx`: P10–P90 band, your-power-returns marker), UI for the weather card (`WeatherCard.jsx`, basic version done). **Nap h15:30–17:00.** |
| **18–20** | Accessibility audit (screen reader, keyboard), copy red-team (plain language, no false precision, safety labels). |
| **20** | 🧊 Feature freeze. |
| **20–24** | Final demo script, slide design, rehearsal ×3 with Akshat. |

## Nap schedule (h14–18)

| time | asleep | awake |
|---|---|---|
| h14:00–15:30 | Jaid, Nandan | Akshat (modeling), Abby (frontend) |
| h15:30–17:00 | Akshat, Abby | Jaid (data), Nandan (backend) |
| h17:00–18:00 | — | everyone: sync + merge separators |

At least one backend-capable and one frontend-or-modeling person is awake at all times.

## h8–9 integration checkpoint: one premise end-to-end

Pass when **one real premise** (from AEP data, not synthetic) goes through all of this:
- [ ] `/api/health` shows `synthetic_data: false`
- [ ] the premise appears on the map and clicking it returns a `ConciergeResponse`
- [ ] risk factors name real equipment kinds on its path (friendly names, no IDs)
- [ ] restoration range is plausible against ARCOS durations; steps run upstream-first
- [ ] chat answers about that premise (offline at least)
- [ ] `make test` still green (synthetic)

If the real data isn't ready, the checkpoint runs on the synthetic network and Jaid posts an ETA. Nobody stops working.

## Definition of done (maps to the challenge's minimum viable demo)

| MVD step | done when |
|---|---|
| **1.** Customer selects or enters an anonymized location | Click on the map **or** type a premise ID; an unknown ID gives the fallback, never a crash. |
| **2.** Risk + confidence + explanation | Band + confidence + top factors in plain language. Assumptions, missing data and "could change if" are visible. |
| **3.** Explore scenarios → restoration range | Severity, crews, road access and reported damage each visibly move the P10–P90 range. Drivers explain why. Steps run upstream-first. The range is labeled a model estimate. |
| **4.** Preparation actions + alert eligibility | Actions change with band, duration and **declared** needs only. Safety items are labeled. Eligibility and the rule text are shown. Escalations are visible. |
| **5.** At least one proactive message | All four templates render (EN, plus ES with the toggle). The estimate-updated message shows old → new. Live SNS text works or is shown as a dry-run. |
| **6.** Privacy, safety, uncertainty, limits | Confirmed vs estimate vs actions are separate. A downed-line chat gets the fixed 911 message. No IDs, coordinates or facility locations anywhere. Fallback demo works. LLM numbers only ever come from tools. |
| **Judges' interaction** | A judge can drag a slider and see the answer change in under 1 second. |

## Git rules

- **One branch per person**: `feat/akshat-modeling`, `feat/jaid-data`, `feat/nandan-backend`, `feat/abby-frontend`. Short-lived topic branches off these are fine.
- **Small PRs into `main`**, using the PR template checklist. One reviewer: the owner of any shared file you touched, otherwise anyone.
- **Pull `main` every 2 hours** (`git pull --rebase origin main`) and at every checkpoint.
- **Never commit** `data/raw/`, `data/processed/`, `.env`, keys, ARNs or phone numbers. Run `git status` before every commit. The AEP data lives in git only as `data/archives/` (get it with `make data`); don't add new data files without telling the team.
- `main` must always pass `make test` and `npm run build`. If you break it, fixing it is your top priority.
- After h20 (feature freeze), only bug-fix PRs, and each one gets announced.
