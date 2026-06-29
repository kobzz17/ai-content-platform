# AI Content Platform — контекст проекта

## Что это
AI-платформа для управления Telegram-аккаунтами: мониторинг каналов, автоматические реакции/комментарии через Claude AI, управление сессиями, массовый импорт аккаунтов.

## Запуск

```bash
# Бэкенд (Python 3.14, FastAPI)
cd backend
.venv/bin/python -m uvicorn src.main:app --reload --port 8000

# Фронтенд (React + Vite)
cd frontend
npm run dev        # http://localhost:5173

# Получить session string для нового аккаунта
cd backend && .venv/bin/python get_session.py +79001234567
```

## Переменные окружения (`backend/.env`)
```
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
ANTHROPIC_API_KEY=...
DATABASE_URL=sqlite+aiosqlite:///./tg_manager.db
```

## Архитектура

```
backend/src/
  main.py              — FastAPI app, lifespan (запуск задач при старте)
  models.py            — SQLAlchemy модели: Account, BotTask, ChannelTask, ChannelLog
  database.py          — движок БД + лёгкие миграции в init_db()
  session_manager.py   — пул Telethon клиентов (один на аккаунт)
  config.py            — настройки через pydantic-settings + .env
  api/
    accounts.py        — CRUD аккаунтов, импорт batch/tdata
    channels.py        — задачи мониторинга каналов
    automation.py      — задачи бот-автоматизации в чатах
    messages.py        — чтение диалогов и отправка сообщений
    ai.py              — suggest/improve через Claude
  services/
    channel_service.py — asyncio-цикл мониторинга каналов (реакции + комментарии)
    bot_service.py     — asyncio-цикл автоответчика в чатах
    ai_service.py      — обёртка над Anthropic API
    tdata_reader.py    — парсер Telegram Desktop tdata (без opentele, AES-IGE + MTProto v1)

frontend/src/
  App.tsx              — корневой компонент, модалки добавления/импорта аккаунтов
  api/client.ts        — все API-вызовы к бэкенду
  components/
    AccountSidebar.tsx — список аккаунтов
    AutomationView.tsx — вкладка автоматизации (каналы + чаты)
    ChatView.tsx        — просмотр диалогов
    AIPanel.tsx        — AI-подсказки к сообщениям
```

## Ключевые модели БД

- **Account** — аккаунт Telegram (session_string, phone, status, proxy)
- **ChannelTask** — задача мониторинга канала (keywords, probabilities, session_mode)
- **ChannelSubscription** — подписка задачи на конкретный канал
- **ChannelLog** — лог действий (reacted/commented/subscribed/error)
- **BotTask** — задача автоответчика в чате
- **BotLog** — лог действий бота

## Режимы сессии (SessionMode)
`always` | `random` (офлайн 1–6ч случайно) | `work_hours` (9–20 UTC) | `evening` (18–23 UTC)

## Импорт аккаунтов
- **Session strings**: POST `/api/accounts/import-batch` — JSON или TSV файл
- **tdata (Telegram Desktop)**: POST `/api/accounts/import-tdata` — ZIP-архив с папками tdata

## Реакции в каналах
Эмодзи без вариационных селекторов: `["👍", "❤", "🔥", "👏", "🤔", "🎉", "😮"]`
Telegram отклоняет `❤️` (с U+FE0F) — использовать только голые codepoints.

## Важные ограничения
- Лимит загрузки файлов: 50 МБ
- Параметр `limit` в GET-эндпоинтах: максимум 500
- Auth-сессии истекают через 10 минут (`_AUTH_TIMEOUT_SEC`)
- `tdata_reader.py` работает только с СОВРЕМЕННЫМ форматом TDesktop (4.x+), CreateLocalKey, не Legacy

## Частые команды
```bash
# Проверить статус задач в БД
cd backend && .venv/bin/python -c "
import asyncio
from src.database import async_session_maker
from src.models import ChannelTask
from sqlalchemy import select

async def main():
    async with async_session_maker() as db:
        r = await db.execute(select(ChannelTask))
        for t in r.scalars(): print(t.id, t.status, t.keywords)

asyncio.run(main())"

# Сбросить задачу в running
cd backend && .venv/bin/python -c "
import asyncio
from src.database import async_session_maker
from src.models import ChannelTask, TaskStatus
async def main():
    async with async_session_maker() as db:
        r = await db.execute(__import__('sqlalchemy').select(ChannelTask))
        for t in r.scalars():
            t.status = TaskStatus.running
        await db.commit()
        print('done')
asyncio.run(main())"
```

## GitHub
https://github.com/kobzz17/ai-content-platform
