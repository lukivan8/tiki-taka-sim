"""Build Russian model prompts from English-keyed team and player configuration."""
from __future__ import annotations

from pathlib import Path

import yaml

from .perception import build_perception, describe


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_player(player_id: int) -> tuple[dict, str, str]:
    strategy = load_yaml(ROOT / "strategy.yaml")
    relative = strategy["players"][player_id]
    folder = ROOT / relative
    config = load_yaml(folder / "player.yaml")
    role = (folder / "role.md").read_text(encoding="utf-8").strip()
    situations = (folder / "situations.md").read_text(encoding="utf-8").strip()
    return config, role, situations


def build_system_prompt(player_id: int) -> str:
    strategy = load_yaml(ROOT / "strategy.yaml")
    team_strategy = (ROOT / "strategy.md").read_text(encoding="utf-8").strip()
    config, role, situations = load_player(player_id)
    focus = config["strategic_focus"]
    priorities = "\n".join(
        f"{index}. {item['action']}: {item['when']}. Смысл: {item['purpose']}."
        for index, item in enumerate(focus["priorities"], 1)
    )
    formation = ", ".join(
        f"№{pid} ({point[0]:.0f}, {point[1]:.0f})"
        for pid, point in strategy["formation"]["points"].items()
    )
    return f"""Ты — автономный агент команды «{strategy['name']}» и управляешь ТОЛЬКО игроком №{player_id}.
Все пять агентов получают один снимок мира, но не командуют друг другом. Координация возникает из общей геометрии, ролей и наблюдаемого состояния.
Ты stateless: не предполагай, что партнёр помнит прошлый тик, продолжит последовательность или выполнит ожидаемое действие.
Текущее персональное наблюдение всегда важнее общих примеров ниже. В нём уже рассчитаны твоя ответственность, доступные команды и динамическая точка восстановления.

## Стратегия команды
{team_strategy}

## Твоя роль
{role}

Стратегический фокус:
- Позиция: {focus['position']}.
- Рабочая зона: {focus['playing_zone']}.
- Главная задача: {focus['main_objective']}.
- Без мяча: {focus['without_ball']}.
- После потери: {focus['after_turnover']}.

## Приоритеты роли
{priorities}

## Тактические ситуации роли
Это независимые примеры распознавания текущего состояния, а не комбинации из нескольких шагов. Используй только тот пример, факты которого действительно наблюдаешь сейчас.
{situations}

Стартовая схема {strategy['formation']['name']}: {formation}.
Выбери ровно одну команду только за №{player_id}. Не придумывай действия партнёрам. Объяснение rationale — одна короткая строка на русском для реплея.
Выбирай только из списка «ДОСТУПНЫЕ КОМАНДЫ» текущего наблюдения. Если ты не первичный игрок мяча, запрещено присоединяться к перехвату: восстанавливай ролевую точку, сохраняй ширину или страхуй.
Не называй зону свободной без подтверждения расстоянием соперника и линией владельца. Не используй MOVE_TO в текущую точку: цель должна исправлять структуру или создавать измеримый новый угол.
IDLE допустим только если он присутствует в списке доступных команд. Если MOVE_TO доступен, но IDLE отсутствует, двигайся к указанной динамической точке восстановления или к подтверждённой открытой ролевой зоне.

## Обязательные параметры команды
- MOVE_TO и DRIBBLE: обязательно target_x, target_y и sprint.
- PASS: обязательно target_player_id и type (GROUND, AERIAL, THROUGH или NORMAL).
- SHOOT: обязательно aim_location и power.
- PRESS_BALL: обязательно intensity. MARK: target_player_id и tightness.
- INTERCEPT: обязательно aggressive. SLIDE_TACKLE: target_player_id, sprint и distance.
- GK_DISTRIBUTE: обязательно target_player_id и method.
- CLEAR и IDLE не имеют параметров. Никогда не выбирай команду без всех её обязательных параметров.
"""


def build_observation(player_id: int, payload: dict) -> str:
    config, _, _ = load_player(player_id)
    perception = build_perception(payload)
    return "Текущее наблюдение. Это факты, а не подсказка лучшего действия:\n" + describe(perception, config)
