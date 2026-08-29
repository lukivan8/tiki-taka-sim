# AFC Overnight Evolution — Morning Decision Packet

Run `afc-evolution-20260828T202307Z` · 2026-08-28 20:23:07 to 2026-08-29 03:00:00 UTC

## Recommendation

**Primary: `release-deep-denial-g4`** (`ff7060ffc0c4…`, `teams/release-deep-denial-g4`). It is the best-supported stable team produced by the evolutionary league: Elo **1511.707**, 27 trusted games, **4-20-3**, goals **4:3**. Its rating peaked at 1531.555. It drew the frozen G5 finalist directly, held Nova 0-0 in both fresh orientations, and split a fresh scoring pair 1-1 with its known Strict Switch exploiter. Its main known weakness is `simple-four-modes` at home: a clean 0-1 final loss after a clean reverse 0-0.

**First backup/control: `simple-four-modes`** (`46d137026d06…`). It is the numerical Elo leader at **1536.369**, 19 trusted games, **3-15-1**, goals **3:1**, and beat both G4 and G5 cleanly when Simple was home. It remains one trusted game short of the mechanical stable threshold; the final stabilization pair yielded one excluded draw and one clean draw. Use it when real-AFC smoke confirms its goalkeeper and low-block assumptions.

**Targeted alternative: `release-switch-shield-g5`** (`692e83ee34a9…`). Stable at Elo **1496.923**, 20 trusted games, **1-18-1**, goals **1:1**. It successfully robustified G4's opposite-lane weakness—cutting the original exploiter's paired shots from four to one and winning 1-0 aggregate—and repeatedly neutralized Nova. It is not the primary because Simple beat it cleanly 1-0 and its broad attack remained sparse.

Decision rule: prefer stable, broad, evolved evidence over a higher provisional Elo or a single specialist peak. If one additional clean trusted leg makes Simple stable and real-AFC calibration preserves its early-shot/keeper behavior, compare Simple and G4 in another fresh side-swapped pair before tournament lock.

## Strength picture

Elo includes only matches without harmful `error-idle`/`runner-idle`. Explicit, labeled deterministic recovery remains eligible and auditable. Stable means at least 20 trusted legs.

| Rank / role | Team | Lineage | Elo | Trusted W-D-L | Complete trusted pairs | GF:GA | Status | Best evidence | Worst evidence | Harmful decisions / all decisions | Transfer class |
|---|---|---|---:|---:|---:|---:|---|---|---|---:|---|
| 1 primary | `release-deep-denial-g4` | Release G4 | 1511.707 | 4-20-3 | 10 | 4:3 | stable (27) | Nova 3-6-1 over 10 trusted legs; fresh 0-0/0-0 | Simple 0-4-1; final away 0-1 | 9 / 12,000 (0.075%) | mixed, model-driven prompts + narrow validated role recovery |
| 2 backup | `simple-four-modes` | existing low-block seed | 1536.369 | 3-15-1 | 5 | 3:1 | provisional (19) | G4 1-4-0 and G5 1-4-0 | opening 0-1 to Release | 7 / 7,800 (0.090%) | mixed; model policy + deterministic goalkeeper behavior |
| 3 original anchor | `release-and-run` | Release seed | 1501.489 | 3-17-2 | 5 | 3:2 | stable (22) | beat Simple and vertical children | Nova 0-4-1; late clean loss to Simple | 12 / 12,300 (0.098%) | model-driven structural |
| 4 targeted alternative | `release-switch-shield-g5` | Release robustification G5 | 1496.923 | 1-18-1 | 6 | 1:1 | stable (20) | Strict Switch 1-2-0; repeated Nova draws | Simple 0-4-1 | 4 / 8,400 (0.048%) | mixed, model prompts + narrow recovery |
| 5 distinct control | `nova-vertical` | historical high-start | 1493.651 | 3-24-3 | 11 | 3:3 | stable (30) | Release 1-4-0; G3 1-3-0 | G4 1-6-3 | 0 / 11,700 (0%) | mixed/rigid command-mask risk |
| 6 counter | `strict-switch-counter-g4` | Strict G4 | 1491.457 | 1-4-2 | 3 | 1:2 | provisional (7) | four-shot paired G4 exploit; final home 1-0 G4 | G5 0-2-1 | 0 / 2,400 (0%) | mixed, explicit situation prompt + narrow recovery |
| 7 attacking ceiling | `strict-wide-pocket-g3` | Strict G3 | 1489.286 | 0-11-1 | 5 | 0:1 | provisional (12) | four child shots/two goals in excluded 2-2 | Nova 0-3-1 | 0 / 4,500 (0%) | mixed/rigid mask; boundary recovery |
| control | `vertical-wingbacks` | existing | 1501.571 | 0-6-0 | 0 | 0:0 | provisional (6) | stable shape, no trusted loss | no trusted scoring evidence | 6 / 3,600 (0.167%) | model-driven structural |

The complete table is in `ratings.csv`; every update is in `ELO_HISTORY.csv`. Elo trajectories for the important teams were:

- Release: 1500 start → 1531.935 peak → 1501.489 final.
- Nova: 1500 → 1529.281 peak → 1493.651 final.
- G4: 1500 → 1531.555 peak → 1511.707 final.
- G5: 1500 → 1516.119 peak → 1496.923 final.
- Simple: 1500 → 1540.145 peak → 1536.369 final (provisional).
- Strict Switch: 1500 → 1502.588 peak → 1491.457 final (provisional).

## Matchup structure and non-transitivity

The full trusted payoff table is `MATCHUP_MATRIX.csv`. Important slices:

| Team A | Team B | Trusted legs | A W-D-L | Goals A:B | Conclusion |
|---|---|---:|---:|---:|---|
| G4 | Nova | 10 | 3-6-1 | 3:1 | G4's compact countermeasure generalized, but did not eliminate all variance |
| Simple | G4 | 5 | 1-4-0 | 1:0 | strongest known primary weakness; Simple-home orientation decisive |
| Simple | G5 | 5 | 1-4-0 | 1:0 | shield mutation regressed against the same control |
| G5 | Strict Switch | 3 | 1-2-0 | 1:0 | successful targeted robustification |
| Strict Switch | G4 | 4 | 1-2-1 | 1:1 | exploiter creates real side-sensitive danger, not a universal win |
| G4 | G5 | 3 | 0-3-0 | 0:0 | robust successor does not dominate incumbent |
| Nova | Release | 5 | 1-4-0 | 1:0 | original counter that launched the Release lineage |

The league is non-transitive and orientation-sensitive: Release beat Simple early; Nova beat Release; G4 evolved to beat Nova; Strict Switch created four shots to zero against G4; G5 beat Strict Switch; Simple then beat G5 and G4 from its home orientation. Final Strict Switch–G4 split 1-1 on the same seed after side swap. Elo is therefore an orientation metric, not the selection oracle.

There is also a global home/kickoff signal: among 79 trusted legs, home teams won 10 and away teams won 5, with goals 10:5; all three decisive goals in the 14-leg held-out block were home goals. Because the Arena gives team 0 the initial kickoff and mirrors away x/y, “Simple at home” cannot yet be separated from a broader side advantage. This is why paired legs are reported separately.

The final G4 loss gives one concrete probe: at tick 2 / 4 s, Simple player 2 released from `(14.5,-6.0)` to forward 4; at tick 5 / 10 s, forward 4 controlled at `(34.3,-13.4)` and scored the only shot. Simple attempted the same initial pass in its earlier G5 win but did not score until tick 56, so kickoff access is a plausible enabler rather than a complete explanation.

## Evolution performed

The initial population was `nova-baseline`, `nova-vertical`, `nova-strict`, `kd-verticalis`, `vertical-wingbacks`, `release-and-run`, and `simple-four-modes`. The campaign created 17 immutable English candidate artifacts, registered 24 total teams, and completed 126 full matches (79 trusted).

Meaningful transitions:

1. Opening characterization produced two decisive signals: `nova-vertical` beat Release 1-0 and became the first Elo leader; `release-and-run` then beat Simple 1-0 and became the distinct scoring mutation substrate.
2. The Nova–Release replay exposed late wide access that the Release branch needed to repair.
3. Release counterpress/forward-wave/deep-denial branches were screened. G2 and G3 repaired shape and reliability; G4 added validator-checked role recovery and repeatedly produced a 1-0/0-0 Nova pair on fresh seeds.
4. `strict-wide-pocket-g1 → g2 → g3` repaired movement and boundary carry failures. G3 produced the night's 2-2 attacking peak, although the parent-side harmful idle excluded it from Elo.
5. `strict-switch-counter-g4` used far-side switches to create all four shots in a clean paired screen against G4.
6. `release-switch-shield-g5` robustified the far wingback responsibility, beat the exploiter 1-0 aggregate, and preserved Nova resistance.
7. Broad play rejected sole promotion for G5 after its clean Simple loss. Frozen final validation retained G4 as the stable evolved primary.

There were two main lineage-leader chains, one successful champion exploiter, and one successful robustification cycle. Detailed falsifiable hypotheses, classifications, negative results, and mutation types are in `LINEAGES.md`.

## Champion chain

`nova-vertical` first Elo leader and Release counter
→ `release-and-run` supplies distinct scoring lineage substrate
→ Nova replay exposes wide late-shot weakness
→ `release-deep-denial-g2`
→ G3 operational repair
→ **`release-deep-denial-g4` stable champion**
→ `strict-switch-counter-g4` exposes opposite-lane shots
→ `release-switch-shield-g5` robustifies that counter
→ broad Simple regression blocks G5 promotion
→ **G4 remains final stable evolved primary**, with Simple explicitly reported as provisional Elo leader.

## Portfolio

Bring the smallest useful set:

1. **PRIMARY — `release-deep-denial-g4`** (`ff7060ffc0c4…`, `teams/release-deep-denial-g4`). Use by default. Compact 3-1 denial, one primary presser, high forward outlet, narrow validator recovery. Switch away only if the real simulator reproduces Simple's immediate home-side shot or G4's far-lane exposure.
2. **BACKUP/CONTROL — `simple-four-modes`** (`46d137026d06…`, `teams/simple-four-modes`). Use against Release-family shapes if one more trusted test and real-AFC goalkeeper calibration pass. It is the strongest numerical team but not yet stable.
3. **TARGETED ALTERNATIVE — `release-switch-shield-g5`** (`692e83ee34a9…`, `teams/release-switch-shield-g5`). Use when opponents repeatedly switch from ball-side pressure into the far high lane, or when Nova-style high starts dominate. Do not use blindly against Simple-like low blocks.
4. **COUNTER — `strict-switch-counter-g4`** (`6bbafafba7a7…`, `teams/strict-switch-counter-g4`). Use specifically against compact 3-1 teams whose far wingback follows ball pressure. It is only seven trusted games and should not be the general default.

Retain `nova-vertical` as a stable, strategically distinct calibration opponent and `strict-wide-pocket-g3` as an attacking-ceiling research survivor, not tournament defaults.

## What the matches taught

- **Perception and execution:** the most consequential operational failures were semantic movement/carry rejects, not missing tactical facts. Validator-checked recovery repaired G4/G5 and Strict G3 without altering the frozen world. Old baseline/KD artifacts remained too unreliable for rating.
- **Roles and responsibility:** one primary ball defender plus explicit cover prevented clustering better than generalized aggression. The far wingback's goal-side inner-channel responsibility—not “press harder”—was the specific fix for switch exposure.
- **Progression:** direct-shot prompts did not help when teams never reached the 22-30 m shooting window. The bottleneck was reaching terminal geometry, not willingness to shoot once there.
- **Width:** high wide pockets generated the most shots, but a compact team could deny them until a fast far-side switch displaced the block. Width needs separation and switch timing, not two forwards converging on the owner.
- **Transitions:** the 120-second/60-decision horizon strongly rewards the first valid terminal chance. Most decisive matches had exactly one scoring shot.
- **Goalkeeping:** saves and deterministic keeper behavior materially shape the low-score regime. Simple's transfer sensitivity is high because its keeper code accounted for 1,547 deterministic decisions across its complete audit sample.
- **Model limitations:** stateless Nova frequently chose harmless structure but rarely assembled multi-step progression. Narrow structural prompts transferred better than verbose finishing instructions; deterministic recovery improved availability but did not create attack.

## Failed ideas worth preserving

- `release-forward-wave-g1` and `release-high-wave-g2`: more forward aggression increased clustering without creating shots.
- `release-counterpress-g1`: situationally useful but side-sensitive and not a stronger generalist.
- `release-balanced-g5`: reduced clustering but produced no shots; rejected.
- `release-finish-window-g6`: forcing the final action failed because the team did not enter the specified window.
- `release-reliable-g1`: fixed some operational behavior but failed to preserve scoring.
- `simple-pressure-carry-g1`: clean and less clustered, but no terminal opportunity; pressure/carry hypothesis contradicted.
- `vertical-safe-release-g1` and `vertical-direct-shot-g1`: did not improve away progression and lost rating evidence; the high-start parent survived instead.
- Strict G1/G2: tactically promising shots, but collision/backward-carry semantic failures required two reliability generations before G3.

## Evidence limits

- The simulator is the verified local AFC-compatible proxy, not the unpublished tournament environment.
- Only 9 of 24 teams exceeded two trusted games; only four reached 20 trusted games. Simple is one game short at 19; Strict Switch and Strict G3 are provisional specialists.
- Goals are sparse, many outcomes are 0-0, and confidence intervals were not estimated. Elo deltas can be dominated by one terminal shot.
- Side swap changed outcomes in final G4–Simple and G4–Strict Switch pairs. Formation mirroring, kickoff ownership, or opponent home orientation may be causal; do not collapse paired legs into a single invariant claim.
- Excluded matches remain tactically informative but never affect rating. Operational failure can belong to only one team, yet the whole match is excluded to avoid counterfactual scoring claims.
- Newly created candidates inherit historical Russian perception/runtime substrate in wrappers; every new or substantially changed artifact and rationale added tonight is English. This mixed substrate is preserved intentionally rather than silently translating a known team. Per-match `home_hash`/`away_hash` identify the leaf artifact; `CANDIDATES.csv` additionally records a conservative closure hash over every recorded code or evidence ancestor.

## Files

- Machine truth: `state.json`
- Flat candidate registry: `CANDIDATES.csv`; immutable manifests: `teams/<team-id>/team.yaml`
- Current rating: `ratings.csv`; chronological updates: `ELO_HISTORY.csv`
- Flat match registry: `MATCH_RESULTS.csv`
- Per-team operational provenance: `RELIABILITY.csv`
- Pairwise trusted evidence: `MATCHUP_MATRIX.csv`
- Hypotheses and ancestry: `LINEAGES.md`
- Ordered morning watch list: `IMPORTANT_REPLAYS.md`
- Real-AFC procedure: `TOURNAMENT_ADAPTATION.md`
- Compact per-match audits: `telemetry/*.json`
- Planned batch schedules (some branches stopped before every row): `*.csv`; actual execution truth: `MATCH_RESULTS.csv`; runners: `campaign.py`, `run_schedule.py`

Integrity audit: all 126 authoritative replays and all 126 viewer recordings match their recorded SHA-256 values. Every viewer recording contains the start marker, 7,201 simulation frames (ticks 0-7200), and the 120.0-second end marker. All four decision-critical team leaf hashes were constant across every match; recorded ancestry is covered by conservative closure hashes. All 24 manifests currently load into five-agent teams, all candidate modules compile, and the final 85-test suite passes.

No external web evidence was used. Strategy selection rests on repository truth, frozen-Arena matches, replay events, and inference provenance.
