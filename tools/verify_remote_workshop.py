#!/usr/bin/env python3
"""Run one real ten-player decision through the configured public Nova gateway."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


if not os.environ.get("AFC_NOVA_GATEWAY_URL") or not os.environ.get("AFC_GATEWAY_TOKEN"):
    raise SystemExit("source .env with AFC_NOVA_GATEWAY_URL and AFC_GATEWAY_TOKEN first")

import live_match_server
from live_match_server import LiveMatch


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        previous = live_match_server.LIVE_ROOT
        live_match_server.LIVE_ROOT = Path(directory)
        try:
            match = LiveMatch("nova-baseline", "nova-baseline", realtime=False, duration_seconds=0.2)
            match.start()
            match.thread.join(180)
        finally:
            live_match_server.LIVE_ROOT = previous
    if match.thread.is_alive():
        match.stop()
        raise SystemExit("remote verification timed out")
    results = [
        result
        for message in match.messages
        for result in message.get("agentResults", [])
    ]
    sources = sorted({result.get("decisionSource") for result in results})
    valid = sum(result.get("status") == "valid" for result in results)
    print({
        "status": match.status,
        "score": match.world.score,
        "physicsFrames": match.world.tick + 1,
        "agentResults": len(results),
        "validDecisions": valid,
        "decisionSources": sources,
        "errors": sorted({
            result.get("modelError") for result in results if result.get("modelError")
        }),
    })
    if match.status != "finished" or len(results) != 10:
        raise SystemExit("remote workshop verification failed")
    if any(source not in {"nova-gateway", "error-idle"} for source in sources):
        raise SystemExit("a decision bypassed the remote Nova gateway")


if __name__ == "__main__":
    main()
