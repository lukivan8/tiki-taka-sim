# AFC Evolution Campaign Progress

- Run: `afc-evolution-20260828T202307Z`
- Started: 2026-08-28 20:23:07 UTC (01:23:07 Asia/Almaty)
- Deadline: 2026-08-29 03:00:00 UTC (08:00 Asia/Almaty)
- Initial budget: 6h 36m 53s
- Current phase: completed at the 03:00 UTC handoff; all match processes ended at 02:06:56 UTC
- Frozen finalists since 01:30:10 UTC: `release-deep-denial-g4` and `release-switch-shield-g5`

## Current answer

Use `release-deep-denial-g4` as the primary. It is the strongest supported **stable evolved** generalist: Elo 1511.707 over 27 trusted games (4-20-3, 4:3), direct final draw with G5, a fresh 0-0/0-0 Nova pair, and a split 1-1 final pair with its known strict-switch exploiter. Its main weakness is a clean 0-1 loss when `simple-four-modes` was home.

`simple-four-modes` is the numerical Elo leader at 1536.369 and beat both finalists cleanly from its home orientation, but it has 19 trusted games and remains provisional. Treat it as the first backup/control, not as an unqualified champion. `release-switch-shield-g5` is stable at 20 trusted games and is the targeted alternative against strict-switch/Nova shapes, but its Elo is 1496.923 and it also lost cleanly to Simple.

## Campaign state

- 24 teams registered: 7 discovered starting teams and 17 immutable candidates.
- 126 full 120-second matches completed; 79 trusted Elo legs and 47 retained-but-excluded legs.
- Every full match recorded 600 decisions and preserved replay, 60 Hz recording, hashes, seed, telemetry, and inference provenance.
- Four lineages were evolved or attacked. Opening characterization made Nova the first Elo leader while Release supplied distinct scoring evidence; Release then reached G4, was exploited by Strict Switch G4, and was robustified into Release Switch Shield G5.
- Historical `kd-verticalis` and `nova-baseline` were suspended after repeated harmful semantic fallbacks; their matches remain in the audit but not Elo.
- No candidate, simulator, Arena, scoring, physics, command semantics, or model configuration changed after finalist freeze.

## Verified environment and safety

- Arena `nova-baseline-v2`, replay schema `afc-replay/v2`, model `us.amazon.nova-micro-v1:0`.
- 120 seconds at 60 Hz; decisions every 2 seconds; 60 decisions/player.
- All 85 repository tests passed before league play and again after final validation; live smoke was 10/10 valid with no fallback.
- Checkout began dirty on `main`, two commits ahead of `origin/main`. Pre-existing tracked/untracked work was preserved. Campaign additions are uncommitted.

## Final validation

Held-out seeds 9101-9107 were never used for mutation. Finalist head-to-head was 0-0 aggregate. G4 and G5 each held Nova 0-0/0-0. Simple beat G4 1-0 at home and drew the reverse; against G5 it repeated a home-side danger pattern with one prior clean 1-0, then a clean 0-0 and an excluded 0-0. G4 and Strict Switch split their final pair 1-1, proving side-sensitive non-transitivity.

See `RUN_SUMMARY.md` for the decision packet, `LINEAGES.md` for hypotheses, and `IMPORTANT_REPLAYS.md` for the ordered watch list.
