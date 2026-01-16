VENV := .venv
PIP := $(VENV)/bin/pip

.PHONY: venv deps initdb discover feed ingest-porla fmt lint

# Create a local Python virtual environment under .venv
venv:
	python3 -m venv $(VENV)

# Install runtime + dev dependencies into the venv
deps: venv
	$(PIP) install -U pip
	$(PIP) install -e .[dev]

# Initialize the SQLite schema (data/state.db)
initdb:
	$(VENV)/bin/python src/cli.py initdb --config config.yaml

discover:
	$(VENV)/bin/python src/cli.py discover --config config.yaml

feed:
	$(VENV)/bin/python src/cli.py feed --config config.yaml

ingest-porla:
	$(VENV)/bin/python src/cli.py ingest-porla --config config.yaml

# Auto-format Python with ruff
fmt:
	$(VENV)/bin/ruff format src

# Lint Python with ruff
lint:
	$(VENV)/bin/ruff check src
