.PHONY: check verify-sample-agents play-local-model

check:
	cargo test --workspace

verify-sample-agents:
	bash scripts/verify-sample-agents.sh

play-local-model:
	bash scripts/play-local-model.sh
