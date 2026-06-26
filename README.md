# TG Manager

Единый интерфейс для управления несколькими Telegram-аккаунтами с AI-ассистентом.

## Что умеет

- **Мультиаккаунт** — добавляй 20–30 аккаунтов, переключайся одним кликом
- **Диалоги** — видишь все чаты выбранного аккаунта в одном месте  
- **Отправка** — пишешь и отправляешь сам, AI только предлагает варианты
- **AI-ассистент** — генерирует 3 варианта ответа по контексту переписки
- **Улучшение текста** — скажи AI "сделай короче" или "формальнее"

## Быстрый старт

### Требования
- Python 3.11+
- Node.js 18+
- Telegram API credentials: [my.telegram.org](https://my.telegram.org) → API development tools

### Бэкенд

```bash
cd backend
cp ../.env.example .env
# Заполни .env (TELEGRAM_API_ID, TELEGRAM_API_HASH, ANTHROPIC_API_KEY)

pip install -e .
uvicorn src.main:app --reload
# → http://localhost:8000
# → Swagger: http://localhost:8000/docs
```

### Фронтенд

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

## Добавить аккаунт

1. Нажми **+** в левой панели
2. Введи название и номер телефона
3. Получи код в Telegram, введи его
4. Аккаунт появится в списке

## Структура проекта

```
backend/src/
  main.py              FastAPI приложение
  config.py            Настройки из .env
  database.py          SQLite (SQLAlchemy async)
  models.py            Модель Account
  session_manager.py   Telethon сессии для каждого аккаунта
  api/
    accounts.py        CRUD аккаунтов + auth flow
    messages.py        Диалоги и сообщения
    ai.py              AI suggestions
  services/
    ai_service.py      Claude API интеграция

frontend/src/
  App.tsx              Корневой компонент
  api/client.ts        Typed API клиент
  components/
    AccountSidebar.tsx Список аккаунтов
    ChatView.tsx        Диалоги + чат
    AIPanel.tsx         AI-панель справа
```

## API

После запуска бэкенда: **http://localhost:8000/docs**

Ключевые эндпоинты:
- `POST /api/accounts/auth/start` — отправить код на телефон
- `POST /api/accounts/auth/confirm` — подтвердить код, сохранить сессию
- `GET  /api/accounts/{id}/dialogs` — список диалогов аккаунта
- `GET  /api/accounts/{id}/dialogs/{chat_id}/messages` — история чата
- `POST /api/accounts/{id}/dialogs/{chat_id}/send` — отправить сообщение
- `POST /api/ai/suggest` — 3 варианта ответа от AI
- `POST /api/ai/improve` — улучшить текст по инструкции
