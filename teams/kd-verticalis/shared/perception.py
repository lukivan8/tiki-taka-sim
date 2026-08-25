"""Model-oriented football perception rendered as concise Russian facts."""
from __future__ import annotations

import math
from dataclasses import dataclass

FIELD_X, FIELD_Y, GOAL_X, GOAL_HALF_WIDTH = 55.0, 35.0, 56.0, 3.66
PASS_SPEED, RUN_SPEED, SPRINT_SPEED, ACCELERATION = 18.0, 7.2, 9.2, 14.0
WALK_SPEED = 5.6
# A command that omits sprint resolves to walkSpeed, not runSpeed: the arena
# treats "not sprinting" as walking. Sprint therefore costs stamina but is never
# slower, and even an exhausted sprinter (9.2 * 0.78 = 7.18) outruns a walk.
SPRINT_DRAIN_PER_SECOND = 0.085
SPRINT_THRESHOLD = 0.08
EXHAUSTED_FACTOR = 0.78


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def distance_to(self, other: "Point") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def projected(self, velocity: "Point", seconds: float) -> "Point":
        return Point(_clamp(self.x + velocity.x*seconds, -FIELD_X, FIELD_X),
                     _clamp(self.y + velocity.y*seconds, -FIELD_Y, FIELD_Y))


@dataclass(frozen=True)
class Player:
    player_id: int
    position: Point
    velocity: Point
    speed: float
    stamina: float
    current_action: int
    last_action: str
    sprinting: bool


@dataclass(frozen=True)
class PassLine:
    distance: float
    ball_time: float
    nearest_interceptor: int | None
    opponent_time: float
    blockers: tuple[int, ...]
    margin: float

    @property
    def open(self) -> bool:
        return not self.blockers and self.margin > 0.2


@dataclass(frozen=True)
class Perception:
    team_id: int
    player_id: int
    game_time: float
    self_player: Player
    ball: Point
    ball_velocity: Point
    possession_team: int | None
    possession_player: int | None
    teammates: dict[int, Player]
    opponents: dict[int, Player]
    attack_sign: int

    def distance_to_ball(self) -> float:
        return self.self_player.position.distance_to(self.ball)

    @property
    def owns_ball(self) -> bool:
        return self.possession_team == self.team_id and self.possession_player == self.player_id

    def pass_line(self, start: Point, end: Point, speed: float = PASS_SPEED) -> PassLine:
        dx, dy = end.x-start.x, end.y-start.y
        distance = math.hypot(dx, dy)
        length_squared = max(0.001, distance*distance)
        ball_time = distance/speed
        candidates: list[tuple[float, int, float]] = []
        blockers: list[int] = []
        for opponent in self.opponents.values():
            projection = ((opponent.position.x-start.x)*dx +
                          (opponent.position.y-start.y)*dy) / length_squared
            if not 0.03 < projection < 0.98:
                continue
            closest = Point(start.x+projection*dx, start.y+projection*dy)
            lateral = opponent.position.distance_to(closest)
            opponent_time = _arrival_time(opponent, closest)
            pass_time_here = ball_time*projection
            candidates.append((opponent_time-pass_time_here, opponent.player_id, opponent_time))
            if lateral < 2.2 or opponent_time <= pass_time_here+0.2:
                blockers.append(opponent.player_id)
        if not candidates:
            return PassLine(distance, ball_time, None, 99.0, (), 99.0)
        margin, player_id, opponent_time = min(candidates)
        return PassLine(distance, ball_time, player_id, opponent_time,
                        tuple(sorted(set(blockers))), margin)


def build_perception(payload: dict) -> Perception:
    state = payload["gameState"]
    team_id = int(payload["teamId"])
    player_id = int(payload["myPlayers"][0])
    sign = 1 if team_id == 0 else -1
    teammates, opponents = {}, {}
    for raw in state["players"]:
        raw_team = 0 if raw["teamCode"] == "home" else 1
        raw_id = int(raw["agentId"].rsplit("_", 1)[-1])
        velocity = raw.get("velocity", {})
        player = Player(
            raw_id,
            Point(sign*float(raw["position"]["x"]), sign*float(raw["position"]["y"])),
            Point(sign*float(velocity.get("x", 0)), sign*float(velocity.get("y", 0))),
            float(raw.get("speed", 0)), float(raw.get("stamina", 1)),
            int(raw.get("currentAction", 0)), str(raw.get("lastAction", "IDLE")),
            bool(raw.get("isSprinting", False)),
        )
        (teammates if raw_team == team_id else opponents)[raw_id] = player
    owner = state["ball"].get("possessionAgentId")
    ball_velocity = state["ball"].get("velocity", {})
    return Perception(
        team_id=team_id, player_id=player_id, game_time=float(state["gameTime"]),
        self_player=teammates[player_id],
        ball=Point(sign*float(state["ball"]["position"]["x"]),
                   sign*float(state["ball"]["position"]["y"])),
        ball_velocity=Point(sign*float(ball_velocity.get("x", 0)),
                            sign*float(ball_velocity.get("y", 0))),
        possession_team=state["ball"].get("possessionTeamId"),
        possession_player=int(owner.rsplit("_", 1)[-1]) if owner else None,
        teammates=teammates, opponents=opponents, attack_sign=sign,
    )


def _arrival_time(player: Player, point: Point) -> float:
    distance = player.position.distance_to(point)
    if distance < 0.05:
        return 0.0
    ux, uy = (point.x-player.position.x)/distance, (point.y-player.position.y)/distance
    initial = max(0.0, player.velocity.x*ux+player.velocity.y*uy)
    maximum = SPRINT_SPEED if player.stamina > 0.08 else RUN_SPEED*0.78
    initial = min(initial, maximum)
    accelerate_time = max(0.0, (maximum-initial)/ACCELERATION)
    accelerate_distance = initial*accelerate_time + 0.5*ACCELERATION*accelerate_time**2
    if distance <= accelerate_distance:
        return (-initial+math.sqrt(initial**2+2*ACCELERATION*distance))/ACCELERATION
    return accelerate_time+max(0.0, distance-accelerate_distance)/maximum


def _intercept_time(player: Player, perception: Perception) -> tuple[float, Point]:
    for step in range(13):
        seconds = step*0.25
        point = perception.ball.projected(perception.ball_velocity, seconds)
        if _arrival_time(player, point) <= seconds+0.12:
            return seconds, point
    point = perception.ball.projected(perception.ball_velocity, 3.0)
    return _arrival_time(player, point), point


def responsibility(perception: Perception) -> tuple[list[tuple[float, int, Point]], list[tuple[float, int, Point]]]:
    def ranked(players: dict[int, Player], keeper_limited: bool) -> list[tuple[float, int, Point]]:
        values = []
        for pid, player in players.items():
            time_to_ball, point = _intercept_time(player, perception)
            if keeper_limited and pid == 0 and not (point.x <= -40 and abs(point.y) <= 12):
                time_to_ball += 20
            if player.last_action in {"INTERCEPT", "PRESS_BALL"}:
                time_to_ball -= 0.12
            values.append((max(0.0, time_to_ball), pid, point))
        return sorted(values)
    return ranked(perception.teammates, True), ranked(perception.opponents, False)


def _role_anchor(perception: Perception, player_id: int) -> Point:
    # Decisions arrive every 2 s nominally, but a real Nova match measured 6.7 s
    # median between applied ticks. Anchoring to where the ball IS means every
    # player is permanently running to where the ball WAS. Lead it instead.
    # Swept against a 6.7 s decision interval over 40 seeds: a 0.9 s lead scores
    # 80, the 1.8-2.2 s plateau scores 120. 2.0 s sits in the middle of it.
    ball = perception.ball.projected(perception.ball_velocity, 2.0)
    ours = perception.possession_team == perception.team_id
    theirs = perception.possession_team is not None and not ours
    if player_id == 0:
        return Point(-50, _clamp(ball.y*0.10, -3.2, 3.2))
    if player_id == 1:
        # The pocket that wins us matches also loses them. Our own goal has a
        # mirrored pair at (-44, ±12): a shot struck from there is not saved by
        # our keeper either. Whenever the ball enters that band, the defender
        # covers the pocket instead of holding a central screen, because a
        # central attacker is exactly the one our keeper does stop.
        # Start dropping while the attack is still building: commands are issued
        # every 2 s, and an attacker running at the pocket covers ~15 m in that
        # time. Waiting until the ball is already deep means arriving late.
        #
        # The conceding band is wide (|y| from ~6 to ~24), so a fixed offset
        # cannot cover it. Track the ball's own line instead: stay goal-side of
        # it and slightly inside, which is where the shot must pass.
        if ball.x <= -6.0 and abs(ball.y) >= 6.0:
            return Point(_clamp(ball.x - 6.0, -46.0, -24.0),
                         _clamp(ball.y * 0.80, -20.0, 20.0))
        return Point(_clamp(ball.x-13, -38, -18), _clamp(ball.y*0.28, -12, 12))
    if player_id == 2:
        offset = -10 if ours else -14 if theirs else -11
        return Point(_clamp(ball.x+offset, -20, 30), _clamp(ball.y*0.38, -12, 12))
    side = -1 if player_id == 3 else 1
    if ours:
        # Attacking: sit in the wide-deep finishing pocket as soon as the ball
        # has crossed halfway, instead of trailing 13 m behind the ball.
        pocket = shooting_pocket(perception, side)
        if ball.x >= 6.0:
            return pocket
        return Point(_clamp(ball.x + 20.0, 8.0, pocket.x),
                     _clamp(side * 13.0 + ball.y * 0.18, -18.0, 18.0))
    if theirs:
        # A single defender cannot cover the conceding band, which spans |y| ~6
        # to ~24 on both flanks. When the attack comes down our own flank and is
        # already deep, this forward is the only player who can get goal-side of
        # the shot in time, so it tracks back into the threatened pocket. The
        # opposite forward stays high as the counter outlet.
        #
        # Possession flips constantly, and recomputing this branch on every flip
        # made the forwards the most unstable role in the squad: logged anchor
        # shifts averaged 18 m and peaked at 53 m, so they spent the interval
        # turning round instead of arriving. Only abandon the pocket for a
        # threat that is actually deep on this flank.
        same_flank = (ball.y < 0) == (side < 0)
        if same_flank and ball.x <= -12.0 and abs(ball.y) >= 6.0:
            return Point(_clamp(ball.x - 3.0, -46.0, -20.0),
                         _clamp(ball.y * 0.90, -22.0, 22.0))
        if ball.x >= -6.0:
            # The ball is not yet a threat to our goal: hold the outlet high
            # rather than tracking a ball that may be ours again next tick.
            return shooting_pocket(perception, side)
        return Point(_clamp(ball.x + 6.0, -6.0, 26.0),
                     _clamp(side * 15.0 + ball.y * 0.20, -22.0, 22.0))
    return Point(_clamp(ball.x + 10.0, -4.0, 40.0),
                 _clamp(side * 14.0 + ball.y * 0.20, -20.0, 20.0))


# A player that reaches its anchor stops dead until the next decision, and with
# a 6.7 s interval that is most of the match: 57 % of logged outfield speed
# samples were under 0.5 m/s. Pushing the target past the anchor along the same
# ray keeps the player running for the whole interval.
#
# How far to push depends on how often decisions land, and the two regimes
# disagree. At the realistic 6.7 s Nova interval, 0 m leaves 57 % of speed
# samples under 0.5 m/s; 6 m cuts that to 36 % and lifts distance covered from
# 359 to 431 m per outfielder. At a fast 2 s interval the trade reverses,
# because arriving exactly beats covering ground when commands are frequent --
# and past 6 m it does not degrade gracefully: over 48 matches, 6 m still wins
# 336-0 while 8 m collapses to 144-144. 6 m is the last safe value in both
# regimes. Finishing pockets stay exempt: overrunning the one geometry that
# beats the keeper is what costs goals.
ANCHOR_OVERSHOOT = 6.0


def _is_finishing_pocket(point: Point) -> bool:
    return point.x >= 38.0 and abs(point.y) >= 8.0


# Same corridors validate_semantics enforces for MOVE_TO. Overshoot has to stay
# inside them or the extended target is rejected and the player falls back to
# doing nothing, which is exactly what the overshoot exists to prevent.
ROLE_ZONES = {
    1: (-45.0, -10.0, -22.0, 22.0), 2: (-22.0, 46.0, -20.0, 20.0),
    3: (-48.0, 52.0, -26.0, -4.0), 4: (-48.0, 52.0, 4.0, 26.0),
}


def dynamic_anchor(perception: Perception, player_id: int) -> Point:
    """Role anchor, extended so the player is still running when the next
    decision lands.

    The keeper is exempt (it holds the goal line) and so are the finishing
    pockets, which must be occupied rather than run through.
    """
    anchor = _role_anchor(perception, player_id)
    if player_id == 0 or ANCHOR_OVERSHOOT <= 0 or _is_finishing_pocket(anchor):
        return anchor
    me = perception.self_player.position
    dx, dy = anchor.x - me.x, anchor.y - me.y
    distance = math.hypot(dx, dy)
    if distance < 0.5:
        return anchor
    scale = (distance + ANCHOR_OVERSHOOT) / distance
    x, y = me.x + dx*scale, me.y + dy*scale
    x1, x2, y1, y2 = ROLE_ZONES.get(player_id, (-49.0, 49.0, -31.0, 31.0))
    extended = Point(_clamp(x, x1, x2), _clamp(y, y1, y2))
    # Clamping can drag the point back behind the anchor; never return something
    # nearer than the anchor itself, or the overshoot becomes an undershoot.
    if me.distance_to(extended) < distance:
        return anchor
    return extended


def _shot_geometry(perception: Perception, origin: Point) -> tuple[float, float, list[str], list[int]]:
    a1 = math.atan2(-GOAL_HALF_WIDTH-origin.y, GOAL_X-origin.x)
    a2 = math.atan2(GOAL_HALF_WIDTH-origin.y, GOAL_X-origin.x)
    visible, all_blockers = [], set()
    for name, target_y in (("BL", -3.05), ("CENTER", 0.0), ("TR", 3.05)):
        line = perception.pass_line(origin, Point(GOAL_X, target_y), speed=28.0)
        all_blockers.update(line.blockers)
        if not line.blockers:
            visible.append(name)
    return (origin.distance_to(Point(GOAL_X, 0)), abs(math.degrees(a2-a1)),
            visible, sorted(all_blockers))



# --- KD Verticalis: shot-quality model -------------------------------------
# The arena goalkeeper is not a probability roll. It is a deterministic 60 Hz
# reflex with three exploitable limits, all read from arena.yaml:
#   * it only reacts once the ball is predicted to cross the goal line within
#     goalHalfWidth + predictionMargin = 4.66 m;
#   * it reacts 0.18 s late, then moves laterally at only 7.5 m/s, capped at
#     maximumLateralPosition = 4.2 m;
#   * it saves by proximity (goalkeeperControlRadius = 2.15 m) at its own plane
#     x = halfLength - goalLineOffset, not on the goal line.
# A shot struck from a wide, deep position crosses the keeper plane far from
# y = 0 while giving the keeper well under half a second of usable reaction, so
# the keeper is still near the middle when the ball passes. That is the whole
# basis of this team: arrive in the wide-deep pocket, then finish.
KEEPER_PLANE_X = GOAL_X - 1.0 - 5.0        # halfLength - goalLineOffset
KEEPER_REACTION = 0.18
KEEPER_LATERAL_SPEED = 7.5
KEEPER_LATERAL_ACCELERATION = 22.0
KEEPER_SAVE_RADIUS = 2.15
KEEPER_LATERAL_LIMIT = 4.2
KEEPER_TRIGGER_REACH = GOAL_HALF_WIDTH + 1.0
SHOT_SPEED = 28.0

AIM_TARGETS = {"BL": -3.05, "CENTER": 0.0, "TR": 3.05}


def _keeper_reachable(seconds: float) -> float:
    """Lateral metres the keeper can cover within `seconds` of ball flight."""
    usable = max(0.0, seconds - KEEPER_REACTION)
    ramp = KEEPER_LATERAL_SPEED / KEEPER_LATERAL_ACCELERATION
    if usable <= ramp:
        return 0.5 * KEEPER_LATERAL_ACCELERATION * usable * usable
    return 0.5 * KEEPER_LATERAL_SPEED * ramp + (usable - ramp) * KEEPER_LATERAL_SPEED


def shot_quality(perception: Perception, origin: Point, aim: str,
                 power: float = 1.0) -> tuple[bool, float, str]:
    """Return (scores, keeper_clearance_metres, reason) for one concrete shot.

    Ball flight is a straight line: drag scales both velocity components
    equally, so only the speed decays and the trajectory stays straight.
    """
    target_y = AIM_TARGETS[aim]
    dx, dy = GOAL_X - origin.x, target_y - origin.y
    distance = math.hypot(dx, dy)
    if distance < 0.5:
        return False, 0.0, "нулевая дистанция"
    ux, uy = dx / distance, dy / distance
    if ux <= 0.001:
        return False, 0.0, "нет направления к воротам"
    speed = SHOT_SPEED * _clamp(power, 0.25, 1.0)

    # Where the ball actually crosses the goal line. The aim point sits one
    # metre BEYOND the line, so a wide shot aimed at a post drifts wide.
    goal_line_x = GOAL_X - 1.0
    y_at_line = origin.y + uy * (goal_line_x - origin.x) / ux
    if abs(y_at_line) >= GOAL_HALF_WIDTH - 0.15:
        return False, 0.0, f"мимо створа (y={y_at_line:+.2f})"

    if perception.pass_line(origin, Point(GOAL_X, target_y), speed=speed).blockers:
        return False, 0.0, "линия удара перекрыта полевым игроком"

    keeper = perception.opponents.get(0)
    keeper_y = keeper.position.y if keeper else 0.0

    plane_distance = (KEEPER_PLANE_X - origin.x) / ux
    if plane_distance <= 0:
        return True, GOAL_HALF_WIDTH - abs(y_at_line), "удар из-за линии вратаря"
    y_at_plane = origin.y + uy * plane_distance
    travel = plane_distance / speed

    # Does the reflex even trigger? Outside the trigger reach the keeper never
    # leaves its strategic position at all.
    if abs(y_at_line) <= KEEPER_TRIGGER_REACH:
        wanted = _clamp(y_at_plane, -KEEPER_LATERAL_LIMIT, KEEPER_LATERAL_LIMIT)
        step = _keeper_reachable(travel)
        final_y = keeper_y + _clamp(wanted - keeper_y, -step, step)
    else:
        final_y = keeper_y
    # Safety margin: the keeper also carries momentum from its own strategic
    # movement, so demand real daylight rather than a knife-edge miss. Long
    # shots give the keeper time to recover fully, so they must clear by more.
    margin = 0.35 + _clamp((travel - 0.35) * 1.6, 0.0, 1.6)
    clearance = abs(y_at_plane - final_y) - KEEPER_SAVE_RADIUS - margin
    if clearance <= 0:
        return False, clearance, f"вратарь достаёт (запас {clearance:+.2f} м)"
    return True, clearance, f"вратарь не успевает (запас {clearance:+.2f} м)"


# Decisions are issued every 2 s while physics runs at 60 Hz, so the ball is
# struck from a slightly different place than the one evaluated here. A
# knife-edge shot does not survive that gap: demand real daylight.
MINIMUM_CLEARANCE = 1.2


def best_shot(perception: Perception, origin: Point) -> tuple[str | None, float, str]:
    """Pick the aim with the largest keeper clearance, or None if nothing scores."""
    scoring = []
    for aim in ("CENTER", "BL", "TR"):
        ok, clearance, reason = shot_quality(perception, origin, aim)
        if ok and clearance >= MINIMUM_CLEARANCE:
            scoring.append((clearance, aim, reason))
    if not scoring:
        return None, 0.0, "нет забивающего направления из этой точки"
    clearance, aim, reason = max(scoring)
    return aim, clearance, reason


def shooting_pocket(perception: Perception, side: int) -> Point:
    """Wide-deep finishing pocket for one flank, biased away from the keeper."""
    keeper = perception.opponents.get(0)
    keeper_y = keeper.position.y if keeper else 0.0
    magnitude = _clamp(12.0 + abs(keeper_y) * 0.4, 9.0, 16.0)
    return Point(44.0, side * magnitude)


def sprint_directive(perception: Perception, target: Point | None = None) -> tuple[bool, str]:
    """Decide sprint for the model instead of asking it to guess.

    The arena has no middle gear reachable from a command: `sprint: false` is
    walkSpeed (5.6), `sprint: true` is sprintSpeed (9.2) and falls back to
    7.18 when stamina runs out. Since the floor of sprinting still beats
    walking, the only real question is whether stamina should be banked, and
    that only matters when nothing is happening near you.
    """
    stamina = perception.self_player.stamina
    if stamina <= SPRINT_THRESHOLD:
        return True, (f"выносливость {stamina:.2f} на нуле, но спринт всё равно даёт "
                      f"{SPRINT_SPEED*EXHAUSTED_FACTOR:.1f} м/с против {WALK_SPEED:.1f} шагом")
    distance = perception.distance_to_ball()
    if target is not None:
        gap = perception.self_player.position.distance_to(target)
    else:
        gap = perception.self_player.position.distance_to(
            dynamic_anchor(perception, perception.player_id))
    contested = perception.possession_team != perception.team_id
    if perception.owns_ball:
        return True, "с мячом темп решает: спринт"
    if distance <= 18.0 or contested:
        return True, f"мяч в {distance:.1f} м и он не наш — спринт обязателен"
    if gap > 4.0:
        return True, f"до точки {gap:.1f} м — спринт"
    return False, f"мяч далеко ({distance:.1f} м), до точки {gap:.1f} м — можно восстановиться"


def allowed_commands(perception: Perception) -> tuple[str, ...]:
    team_rank, _ = responsibility(perception)
    primary = team_rank[0][1]
    anchor_distance = perception.self_player.position.distance_to(
        dynamic_anchor(perception, perception.player_id))
    base = ["MOVE_TO"]
    # IDLE was available to anyone sitting near their anchor, and the model took
    # it whenever it could not think of something better ("ожидание действий
    # партнёров"). Standing still is almost never right in a 120 s match: even
    # in position, a player should be adjusting to the ball. Only the keeper may
    # hold, and only with the ball far away and safely in our control.
    keeper_may_hold = (
        perception.player_id == 0
        and anchor_distance <= 1.0
        and perception.distance_to_ball() > 30.0
        and perception.possession_team == perception.team_id
    )
    if keeper_may_hold:
        base += ["IDLE"]
    if perception.owns_ball:
        if perception.player_id == 0:
            base += ["GK_DISTRIBUTE", "CLEAR"]
        else:
            # A carrier that picks MOVE_TO walks away from the ball it is
            # holding; in the logged match #3 did exactly this and lost 45 s
            # crossing the pitch without ever advancing the ball. With the ball,
            # the only ways to move it are DRIBBLE, PASS, SHOOT or CLEAR.
            base = ["PASS", "DRIBBLE", "CLEAR"]
            aim, _, _ = best_shot(perception, perception.self_player.position)
            if aim is not None:
                base += ["SHOOT"]
    else:
        secondary = team_rank[1][1] if len(team_rank) > 1 else None
        distance = perception.distance_to_ball()
        is_primary = perception.player_id == primary
        # The baseline let ONLY the single primary player contest the ball, so
        # a defender standing next to an opponent could not tackle and had to
        # watch. One presser is not a press: the ball carrier simply walks past
        # them. Anyone genuinely close to the ball may contest it, and the
        # designated cover may support the press.
        close = distance <= 6.0
        if perception.possession_team is None:
            if is_primary or close:
                base += ["INTERCEPT"]
        elif perception.possession_team != perception.team_id:
            if is_primary or close or perception.player_id == secondary:
                base += ["PRESS_BALL", "INTERCEPT"]
            # Tackling is a proximity fact, not a role privilege. The simulator
            # already requires the opponent to be within reach for it to work.
            if distance <= 2.6 and perception.player_id != 0:
                base += ["SLIDE_TACKLE"]
            base += ["MARK"]
    return tuple(dict.fromkeys(base))


def validate_semantics(perception: Perception, command_type: str,
                       target_player_id: int | None = None,
                       target_x: float | None = None,
                       target_y: float | None = None) -> None:
    if command_type not in allowed_commands(perception):
        raise ValueError(f"{command_type} недоступна игроку №{perception.player_id} в текущем состоянии")
    if command_type in {"PASS", "GK_DISTRIBUTE", "MARK", "SLIDE_TACKLE"}:
        if target_player_id is None:
            raise ValueError(f"{command_type} требует target_player_id")
        if command_type in {"PASS", "GK_DISTRIBUTE"} and target_player_id == perception.player_id:
            raise ValueError("нельзя передавать самому себе")
    if command_type == "MOVE_TO":
        target = Point(float(target_x), float(target_y))
        anchor = dynamic_anchor(perception, perception.player_id)
        primary = responsibility(perception)[0][0][1]
        if perception.player_id == 0 and target.distance_to(anchor) > 6:
            raise ValueError("вратарь MOVE_TO обязан оставаться возле динамической точки створа")
        if (perception.possession_team != perception.team_id and
                perception.player_id != primary and target.distance_to(anchor) > 8):
            raise ValueError("не первичный игрок без мяча обязан восстанавливать динамическую ролевую точку")
        role_zones = {
            1: (-45, -10, -22, 22), 2: (-22, 46, -20, 20),
            3: (-48, 52, -26, -4), 4: (-48, 52, 4, 26),
        }
        if perception.player_id in role_zones:
            x1, x2, y1, y2 = role_zones[perception.player_id]
            if not (x1 <= target.x <= x2 and y1 <= target.y <= y2):
                raise ValueError("цель MOVE_TO находится вне ролевого коридора игрока")
    if command_type == "DRIBBLE":
        target = Point(float(target_x), float(target_y))
        if perception.self_player.position.distance_to(target) < 2:
            raise ValueError("DRIBBLE должен продвигать мяч минимум на 2 метра")
        if target.x < perception.self_player.position.x-2:
            raise ValueError("DRIBBLE не должен вести мяч назад без явной причины")
    if command_type == "SHOOT":
        aim, _, reason = best_shot(perception, perception.self_player.position)
        if aim is None:
            raise ValueError(f"SHOOT недоступен из этой точки: {reason}")


def describe(perception: Perception, player_config: dict) -> str:
    if perception.possession_team is None:
        possession = "мяч свободен"
    elif perception.possession_team == perception.team_id:
        possession = "мяч у тебя" if perception.owns_ball else f"мяч у партнёра №{perception.possession_player}"
    else:
        possession = f"мяч у соперника №{perception.possession_player}"
    team_rank, enemy_rank = responsibility(perception)
    own_rank = next(i for i, item in enumerate(team_rank, 1) if item[1] == perception.player_id)
    primary_time, primary_id, primary_point = team_rank[0]
    secondary_time, secondary_id, _ = team_rank[1]
    enemy_time, enemy_id, _ = enemy_rank[0]
    is_primary = perception.player_id == primary_id
    anchor = dynamic_anchor(perception, perception.player_id)
    _sprint_now, _sprint_reason = sprint_directive(perception, anchor)
    field_players = [p for pid, p in perception.teammates.items() if pid != 0]
    centroid = Point(sum(p.position.x for p in field_players)/len(field_players),
                     sum(p.position.y for p in field_players)/len(field_players))
    width = max(p.position.y for p in field_players)-min(p.position.y for p in field_players)
    depth = max(p.position.x for p in field_players)-min(p.position.x for p in field_players)
    close_to_ball = [p.player_id for p in perception.teammates.values()
                     if p.position.distance_to(perception.ball) < 6]
    nearest_mate_distance = min((perception.self_player.position.distance_to(p.position)
        for pid, p in perception.teammates.items() if pid != perception.player_id), default=99)
    lines = [
        f"Время {perception.game_time:.1f} с; {possession}.",
        f"Ты №{perception.player_id}: ({perception.self_player.position.x:.1f}, {perception.self_player.position.y:.1f}); "
        f"скорость {perception.self_player.speed:.1f} вектор ({perception.self_player.velocity.x:.1f}, "
        f"{perception.self_player.velocity.y:.1f}); выносливость {perception.self_player.stamina:.2f}; "
        f"прошлое действие {perception.self_player.last_action}.",
        f"Мяч: ({perception.ball.x:.1f}, {perception.ball.y:.1f}); скорость "
        f"({perception.ball_velocity.x:.1f}, {perception.ball_velocity.y:.1f}); до тебя {perception.distance_to_ball():.1f} м.",
        f"ТВОЯ ОТВЕТСТВЕННОСТЬ: ранг прибытия {own_rank}/5. Первичный №{primary_id} ({primary_time:.2f} с), "
        f"страхующий №{secondary_id} ({secondary_time:.2f} с), ближайший соперник №{enemy_id} ({enemy_time:.2f} с).",
        (f"ТЫ НАЗНАЧЕН первичным игроком мяча; прогнозная точка ({primary_point.x:.1f}, {primary_point.y:.1f})."
         if is_primary else f"ТЫ НЕ ПЕРВИЧНЫЙ: №{primary_id} уже отвечает за мяч. Не присоединяйся к клубку."),
        f"Форма: центр полевых ({centroid.x:.1f}, {centroid.y:.1f}); глубина {depth:.1f}; ширина {width:.1f}; "
        f"у мяча (<6 м) {close_to_ball or 'нет'}; ближайший партнёр {nearest_mate_distance:.1f} м.",
        f"Динамическая точка восстановления роли ({anchor.x:.1f}, {anchor.y:.1f}); отклонение "
        f"{perception.self_player.position.distance_to(anchor):.1f} м.",
        f"СПРИНТ: {'ДА' if _sprint_now else 'НЕТ'} — {_sprint_reason}. "
        f"Это расчёт, а не предпочтение: ставь sprint={str(_sprint_now).lower()} "
        f"(для INTERCEPT — aggressive={str(_sprint_now).lower()}). "
        f"sprint=false означает шаг {WALK_SPEED:.1f} м/с вместо {SPRINT_SPEED:.1f} м/с.",
    ]
    # MARK is the one movement intent the arena never sprints: the marker walks
    # at 5.6 m/s while the player being marked may sprint at 9.2. Say so, or the
    # model treats marking as a real way to contain a runner.
    fastest_opponent = max(perception.opponents.values(), key=lambda x: x.speed)
    if fastest_opponent.speed > WALK_SPEED:
        lines.append(
            f"ВНИМАНИЕ: MARK всегда идёт шагом {WALK_SPEED:.1f} м/с. Соперник №"
            f"{fastest_opponent.player_id} уже бежит {fastest_opponent.speed:.1f} м/с — "
            f"опекой его не догнать. Против бегущего используй PRESS_BALL "
            f"(intensity ≥ 0.9), INTERCEPT (aggressive) или закрывай зону через MOVE_TO.")
    if len(close_to_ball) >= 2 and not is_primary:
        lines.append("ВОЗЛЕ МЯЧА УЖЕ ДВА ИЛИ БОЛЬШЕ ПАРТНЁРОВ: дополнительное сближение разрушит структуру.")
    lines.append("Партнёры:")
    for pid, p in sorted(perception.teammates.items()):
        if pid != perception.player_id:
            lines.append(f"- №{pid}: ({p.position.x:.1f},{p.position.y:.1f}), v=({p.velocity.x:.1f},{p.velocity.y:.1f}), "
                         f"до мяча {p.position.distance_to(perception.ball):.1f}, действие {p.last_action}.")
    lines.append("Соперники:")
    for pid, p in sorted(perception.opponents.items()):
        lines.append(f"- №{pid}: ({p.position.x:.1f},{p.position.y:.1f}), v=({p.velocity.x:.1f},{p.velocity.y:.1f}), "
                     f"до мяча {p.position.distance_to(perception.ball):.1f}.")
    owner = (perception.teammates.get(perception.possession_player)
             if perception.possession_team == perception.team_id else None)
    origin = owner.position if owner else perception.self_player.position
    lines.append("Линии от владельца:" if owner else "Линии от тебя (у команды нет владельца):")
    for pid, mate in sorted(perception.teammates.items()):
        if owner and pid == owner.player_id or not owner and pid == perception.player_id:
            continue
        line = perception.pass_line(origin, mate.position)
        pressure = min((mate.position.distance_to(x.position) for x in perception.opponents.values()), default=99)
        lines.append(f"- к №{pid}: {'ОТКРЫТА' if line.open else 'РИСК'}; {line.distance:.1f} м/{line.ball_time:.2f} с; "
                     f"перехватчик {line.nearest_interceptor if line.nearest_interceptor is not None else 'нет'}, "
                     f"запас {line.margin:.2f} с; давление {pressure:.1f} м; продвижение {mate.position.x-origin.x:+.1f}; "
                     f"блокируют {list(line.blockers) or 'нет'}.")
    lines.append("Ролевые зоны:")
    for item in player_config.get("control_points", []):
        point = Point(float(item["x"]), float(item["y"]))
        nearest_mate = min(perception.teammates.values(), key=lambda x: x.position.distance_to(point))
        nearest_enemy = min(perception.opponents.values(), key=lambda x: x.position.distance_to(point))
        lane = perception.pass_line(origin, point) if owner else None
        lines.append(f"- {item['name']} ({point.x:.0f},{point.y:.0f}): тебе {_arrival_time(perception.self_player, point):.2f} с; "
                     f"наш №{nearest_mate.player_id} {nearest_mate.position.distance_to(point):.1f} м; "
                     f"соперник №{nearest_enemy.player_id} {nearest_enemy.position.distance_to(point):.1f} м; "
                     f"линия владельца {'открыта' if lane and lane.open else 'риск/нет'}.")
    goal_distance, goal_angle, visible_aims, shot_blockers = _shot_geometry(perception, perception.self_player.position)
    keeper_point = perception.opponents[0].position
    lines.append(f"Удар от тебя: до ворот {goal_distance:.1f} м; угол {goal_angle:.1f}°; "
                 f"геометрически открыты {visible_aims or 'нет'}; блокируют {shot_blockers or 'нет'}; "
                 f"вратарь ({keeper_point.x:.1f},{keeper_point.y:.1f}).")

    # Verdict per aim from the deterministic keeper model. This is the fact that
    # decides finishing: geometric visibility alone does not beat the reflex.
    lines.append("РАСЧЁТ УДАРА (модель рефлекса вратаря, не мнение):")
    for aim in ("BL", "CENTER", "TR"):
        ok, clearance, reason = shot_quality(perception, perception.self_player.position, aim)
        lines.append(f"- {aim}: {'ЗАБИВАЕТ' if ok else 'НЕ ЗАБИВАЕТ'} — {reason}.")
    chosen_aim, chosen_clearance, _ = best_shot(perception, perception.self_player.position)
    if chosen_aim is not None:
        lines.append(f"ЛУЧШЕЕ НАПРАВЛЕНИЕ: {chosen_aim} с запасом {chosen_clearance:.2f} м. "
                     f"Если SHOOT доступен — бей туда с power 1.0.")
    else:
        lines.append("ЗАБИВАЮЩЕГО УДАРА ОТСЮДА НЕТ: улучшай позицию или отдавай пас, не бей наугад.")

    # Where the goal actually comes from, for every attacking decision.
    for side, name in ((-1, "левый"), (1, "правый")):
        pocket = shooting_pocket(perception, side)
        aim, clearance, _ = best_shot(perception, pocket)
        holder = min(perception.teammates.values(),
                     key=lambda x: x.position.distance_to(pocket))
        enemy = min(perception.opponents.values(),
                    key=lambda x: x.position.distance_to(pocket))
        lines.append(
            f"ЗАБИВНАЯ ЗОНА ({name} карман, {pocket.x:.0f},{pocket.y:.0f}): "
            f"{'удар оттуда забивает ' + aim if aim else 'оттуда пока не забивает'}"
            f"{f' (запас {clearance:.2f} м)' if aim else ''}; "
            f"тебе {_arrival_time(perception.self_player, pocket):.2f} с; "
            f"ближе всех наш №{holder.player_id} ({holder.position.distance_to(pocket):.1f} м); "
            f"соперник №{enemy.player_id} {enemy.position.distance_to(pocket):.1f} м; "
            f"линия владельца {'открыта' if owner and perception.pass_line(origin, pocket).open else 'риск/нет'}.")
    lines.append("ДОСТУПНЫЕ КОМАНДЫ: " + ", ".join(allowed_commands(perception)) + ".")
    if not is_primary and perception.possession_team != perception.team_id:
        lines.append(f"ОГРАНИЧЕНИЕ MOVE_TO БЕЗ МЯЧА: цель должна быть не дальше 8 м от динамической точки ({anchor.x:.1f},{anchor.y:.1f}).")
    if perception.player_id == 0:
        lines.append("ОГРАНИЧЕНИЕ ВРАТАРЯ: MOVE_TO только в радиусе 6 м от динамической точки створа.")
    lines.append("Выбери одну доступную команду. target_x/target_y — в координатах атаки; транспорт зеркалит away.")
    return "\n".join(lines)
