"""Model-oriented football perception rendered as concise Russian facts."""
from __future__ import annotations

import math
from dataclasses import dataclass

FIELD_X, FIELD_Y, GOAL_X, GOAL_HALF_WIDTH = 55.0, 35.0, 56.0, 3.66
PASS_SPEED, RUN_SPEED, SPRINT_SPEED, ACCELERATION = 18.0, 7.2, 9.2, 14.0
# arena.goalkeeping: the keeper only slides to +-4.2 m and only reacts to a ball
# faster than 8 m/s, so it is a lateral race, not a body that blocks the goal.
KEEPER_ID, KEEPER_LATERAL_REACH, SHOT_SPEED = 0, 4.2, 28.0
SHOT_RANGE, MINIMUM_PASS_DISTANCE = 30.0, 2.4


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

    def pass_line(self, start: Point, end: Point, speed: float = PASS_SPEED,
                  ignore_ids: frozenset[int] = frozenset()) -> PassLine:
        dx, dy = end.x-start.x, end.y-start.y
        distance = math.hypot(dx, dy)
        length_squared = max(0.001, distance*distance)
        ball_time = distance/speed
        candidates: list[tuple[float, int, float]] = []
        blockers: list[int] = []
        for opponent in self.opponents.values():
            if opponent.player_id in ignore_ids:
                continue
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


def dynamic_anchor(perception: Perception, player_id: int) -> Point:
    ball = perception.ball
    ours = perception.possession_team == perception.team_id
    theirs = perception.possession_team is not None and not ours
    if player_id == 0:
        return Point(-50, _clamp(ball.y*0.10, -3.2, 3.2))
    if player_id == 1:
        return Point(_clamp(ball.x-13, -38, -18), _clamp(ball.y*0.28, -10, 10))
    if player_id == 2:
        offset = -10 if ours else -14 if theirs else -11
        return Point(_clamp(ball.x+offset, -20, 30), _clamp(ball.y*0.38, -12, 12))
    side = -1 if player_id == 3 else 1
    # With our possession the forward runs a full pass ahead of the ball instead
    # of shadowing it, so a shooting position exists before the ball arrives.
    offset = 26 if ours else -7 if theirs else 5
    return Point(_clamp(ball.x+offset, -8, 46),
                 _clamp(side*14+ball.y*0.22, -24 if side < 0 else 8,
                        -8 if side < 0 else 24))


def _lateral_offset(point: Point, start: Point, end: Point) -> float:
    dx, dy = end.x-start.x, end.y-start.y
    length_squared = max(0.001, dx*dx+dy*dy)
    projection = _clamp(((point.x-start.x)*dx+(point.y-start.y)*dy)/length_squared, 0.0, 1.0)
    return point.distance_to(Point(start.x+projection*dx, start.y+projection*dy))


def _shot_geometry(perception: Perception, origin: Point) -> tuple[float, float, list[str], list[int], dict[str, float]]:
    """Rank the three aim points; the keeper is a lateral race, not a blocker."""
    a1 = math.atan2(-GOAL_HALF_WIDTH-origin.y, GOAL_X-origin.x)
    a2 = math.atan2(GOAL_HALF_WIDTH-origin.y, GOAL_X-origin.x)
    keeper = perception.opponents.get(KEEPER_ID)
    visible, all_blockers, keeper_offsets = [], set(), {}
    for name, target_y in (("BL", -3.05), ("CENTER", 0.0), ("TR", 3.05)):
        target = Point(GOAL_X, target_y)
        line = perception.pass_line(origin, target, speed=SHOT_SPEED,
                                    ignore_ids=frozenset({KEEPER_ID}))
        all_blockers.update(line.blockers)
        keeper_offsets[name] = (_lateral_offset(keeper.position, origin, target)
                                if keeper else 99.0)
        if not line.blockers:
            visible.append(name)
    visible.sort(key=lambda name: -keeper_offsets[name])
    return (origin.distance_to(Point(GOAL_X, 0)), abs(math.degrees(a2-a1)),
            visible, sorted(all_blockers), keeper_offsets)


def best_shot_aim(perception: Perception) -> str | None:
    """Aim point with a clear corridor and the largest gap from the keeper."""
    _, _, visible, _, _ = _shot_geometry(perception, perception.self_player.position)
    return visible[0] if visible else None


def pass_options(perception: Perception, origin: Point | None = None) -> list[tuple[int, PassLine, float]]:
    """Every teammate line from the ball owner as (player_id, line, progression)."""
    start = origin or perception.self_player.position
    options = []
    for pid, mate in sorted(perception.teammates.items()):
        if pid == perception.player_id:
            continue
        line = perception.pass_line(start, mate.position)
        if line.distance < MINIMUM_PASS_DISTANCE:
            continue
        options.append((pid, line, mate.position.x-start.x))
    return options


def best_pass_target(perception: Perception) -> int | None:
    """Open line with the largest forward progression; risky lines only if none."""
    options = pass_options(perception)
    if not options:
        return None
    open_options = [item for item in options if item[1].open]
    pool = open_options or options
    return max(pool, key=lambda item: (item[2], item[1].margin))[0]


def allowed_commands(perception: Perception) -> tuple[str, ...]:
    team_rank, _ = responsibility(perception)
    primary = team_rank[0][1]
    anchor_distance = perception.self_player.position.distance_to(
        dynamic_anchor(perception, perception.player_id))
    base = ["MOVE_TO"]
    if anchor_distance <= 1.5 and not perception.owns_ball and perception.player_id != primary:
        base += ["IDLE"]
    if perception.owns_ball:
        if perception.player_id == 0:
            base += ["GK_DISTRIBUTE", "CLEAR"]
        else:
            base += ["PASS", "DRIBBLE", "CLEAR"]
            shot_distance, _, visible, _, _ = _shot_geometry(perception, perception.self_player.position)
            if shot_distance <= SHOT_RANGE and visible:
                base += ["SHOOT"]
    elif perception.player_id == primary:
        if perception.possession_team is None:
            base += ["INTERCEPT"]
        elif perception.possession_team != perception.team_id:
            base += ["PRESS_BALL", "INTERCEPT"]
            if perception.distance_to_ball() <= 2.2:
                base += ["SLIDE_TACKLE"]
    elif (perception.possession_team is not None and
          perception.possession_team != perception.team_id):
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
    if command_type == "PASS":
        receiver = perception.teammates.get(int(target_player_id))
        if receiver is None:
            raise ValueError("адресат передачи отсутствует на поле")
        origin = perception.self_player.position
        if origin.distance_to(receiver.position) < MINIMUM_PASS_DISTANCE:
            raise ValueError("адресат передачи ближе минимальной дистанции паса")
        progression = receiver.position.x-origin.x
        forward = [item for item in pass_options(perception) if item[1].open and item[2] >= 3.0]
        if progression < 0 and forward:
            raise ValueError(
                "передача назад запрещена: есть открытая линия к №"
                f"{max(forward, key=lambda item: item[2])[0]} с продвижением вперёд")
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
            1: (-45, -12, -14, 14), 2: (-25, 35, -18, 18),
            3: (-10, 50, -26, -5), 4: (-10, 50, 5, 26),
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
        distance, _, visible, _, _ = _shot_geometry(perception, perception.self_player.position)
        if distance > SHOT_RANGE or not visible:
            raise ValueError("SHOOT недоступен: слишком далеко или нет открытого направления створа")


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
        too_close = " СЛИШКОМ БЛИЗКО" if line.distance < MINIMUM_PASS_DISTANCE else ""
        lines.append(f"- к №{pid}: {'ОТКРЫТА' if line.open else 'РИСК'}{too_close}; {line.distance:.1f} м/{line.ball_time:.2f} с; "
                     f"перехватчик {line.nearest_interceptor if line.nearest_interceptor is not None else 'нет'}, "
                     f"запас {line.margin:.2f} с; давление {pressure:.1f} м; продвижение {mate.position.x-origin.x:+.1f}; "
                     f"блокируют {list(line.blockers) or 'нет'}.")
    if perception.owns_ball:
        options = pass_options(perception)
        best = best_pass_target(perception)
        forward = [item for item in options if item[1].open and item[2] >= 3.0]
        if best is None:
            lines.append("ЛУЧШАЯ ПЕРЕДАЧА: адресатов дальше "
                         f"{MINIMUM_PASS_DISTANCE:.1f} м нет; PASS будет отклонён, используй DRIBBLE или SHOOT.")
        else:
            progression = dict((pid, gain) for pid, _, gain in options)[best]
            lines.append(f"ЛУЧШАЯ ПЕРЕДАЧА: №{best} с продвижением {progression:+.1f} м.")
        if forward:
            lines.append("ПЕРЕДАЧА НАЗАД ЗАПРЕЩЕНА: есть открытая линия вперёд к №"
                         + ", №".join(str(item[0]) for item in sorted(forward, key=lambda item: -item[2])) + ".")
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
    goal_distance, goal_angle, visible_aims, shot_blockers, keeper_offsets = _shot_geometry(
        perception, perception.self_player.position)
    keeper = perception.opponents[KEEPER_ID]
    aim_text = ", ".join(f"{name} (вратарь в {keeper_offsets[name]:.1f} м от линии)"
                         for name in visible_aims) or "нет"
    lines.append(f"Удар от тебя: до ворот {goal_distance:.1f} м; угол {goal_angle:.1f}°; "
                 f"открытые направления {aim_text}; блокируют полевые {shot_blockers or 'нет'}; "
                 f"вратарь ({keeper.position.x:.1f},{keeper.position.y:.1f}).")
    lines.append(f"Вратарь НЕ считается блокирующим телом: он смещается максимум на "
                 f"{KEEPER_LATERAL_REACH:.1f} м вбок. Направление с наибольшим отходом вратаря от линии — "
                 f"{visible_aims[0] if visible_aims else 'недоступно'}. "
                 f"Удар доступен с дистанции до {SHOT_RANGE:.0f} м.")
    lines.append("ДОСТУПНЫЕ КОМАНДЫ: " + ", ".join(allowed_commands(perception)) + ".")
    if not is_primary and perception.possession_team != perception.team_id:
        lines.append(f"ОГРАНИЧЕНИЕ MOVE_TO БЕЗ МЯЧА: цель должна быть не дальше 8 м от динамической точки ({anchor.x:.1f},{anchor.y:.1f}).")
    if perception.player_id == 0:
        lines.append("ОГРАНИЧЕНИЕ ВРАТАРЯ: MOVE_TO только в радиусе 6 м от динамической точки створа.")
    lines.append("Выбери одну доступную команду. target_x/target_y — в координатах атаки; транспорт зеркалит away.")
    return "\n".join(lines)
