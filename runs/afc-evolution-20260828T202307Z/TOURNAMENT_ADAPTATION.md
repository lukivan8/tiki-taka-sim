# Morning Adaptation to the Real AFC Simulator

Keep the first pass short. Do not rewrite tactics before checking whether the local sensor and execution assumptions transfer.

## Recommended procedure

1. Run one real-AFC smoke for `release-deep-denial-g4`, `simple-four-modes`, and `release-switch-shield-g5`, ideally against the same opponent and both orientations.
2. Save authoritative world states, commands, results, and replay timestamps around kickoff, first possession change, first pressured pass, first shot, first goalkeeper intervention, and any invalid/fallback action.
3. For those states, reproduce each team's current perception text where the real interface exposes enough geometry. Compare stated lane, pressure, responsibility, recovery point, and shot facts against the authoritative replay.
4. Classify every mismatch before editing: perception fact/geometry, model decision, team strategy, execution assumption, or operational protocol.
5. Change representation constants or wording first. Re-run the exact probe. Change role/situation prompts only when the perception was correct and the decision was wrong.
6. Smoke all four portfolio teams after any shared substrate edit. Do not transfer Elo across a changed simulator or changed perception version.
7. If time permits, run a fresh paired G4–Simple comparison. Select Simple only if it becomes stable and its keeper/early-shot behavior transfers; otherwise start G4.

## Most transfer-sensitive assumptions

| Assumption | Local verified value / behavior | Why it matters | First check |
|---|---|---|---|
| Field scale | half-length 55, half-width 35 | every role anchor and distance label | compare kickoff coordinates and touchlines |
| Decision cadence | 2 s, 60 decisions/player in 120 s | favors immediate terminal actions | count real decisions and deadline behavior |
| Player motion | walk 5.6, run 7.2, sprint 9.2; acceleration/braking modeled | arrival ranks and recovery points | measure one unopposed 2 s move |
| Ball/control | control radius 1.18; max control speed 11.5 | interceptions, loose-ball ownership, primary responsibility | inspect first free-ball chase |
| Passes | 18/22/24 speed; lane margin derived from predicted travel | “open” vs intercepted releases | replay an open and a marginal line |
| Shooting | available to 30 m in strict substrate; 28 base speed | single-shot wins and final-window failures | compare first available shot and keeper response |
| Pressure/tackle | press challenge radius 1.55; tackle reach 1.15-2.15 | compact denial and counterpress | inspect nearest-player challenge |
| Goalkeeper | control radius 2.15, lateral cap 4.2, reaction 0.18 s | Simple's strongest results and shot-corridor text | replay same-angle shot; check rush/save geometry |
| Formation mirroring | away mirrors x and y; home starts kickoff | final results were orientation-sensitive | verify coordinate transform and kickoff owner |
| Validation | malformed/invalid action becomes IDLE locally | rating exclusions and recovery wrappers | intentionally validate one edge-case move off-field only |

## Safest first edits

1. Team-local perception constants used for distances, lane corridors, shot availability, pressure, and role anchors.
2. Coordinate mirroring/normalization if away orientation differs.
3. Natural-language labels that disagree with replay geometry (`OPEN`, pressure, forward progress, recovery side).
4. Narrow validator recovery targets if the real command schema rejects a locally valid move.
5. Only then adjust tactical responsibilities. Preserve G4's one-primary presser, central cover, and high outlet unless replay proves the structure itself failed.

Do not first edit the frozen local Arena, bake in `if x then SHOOT`, or replace the model. Those actions destroy comparability and confuse calibration with strategy.

## Team-specific sensitivity

- **G4:** most sensitive to role-anchor coordinates, off-ball movement validation, and far-side recovery. Reproduce Simple's tick-2 pivot release to forward 4 and tick-5 shot first. If that lane or another opposite-lane shot reappears, inspect the far wingback's stated recovery point before changing pressure intensity.
- **Simple:** highest goalkeeper-transfer risk because deterministic keeper behavior is a major part of its action mix. Validate keeper control/rush/save semantics before trusting its Elo lead.
- **G5:** sensitive to away mirroring and “far” wingback identity. Confirm the shield selects the opposite inner channel on both sides.
- **Strict Switch:** sensitive to pass-lane margins and high-start formation coordinates. If the far switch is labeled open but intercepted, repair the lane representation, not the switch priority.
- **Nova:** uses rigid mask-forced choices and 63 deterministic fallbacks in the campaign sample. Treat it as a calibration/control opponent, not the safest transfer default.

## Morning stop rule

Prefer G4 unless one of these is observed twice in clean real-AFC probes: its role recovery is invalid, Simple's early-shot/keeper advantage transfers and reaches stable evidence, or Strict Switch repeatedly creates far-lane shots with no G4 response. Keep every real-AFC result in a separate rating table keyed by simulator/version; never append it to the local `nova-baseline-v2` Elo history.
