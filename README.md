# StormHaven

**HackOHI/O 2026 · AEP "AI Outage Concierge" challenge.** A map-first storm assistant that answers four customer questions for an anonymized location:

1. **Will I lose power?** Risk band + confidence + top contributing factors.
2. **How long could restoration take?** A P10–P90 **range** from a Monte Carlo over damage on the customer's upline path, using AEP labor hours, travel and setup time, and step restoration.
3. **What should I do to prepare?** Curated, sourced safety and prep actions by risk × duration × **declared** needs.
4. **Do I qualify for outage alerts?** Documented eligibility rules, timing, escalations, and EN/ES messages.

Four deterministic engines compute every number. Claude on AWS Bedrock (with Guardrails) only **explains** results, through tool calls. Every answer separates **confirmed facts**, **model estimates**, and **customer actions**, and states its confidence, assumptions and missing data, with a fallback when we can't predict reliably.

Challenge brief: [docs/aep_challenge.pdf](docs/aep_challenge.pdf)

## Run it

Works immediately, without AEP data, on a synthetic network.

```bash
make setup        # once: .venv + pip install -r requirements.txt + npm install
cp .env.example .env   # leave BEDROCK_MODEL_ID blank to run offline
make api          # FastAPI on :8000, interactive docs at http://localhost:8000/docs
make web          # React on http://localhost:5173 (proxies /api -> :8000). Click a dot on the map.
make test         # backend tests (synthetic network)
```

With AEP data in `data/raw/` (never committed):
```bash
make recon        # inventory -> data/processed/recon_report.md
make pipelines    # 01..06; steps whose inputs are missing print SKIP and the backend keeps its synthetic fallback
```
Restart `make api` after pipelines run. `/api/health` reports what's loaded: `synthetic_data` (network) and `labor_from_aep` (labor hours).

**Current data status:** only the AEP labor workbook has been received, so the network is synthetic and the labor hours are AEP. See [docs/DATA_NOTES.md](docs/DATA_NOTES.md).

## Structure

```
config/assumptions.yaml        every assumption, tagged AEP vs assumed (explained in docs/ASSUMPTIONS.md)
data/raw/                      AEP files (git-ignored)
data/processed/                pipeline outputs the backend reads (git-ignored)
pipelines/
  01_recon.py                  inventory, sidecar check, columns, join keys          Jaid
  02_build_topology.py         upline TXT + devices -> edges.csv, nodes_base.csv     Jaid
  03_build_labels.py           ARCOS -> device history, labels, damage mix           Jaid + Akshat
  04_load_labor.py             AEP labor workbook -> labor hours, multiplier, adders Akshat
  05_train_and_backtest.py     calibration + restoration-range coverage              Akshat
  06_export_map_layers.py      circuits GeoJSON, priority facilities -> device IDs   Jaid
backend/app/
  main.py                      /api/health, /api/concierge, /api/map, /api/chat     Nandan
  schemas.py                   API contract (frozen at hour 1)                       shared
  service.py                   runs the 4 engines in order + audit + final scrub     shared
  map_layers.py                Plotly-ready circuit lines + premise points           Jaid
  engines/risk.py              1. Will I lose power?                                 Akshat
  engines/restoration.py       2. How long? Monte Carlo + step restoration           Akshat + Jaid
  engines/guidance.py          3. What should I do? rules + curated library          Abby
  engines/alerts.py            4. Do I get alerts? rules + messages                  Nandan + Abby
  core/data_loader.py          real-or-synthetic DataStore + processed-file contract Jaid
  core/topology.py             upline paths, location resolution                     Jaid
  core/privacy.py              friendly names, scrubbing, LLM allowlist              Nandan
  core/audit.py                append-only JSONL audit (DynamoDB later)              Nandan
  ai/                          Bedrock Converse + tool calling, prompts, offline     Nandan
  notify/sns_sender.py         SNS text sender (dry-run without SNS_TOPIC_ARN)       Nandan
  content/                     guidance library + EN/ES message templates            Abby
frontend/src/
  App.jsx                      state + layout                                        Abby
  components/OutageMap.jsx     Plotly scattermap (MapLibre, carto-positron, no token)
  components/ScenarioControls  sliders, damage, opt-in needs, demo utility toggle
  components/ResultsPanel      Safety banner + Confirmed / Our estimate / What you can do
  components/StepTimeline      restoration steps (stub)
  components/ChatPanel         /api/chat (stub)
docs/                          TEAM_TASKS, API_CONTRACT, ASSUMPTIONS, DATA_NOTES, DEMO_SCRIPT
```

## Team

| who | role | start here |
|---|---|---|
| Akshat | modeling, pitch owner | `engines/risk.py`, `engines/restoration.py`, `pipelines/04`, `pipelines/05`, `docs/ASSUMPTIONS.md` |
| Jaid | data + geospatial | `pipelines/01–03, 06`, `core/data_loader.py`, `core/topology.py`, `map_layers.py`, `docs/DATA_NOTES.md` |
| Nandan | backend, AWS, AI | `main.py`, `ai/`, `core/privacy.py`, `core/audit.py`, `notify/`, `engines/alerts.py`, deploy |
| Abby | product, UX, content | `frontend/`, `engines/guidance.py`, `content/`, `docs/DEMO_SCRIPT.md` |

Hour-by-hour plan, ownership and git rules: [docs/TEAM_TASKS.md](docs/TEAM_TASKS.md).

## Hard rules
- No secrets in code. No AEP data in git.
- The LLM never computes probabilities or times. It calls tools and explains.
- Every customer-facing string passes through `core/privacy.scrub_text`. The LLM receives only allowlisted derived fields.
- Restoration is always a range labeled as a model estimate. `confirmed_etr` comes only from the (simulated) utility status.
- Declared needs are opt-in checkboxes only; we never infer them.
- Priority-facility locations never leave the backend.
