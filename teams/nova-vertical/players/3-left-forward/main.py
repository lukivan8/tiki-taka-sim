#!/usr/bin/env python3
"""AgentCore entrypoint for player 3, the left forward."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.runtime import create_agentcore_app
app = create_agentcore_app(3)
if __name__ == "__main__": app.run()
