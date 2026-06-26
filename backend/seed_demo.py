"""
Populates the database with demo accounts, bot tasks and logs for presentation.
Run once:
    cd /Users/kobz/ai-content-platform/backend
    .venv/bin/python seed_demo.py
"""
import asyncio
from datetime import datetime, timedelta
import random
from src.database import init_db, async_session_maker
from src.models import Account, AccountStatus, BotTask, BotLog, TaskStatus


ACCOUNTS = [
    dict(label="Алексей К.",    phone="+79001112233", first_name="Алексей",  username="alex_korolev",   avatar_color="#5b8af7", session_string="DEMO"),
    dict(label="Марина С.",     phone="+79009998877", first_name="Марина",   username="marina_sova",    avatar_color="#e85d75", session_string="DEMO"),
    dict(label="Дмитрий Р.",    phone="+79005554433", first_name="Дмитрий",  username="dima_rogov",     avatar_color="#3ec97e", session_string="DEMO"),
]

TASKS = [
    dict(account_idx=0, chat_name="Команда разработки 🔧", chat_id=-1001234567890,
         persona="Опытный разработчик, любит обсуждать технологии и делиться инсайтами",
         reply_probability=75, min_delay=8, max_delay=35, proactive_interval=30,
         status=TaskStatus.running),
    dict(account_idx=1, chat_name="Команда разработки 🔧", chat_id=-1001234567890,
         persona="Аналитик, задаёт точные вопросы, вникает в детали",
         reply_probability=60, min_delay=10, max_delay=45, proactive_interval=None,
         status=TaskStatus.running),
    dict(account_idx=2, chat_name="Маркетинг и продажи 📈", chat_id=-1009876543210,
         persona="Энергичный маркетолог, следит за трендами",
         reply_probability=80, min_delay=5, max_delay=20, proactive_interval=20,
         status=TaskStatus.paused),
]

LOGS = [
    # Команда разработки — последний час
    (0, "topic_posted", "Кстати, кто-нибудь пробовал новый подход к деплою через GitHub Actions? Мы на прошлой неделе перешли — значительно ускорилось."),
    (1, "replied",      "Да, мы тоже переходим. Пока настраиваем, но уже видно что удобнее чем Jenkins был."),
    (0, "replied",      "Согласен, особенно нравится интеграция с PR — сразу видно статус прямо в интерфейсе."),
    (1, "topic_posted", "Вопрос к команде: как вы организуете code review? Есть ли у вас чеклист или всё по ситуации?"),
    (0, "replied",      "У нас есть базовый чеклист, но честно говоря соблюдается процентов на 70. Думаем автоматизировать часть проверок."),
    (1, "replied",      "Линтеры хорошо помогают для автоматизации. SonarQube ещё смотрели?"),
    (0, "replied",      "Смотрели, но для нашего масштаба пока избыточно. Пока ESLint + тесты закрывают основное."),
    # Маркетинг
    (2, "topic_posted", "Интересный кейс увидел: конкурент запустил рассылку через Telegram и за неделю +15% к конверсии. Стоит нам попробовать?"),
    (2, "replied",      "Метрики за прошлую неделю неплохие, органика выросла на 12%. Надо обсудить что двигало рост."),
    (2, "replied",      "Согласна с коллегами. Думаю основной драйвер — посты в понедельник утром, аудитория активнее."),
]


async def main():
    await init_db()
    async with async_session_maker() as db:
        # Check if demo data already exists
        from sqlalchemy import select
        existing = await db.execute(select(Account).where(Account.phone == "+79001112233"))
        if existing.scalar_one_or_none():
            print("⚠️  Demo data already exists, skipping.")
            return

        # Insert accounts
        account_objs = []
        for a in ACCOUNTS:
            obj = Account(
                label=a["label"], phone=a["phone"],
                first_name=a["first_name"], username=a["username"],
                avatar_color=a["avatar_color"], session_string=a["session_string"],
                status=AccountStatus.active, is_active=True,
            )
            db.add(obj)
            account_objs.append(obj)
        await db.flush()

        # Insert tasks
        task_objs = []
        for t in TASKS:
            acc = account_objs[t["account_idx"]]
            last_action = datetime.utcnow() - timedelta(minutes=random.randint(2, 60))
            obj = BotTask(
                account_id=acc.id,
                chat_id=t["chat_id"], chat_name=t["chat_name"],
                persona=t["persona"],
                reply_probability=t["reply_probability"],
                min_delay=t["min_delay"], max_delay=t["max_delay"],
                proactive_interval=t["proactive_interval"],
                status=t["status"],
                last_action_at=last_action,
            )
            db.add(obj)
            task_objs.append(obj)
        await db.flush()

        # Insert logs (newest last so reverse order for created_at)
        base_time = datetime.utcnow() - timedelta(hours=1, minutes=30)
        for i, (task_idx, action, text) in enumerate(LOGS):
            task = task_objs[task_idx]
            created = base_time + timedelta(minutes=i * 9 + random.randint(0, 5))
            db.add(BotLog(
                task_id=task.id, action=action, text=text, created_at=created
            ))

        await db.commit()
        print("✅ Demo data inserted:")
        print(f"   {len(ACCOUNTS)} accounts")
        print(f"   {len(TASKS)} bot tasks")
        print(f"   {len(LOGS)} log entries")


if __name__ == "__main__":
    asyncio.run(main())
