import enum
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Boolean, Integer, BigInteger, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class AccountStatus(str, enum.Enum):
    active = "active"
    limited = "limited"       # Telegram put a temporary limit
    needs_reauth = "needs_reauth"
    disabled = "disabled"


class TaskStatus(str, enum.Enum):
    running = "running"
    paused = "paused"
    stopped = "stopped"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(255))          # friendly name you give it
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    session_string: Mapped[str] = mapped_column(Text)        # encrypted Telethon session
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_color: Mapped[str] = mapped_column(String(7), default="#5b8af7")  # UI color
    status: Mapped[AccountStatus] = mapped_column(SAEnum(AccountStatus), default=AccountStatus.active)
    proxy: Mapped[str | None] = mapped_column(String(255), nullable=True)   # socks5://host:port
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BotTask(Base):
    __tablename__ = "bot_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), default=TaskStatus.running)
    persona: Mapped[str] = mapped_column(Text, default="Дружелюбный человек, любящий поддерживать разговор")
    reply_probability: Mapped[int] = mapped_column(Integer, default=70)
    min_delay: Mapped[int] = mapped_column(Integer, default=5)
    max_delay: Mapped[int] = mapped_column(Integer, default=30)
    proactive_interval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BotLog(Base):
    __tablename__ = "bot_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("bot_tasks.id"))
    action: Mapped[str] = mapped_column(String(50))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
