.PHONY: help test check run import rules setup setup-coa backup backup-list clean

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  help        Show this help message"
	@echo "  test        Run the test suite"
	@echo "  check       Check database for inconsistencies"
	@echo "  run         Launch the Pyre TUI"
	@echo "  import      Import a bank file (make import FILE=path/to/file.qfx)"
	@echo "  rules       List payee rules"
	@echo "  setup       Create venv, install deps, and seed starter accounts"
	@echo "              Use SKIP_COA=1 to skip the Chart of Accounts setup"
	@echo "  setup-coa   Seed a minimal personal Chart of Accounts"
	@echo "  backup      Back up the database with a timestamp (NOTE='text' optional)"
	@echo "  backup-list List existing database backups"
	@echo "  clean       Remove *.pdf, *.qfx, *.ofx, *.csv from project root"

test:
	. venv/bin/activate && python -m pytest tests/ -v

check:
	. venv/bin/activate && python scripts/check_db.py

run:
	. venv/bin/activate && python -m pyre

import:
	. venv/bin/activate && python -m pyre $(FILE)

rules:
	. venv/bin/activate && PYTHONPATH=. python scripts/list_rules.py

setup:
	python -m venv venv
	. venv/bin/activate && pip install -r requirements.txt
	@if [ ! -f company.yaml ]; then \
		sed 's/Your Company, Inc./ACME, Inc./' company.yaml.sample > company.yaml; \
		echo "Created company.yaml -- set the name to your company (appears in reports), or yourself (personal accounting)"; \
	fi
ifndef SKIP_COA
	@$(MAKE) setup-coa
endif

setup-coa:
	. venv/bin/activate && python scripts/setup_coa.py

backup:
	@set -a && . ./.env && set +a && \
	db="$$PYRE_DB_PATH" && \
	if [ -f "$$db.lock" ]; then echo "Error: lock file $$db.lock exists, database may be in use"; exit 1; fi && \
	if [ ! -f "$$db" ]; then echo "Error: $$db not found"; exit 1; fi && \
	ts=$$(date +%Y%m%d-%H%M%S) && \
	backup="$${db%.db}-backup-$$ts.db" && \
	cp "$$db" "$$backup" && echo "Backup created: $$backup" && \
	if [ -n "$(NOTE)" ]; then echo "$(NOTE)" > "$$backup.note"; echo "  Note: $(NOTE)"; fi

backup-list:
	@set -a && . ./.env && set +a && \
	dir=$$(dirname "$$PYRE_DB_PATH") && \
	base=$$(basename "$$PYRE_DB_PATH" .db) && \
	files=$$(ls -1t "$$dir/$$base-backup-"*.db 2>/dev/null) && \
	if [ -z "$$files" ]; then echo "No backups found."; exit 0; fi && \
	now=$$(date +%s) && \
	count=$$(echo "$$files" | wc -l | tr -d ' ') && \
	total=$$(echo "$$files" | xargs du -ch | tail -1 | cut -f1) && \
	dbsize=$$(du -h "$$PYRE_DB_PATH" | cut -f1) && \
	echo "Current DB: $$dbsize  |  $$count backup(s)  |  $$total total" && \
	echo "" && \
	echo "$$files" | while read f; do \
		size=$$(du -h "$$f" | cut -f1) && \
		name=$$(basename "$$f") && \
		ts=$$(echo "$$name" | sed 's/.*-backup-\([0-9]*\)-\([0-9]*\)\.db/\1 \2/') && \
		day=$$(echo "$$ts" | cut -d' ' -f1) && \
		time=$$(echo "$$ts" | cut -d' ' -f2) && \
		pretty=$$(date -d "$${day:0:4}-$${day:4:2}-$${day:6:2} $${time:0:2}:$${time:2:2}:$${time:4:2}" "+%b %d %Y  %H:%M" 2>/dev/null) && \
		epoch=$$(date -d "$${day:0:4}-$${day:4:2}-$${day:6:2} $${time:0:2}:$${time:2:2}:$${time:4:2}" +%s 2>/dev/null) && \
		diff=$$((now - epoch)) && \
		if [ $$diff -lt 60 ]; then ago="just now"; \
		elif [ $$diff -lt 3600 ]; then ago="$$((diff / 60))m ago"; \
		elif [ $$diff -lt 86400 ]; then ago="$$((diff / 3600))h ago"; \
		else ago="$$((diff / 86400))d ago"; fi && \
		echo "  $$pretty    $$size    ($$ago)" && \
		if [ -f "$$f.note" ]; then echo "  Note: $$(cat "$$f.note")"; fi && \
		echo "  $$f" && \
		echo ""; \
	done

clean:
	rm -f *.pdf *.qfx *.ofx *.csv
