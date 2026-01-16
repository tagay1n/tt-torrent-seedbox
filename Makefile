VENV := .venv
PIP := $(VENV)/bin/pip
UNIT ?= ttseed-dashboard.service

.PHONY: venv deps initdb run-ingest run-stats run-reconcile run-dashboard install-systemd uninstall-systemd install-porla-systemd uninstall-porla-systemd status logs fmt lint test

# Create a local Python virtual environment under .venv
venv:
	python3 -m venv $(VENV)

# Install runtime + dev dependencies into the venv
deps: venv
	$(PIP) install -U pip
	$(PIP) install -e .[dev]

# Initialize the SQLite schema (data/state.db)
initdb:
	$(VENV)/bin/python src/main.py initdb --config config.yaml

# Run feed ingest once
run-ingest:
	$(VENV)/bin/python src/main.py ingest --config config.yaml

# Install ttseed into /opt/ttseed and enable systemd units/timers
install-systemd:
	sudo mkdir -p /opt/ttseed
	sudo rsync -a --exclude '.venv' --exclude 'data/state.db' ./ /opt/ttseed/
	sudo python3 -m venv /opt/ttseed/.venv
	sudo /opt/ttseed/.venv/bin/pip install -U pip
	sudo /opt/ttseed/.venv/bin/pip install -e /opt/ttseed
	sudo install -m 644 deploy/systemd/ttseed-*.service /etc/systemd/system/
	sudo install -m 644 deploy/systemd/ttseed-*.timer /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable --now ttseed-dashboard.service
	sudo systemctl enable --now ttseed-ingest.timer
	sudo systemctl enable --now ttseed-stats.timer
	sudo systemctl enable --now ttseed-reconcile.timer

# Disable/remove ttseed systemd units/timers
uninstall-systemd:
	sudo systemctl disable --now ttseed-dashboard.service ttseed-ingest.timer ttseed-stats.timer ttseed-reconcile.timer
	sudo rm -f /etc/systemd/system/ttseed-*.service /etc/systemd/system/ttseed-*.timer
	sudo systemctl daemon-reload

# Install Porla systemd unit (expects /usr/local/bin/porla)
install-porla-systemd:
	sudo install -m 644 deploy/systemd/porla.service /etc/systemd/system/porla.service
	sudo systemctl daemon-reload
	sudo systemctl enable --now porla.service

# Disable/remove Porla systemd unit
uninstall-porla-systemd:
	sudo systemctl disable --now porla.service
	sudo rm -f /etc/systemd/system/porla.service
	sudo systemctl daemon-reload

# Show status of ttseed systemd units/timers
status:
	systemctl status ttseed-dashboard.service ttseed-ingest.timer ttseed-stats.timer ttseed-reconcile.timer --no-pager

# Tail logs for a unit (override with UNIT=...)
logs:
	journalctl -u $(UNIT) -n 200 --no-pager

# Auto-format Python with ruff
fmt:
	$(VENV)/bin/ruff format src

# Lint Python with ruff
lint:
	$(VENV)/bin/ruff check src
