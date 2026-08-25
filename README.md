# AWS Nova Football Workshop

5v5 workshop: каталог независимых команд из пяти Amazon Nova Micro агентов,
один конфиг симуляции и live/replay UI с точными 60 Hz кадрами. `nova-baseline`
служит примером, а новые команды автоматически появляются в выборе матча.

## Структура

- `teams/nova-baseline/` — неизменяемый пример полноценной команды.
- `teams/<team-id>/` — самостоятельные стратегии, роли и расчёты геометрии команд.
- `teams/<team-id>/shared/commands.py` — локальный строгий Pydantic-контракт решения.
- `arena/arena.yaml` — все параметры физики и шесть стандартных стартовых схем.
- `tools/simulator.py` — детерминированная физика 60 Hz.
- `tools/live_match_server.py` — Nova vs Nova в реальном времени и запись матчей.
- `viewer/` — live canvas и проигрыватель новых записей.
- `deploy/afc-live.service` — systemd unit для сервера.

Генерируемые матчи и счётчики квот пишутся в `var/` и не являются частью
репозитория.

## Локальный запуск владельца AWS

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
make check
make live
```

Откройте `http://127.0.0.1:8300/`. Для прямого Nova-вызова нужны AWS credentials
с доступом к Bedrock в `us-east-1`. Backend всех команд фиксирован на
`us.amazon.nova-micro-v1:0`.

Подробнее о настройке ролей: [`teams/nova-baseline/README.md`](teams/nova-baseline/README.md).

## Работа друзей без AWS credentials

Друг клонирует репозиторий и полностью локально запускает симулятор, геометрию,
Pydantic-валидацию, пять ролей и viewer. На ваш сервер через Cloudflare уходит
только системный промпт конкретного игрока и текст его текущего наблюдения.
Сервер жёстко использует `us.amazon.nova-micro-v1:0` и возвращает только
`afc-nova-decision/v1`. Клиент не может выбрать другую модель, передать Python-код
или получить AWS credentials.

```text
локальные teams/* + геометрия + 60 Hz симулятор
                   |
                   | HTTPS + персональный invite-token
                   v
https://afc.ivanlukov.com/api/inference
                   |
                   v
          Nova Micro с AWS сервера
```

### 1. Владелец создаёт персональный invite

На сервере из корня репозитория:

```bash
make create-invite NAME=alice
```

Команда один раз напечатает `AFC_GATEWAY_TOKEN=...` и сохранит конфигурацию в
`~/.config/tiki-taka-sim/gateway-tokens.json` с правами `0600`. Передайте другу
только напечатанный invite-token. AWS key, Cloudflare Tunnel token и содержимое
серверного credentials-файла передавать нельзя.

Значения по умолчанию для одного invite:

- 3000 Nova-вызовов в UTC-сутки — пять полных матчей по 600 решений;
- 600 запросов в минуту;
- не более 10 одновременных запросов.

Свои лимиты можно задать при создании:

```bash
.venv-afc/bin/python tools/create_gateway_invite.py alice \
  --daily-limit 6000 --rpm 600 --concurrency 10 --replace
```

`--replace` немедленно ротирует старый токен. Сервер перечитывает файл
автоматически, поэтому restart не требуется.

### 2. Друг настраивает клон

```bash
git clone https://github.com/lukivan8/tiki-taka-sim.git
cd tiki-taka-sim
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

В `.env` нужно заменить только токен:

```dotenv
AFC_NOVA_GATEWAY_URL=https://afc.ivanlukov.com/api/inference
AFC_GATEWAY_TOKEN=полученный-персональный-токен
AFC_GATEWAY_TIMEOUT_SECONDS=90
```

Затем загрузить переменные и запустить:

```bash
set -a
source .env
set +a

make check
make live
```

Открыть `http://127.0.0.1:8300/`. Все изменения в `teams/` остаются на компьютере
друга; AWS-вызовы выполняются сервером. В decision log поле `decisionSource`
будет равно `nova-gateway`, что позволяет проверить, что локальные AWS credentials
не использовались.

В поле `Invite token` локальной страницы нужно вставить тот же
`AFC_GATEWAY_TOKEN`. Локальный сервер использует его только для разрешения старта
матча; удалённый сервер независимо применяет настоящую квоту к каждому вызову.

Полный путь десяти игроков можно проверить одним коротким настоящим интервалом:

```bash
make verify-remote
```

Команда получает десять решений через публичный gateway и не сохраняет тестовый
replay.

### 3. Создание нескольких команд

Новая команда создаётся из baseline одной командой:

```bash
make create-team NAME=alice-press DISPLAY_NAME="Alice Press" FORMATION=1-2-1
```

Можно клонировать уже существующую экспериментальную команду:

```bash
make create-team NAME=alice-v2 DISPLAY_NAME="Alice v2" SOURCE=alice-press FORMATION=3-1
```

Генератор создаёт `teams/alice-press/`, меняет `teamId`, отображаемое имя,
`formationPreset` и entrypoint. Если `FORMATION` не указан, схема наследуется от
исходной команды. Регистрировать команду в Python или JavaScript не нужно: сервер
сканирует `teams/*/team.yaml`. После создания команды обновите страницу; она
появится в обоих выпадающих списках. Изменения стратегии применяются к следующему
матчу без restart сервера. Любую команду можно запустить против другой или самой себя.

Доступны шесть схем для четырёх полевых игроков; вратарь №0 всегда расположен
отдельно у своих ворот:

| `formationPreset` | Структура |
|---|---|
| `1-1-2` | защитник, связующий и два форварда |
| `1-2-1` | ромб: защитник, два полузащитника и форвард |
| `2-1-1` | два защитника, связующий и форвард |
| `2-2-0` | квадрат без закреплённого форварда |
| `3-1` | низкий блок из трёх и один форвард |
| `1-3` | один защитник и высокая линия из трёх |

Схема принадлежит команде: live-страница показывает её без возможности изменить,
а `POST /api/matches` не принимает `homeFormation`/`awayFormation`. Для ручной
смены отредактируйте `formationPreset` в `teams/<team-id>/team.yaml`.
Координаты берутся из arena и автоматически включаются в системные промпты игроков.

Требования к команде:

- имя папки и `teamId` совпадают и являются lowercase slug;
- `backend` всегда равен `nova-micro`;
- `formationPreset` содержит одну из шести стандартных схем;
- в папке присутствуют `team.yaml`, `strategy.yaml`, `strategy.md`, `live_team.py`
  и пять каталогов игроков;
- каждая команда загружается в отдельном Python package, поэтому её `shared/`,
  промпты и геометрия не смешиваются с другими командами.

### 4. Что друг может менять

- `teams/<team-id>/strategy.md` и `strategy.yaml`;
- `teams/<team-id>/players/*/role.md`;
- `teams/<team-id>/players/*/situations.md`;
- `teams/<team-id>/players/*/player.yaml`;
- расчёты в `teams/<team-id>/shared/perception.py`;
- локальную Pydantic/семантическую проверку команд.

После изменения файлов достаточно начать новый матч; уже запущенный матч продолжит
работать со своей загруженной версией команды.

## Публичный сервер и защита расходов

`POST /api/inference`, `POST /api/matches` и остановка матча требуют
`Authorization: Bearer <invite-token>`. На публичной странице invite вводится в
поле `Invite token` и хранится только в `sessionStorage` вкладки. Просмотр сайта,
каталога и уже созданного replay не расходует Nova-вызовы.

Cloudflare Tunnel публикует только origin `127.0.0.1:8300`; приложение независимо
проверяет персональный invite и ведёт постоянный суточный счётчик в SQLite. При
желании поверх этого можно включить Cloudflare Access и заполнить
`CF_ACCESS_CLIENT_ID`/`CF_ACCESS_CLIENT_SECRET` в локальном `.env`.
