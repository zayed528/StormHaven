# StormHaven

StormHaven is an outage intelligence and restoration-planning platform developed for the HackOHI/O 2026 AEP AI Outage Concierge challenge. It combines a customer-facing outage assistant with an operator console for storm replay, restoration planning, alert analysis, and scenario exploration.

The application is designed around a strict separation of responsibilities:

- Deterministic Python engines calculate outage risk, restoration ranges, preparedness guidance, and alert eligibility.
- The chatbot uses Amazon Bedrock only to understand and route questions; it does not generate outage calculations.
- Real AEP-derived data remains in an access-controlled backend and is never exposed through an anonymous public deployment.
- A separate fail-closed public-demo mode can operate exclusively on synthetic data when a public demonstration is required.

## Key capabilities

### Customer experience

- Interactive outage-risk map with risk dots and heatmap views
- Location-specific outage probability and confidence
- Monte Carlo restoration-time ranges with scenario comparisons
- Preparedness and electrical-safety recommendations
- Alert eligibility, escalation logic, and message previews
- English and Spanish interface support
- Scenario-aware conversational assistant with deterministic fallback

### Utility operations

- Circuit-level operational overview
- Historical storm replay using processed challenge data
- Restoration sequencing based on customer impact and repair effort
- Crew-capacity, road-access, and workload scenarios
- Restoration progress curves and completion estimates
- Alert queue and escalation overview
- Privacy-scrubbed prediction audit view

## System architecture

```text
React + Vite
    |
    | HTTPS / JSON
    v
FastAPI
    |
    +-- Risk engine
    +-- Monte Carlo restoration engine
    +-- Guidance engine
    +-- Alert eligibility engine
    +-- Storm restoration planner
    |
    +-- Processed AEP challenge data
    +-- Amazon S3 private runtime bundle (production)
    +-- Amazon Bedrock Converse API + Guardrails (optional)
```

The four customer engines are deterministic. Bedrock can select an answer category or request a strictly validated what-if scenario, but Python renders all user-facing outage facts from engine output. If Bedrock is unavailable, malformed, or blocked by a guardrail, the application returns a deterministic response.

## Technology stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18, Vite, Plotly.js |
| Backend | Python 3.12, FastAPI, Pydantic |
| Modeling | pandas, NumPy, scikit-learn, NetworkX |
| Geospatial processing | GeoPandas, Shapely, Pyogrio |
| AI integration | Amazon Bedrock Converse API, Amazon Nova Lite, Bedrock Guardrails |
| AWS integration | Amazon S3, optional Amazon SNS |
| Testing | pytest, Node.js test runner |

## Data and privacy model

StormHaven supports two deliberately separate operating modes.

### Private real-data mode

Private mode uses the authorized AEP-derived challenge dataset and enables the complete customer experience, Utility Console, and restoration planner. Raw and processed datasets must remain access-controlled and must not be committed to a public repository or exposed through anonymous endpoints.

Production can download an approved runtime bundle from a private S3 bucket through the standard AWS credential provider chain. AWS credentials must never be placed in source code or committed environment files.

### Public synthetic-demo mode

Public-demo mode is a separate, fail-closed deployment boundary. When `STORMHAVEN_PUBLIC_DEMO=true`:

- `STORMHAVEN_DATA` must be `synthetic`.
- S3 data loading is prohibited.
- Real premise IDs, circuit IDs, topology, and coordinates are rejected.
- Operator, planner, notification, documentation, and unnecessary routes are disabled.
- Health responses are reduced to non-sensitive status information.

Public-demo mode is not a substitute for the authorized real-data demonstration. It exists only to prevent private infrastructure data from being exposed anonymously.

## Prerequisites

- Python 3.12
- Node.js 18 or newer
- npm
- GNU Make
- Authorized challenge data for real-data operation
- AWS access only when using private S3, Bedrock, or SNS integrations

## Local setup

From the repository root:

```bash
make setup
cp .env.example .env
```

Review `.env` before starting the application. Do not place AWS access keys or session tokens in this file. Local and deployed environments should use the standard AWS credential provider chain.

### Start the backend

```bash
make api
```

FastAPI starts at `http://127.0.0.1:8000`. In private mode, interactive API documentation is available at `http://127.0.0.1:8000/docs`.

### Start the frontend

In a second terminal:

```bash
make web
```

The frontend starts at `http://127.0.0.1:5173` and proxies `/api` requests to the local FastAPI server.

## Real-data operation

Real-data mode must be used only with authorized AEP challenge data.

Configure the backend with:

```dotenv
STORMHAVEN_DATA=real
STORMHAVEN_PUBLIC_DEMO=false
STORMHAVEN_S3_ENABLED=true
STORMHAVEN_S3_BUCKET=<private-bucket-name>
STORMHAVEN_S3_PREFIX=<approved-runtime-prefix>
```

For a local build from authorized source files:

```bash
make data
```

This unpacks the available data package and runs the processing pipeline. Restart the API after rebuilding processed data.

The restoration planner additionally requires `data/processed/damage_work.csv`, generated by pipeline stage 04. If the network loads but storm replay is unavailable, rebuild stages 03 and 04 or run the complete pipeline:

```bash
make pipelines
```

Verify the active data source through:

```bash
curl http://127.0.0.1:8000/api/health
```

For an authorized local Utility Console session, enable both backend routes and the frontend tab:

```bash
STORMHAVEN_DATA=real \
STORMHAVEN_PUBLIC_DEMO=false \
STORMHAVEN_ENABLE_OPERATOR_ROUTES=true \
make api
```

Then start the frontend in another terminal:

```bash
cd frontend
VITE_ENABLE_OPERATOR_CONSOLE=1 npm run dev
```

Operator routes must be placed behind authentication and authorization in any network-accessible deployment.

## Bedrock configuration

Bedrock is optional. Clearing `BEDROCK_MODEL_ID` enables deterministic offline chat.

```dotenv
AWS_REGION=us-east-2
BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
BEDROCK_GUARDRAIL_ID=<guardrail-id>
BEDROCK_GUARDRAIL_VERSION=<guardrail-version>
```

The integration uses the AWS SDK credential provider chain. Never store AWS credentials in `.env`, frontend variables, logs, or source files.

The chatbot preserves the following boundaries:

- Conversation history is validated, bounded, and privacy-scrubbed.
- Tool names and arguments are strictly allowlisted.
- Current outage results are calculated before the model is called.
- Numerical content is rendered from deterministic engine output.
- Guardrail intervention, AWS failure, and malformed output trigger safe fallback.

## API overview

### Customer APIs

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Service and active data-mode status |
| `GET` | `/api/map` | Map layers and risk visualization data |
| `GET` | `/api/locate` | Resolve an authorized location input |
| `POST` | `/api/concierge` | Run all four deterministic customer engines |
| `POST` | `/api/chat` | Ask a grounded, scenario-aware question |
| `GET` | `/api/weather` | Weather context for private mode |

### Restricted operator APIs

These routes are registered only when `STORMHAVEN_ENABLE_OPERATOR_ROUTES=true` and public-demo mode is disabled.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/console/circuits` | Circuit-level operational summary |
| `GET` | `/api/console/restoration/{circuit_id}` | Restoration order and representative estimate |
| `GET` | `/api/console/alerts` | Alert queue and escalation overview |
| `GET` | `/api/console/audit` | Privacy-scrubbed audit tail |
| `GET` | `/api/planner/storms` | Available historical storm replays |
| `GET` | `/api/planner/plan` | Scenario-based restoration plan |

The complete request and response contract is documented in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## Testing

Run the backend test suite:

```bash
make test
```

Run the frontend tests and production build:

```bash
cd frontend
npm test
npm run build
```

The test suite covers deterministic engines, real-data integration, public-mode privacy boundaries, S3 loading, chatbot grounding and fallback, route configuration, location handling, notification behavior, and frontend chat state.

## Project structure

```text
backend/
  app/
    ai/                 Bedrock client, prompts, routing, and fallback
    content/            Guidance and bilingual message templates
    core/               Data loading, topology, privacy, and audit utilities
    engines/            Risk, restoration, guidance, alerts, and planner
    notify/             Optional notification integration
    console.py          Restricted Utility Console API
    main.py             FastAPI application and route registration
    map_layers.py       Customer and operator map layers
    planner_routes.py   Restricted restoration-planner API
    public_demo.py      Fail-closed public-mode boundary
    schemas.py          API request and response models
    service.py          Deterministic engine orchestration
  tests/                Backend unit, integration, and privacy tests

frontend/
  src/
    api/                Backend client
    components/         Customer map, results, scenario controls, and chat
    console/            Utility Console and restoration planner
    onboarding/         Location-selection experience
    App.jsx             Application state and view composition

pipelines/              Real-data processing, calibration, and reporting
config/assumptions.yaml Explicit model and operational assumptions
docs/                   API, assumptions, data, QA, and demonstration guides
```

## Processing pipeline

| Stage | Purpose |
| --- | --- |
| `00_unpack_data.py` | Unpack authorized source packages |
| `01_recon.py` | Inventory source files and validate expected inputs |
| `02_build_topology.py` | Construct the directed electrical topology |
| `03_build_labels.py` | Attribute damage, build event labels, and estimate damage rates |
| `04_load_labor.py` | Convert labor references and repair attributes into work estimates |
| `05_train_and_backtest.py` | Calibrate and evaluate model behavior |
| `06_export_map_layers.py` | Generate map layers and protected priority metadata |
| `07_weather.py` | Prepare historical weather context |
| `08_features.py` | Build model features |
| `09_model_v1.py` | Produce versioned model artifacts |
| `10_figures.py` | Generate evaluation and presentation figures |

All modeling and operational assumptions are centralized in [`config/assumptions.yaml`](config/assumptions.yaml) and explained in [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md).

## Security requirements

- Never expose private AEP-derived data through anonymous endpoints.
- Never commit raw or processed challenge datasets, credentials, `.env`, or generated audit logs.
- Use explicit CORS origins in production; wildcard production CORS is rejected.
- Keep operator, planner, notification, and documentation routes disabled unless protected by authentication and authorization.
- Do not expose premise IDs, circuit IDs, raw topology, precise equipment coordinates, or critical-facility locations to unauthorized users.
- Treat declared customer needs as opt-in inputs; never infer sensitive needs.
- Keep customer-facing restoration output labeled as a model estimate unless a trusted utility source supplies a confirmed estimate.
- Require event-organizer or data-owner approval before demonstrating real infrastructure information to anyone outside the authorized team.

## Documentation

- [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) — API contracts and examples
- [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) — modeling assumptions and validation notes
- [`docs/DATA_NOTES.md`](docs/DATA_NOTES.md) — data inventory and transformation details
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — demonstration flow
- [`docs/QA_PREP.md`](docs/QA_PREP.md) — review and presentation preparation
- [`docs/aep_challenge.pdf`](docs/aep_challenge.pdf) — challenge brief

## Project status

StormHaven is a hackathon prototype intended for controlled demonstration and technical evaluation. Predictions are estimates, not official outage confirmations or restoration commitments. Production use would require utility approval, formal security review, authenticated operator access, data-governance controls, monitoring, and validation against operational systems.
