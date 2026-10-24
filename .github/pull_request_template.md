## What changed
<!-- One or two lines. Link the TEAM_TASKS.md item if there is one. -->

## How to check it
<!-- e.g. "make api, select P-31111, drag severity to 90, band goes High -> Very High" -->

## Checklist
- [ ] `make test` passes locally
- [ ] `cd frontend && npm run build` passes (if frontend touched)
- [ ] No AEP data committed (`git status` shows nothing under `data/raw/` or `data/processed/`)
- [ ] No secrets committed (no `.env`, no keys, no ARNs or phone numbers in code)
- [ ] `backend/app/schemas.py` unchanged, **or** the change was announced in team chat and `docs/API_CONTRACT.md` updated
- [ ] `config/assumptions.yaml` unchanged, **or** the change was announced and `docs/ASSUMPTIONS.md` updated
- [ ] Customer-facing text goes through `core/privacy.scrub_text`; no LLM-computed numbers
- [ ] Pulled latest `main` before opening this PR
