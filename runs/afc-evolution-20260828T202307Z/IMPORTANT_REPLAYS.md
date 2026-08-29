# Important Replays — Morning Watch List

The viewer is running at `http://127.0.0.1:8300`. If it needs restarting, run `make live`; the Makefile automatically selects `.venv-afc/bin/python` in this checkout. Each URL below opens the exact 60 Hz recording. Hashes are abbreviated to 12 characters; full implementation, replay, and recording SHA-256 checksums are in `state.json` and `telemetry/<match-id>.json`.

## 1. Opening breakthrough: Release beats Simple

- Match `64e2c5147c60`, seed 1219: `release-and-run` (`8cb4672d6d92`) 1-0 `simple-four-modes` (`46d137026d06`), trusted.
- Replay: `var/matches/matches/20260828T210415Z-64e2c5147c60-release-and-run-vs-simple-four-modes.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/64e2c5147c60.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260828T210415Z-64e2c5147c60-release-and-run-vs-simple-four-modes.frames.ndjson)
- Elo: Release 1484.000→1500.736; Simple 1500.000→1483.264.
- Watch 64-70 s / tick 33: Release player 1's only shot becomes the winning goal. This established Release as a serious mutation substrate and the short-horizon “one terminal chance matters” prior.

## 2. Nova exposes the incumbent

- Match `dafa2e6a6f56`, seed 1216: `nova-vertical` (`4dedda7a9c69`) 1-0 `release-and-run` (`8cb4672d6d92`), trusted.
- Replay: `var/matches/matches/20260828T205655Z-dafa2e6a6f56-nova-vertical-vs-release-and-run.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/dafa2e6a6f56.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260828T205655Z-dafa2e6a6f56-nova-vertical-vs-release-and-run.frames.ndjson)
- Elo: Nova 1500.000→1516.000; Release 1500.000→1484.000.
- Watch 112-118 s / tick 57: Nova forward 3 reaches a wide late shot. This directly motivated compact deep denial.

## 3. G4's first important failure

- Match `91cc4fe392ce`, seed 1802: `release-deep-denial-g4` (`ff7060ffc0c4`) 0-1 `nova-vertical` (`4dedda7a9c69`), trusted.
- Replay: `var/matches/matches/20260828T215708Z-91cc4fe392ce-release-deep-denial-g4-vs-nova-vertical.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/91cc4fe392ce.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260828T215708Z-91cc4fe392ce-release-deep-denial-g4-vs-nova-vertical.frames.ndjson)
- Elo: G4 1500.670→1485.279; Nova 1513.890→1529.281.
- Watch 102-108 s / tick 52: Nova forward 4 converts the sole shot. This prevented promotion on one favorable seed.

## 4. G4 adaptation succeeds on a fresh seed

- Match `b2fb28382816`, seed 2001: `release-deep-denial-g4` (`ff7060ffc0c4`) 1-0 `nova-vertical` (`4dedda7a9c69`), trusted.
- Replay: `var/matches/matches/20260828T220212Z-b2fb28382816-release-deep-denial-g4-vs-nova-vertical.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/b2fb28382816.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260828T220212Z-b2fb28382816-release-deep-denial-g4-vs-nova-vertical.frames.ndjson)
- Elo: G4 1487.295→1505.128; Nova 1527.265→1509.432.
- Watch 34-40 s / tick 18 for G4 player 3's wide finish, then 114-120 s / tick 58 for Nova player 4's saved reply. This is the clearest G4 promotion replay.

## 5. Highest attacking ceiling (excluded from Elo)

- Match `5307df2e4071`, seed 2403: `strict-wide-pocket-g3` (`87f330493b3e`) 2-2 `nova-strict` (`e776dc269b79`), excluded because the parent had one harmful idle.
- Replay: `var/matches/matches/20260828T224239Z-5307df2e4071-strict-wide-pocket-g3-vs-nova-strict.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/5307df2e4071.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260828T224239Z-5307df2e4071-strict-wide-pocket-g3-vs-nova-strict.frames.ndjson)
- No Elo update. G3 itself used validated recovery and had no harmful idle.
- Watch ticks 8, 10, 16, 35, 48, and 58 (16-118 s): six shots and four goals. G3 scores at ticks 16 and 48; this is the best evidence for its attacking-ceiling role.

## 6. Strict Switch exposes G4

- Match `658a42a6d150`, seed 3101: `strict-switch-counter-g4` (`6bbafafba7a7`) 0-0 `release-deep-denial-g4` (`ff7060ffc0c4`), trusted.
- Replay: `var/matches/matches/20260828T235734Z-658a42a6d150-strict-switch-counter-g4-vs-release-deep-denial-g4.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/658a42a6d150.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260828T235734Z-658a42a6d150-strict-switch-counter-g4-vs-release-deep-denial-g4.frames.ndjson)
- Elo: Strict Switch 1500.000→1501.356; G4 1529.526→1528.170.
- Watch 56-64 s / ticks 29 and 31: both high forwards shoot after opposite-lane access. Together with side swap `16143d3cb00e`, Strict Switch created all four paired shots to G4's zero.

## 7. Side-swapped exploit replication

- Match `16143d3cb00e`, seed 3101: `release-deep-denial-g4` (`ff7060ffc0c4`) 0-0 `strict-switch-counter-g4` (`6bbafafba7a7`), trusted.
- Replay: `var/matches/matches/20260828T235933Z-16143d3cb00e-release-deep-denial-g4-vs-strict-switch-counter-g4.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/16143d3cb00e.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260828T235933Z-16143d3cb00e-release-deep-denial-g4-vs-strict-switch-counter-g4.frames.ndjson)
- Elo: G4 1528.170→1526.938; Strict Switch 1501.356→1502.588.
- Watch 66-84 s / ticks 34 and 41: the away high forwards reproduce the two-shot advantage. This made the exploitation hypothesis causal enough to robustify.

## 8. G5 targeted robustification works

- Match `abe1ff57b96a`, seed 3101: `strict-switch-counter-g4` (`6bbafafba7a7`) 0-1 `release-switch-shield-g5` (`692e83ee34a9`), trusted.
- Replay: `var/matches/matches/20260829T000216Z-abe1ff57b96a-strict-switch-counter-g4-vs-release-switch-shield-g5.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/abe1ff57b96a.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260829T000216Z-abe1ff57b96a-strict-switch-counter-g4-vs-release-switch-shield-g5.frames.ndjson)
- Elo: Strict Switch 1502.588→1486.469; G5 1500.000→1516.119.
- Watch 46-52 s / tick 24: G5 forward 4 scores its only shot. Across the original pair, G5 cut exploiter shots from four to one and won 1-0 aggregate.

## 9. G5's broad regression

- Match `58b83ce65c32`, seed 3404: `simple-four-modes` (`46d137026d06`) 1-0 `release-switch-shield-g5` (`692e83ee34a9`), trusted.
- Replay: `var/matches/matches/20260829T011948Z-58b83ce65c32-simple-four-modes-vs-release-switch-shield-g5.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/58b83ce65c32.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260829T011948Z-58b83ce65c32-simple-four-modes-vs-release-switch-shield-g5.frames.ndjson)
- Elo: Simple 1508.236→1524.329; G5 1510.250→1494.157.
- Watch 110-116 s / tick 56: Simple's forward converts the only shot. The targeted shield did not generalize into a superior champion.

## 10. Final primary's worst held-out matchup

- Match `8ee85eb85733`, seed 9102: `simple-four-modes` (`46d137026d06`) 1-0 `release-deep-denial-g4` (`ff7060ffc0c4`), trusted.
- Replay: `var/matches/matches/20260829T013824Z-8ee85eb85733-simple-four-modes-vs-release-deep-denial-g4.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/8ee85eb85733.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260829T013824Z-8ee85eb85733-simple-four-modes-vs-release-deep-denial-g4.frames.ndjson)
- Elo: Simple 1524.234→1540.145; G4 1522.312→1514.356.
- Watch 4-12 s / ticks 2-5: Simple player 2 passes from `(14.5,-6.0)` and player 4 receives at `(34.3,-13.4)`, then scores immediately from the only shot. The reverse leg was a clean 0-0, making kickoff/orientation a material known risk.

## 11. Final non-transitive split

- Match `358b614413ba`, seed 9106: `release-deep-denial-g4` (`ff7060ffc0c4`) 1-0 `strict-switch-counter-g4` (`6bbafafba7a7`), trusted.
- Replay: `var/matches/matches/20260829T015625Z-358b614413ba-release-deep-denial-g4-vs-strict-switch-counter-g4.ndjson`
- Audit: `runs/afc-evolution-20260828T202307Z/telemetry/358b614413ba.json`
- [Viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260829T015625Z-358b614413ba-release-deep-denial-g4-vs-strict-switch-counter-g4.frames.ndjson)
- Elo: G4 1513.374→1520.794; Strict Switch 1488.122→1473.283.
- Watch 24-30 s / tick 13: G4's forward scores the only shot. The side swap `87234b2ae5b9` reverses the result: [viewer](http://127.0.0.1:8300/viewer/?log=/var/matches/recordings/20260829T015847Z-87234b2ae5b9-strict-switch-counter-g4-vs-release-deep-denial-g4.frames.ndjson), audit `runs/afc-evolution-20260828T202307Z/telemetry/87234b2ae5b9.json`, 66-86 s / ticks 34 and 41. Strict Switch 1473.283→1491.457; G4 1520.794→1511.707.
