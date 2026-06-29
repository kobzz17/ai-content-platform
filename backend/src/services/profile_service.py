"""
Автоматическая настройка профилей Telegram-аккаунтов:
- Генерация реалистичного русского имени и фамилии
- Генерация уникального username
- Генерация биографии
- Загрузка и установка аватарки
"""
import asyncio
import logging
import random
import urllib.request
from datetime import datetime
from src.database import async_session_maker
from src.models import Account, AccountEvent

logger = logging.getLogger(__name__)

# ── Имена ────────────────────────────────────────────────────────────────────

MALE_FIRST = [
    "Александр", "Дмитрий", "Михаил", "Андрей", "Сергей",
    "Алексей", "Артём", "Максим", "Иван", "Никита",
    "Денис", "Антон", "Илья", "Кирилл", "Роман",
    "Евгений", "Владимир", "Даниил", "Тимур", "Виктор",
    "Павел", "Глеб", "Фёдор", "Арtem", "Константин",
]

FEMALE_FIRST = [
    "Анастасия", "Екатерина", "Мария", "Анна", "Ольга",
    "Наталья", "Валерия", "Полина", "Виктория", "Юлия",
    "Ирина", "Дарья", "Алина", "Кристина", "Татьяна",
    "Елена", "Ксения", "Вероника", "Алёна", "Светлана",
    "Надежда", "Людмила", "Зоя", "Вера", "Лариса",
]

LAST_NAMES = [
    "Иванов", "Смирнов", "Кузнецов", "Попов", "Васильев",
    "Петров", "Соколов", "Михайлов", "Новиков", "Фёдоров",
    "Морозов", "Волков", "Алексеев", "Лебедев", "Семёнов",
    "Егоров", "Павлов", "Козлов", "Степанов", "Николаев",
    "Орлов", "Андреев", "Макаров", "Никитин", "Захаров",
    "Зайцев", "Соловьёв", "Борисов", "Яковлев", "Григорьев",
    "Романов", "Воробьёв", "Сергеев", "Кузьмин", "Фролов",
    "Александров", "Дмитриев", "Королёв", "Гусев", "Тихонов",
]

BIO_TEMPLATES = [
    "Просто живу и радуюсь жизни 🙂",
    "IT, кофе, путешествия",
    "Музыка / книги / кино",
    "Работаю, учусь, развиваюсь",
    "Люблю природу и хорошие беседы",
    "Предпочитаю дело разговорам",
    "Спорт и здоровый образ жизни",
    "Читаю, думаю, иногда пишу",
    "Технологии и всё интересное",
    "Жизнь — это путешествие 🌍",
    "",  # без биографии (30% случаев)
    "",
    "",
]

# Таблица транслитерации для username
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}


def _translit(text: str) -> str:
    result = []
    for ch in text.lower():
        result.append(_TRANSLIT.get(ch, ch))
    return "".join(result)


def generate_name(gender: str = "random") -> dict:
    """Генерация случайного русского имени."""
    if gender == "random":
        gender = random.choice(["male", "female"])

    first = random.choice(MALE_FIRST if gender == "male" else FEMALE_FIRST)
    last = random.choice(LAST_NAMES)
    # Женские фамилии с -а
    if gender == "female" and last.endswith(("в", "н", "к", "р", "в")):
        last = last + "а"

    return {"first_name": first, "last_name": last, "gender": gender}


def generate_username(first_name: str, last_name: str) -> str:
    """Генерация реалистичного Telegram username."""
    first_t = _translit(first_name)
    last_t = _translit(last_name)

    patterns = [
        f"{first_t}_{last_t[:3]}{random.randint(10, 99)}",
        f"{first_t[0]}{last_t}{random.randint(10, 99)}",
        f"{first_t}{random.randint(100, 9999)}",
        f"{last_t}_{first_t[0]}{random.randint(10, 99)}",
        f"{first_t}_{random.randint(1990, 2003)}",
    ]

    username = random.choice(patterns)
    # Оставляем только допустимые символы (a-z, 0-9, _)
    username = "".join(c for c in username if c.isalnum() or c == "_")
    # Telegram: минимум 5, максимум 32 символа, начинается с буквы
    if not username[0].isalpha():
        username = "user_" + username
    username = username[:32]
    if len(username) < 5:
        username = username + str(random.randint(1000, 9999))
    return username


def generate_bio() -> str:
    return random.choice(BIO_TEMPLATES)


# ── Аватарка ─────────────────────────────────────────────────────────────────

def _fetch_avatar(account_id: int) -> bytes | None:
    """
    Скачивает уникальную аватарку.
    Использует pravatar.cc — набор реальных фотографий (70 вариантов).
    Индекс детерминирован по account_id чтобы не повторяться на первых 70 аккаунтах.
    """
    idx = (account_id % 70) + 1
    urls = [
        f"https://i.pravatar.cc/512?img={idx}",
        f"https://randomuser.me/api/portraits/{'men' if idx % 2 == 0 else 'women'}/{idx % 99}.jpg",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                if len(data) > 5000:  # минимальный размер нормальной фотографии
                    return data
        except Exception as e:
            logger.debug("Avatar fetch failed from %s: %s", url, e)
    return None


# ── Публичный API ─────────────────────────────────────────────────────────────

async def setup_profile(
    account_id: int,
    session_string: str,
    proxy: str | None = None,
    gender: str = "random",
    set_photo: bool = True,
) -> dict:
    """
    Настройка профиля аккаунта: имя, username, биография, аватарка.
    Возвращает dict с результатом.
    """
    import src.session_manager as sm
    from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
    from telethon.tl.functions.photos import UploadProfilePhotoRequest
    from telethon.errors import UsernameOccupiedError, UsernameInvalidError

    result = {"account_id": account_id, "changes": [], "errors": []}

    try:
        client = await sm.get_client(account_id, session_string, proxy)
    except Exception as e:
        result["errors"].append(f"Подключение: {e}")
        return result

    name = generate_name(gender)
    first = name["first_name"]
    last = name["last_name"]
    bio = generate_bio()

    # 1. Обновить имя и биографию
    try:
        await client(UpdateProfileRequest(
            first_name=first,
            last_name=last,
            about=bio,
        ))
        result["changes"].append(f"Имя: {first} {last}")
        if bio:
            result["changes"].append(f"Bio: {bio}")

        # Сохранить в БД
        async with async_session_maker() as db:
            acc = await db.get(Account, account_id)
            if acc:
                acc.first_name = first
                acc.last_name = last
                acc.label = f"{first} {last}"
            await db.commit()
    except Exception as e:
        result["errors"].append(f"Имя: {e}")

    # 2. Установить username (с несколькими попытками)
    for attempt in range(5):
        username = generate_username(first, last)
        try:
            await client(UpdateUsernameRequest(username=username))
            result["changes"].append(f"Username: @{username}")
            async with async_session_maker() as db:
                acc = await db.get(Account, account_id)
                if acc:
                    acc.username = username
                await db.commit()
            break
        except UsernameOccupiedError:
            continue  # Попробовать другой
        except UsernameInvalidError as e:
            result["errors"].append(f"Username невалидный: {e}")
            break
        except Exception as e:
            result["errors"].append(f"Username: {e}")
            break

    # 3. Установить аватарку
    if set_photo:
        try:
            photo_bytes = await asyncio.get_event_loop().run_in_executor(
                None, _fetch_avatar, account_id
            )
            if photo_bytes:
                file = await client.upload_file(photo_bytes, file_name="avatar.jpg")
                await client(UploadProfilePhotoRequest(file=file))
                result["changes"].append("Аватарка установлена")
            else:
                result["errors"].append("Аватарка: не удалось скачать фото")
        except Exception as e:
            result["errors"].append(f"Аватарка: {e}")

    # Залогировать результат
    async with async_session_maker() as db:
        from src.models import WarmupLog
        db.add(WarmupLog(
            account_id=account_id,
            action="profile_setup",
            detail=f"Имя: {first} {last}, изменения: {len(result['changes'])}, ошибки: {len(result['errors'])}",
        ))
        await db.commit()

    logger.info("Profile setup for account %d: %d changes, %d errors",
                account_id, len(result["changes"]), len(result["errors"]))
    return result
