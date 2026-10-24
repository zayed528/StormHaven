# Run from the repo root. Override the interpreter with: make api PY=python3
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
# Same interpreter, usable after `cd backend`: paths become absolute, bare commands (python3) stay as-is.
PYRUN := $(if $(findstring /,$(PY)),$(abspath $(PY)),$(PY))

.PHONY: setup data api test web recon pipelines

setup:            ## one-time: venv + Python deps + frontend deps
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

data:             ## unpack data/archives into data/raw, then build data/processed (~15 s)
	$(PY) pipelines/00_unpack_data.py
	$(MAKE) pipelines PY=$(PY)

api:              ## FastAPI on :8000 (docs at /docs)
	cd backend && $(PYRUN) -m uvicorn app.main:app --reload --port 8000

test:             ## backend tests (synthetic network if no processed data)
	cd backend && $(PYRUN) -m pytest -q

web:              ## React dev server on :5173, proxies /api -> :8000
	cd frontend && npm run dev

recon:            ## inventory data/raw -> data/processed/recon_report.md
	$(PY) pipelines/01_recon.py

pipelines:        ## full data build; each step needs the previous step's outputs
	$(PY) pipelines/01_recon.py
	$(PY) pipelines/02_build_topology.py
	$(PY) pipelines/03_build_labels.py
	$(PY) pipelines/04_load_labor.py
	$(PY) pipelines/05_train_and_backtest.py
	$(PY) pipelines/06_export_map_layers.py
	$(PY) pipelines/07_weather.py
