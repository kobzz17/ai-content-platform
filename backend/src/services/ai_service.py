import anthropic
from src.config import settings

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
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


async def generate_bot_reply(conversation: list[dict], persona: str) -> str:
    """Generate a single natural reply for a bot persona in a group chat."""
    history_text = "\n".join(f"{m['sender']}: {m['text']}" for m in conversation[-10:])
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=200,
        system=(
            f"Ты — {persona}. Ты участник группового чата в Telegram. "
            "Напиши ОДНО короткое, естественное сообщение по-русски. "
            "Будь разговорчивым, живым. Без приветствий и подписей. "
            "Максимум 1-2 предложения."
        ),
        messages=[{
            "role": "user",
            "content": f"Разговор:\n{history_text}\n\nНапиши свой ответ:"
        }],
    )
    return message.content[0].text.strip()


async def generate_new_topic(persona: str) -> str:
    """Generate a new conversation topic to post proactively."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=150,
        system=(
            f"Ты — {persona}. Ты хочешь начать новую тему в групповом чате Telegram. "
            "Напиши короткое, интересное сообщение по-русски — вопрос или наблюдение. "
            "Будь непринуждённым. Максимум 2 предложения."
        ),
        messages=[{
            "role": "user",
            "content": "Напиши что-нибудь, чтобы начать разговор:"
        }],
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
