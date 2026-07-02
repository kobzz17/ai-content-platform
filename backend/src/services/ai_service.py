import httpx
import anthropic
from src.config import settings

_client: anthropic.AsyncAnthropic | None = None

_PROXY_URL = "socks5://134.122.1.61:11679"


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        http_client = httpx.AsyncClient(proxy=_PROXY_URL)
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            http_client=http_client,
        )
    return _client


async def suggest_reply(
    conversation_history: list[dict],  # [{"sender": "...", "text": "..."}]
    prompt_hint: str = "",
    tone: str = "friendly",
) -> list[str]:
    """Generate 3 reply suggestions for the given conversation context."""
    history_text = "\n".join(
        f"{m['sender']}: {m['text']}" for m in conversation_history[-10:]
    )

    user_prompt = f"""Conversation so far:
{history_text}

{f"My goal for this reply: {prompt_hint}" if prompt_hint else ""}
Tone: {tone}

Write 3 different reply options. Each should be natural, concise, conversational Russian.
Return exactly 3 options separated by "---", no numbering, no extra text."""

    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=512,
        system="You are a helpful assistant generating Telegram message suggestions. Write in natural Russian unless the conversation is in another language.",
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()
    options = [o.strip() for o in raw.split("---") if o.strip()]
    return options[:3]


_CHAT_STYLE = (
    "Ты пишешь в групповом чате в Телеграм. Правила:\n"
    "• ТОЛЬКО русский язык. Ноль английских слов, даже 'ок' пиши 'ок' или 'окей'.\n"
    "• ОЧЕНЬ коротко — 1-2 предложения, часто одно. Иногда просто смайл или одно слово.\n"
    "• Строчные буквы, без точки в конце, опечатки иногда — это норма.\n"
    "• Живые реакции: 'ахахах', 'да ладно', 'ну и ну', 'чё серьёзно', 'ну ты выдал', 'не верю', 'эм', 'блин'.\n"
    "• НЕ используй слова: 'безусловно', 'действительно', 'стоит отметить', 'интересно', 'согласен'.\n"
    "• НЕ начинай с имени собеседника.\n"
    "• Иногда мысль обрывается на полуслове... или ставишь вопрос вместо утверждения."
)


async def generate_bot_reply(
    conversation: list[dict],
    persona: str,
    trigger_text: str = "",
    trigger_sender: str = "",
) -> str:
    """Reply to a specific message in the group chat, building on that thread."""
    history_text = "\n".join(f"{m['sender']}: {m['text']}" for m in conversation[-10:])

    if trigger_text:
        focus = (
            f"\nТы реагируешь конкретно на это сообщение от {trigger_sender}:\n"
            f"«{trigger_text}»\n"
            "Прими его позицию, возрази, добавь своё — но не просто 'согласен' или 'интересно'."
        )
    else:
        focus = "\nОтветь на последнее сообщение в разговоре."

    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=130,
        system=f"{persona}\n\n{_CHAT_STYLE}",
        messages=[{
            "role": "user",
            "content": f"Контекст чата:\n{history_text}{focus}"
        }],
    )
    return message.content[0].text.strip()


async def generate_new_topic(persona: str) -> str:
    """Throw something into the chat unprompted — news, observation, question from daily life."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=110,
        system=(
            f"{persona}\n\n{_CHAT_STYLE}\n\n"
            "Ты сам(а) что-то закидываешь в чат — как будто только что увидел новость, "
            "что-то случилось, или просто мысль в голове. Не объявление, а живая реплика."
        ),
        messages=[{
            "role": "user",
            "content": "Напиши что-нибудь, чтобы начать разговор:"
        }],
    )
    return message.content[0].text.strip()


async def generate_channel_comment(post_text: str, persona: str) -> str:
    """Generate a natural comment for a Telegram channel post."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=150,
        system=(
            f"Ты — {persona}. Оставляешь комментарий под постом в Telegram-канале. "
            "Напиши ОДИН короткий, живой комментарий по-русски. "
            "Можешь согласиться, задать вопрос или добавить своё мнение. "
            "Без приветствий. Максимум 2 предложения."
        ),
        messages=[{"role": "user", "content": f"Пост:\n{post_text[:500]}\n\nТвой комментарий:"}],
    )
    return message.content[0].text.strip()


async def generate_group_reply(conversation: list[dict], persona: str, replying_to: str) -> str:
    """Reply to a specific person in a group chat."""
    history_text = "\n".join(f"{m['sender']}: {m['text']}" for m in conversation[-10:])
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=180,
        system=(
            f"Ты — {persona}. Ты участник группового чата в Telegram. "
            f"Ты отвечаешь на сообщение от {replying_to}. "
            "Напиши ОДНО короткое, живое сообщение по-русски. "
            "Можно согласиться, поспорить, задать вопрос или добавить что-то своё. "
            "Без приветствий. 1-2 предложения. Разговорный стиль."
        ),
        messages=[{"role": "user", "content": f"Разговор:\n{history_text}\n\nТвой ответ {replying_to}:"}],
    )
    return message.content[0].text.strip()


async def generate_news_share(news_text: str, channel: str, persona: str) -> str:
    """Generate a short commentary when sharing news from a channel."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=150,
        system=(
            f"Ты — {persona}. Ты делишься новостью из Telegram-канала с друзьями в групповом чате. "
            "Напиши короткий живой комментарий по-русски — своё мнение или реакцию на новость. "
            "1-2 предложения. Без заголовков. Разговорный стиль."
        ),
        messages=[{"role": "user", "content": f"Новость из {channel}:\n{news_text}\n\nТвой комментарий:"}],
    )
    return message.content[0].text.strip()


async def improve_text(text: str, instruction: str) -> str:
    """Rewrite a draft message according to an instruction (shorter, more formal, etc.)."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=256,
        system="You rewrite messages as instructed. Return only the rewritten text.",
        messages=[{"role": "user", "content": f"Message: {text}\n\nInstruction: {instruction}"}],
    )
    return message.content[0].text.strip()
