import random
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


_CHAT_STYLE = (
    "Ты пишешь в групповом чате в Телеграм. СТРОГИЕ правила:\n"
    "• ТОЛЬКО русский язык и кириллица. Ноль других алфавитов. Иностранные слова транслитерируй ('контент', 'окей', 'лайк').\n"
    "• Начинай сообщение с ЗАГЛАВНОЙ буквы — как обычный человек.\n"
    "• ОЧЕНЬ коротко — 1-2 предложения. Иногда одно слово или просто эмодзи.\n"
    "• Без точки в конце. Опечатки изредка — это норм.\n"
    "• АНАЛИЗИРУЙ контекст и тон сообщения:\n"
    "  — Если это ШУТКА или что-то смешное → реагируй смехом: 'Ахахах', 'Умираю 💀', 'Это шедевр', 'Стоп ну это топ', 'АААХА'\n"
    "  — Если удивительная новость → 'Да ладно', 'Серьёзно?', 'Ничего себе', 'Вот это поворот'\n"
    "  — Если жалоба/нытьё → 'Блин, да', 'Знакомо', 'Это боль', 'Сочувствую'\n"
    "  — Если вопрос → дай конкретный короткий ответ своими словами\n"
    "  — Если обычная новость/история → добавь своё мнение или уточни что-то\n"
    "• НЕ используй: 'безусловно', 'действительно', 'стоит отметить', 'согласен', 'интересно'.\n"
    "• НЕ начинай с имени собеседника."
)


_OPINION_STANCES = {
    "conservative": (
        "Твоя позиция: склоняйся к более осторожному/меньшему/бюджетному варианту. "
        "Аргументируй коротко — практичность, не переплачивать, хватит для задачи."
    ),
    "bold": (
        "Твоя позиция: склоняйся к более смелому/большему/продвинутому варианту. "
        "Аргументируй коротко — раз уж брать, то нормальное, потом не пожалеешь."
    ),
    "neutral": (
        "Твоя позиция: дай взвешенный ответ — зависит от задачи/бюджета/ситуации. "
        "Уточни что именно важно учесть, 1-2 конкретных критерия."
    ),
}


async def generate_bot_reply(
    conversation: list[dict],
    persona: str,
    trigger_text: str = "",
    trigger_sender: str = "",
    is_question: bool = False,
    opinion_stance: str | None = None,
    known_friends: list[str] | None = None,
    own_recent: list[str] | None = None,
) -> str:
    """Reply to a specific message in the group chat, building on that thread."""
    history_text = "\n".join(f"{m['sender']}: {m['text']}" for m in conversation[-10:])

    if trigger_text:
        if is_question:
            stance_hint = f"\n{_OPINION_STANCES[opinion_stance]}" if opinion_stance else ""
            focus = (
                f"\n{trigger_sender} задал(а) вопрос:\n«{trigger_text}»\n"
                f"Дай конкретный живой ответ — своё мнение, совет или опыт.{stance_hint} "
                f"Можешь обратиться к {trigger_sender} по имени."
            )
        else:
            # 40% chance to address by name
            name_hint = f"Можешь упомянуть имя {trigger_sender}. " if random.randint(1, 100) <= 40 else ""
            focus = (
                f"\nТы реагируешь на сообщение от {trigger_sender}:\n"
                f"«{trigger_text}»\n"
                f"{name_hint}"
                "Сначала пойми тон: если это шутка/мем/нелепость — реагируй смехом или коротким восклицанием. "
                "Если обычный текст — прими позицию, возрази или добавь своё мнение."
            )
    else:
        focus = "\nОтветь на последнее сообщение в разговоре."

    friends_ctx = ""
    if known_friends:
        friends_ctx = f"\nЗнакомые в этом чате: {', '.join(known_friends[:5])}. Они свои — можешь обращаться к ним по имени."

    recent_ctx = ""
    if own_recent:
        recent_ctx = f"\nТы уже писал(а): «{' / '.join(own_recent[-3:])}». Не повторяй эти мысли дословно."

    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=130,
        system=f"{persona}\n\n{_CHAT_STYLE}",
        messages=[{
            "role": "user",
            "content": f"Контекст чата:\n{history_text}{focus}{friends_ctx}{recent_ctx}"
        }],
    )
    result = message.content[0].text.strip()
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


_TOPIC_PROMPTS = {
    "personal": (
        "Расскажи что-то личное из своего дня или жизни — маленькую историю, казус, "
        "что случилось по дороге, на работе, дома, в магазине. Не придумывай ничего пафосного, "
        "просто живая мелочь из жизни. 1-2 предложения."
    ),
    "plans": (
        "Брось в чат что-нибудь живое — что делаешь, что на уме, планы или просто спроси "
        "про чужие дела. Тема абсолютно любая: вечер, работа, еда, хобби, покупка, поездка, "
        "кино, кафе, встреча, музыка, погода — всё что угодно. Разговорно, одно предложение."
    ),
    "news": (
        "Поделись новостью или тем, что только что прочитал(а) — что-то интересное, смешное "
        "или возмутительное из твоей сферы (учти свои интересы). Формат: короткий пересказ + своя реакция. "
        "Не придумывай конкретных цифр/имён, пиши обобщённо. 1-2 предложения."
    ),
    "question": (
        "Задай группе вопрос — за советом, мнением или рекомендацией по чему угодно: "
        "техника, работа, хобби, покупки, еда, кафе, куда сходить, фильм/книга/игра, "
        "отношения, деньги, поездки, бытовое, здоровье — абсолютно любая тема. "
        "Стиль: 'ребят, кто знает...', 'а вы как...', 'что думаете про...', 'куда бы посоветовали'. "
        "Одно предложение."
    ),
    "rant": (
        "Поныть или высказаться о чём-то раздражающем из жизни — пробки, цены, погода, "
        "очереди, работа, люди. Эмоционально но коротко. Начни с 'блин', 'ну вот', 'всё', 'опять'."
    ),
    "funny": (
        "Поделись чем-то смешным или нелепым что увидел(а) или вспомнил(а). "
        "Может мем, видео, ситуация из жизни. Очень коротко, с реакцией типа 'умираю', 'это шедевр'."
    ),
    "morning": (
        "Утреннее приветствие или мысль — не официальное, а живое: 'всем привет наконец-то', "
        "'ну и ночка была', 'доброе утро господа', 'кто не спит?' — и добавь одну мысль или вопрос."
    ),
}


async def generate_new_topic(
    persona: str,
    news_snippet: str = "",
    current_topic: str = "",
    recent_topics: list[str] | None = None,
) -> str:
    """Post something unprompted — personal life, plans, news, questions, rants."""
    import random
    from datetime import datetime, timezone

    hour = datetime.now(timezone.utc).hour
    # Time-aware topic selection
    if hour in range(6, 11):
        weights = {"morning": 3, "news": 2, "personal": 2, "plans": 1, "rant": 1, "funny": 1, "question": 1}
    elif hour in range(11, 16):
        weights = {"plans": 2, "news": 2, "question": 2, "personal": 2, "rant": 1, "funny": 1, "morning": 0}
    elif hour in range(16, 22):
        weights = {"personal": 3, "rant": 2, "plans": 2, "funny": 2, "news": 1, "question": 1, "morning": 0}
    else:
        weights = {"personal": 2, "funny": 2, "rant": 2, "news": 1, "plans": 1, "question": 1, "morning": 0}

    # If we have real news from a channel — use it (skip random topic)
    if news_snippet:
        topic_type = "news"
    else:
        topic_type = random.choices(list(weights.keys()), weights=list(weights.values()))[0]
    topic_instruction = _TOPIC_PROMPTS[topic_type]

    extra = ""
    if news_snippet:
        extra += f"\n\nВот реальная новость из подписанного канала, которую ты только что прочитал(а) — перескажи своими словами и добавь реакцию:\n{news_snippet[:300]}"
    if current_topic:
        extra += f"\n\nВ чате сейчас обсуждают: «{current_topic}». Продолжи эту тему — добавь своё мнение, уточняющий вопрос или новый угол."
    if recent_topics:
        extra += f"\n\nТы уже недавно говорил(а) о: {' / '.join(recent_topics[-5:])}. Выбери другую тему."

    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=120,
        system=f"{persona}\n\n{_CHAT_STYLE}",
        messages=[{
            "role": "user",
            "content": f"{topic_instruction}{extra}\n\nПиши:"
        }],
    )
    result = message.content[0].text.strip()
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


async def generate_youtube_query(persona: str) -> str:
    """Generate a YouTube search query that fits the bot's persona and interests."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=30,
        system=(
            "Ты генерируешь поисковый запрос для YouTube. "
            "Верни ТОЛЬКО запрос — 2-5 слов на русском, без кавычек и пояснений. "
            "Запрос должен искать интересное/свежее видео по теме, близкой персоне."
        ),
        messages=[{"role": "user", "content": f"Персона: {persona[:300]}\n\nЗапрос:"}],
    )
    return message.content[0].text.strip().strip('"').strip("'")


async def generate_link_share(content_hint: str, source: str, persona: str) -> str:
    """Generate a short message to share a link or forwarded post in group chat."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=100,
        system=f"{persona}\n\n{_CHAT_STYLE}",
        messages=[{
            "role": "user",
            "content": (
                f"Ты делишься с чатом материалом из источника «{source}».\n"
                f"О чём: «{content_hint[:200]}»\n\n"
                "Напиши 1 живое короткое сообщение-подводку — как будто сам(а) наткнулся(ась) "
                "на это и решил(а) скинуть ребятам. Саму ссылку не вставляй. "
                "Можно добавить свою реакцию или задать вопрос. 1 предложение."
            )
        }],
    )
    result = message.content[0].text.strip()
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


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


async def analyze_post_for_boost(post_text: str) -> str:
    """Analyze a Telegram post and extract the main discussion topic/angle."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=80,
        system=(
            "Ты анализируешь пост в Telegram-группе. Определи главную тему и предложи угол для обсуждения. "
            "Верни ОДНО короткое предложение по-русски — о чём пост и что интересно обсудить. "
            "Без кавычек и объяснений."
        ),
        messages=[{"role": "user", "content": f"Пост:\n{post_text[:600]}\n\nТема:"}],
    )
    return message.content[0].text.strip()


async def generate_boost_comment(
    post_text: str,
    topic: str,
    persona: str,
    existing_comments: list[str] | None = None,
) -> str:
    """Generate a contextual comment for boosting a Telegram post."""
    existing = ""
    if existing_comments:
        joined = " / ".join(existing_comments[-3:])
        existing = f"\nДругие уже написали: «{joined}». Не повторяй их мысли дословно."

    if post_text.strip():
        post_ctx = f"В группе появился пост:\n«{post_text[:400]}»\n\n"
    else:
        post_ctx = "В группе обсуждают интересную тему.\n\n"

    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=120,
        system=f"{persona}\n\n{_CHAT_STYLE}",
        messages=[{
            "role": "user",
            "content": (
                f"{post_ctx}"
                f"Тема обсуждения: {topic}\n"
                f"{existing}\n"
                "Напиши живой комментарий — мнение, вопрос, схожий опыт или несогласие. "
                "1-2 предложения, разговорный стиль."
            )
        }],
    )
    result = message.content[0].text.strip()
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


async def improve_text(text: str, instruction: str) -> str:
    """Rewrite a draft message according to an instruction (shorter, more formal, etc.)."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=256,
        system="You rewrite messages as instructed. Return only the rewritten text.",
        messages=[{"role": "user", "content": f"Message: {text}\n\nInstruction: {instruction}"}],
    )
    return message.content[0].text.strip()
