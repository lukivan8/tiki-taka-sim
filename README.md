# AWS Nova Football Workshop

Минимальный 5v5 baseline: одна команда из пяти изолированных Amazon Nova Micro
агентов, один конфиг симуляции и live/replay UI с точными 60 Hz кадрами.

## Структура

- `team/` — финальная команда. Русские роли и ситуации отделены от английского Python-кода.
- `team/shared/perception.py` — общая геометрия без готового «лучшего действия».
- `team/shared/commands.py` — строгий Pydantic-контракт решения.
- `arena/arena.yaml` — все параметры физики и единственная схема `1-1-1-2`.
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

Откройте `http://127.0.0.1:8300/`. Для Nova нужны AWS credentials с доступом к
Bedrock в `us-east-1`. Модель можно переопределить через `AFC_MODEL_ID`.

Подробнее о настройке ролей: [`team/README.md`](team/README.md).

## Работа друзей без AWS credentials

Друг клонирует репозиторий и полностью локально запускает симулятор, геометрию,
Pydantic-валидацию, пять ролей и viewer. На ваш сервер через Cloudflare уходит
только системный промпт конкретного игрока и текст его текущего наблюдения.
Сервер жёстко использует `us.amazon.nova-micro-v1:0` и возвращает только
`afc-nova-decision/v1`. Клиент не может выбрать другую модель, передать Python-код
или получить AWS credentials.

```text
локальный team/ + геометрия + 60 Hz симулятор
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
git clone <URL-РЕПОЗИТОРИЯ>
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

Открыть `http://127.0.0.1:8300/`. Все изменения в `team/` остаются на компьютере
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

### 3. Что друг может менять

- `team/strategy.md` и `team/strategy.yaml`;
- `team/players/*/role.md`;
- `team/players/*/situations.md`;
- `team/players/*/player.yaml`;
- расчёты в `team/shared/perception.py`;
- локальную Pydantic/семантическую проверку команд.

После изменения файлов достаточно остановить `make live` и запустить его снова.

## Публичный сервер и защита расходов

`POST /api/inference`, `POST /api/matches` и остановка матча требуют
`Authorization: Bearer <invite-token>`. На публичной странице invite вводится в
поле `Invite token` и хранится только в `sessionStorage` вкладки. Просмотр сайта,
каталога и уже созданного replay не расходует Nova-вызовы.

Cloudflare Tunnel публикует только origin `127.0.0.1:8300`; приложение независимо
проверяет персональный invite и ведёт постоянный суточный счётчик в SQLite. При
желании поверх этого можно включить Cloudflare Access и заполнить
`CF_ACCESS_CLIENT_ID`/`CF_ACCESS_CLIENT_SECRET` в локальном `.env`.
