# Compare AFC Simulator Probe Replays

You are calibrating perception, not tactics. You receive:

- the local authoritative probe replay;
- the AFC tournament probe replay;
- `teams/simulator-probe/live_team.py` containing the deterministic schedule;
- the current team perception source and configuration.

Correlate equivalent named `PROBE` experiments in both replays. The probe is the controlled HOME team; the sample opponent is uncontrolled. Do not assume identical sample-team actions, tick numbering, wall timing, coordinate orientation, or replay schemas. Align experiments using phase markers, simulation time, commands, and state transitions. Compare authoritative before/after states and actual command outcomes, not commentary or intended behavior.

Measure only perception-critical differences. For every conclusion cite exact local and tournament ticks/times and label it `MEASURED`, `INFERRED`, or `UNRESOLVED`. A result may be `MEASURED` only when the probe command and relevant setup state actually occurred in both replays. Treat a missing, interrupted, rejected, or materially different sample-opponent interaction as unresolved; never invent a value. Identify which current perception assumptions are wrong, locate the exact affected files/constants/functions, and recommend the smallest patches. Do not change tactical policy to compensate for incorrect perception.

At minimum compare:

- coordinates, attack direction, side mirroring, field dimensions, bounds, and goal locations;
- decision interval and one-decision straight/diagonal movement and reachability;
- collision separation and boundary behavior;
- ball control radius, possession changes, and receiver control;
- short/medium/long/diagonal pass speed and travel time;
- receiver and defender reach and practical passing-lane openness/width;
- pressure, tackle, and interception distances, including whether the owner passes before contact;
- shot availability, distance, angle, clear/blocked lanes, and shot direction;
- centered/displaced goalkeeper reach, saves, rebounds, and resulting possession;
- command validation, rejection, normalization, and fallback semantics.

First produce this table, with one row per concept or distinct measured behavior:

| Concept | Local behavior | Tournament behavior | Evidence in both replays | Confidence | Perception impact | Exact recommended edit |
|---|---|---|---|---|---|---|

Use numeric values with units where the replay supports them. Separate facts from interpretation. If local and tournament behavior agree within replay precision, explicitly say no edit is needed.

Finish with exactly this section structure:

## PERCEPTION PATCH PLAN

### P0 — must change before using any strategy

### P1 — materially affects attack or defense

### P2 — uncertain or low impact

For every item include:

- file/function/config key;
- current assumption;
- replacement value or formula;
- replay evidence with exact ticks/times from both files;
- teams most affected;
- one quick validation check.

Do not propose a replay framework, dashboard, statistical model, tactical rewrite, or broad refactor. If no item belongs in a priority level, write `None`.
