"""Model-oriented football perception rendered as concise Russian facts."""
from __future__ import annotations

import math
from dataclasses import dataclass

FIELD_X, FIELD_Y, GOAL_X, GOAL_HALF_WIDTH = 55.0, 35.0, 56.0, 3.66
PASS_SPEED, RUN_SPEED, SPRINT_SPEED, ACCELERATION = 18.0, 7.2, 9.2, 14.0
MIN_DRIBBLE_CLEARANCE = 0.5


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
    """Rank one ball player without pulling specialist roles out of shape."""
    def ranked(players: dict[int, Player], our_roles: bool) -> list[tuple[float, int, Point]]:
        values = []
        for pid, player in players.items():
            time_to_ball, point = _intercept_time(player, perception)
            if our_roles:
                if pid == 0 and not (point.x <= -40 and abs(point.y) <= 12):
                    time_to_ball += 20
                elif pid == 1:  # left wingback must not cross the whole block
                    if point.y > 4:
                        time_to_ball += 10
                elif pid == 2:  # the only centre-back leaves the centre reluctantly
                    if abs(point.y) > 14:
                        time_to_ball += 8
                    if point.x > -10:
                        time_to_ball += 4
                elif pid == 3:  # right wingback mirrors player 1
                    if point.y < -4:
                        time_to_ball += 10
                elif pid == 4:  # the forward never chases a deep defensive ball
                    if point.x < -8:
                        time_to_ball += 20
                    elif perception.possession_team != perception.team_id and point.x < 5:
                        time_to_ball += 5
            if player.last_action in {"INTERCEPT", "PRESS_BALL"}:
                time_to_ball -= 0.12
            values.append((max(0.0, time_to_ball), pid, point))
        return sorted(values)
    return ranked(perception.teammates, True), ranked(perception.opponents, False)


def control_phase(perception: Perception) -> str:
    """Current-snapshot possession state; no memory or multi-tick intention."""
    if perception.possession_team == perception.team_id:
        return "OUR_CONTROL"
    if perception.possession_team is not None:
        return "THEIR_CONTROL"
    our_time = responsibility(perception)[0][0][0]
    their_time = responsibility(perception)[1][0][0]
    if our_time + 0.45 < their_time:
        return "LIKELY_OURS"
    if their_time + 0.45 < our_time:
        return "LIKELY_THEIRS"
    return "CONTESTED"


def _separated_anchor(perception: Perception, player_id: int, anchor: Point) -> Point:
    """Keep an automatically recommended target away from current teammates."""
    if player_id not in {1, 3, 4}:
        return anchor
    result = anchor
    for pid, mate in sorted(perception.teammates.items()):
        if pid == player_id or mate.position.distance_to(result) >= 6:
            continue
        if player_id in {1, 3}:
            side = -1 if player_id == 1 else 1
            low, high = (-25, -7) if side < 0 else (7, 25)
            result = Point(result.x, _clamp(mate.position.y+side*7, low, high))
        else:
            direction = -1 if mate.position.y >= result.y else 1
            result = Point(result.x, _clamp(mate.position.y+direction*7, -10, 10))
    return result


def dynamic_anchor(perception: Perception, player_id: int) -> Point:
    phase = control_phase(perception)
    ball = (perception.ball.projected(perception.ball_velocity, 0.5)
            if perception.possession_team is None else perception.ball)
    attacking = phase in {"OUR_CONTROL", "LIKELY_OURS"}
    if player_id == 0:
        return Point(-50, _clamp(ball.y*0.10, -3.2, 3.2))
    if attacking:
        if player_id == 2:
            return Point(_clamp(ball.x-20, -36, 8), _clamp(ball.y*0.10, -5, 5))
        if player_id in {1, 3}:
            side = -1 if player_id == 1 else 1
            anchor = Point(_clamp(ball.x+10, -12, 44),
                           _clamp(side*16+ball.y*0.20,
                                  -25 if side < 0 else 7,
                                  -7 if side < 0 else 25))
            owner = (perception.teammates.get(perception.possession_player)
                     if perception.possession_team == perception.team_id else None)
            if ball.x >= 30 and owner and owner.player_id == 4:
                shot_zone = Point(_clamp(ball.x+2, 38, 44), side*9)
                if perception.pass_line(owner.position, shot_zone).open:
                    anchor = shot_zone
            return _separated_anchor(perception, player_id, anchor)
        return _separated_anchor(
            perception, player_id,
            Point(_clamp(ball.x+12, -4, 47), _clamp(ball.y*0.15, -6, 6)),
        )
    back_x = _clamp(ball.x-12, -41, -24)
    if player_id == 2:
        return Point(back_x, _clamp(ball.y*0.18, -6, 6))
    if player_id in {1, 3}:
        side = -1 if player_id == 1 else 1
        anchor = Point(back_x+2, _clamp(side*14+ball.y*0.28,
                                       -24 if side < 0 else 6,
                                       -6 if side < 0 else 24))
        return _separated_anchor(perception, player_id, anchor)
    return _separated_anchor(
        perception, player_id,
        Point(_clamp(ball.x+15, -8, 25), _clamp(ball.y*0.12, -5, 5)),
    )


def role_zone(player_id: int) -> tuple[float, float, float, float]:
    return {
        1: (-45, 50, -27, -4),
        2: (-45, 12, -10, 10),
        3: (-45, 50, 4, 27),
        4: (-8, 50, -12, 12),
    }[player_id]


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    dx, dy = end.x-start.x, end.y-start.y
    length_squared = dx*dx+dy*dy
    if length_squared < 0.001:
        return point.distance_to(start)
    ratio = _clamp(((point.x-start.x)*dx+(point.y-start.y)*dy)/length_squared, 0, 1)
    return point.distance_to(Point(start.x+ratio*dx, start.y+ratio*dy))


def dribble_corridors(perception: Perception) -> list[tuple[str, Point, float, int]]:
    """Three short forward choices with measured opponent clearance."""
    origin = perception.self_player.position
    if perception.player_id in {1, 2, 3, 4}:
        minimum_x, maximum_x, minimum_y, maximum_y = role_zone(perception.player_id)
    else:
        minimum_x, maximum_x, minimum_y, maximum_y = (-FIELD_X, FIELD_X, -FIELD_Y, FIELD_Y)
    if perception.player_id in {2, 4}:
        raw = [
            ("прямо", Point(_clamp(origin.x+8, minimum_x, maximum_x),
                            _clamp(origin.y, minimum_y, maximum_y))),
            ("диагональ влево", Point(_clamp(origin.x+7, minimum_x, maximum_x),
                                      _clamp(origin.y-6, minimum_y, maximum_y))),
            ("диагональ вправо", Point(_clamp(origin.x+7, minimum_x, maximum_x),
                                       _clamp(origin.y+6, minimum_y, maximum_y))),
        ]
    else:
        raw = [
            ("прямо", Point(_clamp(origin.x+8, minimum_x, maximum_x),
                            _clamp(origin.y, minimum_y, maximum_y))),
            ("к центру", Point(_clamp(origin.x+7, minimum_x, maximum_x),
                               _clamp(origin.y*0.55, minimum_y, maximum_y))),
            ("наружу", Point(_clamp(origin.x+7, minimum_x, maximum_x),
                             _clamp(origin.y*1.18, minimum_y, maximum_y))),
        ]
    values = []
    for name, target in raw:
        nearest = min(perception.opponents.values(),
                      key=lambda enemy: _distance_to_segment(enemy.position, origin, target))
        clearance = _distance_to_segment(nearest.position, origin, target)
        values.append((name, target, clearance, nearest.player_id))
    return sorted(values, key=lambda item: item[2], reverse=True)


def executable_dribble_corridors(perception: Perception) -> list[tuple[str, Point, float, int]]:
    """Only short role-safe lanes with measurable room count as executable."""
    origin = perception.self_player.position
    zone = role_zone(perception.player_id) if perception.player_id in {1, 2, 3, 4} else None
    return [item for item in dribble_corridors(perception)
            if 2 <= origin.distance_to(item[1]) <= 14 and item[2] > MIN_DRIBBLE_CLEARANCE
            and (zone is None or zone[0] <= item[1].x <= zone[1] and zone[2] <= item[1].y <= zone[3])]


def open_passes(perception: Perception, player_ids: set[int] | None = None) -> list[tuple[int, PassLine]]:
    origin = perception.self_player.position
    values = []
    for pid, mate in perception.teammates.items():
        if pid == perception.player_id or player_ids is not None and pid not in player_ids:
            continue
        line = perception.pass_line(origin, mate.position)
        if line.open:
            values.append((pid, line))
    return sorted(values, key=lambda item: item[1].margin, reverse=True)


def striker_candidates(perception: Perception) -> list[tuple[float, str, Point, bool, float, float, list[str]]]:
    """Rank a small stable menu; the model still chooses whether to move."""
    owner = (perception.teammates.get(perception.possession_player)
             if perception.possession_team == perception.team_id else None)
    ball = perception.ball
    base_x = _clamp(ball.x+14, -4, 44)
    points = [
        ("центр впереди мяча", Point(base_x, 0)),
        ("левое плечо", Point(base_x, -6)),
        ("правое плечо", Point(base_x, 6)),
    ]
    if ball.x > 12:
        points += [
            ("левая ударная", Point(43, -6)),
            ("центральная ударная", Point(45, 0)),
            ("правая ударная", Point(43, 6)),
        ]
    values = []
    for name, point in points:
        nearest = min(perception.opponents.values(),
                      key=lambda enemy: enemy.position.distance_to(point))
        space = nearest.position.distance_to(point)
        advantage = _arrival_time(nearest, point)-_arrival_time(perception.self_player, point)
        lane = perception.pass_line(owner.position, point) if owner else None
        visible = _shot_geometry(perception, point)[2]
        teammate_space = min((mate.position.distance_to(point)
                              for pid, mate in perception.teammates.items()
                              if pid != perception.player_id), default=99)
        lane_open = bool(lane and lane.open)
        score = (3.0 if lane_open else -2.0) + min(space, 8)*0.35 + advantage
        score += max(0, point.x-ball.x)*0.05 + len(visible)*0.35
        score -= perception.self_player.position.distance_to(point)*0.04
        if teammate_space < 5:
            score -= 20
        values.append((score, name, point, lane_open, space, advantage, visible))
    return sorted(values, reverse=True)


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


def high_quality_shot(perception: Perception) -> bool:
    """A conservative ready-made finish where further play is needless risk."""
    if not perception.owns_ball or perception.player_id == 0:
        return False
    distance, angle, visible, blockers = _shot_geometry(perception, perception.self_player.position)
    return (distance <= 16 and angle >= 12 and not blockers and
            "CENTER" in visible and len(visible) >= 2)


def allowed_commands(perception: Perception) -> tuple[str, ...]:
    if high_quality_shot(perception):
        return ("SHOOT",)
    team_rank, _ = responsibility(perception)
    primary = team_rank[0][1]
    phase = control_phase(perception)
    anchor_distance = perception.self_player.position.distance_to(
        dynamic_anchor(perception, perception.player_id))
    base = ["MOVE_TO"]
    if anchor_distance <= 1.5 and not perception.owns_ball and perception.player_id != primary:
        base += ["IDLE"]
    if perception.owns_ball:
        if perception.player_id == 0:
            base += ["GK_DISTRIBUTE", "CLEAR"]
        else:
            base += ["PASS", "CLEAR"]
            if executable_dribble_corridors(perception):
                base += ["DRIBBLE"]
            shot_distance, _, visible, _ = _shot_geometry(perception, perception.self_player.position)
            if shot_distance <= 35 and visible:
                base += ["SHOOT"]
    elif perception.player_id == primary:
        if perception.possession_team is None:
            base += ["INTERCEPT"]
        elif phase == "THEIR_CONTROL":
            base += ["PRESS_BALL", "INTERCEPT"]
            if perception.distance_to_ball() <= 2.2:
                base += ["SLIDE_TACKLE"]
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
        if command_type in {"PASS", "GK_DISTRIBUTE"} and target_player_id not in perception.teammates:
            raise ValueError("передача требует target_player_id партнёра")
        if command_type == "MARK" and target_player_id == 0:
            raise ValueError("полевой игрок не должен персонально преследовать вратаря соперника")
    if command_type == "MOVE_TO":
        target = Point(float(target_x), float(target_y))
        anchor = dynamic_anchor(perception, perception.player_id)
        primary = responsibility(perception)[0][0][1]
        if perception.player_id == 0 and target.distance_to(anchor) > 6:
            raise ValueError("вратарь MOVE_TO обязан оставаться возле динамической точки створа")
        phase = control_phase(perception)
        maximum_anchor_distance = 8 if phase in {"THEIR_CONTROL", "LIKELY_THEIRS", "CONTESTED"} else 16
        if (not perception.owns_ball and perception.player_id != primary and
                target.distance_to(anchor) > maximum_anchor_distance):
            raise ValueError("не первичный игрок без мяча обязан восстанавливать динамическую ролевую точку")
        if perception.player_id in {1, 2, 3, 4}:
            x1, x2, y1, y2 = role_zone(perception.player_id)
            if not (x1 <= target.x <= x2 and y1 <= target.y <= y2):
                raise ValueError("цель MOVE_TO находится вне ролевого коридора игрока")
        occupied = [pid for pid, mate in perception.teammates.items()
                    if pid != perception.player_id and mate.position.distance_to(target) < 5]
        if occupied:
            raise ValueError(f"цель MOVE_TO создаёт сближение менее 5 м с партнёрами {occupied}")
    if command_type == "DRIBBLE":
        target = Point(float(target_x), float(target_y))
        if perception.self_player.position.distance_to(target) < 2:
            raise ValueError("DRIBBLE должен продвигать мяч минимум на 2 метра")
        if perception.self_player.position.distance_to(target) > 14:
            raise ValueError("DRIBBLE должен выбирать короткую проверяемую цель до 14 метров")
        if target.x < perception.self_player.position.x-2:
            raise ValueError("DRIBBLE не должен вести мяч назад без явной причины")
        if perception.player_id in {1, 2, 3, 4}:
            x1, x2, y1, y2 = role_zone(perception.player_id)
            if not (x1 <= target.x <= x2 and y1 <= target.y <= y2):
                raise ValueError("цель DRIBBLE находится вне ролевого коридора игрока")
        clearance = min(_distance_to_segment(enemy.position, perception.self_player.position, target)
                        for enemy in perception.opponents.values())
        if clearance <= MIN_DRIBBLE_CLEARANCE:
            raise ValueError(f"DRIBBLE заблокирован: свободный радиус {clearance:.2f} м <= "
                             f"{MIN_DRIBBLE_CLEARANCE:.1f} м")
    if command_type == "PASS":
        target = perception.teammates[target_player_id]
        selected = perception.pass_line(perception.self_player.position, target.position)
        alternatives = open_passes(perception, set(perception.teammates)-{target_player_id})
        dribbles = executable_dribble_corridors(perception)
        if not selected.open and (alternatives or dribbles):
            options = [f"PASS №{pid} (запас {line.margin:.2f})" for pid, line in alternatives]
            options += [f"DRIBBLE {name} (радиус {clearance:.1f})"
                        for name, _, clearance, _ in dribbles[:1]]
            raise ValueError("рискованный PASS запрещён при безопасной альтернативе: " + "; ".join(options))
    if command_type == "SHOOT":
        distance, _, visible, _ = _shot_geometry(perception, perception.self_player.position)
        if distance > 35 or not visible:
            raise ValueError("SHOOT недоступен: слишком далеко или нет открытого направления створа")


def describe(perception: Perception, player_config: dict) -> str:
    phase = control_phase(perception)
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
        f"Время {perception.game_time:.1f} с; {possession}; ФАЗА {phase}.",
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
    ]
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
        receiver_distance, receiver_angle, receiver_aims, receiver_blockers = _shot_geometry(perception, mate.position)
        lines.append(f"- к №{pid}: {'ОТКРЫТА' if line.open else 'РИСК'}; {line.distance:.1f} м/{line.ball_time:.2f} с; "
                     f"перехватчик {line.nearest_interceptor if line.nearest_interceptor is not None else 'нет'}, "
                     f"запас {line.margin:.2f} с; давление {pressure:.1f} м; продвижение {mate.position.x-origin.x:+.1f}; "
                     f"блокируют {list(line.blockers) or 'нет'}; после приёма: до ворот {receiver_distance:.1f} м, "
                     f"угол {receiver_angle:.1f}°, открытые направления {receiver_aims or 'нет'}, "
                     f"блокируют {receiver_blockers or 'нет'}.")
    if perception.owns_ball and perception.player_id != 0:
        lines.append("Передние коридоры дриблинга (лучший первым):")
        for name, target, clearance, blocker in dribble_corridors(perception):
            status = "ОТКРЫТ" if (perception.self_player.position.distance_to(target) >= 2 and
                                   clearance > MIN_DRIBBLE_CLEARANCE) else "ЗАКРЫТ"
            lines.append(f"- {name} к ({target.x:.1f},{target.y:.1f}): {status}; свободный радиус "
                         f"{clearance:.1f} м, ближайший соперник №{blocker}.")
        shot_distance, _, visible, _ = _shot_geometry(perception, perception.self_player.position)
        wing_passes = open_passes(perception, {1, 3})
        if perception.player_id == 4 and shot_distance <= 20 and not visible:
            lines.append("FINISHING OVERRIDE: до ворот не более 20 м, но удар закрыт. "
                         "Не повторяй DRIBBLE автоматически. Открытый вингер с положительным запасом — "
                         "первый выбор; из двух выбери больший запас. DRIBBLE допустим только по коридору ОТКРЫТ.")
            if wing_passes:
                lines.append("Открытые вингеры для завершения: " + ", ".join(
                    f"№{pid} запас {line.margin:.2f} с" for pid, line in wing_passes) + ".")
    if perception.player_id == 4 and phase in {"OUR_CONTROL", "LIKELY_OURS"} and not perception.owns_ball:
        lines.append("Кандидатные точки нападающего (лучшие первыми; новая точка нужна только при явном выигрыше):")
        for score, name, point, lane_open, space, advantage, visible in striker_candidates(perception)[:4]:
            lines.append(f"- {name} ({point.x:.1f},{point.y:.1f}): оценка {score:.2f}; "
                         f"линия {'ОТКРЫТА' if lane_open else 'РИСК'}; защитник {space:.1f} м; "
                         f"преимущество {advantage:+.2f} с; будущий створ {visible or 'закрыт'}.")
    if perception.player_id == 2 and perception.possession_team is not None and perception.possession_team != perception.team_id:
        owner_player = perception.opponents[perception.possession_player]
        own_goal = Point(-GOAL_X, 0)
        line_distance = _distance_to_segment(perception.self_player.position, owner_player.position, own_goal)
        goal_side = perception.self_player.position.x < owner_player.position.x
        keeper = perception.teammates[0]
        lines.append(f"Разделение с вратарём: ты {'между владельцем и воротами' if goal_side else 'НЕ goal-side'}; "
                     f"отклонение от линии угрозы {line_distance:.1f} м. №0 в "
                     f"({keeper.position.x:.1f},{keeper.position.y:.1f}) закрывает створ; ты закрываешь подход, "
                     "центральный удар и прострел.")
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
    lines.append(f"Удар от тебя: до ворот {goal_distance:.1f} м; угол {goal_angle:.1f}°; "
                 f"открытые направления {visible_aims or 'нет'}; блокируют {shot_blockers or 'нет'}; "
                 f"вратарь ({perception.opponents[0].position.x:.1f},{perception.opponents[0].position.y:.1f}).")
    if high_quality_shot(perception):
        lines.append("HIGH_QUALITY_SHOT: готовый удар обязателен. Выбери только SHOOT CENTER power=1.0; "
                     "не выбирай DRIBBLE или PASS.")
    lines.append("ДОСТУПНЫЕ КОМАНДЫ: " + ", ".join(allowed_commands(perception)) + ".")
    if not is_primary and not perception.owns_ball:
        radius = 8 if phase in {"THEIR_CONTROL", "LIKELY_THEIRS", "CONTESTED"} else 16
        lines.append(f"ОГРАНИЧЕНИЕ MOVE_TO БЕЗ МЯЧА: цель должна быть не дальше {radius} м "
                     f"от динамической точки ({anchor.x:.1f},{anchor.y:.1f}).")
    if perception.player_id == 0:
        lines.append("ОГРАНИЧЕНИЕ ВРАТАРЯ: MOVE_TO только в радиусе 6 м от динамической точки створа.")
    if perception.owns_ball and perception.player_id != 0:
        lines.append(f"ОГРАНИЧЕНИЕ DRIBBLE: цель впереди на расстоянии от 2 до 14 м, внутри ролевого коридора "
                     f"и со свободным радиусом больше {MIN_DRIBBLE_CLEARANCE:.1f} м.")
    if not perception.owns_ball:
        lines.append("ОГРАНИЧЕНИЕ ОТКРЫВАНИЯ: MOVE_TO не может вести ближе 5 м к текущей позиции партнёра.")
    lines.append("Выбери одну доступную команду. target_x/target_y — в координатах атаки; транспорт зеркалит away.")
    return "\n".join(lines)
