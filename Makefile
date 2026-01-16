VENV := .venv
PIP := $(VENV)/bin/pip

.PHONY: venv deps initdb discover feed ingest-porla install-systemd uninstall-systemd cleanup-old-systemd fmt lint

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

# Install ttseed feed+ingest systemd unit/timer
install-systemd:
	sudo install -m 644 deploy/systemd/ttseed-feed-ingest.service /etc/systemd/system/ttseed-feed-ingest.service
	sudo install -m 644 deploy/systemd/ttseed-feed-ingest.timer /etc/systemd/system/ttseed-feed-ingest.timer
	sudo systemctl daemon-reload
	sudo systemctl enable --now ttseed-feed-ingest.timer

# Disable/remove ttseed feed+ingest systemd unit/timer
uninstall-systemd:
	sudo systemctl disable --now ttseed-feed-ingest.timer ttseed-feed-ingest.service
	sudo rm -f /etc/systemd/system/ttseed-feed-ingest.service /etc/systemd/system/ttseed-feed-ingest.timer
	sudo systemctl daemon-reload

# Remove old ttseed units/timers from earlier versions
cleanup-old-systemd:
	sudo systemctl disable --now ttseed-dashboard.service ttseed-ingest.timer ttseed-stats.timer ttseed-reconcile.timer
	sudo rm -f /etc/systemd/system/ttseed-dashboard.service /etc/systemd/system/ttseed-ingest.* /etc/systemd/system/ttseed-stats.* /etc/systemd/system/ttseed-reconcile.*
	sudo systemctl daemon-reload

# Auto-format Python with ruff
fmt:
	$(VENV)/bin/ruff format src

# Lint Python with ruff
lint:
	$(VENV)/bin/ruff check src
