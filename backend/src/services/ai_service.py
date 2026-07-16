import re
import random
import anthropic
from src.config import settings

_client: anthropic.AsyncAnthropic | None = None


def _strip_em_dash(text: str) -> str:
    """Hard-remove em-dashes that Claude occasionally generates despite instructions."""
    return re.sub(r'\s*—\s*', ' ', text).strip()


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


# Comment format options: (name, instruction)
# Assigned per-bot at campaign start to guarantee diversity — no random selection here
_COMMENT_FORMATS = [
    ("emoji_only",
     "ТОЛЬКО эмодзи, НОЛЬ слов. Выбери 1-4 эмодзи которые ПОДХОДЯТ по смыслу и настроению: "
     "смешно — 😂, восхищение — ❤🔥, скепсис — 🤔, негатив — 💀😬, удивление — 😱. "
     "Количество от 1 до 4 — выбирай рандомно. НЕ бери эмодзи с фото или из поста."),
    ("ultra_short",
     "2–4 слова, без точки, можно с маленькой буквы. Реакция на рефлексе."),
    ("short_casual",
     "1 предложение. Без точки в конце необязательно. Живо, не официально."),
    ("medium",
     "1–2 предложения. Можно с эмодзи внутри текста или в конце, можно без. По-человечески."),
    ("question",
     "Один короткий вопрос — конкретный, про деталь или ситуацию. Без точки в конце."),
    ("tangent",
     "1 предложение — личная история или ассоциация, ПРЯМО СВЯЗАННАЯ с темой поста. "
     "Например: если пост про суд — что-то про суды/законы из своей жизни. "
     "НЕ УХОДИ в другую тему. Ассоциация должна читаться как очевидная реакция на ЭТОТ пост."),
]

# Opinion stances — assigned per-bot to guarantee diverse viewpoints in one campaign
_STANCE_INSTRUCTIONS = {
    "positive":  "Ты позитивно настроен — одобряешь, восхищаешься, но без пафоса.",
    "critical":  "Ты скептичен или мягко критичен — 'ну хз', 'мне никогда не нравилась', 'не понимаю хайпа'. Без агрессии.",
    "neutral":   "Ты нейтрален — констатируешь факт или наблюдение без личной оценки.",
    "ironic":    "Лёгкая ирония или подкол — не смеёшься в лицо, но есть сарказм.",
    "engaging":  "Ты вовлекаешь — задаёшь вопрос или провоцируешь других высказаться.",
    "tangent":   "Личный опыт или ассоциация — но строго по теме поста, не выдумывай несвязанные истории.",
}

_BOOST_SYSTEM = (
    "Ты пишешь комментарий в Телеграм как обычный русскоязычный пользователь.\n\n"
    "ЗАПРЕЩЕНО:\n"
    "• длинное тире (—) — НИКОГДА, ни при каких условиях\n"
    "• выдуманные слова и бессмыслица — мысль ВСЕГДА должна быть понятной\n"
    "• 'стоит отметить', 'безусловно', 'действительно', 'следует', 'важно понимать', 'однако'\n"
    "• идеальная пунктуация в каждом предложении\n"
    "• шаблон: реакция + анализ + вопрос\n"
    "• повторять эмодзи которые уже есть в посте, на фото или в других комментариях\n\n"
    "РАЗРЕШЕНО:\n"
    "• писать с маленькой буквы\n"
    "• не ставить точку в конце\n"
    "• 'ну', 'блин', 'кстати', 'короче', 'вообще', '...'\n"
    "• сленг: 'орнул', 'капец', 'жесть', 'топ', 'да ладно', 'ой всё', 'лол', 'хаха'\n"
    "• неполные предложения если звучит естественно и логично\n"
)


async def generate_continuation_comment(
    post_text: str,
    persona: str,
    own_stance: str,
    target_comment: str,
    target_stance: str,
    all_comments: list[str],
    style_examples: list[str] | None = None,
) -> str:
    """Generate a follow-up reply that continues the discussion thread naturally."""
    stance_desc = _STANCE_INSTRUCTIONS.get(own_stance, "")

    # Describe the interaction dynamic
    opposite = {"positive", "critical"}
    if own_stance in opposite and target_stance in opposite and own_stance != target_stance:
        dynamic = "вы на противоположных позициях — продолжи спор, возрази или стой на своём"
    elif own_stance == target_stance:
        dynamic = "вы похожих взглядов — поддержи, добавь что-то своё, укрепи позицию"
    elif own_stance == "neutral":
        dynamic = "ты нейтральный — попробуй примирить спорящих или вынеси наблюдение"
    elif own_stance == "ironic":
        dynamic = "подколи иронично — не зло, но с сарказмом"
    else:
        dynamic = "отреагируй естественно на то что написали"

    style_ctx = ""
    if style_examples:
        joined = " / ".join(f'«{c[:60]}»' for c in style_examples[-4:])
        style_ctx = f"\nТвой обычный стиль письма: {joined}"

    others = "\n".join(f"— {c[:80]}" for c in all_comments[-6:])

    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=100,
        system=(
            f"{_BOOST_SYSTEM}\n"
            f"Твоя персона: {persona[:200]}\n"
            f"Твоя позиция: {stance_desc}"
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Пост: «{post_text[:300]}»\n\n"
                f"Комментарии в треде:\n{others}\n\n"
                f"Ты отвечаешь на:\n«{target_comment[:200]}»\n\n"
                f"Динамика: {dynamic}\n"
                f"Формат: 1 предложение или 2-4 слова, разговорно, без точки в конце.{style_ctx}\n\n"
                "Напиши:"
            )
        }],
    )
    return _strip_em_dash(message.content[0].text.strip().strip('"').strip("'"))


async def search_boost_context(post_text: str) -> str:
    """Search web for context about people/events mentioned in the post."""
    try:
        response = await _get_client().messages.create(
            model=settings.anthropic_model,
            max_tokens=400,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            system=(
                "Найди информацию о людях, событиях или ситуации из текста. "
                "Верни краткую сводку по-русски: кто эти люди, что за ситуация, "
                "что о них известно или думают. 2–3 предложения, только факты."
            ),
            messages=[{
                "role": "user",
                "content": f"Текст поста:\n{post_text[:400]}\n\nЧто известно об этих людях/ситуации?"
            }],
        )
        for block in response.content:
            if hasattr(block, "text") and block.text:
                return block.text.strip()
    except Exception:
        pass
    return ""


async def generate_boost_comment(
    post_text: str,
    topic: str,
    persona: str,
    own_comments: list[str] | None = None,
    real_comments: list[str] | None = None,
    style_index: int = 0,
    prev_comments: list[dict] | None = None,
    extra_context: str = "",
    media_bytes: bytes | None = None,
    media_type: str = "image/jpeg",
    assigned_format: tuple[str, str] | None = None,
    stance: str = "neutral",
    style_examples: list[str] | None = None,
) -> tuple[str, int | None]:
    """Generate a contextual comment for boosting a Telegram post.

    Returns (comment_text, reply_to_index) where reply_to_index is an index
    into prev_comments (reply to that bot's comment) or None (reply to the post).

    assigned_format: pre-assigned (name, instruction) from campaign start for diversity.
    stance: opinion stance (positive/critical/neutral/ironic/engaging/tangent).
    style_examples: past comments from this account — used as style memory.
    """
    import base64

    fmt_name, fmt_instruction = assigned_format if assigned_format else _COMMENT_FORMATS[style_index % len(_COMMENT_FORMATS)][:2]

    # Decide whether to reply to a previous bot comment (~40% if any exist and format allows)
    reply_to_index: int | None = None
    reply_target_text: str = ""
    if prev_comments and fmt_name not in ("emoji_only", "ultra_short") and random.random() < 0.40:
        reply_to_index = random.randint(0, len(prev_comments) - 1)
        reply_target_text = prev_comments[reply_to_index].get("text", "")[:150]

    post_ctx = f"Пост:\n«{post_text[:450]}»" if post_text.strip() else f"Тема: {topic}"

    context_block = ""
    if extra_context:
        context_block = f"\n\nКонтекст из интернета:\n{extra_context[:300]}"

    real_ctx = ""
    if real_comments:
        joined = "\n".join(f"— {c[:100]}" for c in real_comments[:5])
        real_ctx = f"\n\nДругие комментарии под постом:\n{joined}"

    # Style memory — show how this account has written before
    style_ctx = ""
    if style_examples:
        joined = " / ".join(f'«{c[:80]}»' for c in style_examples[-5:])
        style_ctx = f"\n\nТак ты обычно пишешь (твой стиль — придерживайся его):\n{joined}"

    own_ctx = ""
    if own_comments:
        own_ctx = f"\n(В этом буст-треде ты уже писал: «{' / '.join(own_comments[-2:])}» — не повторяй.)"

    # Collect used emojis from prev_comments to avoid repetition
    used_emojis = ""
    if prev_comments:
        import re
        emoji_pattern = re.compile(
            "[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0000FE00-\U0000FEFF]",
            re.UNICODE
        )
        found = []
        for c in prev_comments:
            found.extend(emoji_pattern.findall(c.get("text", "")))
        if found:
            used_emojis = f"\nЭти эмодзи уже использованы другими — НЕ повторяй: {''.join(set(found[:15]))}"

    stance_instruction = _STANCE_INSTRUCTIONS.get(stance, "")

    if reply_target_text:
        task = (
            f"Твоя позиция: {stance_instruction}\n"
            f"Ты отвечаешь на комментарий:\n«{reply_target_text}»\n\n"
            f"Формат: {fmt_instruction}"
        )
    else:
        task = (
            f"Твоя позиция: {stance_instruction}\n"
            f"Формат: {fmt_instruction}"
        )

    text_prompt = (
        f"{post_ctx}{context_block}{real_ctx}{style_ctx}{own_ctx}{used_emojis}\n\n"
        f"{task}\n\n"
        "Напиши:"
    )

    if media_bytes:
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(media_bytes).decode(),
                },
            },
            {"type": "text", "text": text_prompt},
        ]
    else:
        user_content = text_prompt

    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=120,
        system=f"{_BOOST_SYSTEM}\nТвоя персона: {persona[:300]}",
        messages=[{"role": "user", "content": user_content}],
    )
    result = _strip_em_dash(message.content[0].text.strip().strip('"').strip("'"))
    return result, reply_to_index


async def improve_text(text: str, instruction: str) -> str:
    """Rewrite a draft message according to an instruction (shorter, more formal, etc.)."""
    message = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=256,
        system="You rewrite messages as instructed. Return only the rewritten text.",
        messages=[{"role": "user", "content": f"Message: {text}\n\nInstruction: {instruction}"}],
    )
    return message.content[0].text.strip()
