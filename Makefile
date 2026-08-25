.PHONY: check test-nova test-simulator test-live live create-team create-invite verify-remote clean-generated

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; elif [ -x .venv-afc/bin/python ]; then echo .venv-afc/bin/python; else echo python3; fi)

check: test-nova test-simulator test-live

test-nova:
	PYTHONPATH=tools $(PYTHON) -m unittest -v tools.test_nova_team

test-simulator:
	PYTHONPATH=tools $(PYTHON) -m unittest -v tools.test_simulator

test-live:
	PYTHONPATH=tools $(PYTHON) -m unittest -v tools.test_live_match_server

live:
	$(PYTHON) tools/live_match_server.py --host 127.0.0.1 --port $${SIMULATOR_PORT:-8300}

create-team:
	@test -n "$(NAME)" || (echo 'usage: make create-team NAME=alice-team [DISPLAY_NAME="Alice Team"] [SOURCE=nova-baseline]' && exit 2)
	$(PYTHON) tools/create_team.py "$(NAME)" --source "$(or $(SOURCE),nova-baseline)" $(if $(DISPLAY_NAME),--display-name "$(DISPLAY_NAME)",)

create-invite:
	@test -n "$(NAME)" || (echo 'usage: make create-invite NAME=alice' && exit 2)
	$(PYTHON) tools/create_gateway_invite.py "$(NAME)"

verify-remote:
	PYTHONPATH=tools $(PYTHON) tools/verify_remote_workshop.py

clean-generated:
	find var/matches -type f -delete 2>/dev/null || true
