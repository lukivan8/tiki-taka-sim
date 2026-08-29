# Aggressive xG Wave — Initial Evaluation

This evaluation is separate from the completed overnight Elo campaign. It uses
the same frozen `nova-baseline-v2` Arena, 120-second horizon, 60 decisions per
player, and side-swapped comparisons. The simulator has no calibrated xG model;
shot distance and clear close-shot frequency are reported as xG proxies.

## Baseline

Across the overnight campaign's 30 trusted matches, `nova-vertical` produced 31
shots (1.03 per match), eight from at most 20 metres (0.27 per match), and three
goals. Mean shot distance was 23.3 metres.

## Lineage

- G1 combined Strict G3 volume, Strict Switch displacement, Release run-after-
  release, and a closer forced-finish x threshold. Rejected: one 26.2 m shot in
  two G4-defense legs and severe clustering.
- G2 added inner-channel anchors and distance/angle gating on Strict's substrate.
  Rejected: zero shots and a 0-1 loss in its first G4-defense leg.
- G3 moved the crossover onto `nova-vertical`. It repaired spacing and passing
  reliability but produced zero dribbles and zero shots across a clean pair.
- G4 added a validated carry guard when no open pass progressed at least five
  metres. Supported tactically: three shots in two legs, including 18.5 and
  19.1 m attempts, but one harmful movement fallback and one 29.2 m attempt.
- G5 removed optional shots beyond 24 metres and added validator-checked movement
  recovery. Promoted to initial aggressive challenger.

## G5 results

| Opponent / orientation | Result | G5 shots | G5 shot distances | Opponent shots | Harmful G5 fallback |
|---|---:|---:|---|---:|---:|
| G5 home vs G4 | 0-0 | 1 | 15.5 m | 0 | 0 |
| G5 away vs G4 | 0-0 | 1 | 17.9 m | 1 | 0 |
| G5 home vs Nova | 0-0 | 1 | 15.0 m | 0 | 0 |
| G5 away vs Nova | 1-0 | 1 | 21.4 m | 2 | 0 |

Aggregate: **1-3-0**, goals **1:0**, four G5 shots, all at most 22 metres,
mean distance **17.4 m**, and zero harmful fallbacks. Against Nova directly, G5
won **1-0 aggregate**; both created two shots, but G5's mean distance was **18.2
m** versus Nova's **23.5 m**.

This supports the claim that G5 currently has the better observed xG-like chance
profile. It does not yet prove a stable xG advantage: four matches are too few,
and the away G4 leg still showed 1,018 clustering frames.

## Replays

- G5 home vs G4: `var/matches/recordings/20260829T033308Z-5f2c17537511-aggressive-xg-wave-g5-vs-release-deep-denial-g4.frames.ndjson`
- G5 away vs G4: `var/matches/recordings/20260829T033514Z-755e1089dbda-release-deep-denial-g4-vs-aggressive-xg-wave-g5.frames.ndjson`
- G5 home vs Nova: `var/matches/recordings/20260829T033731Z-a1e76d9788a8-aggressive-xg-wave-g5-vs-nova-vertical.frames.ndjson`
- G5 away vs Nova, winning goal: `var/matches/recordings/20260829T033940Z-f58a994b0318-nova-vertical-vs-aggressive-xg-wave-g5.frames.ndjson`

## Next validation threshold

Before replacing Nova as the established attacking benchmark, run at least eight
more fresh, side-swapped legs against `simple-four-modes`, G4, G5 shield, and
Nova. Require at least 1.0 shot per match, at least 0.6 shots from at most 22 m
per match, zero harmful fallback, and no recurring high-clustering orientation.
