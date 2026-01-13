VENV := .venv
PIP := $(VENV)/bin/pip
UNIT ?= ttseed-dashboard.service

.PHONY: venv deps initdb run-ingest run-stats run-reconcile run-dashboard install-systemd uninstall-systemd install-porla-systemd uninstall-porla-systemd status logs fmt lint test

venv:
	python3 -m venv $(VENV)

deps: venv
	$(PIP) install -U pip
	$(PIP) install -e .[dev]

initdb:
	$(VENV)/bin/ttseed-initdb --config config.yaml

run-ingest:
	$(VENV)/bin/ttseed-ingest --config config.yaml

run-stats:
	$(VENV)/bin/ttseed-stats --config config.yaml

run-reconcile:
	$(VENV)/bin/ttseed-reconcile --config config.yaml

run-dashboard:
	$(VENV)/bin/ttseed-dashboard --config config.yaml

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

uninstall-systemd:
	sudo systemctl disable --now ttseed-dashboard.service ttseed-ingest.timer ttseed-stats.timer ttseed-reconcile.timer
	sudo rm -f /etc/systemd/system/ttseed-*.service /etc/systemd/system/ttseed-*.timer
	sudo systemctl daemon-reload

install-porla-systemd:
	sudo install -m 644 deploy/systemd/porla.service /etc/systemd/system/porla.service
	sudo systemctl daemon-reload
	sudo systemctl enable --now porla.service

uninstall-porla-systemd:
	sudo systemctl disable --now porla.service
	sudo rm -f /etc/systemd/system/porla.service
	sudo systemctl daemon-reload

status:
	systemctl status ttseed-dashboard.service ttseed-ingest.timer ttseed-stats.timer ttseed-reconcile.timer --no-pager

logs:
	journalctl -u $(UNIT) -n 200 --no-pager

fmt:
	$(VENV)/bin/ruff format src tests

lint:
	$(VENV)/bin/ruff check src tests

test:
	$(VENV)/bin/pytest
