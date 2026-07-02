import asyncio
import logging
import random
import re
import string

logger = logging.getLogger(__name__)

# ── Name pools ────────────────────────────────────────────────────────────────

_RU_MALE_FIRST = [
    "Андрей", "Дмитрий", "Александр", "Иван", "Михаил", "Сергей", "Николай",
    "Алексей", "Виктор", "Максим", "Роман", "Кирилл", "Павел", "Владимир",
    "Артём", "Евгений", "Денис", "Антон", "Илья", "Олег", "Вадим", "Руслан",
    "Станислав", "Аркадий", "Борис", "Геннадий", "Игорь", "Константин", "Леонид",
    "Тимур", "Марат", "Ринат", "Булат", "Эдуард", "Виталий", "Глеб", "Егор",
    "Фёдор", "Степан", "Семён", "Никита", "Юрий", "Петр", "Григорий", "Захар",
]

_RU_FEMALE_FIRST = [
    "Анастасия", "Лидия", "Глафира", "Мария", "Екатерина", "Ольга", "Наталья",
    "Татьяна", "Ирина", "Светлана", "Елена", "Алина", "Дарья", "Юлия", "Валерия",
    "Ксения", "Полина", "Вероника", "Александра", "Надежда", "Виктория", "Галина",
    "Людмила", "Зинаида", "Тамара", "Валентина", "Любовь", "Нина", "Маргарита",
    "Регина", "Карина", "Диана", "Яна", "Кристина", "Инна", "Лариса", "Жанна",
    "Тамила", "Альфия", "Зульфия", "Эльвира", "Гузель", "Айгуль", "Лейла",
]

_RU_MALE_LAST = [
    "Смирнов", "Козлов", "Новиков", "Морозов", "Петров", "Волков", "Соколов",
    "Попов", "Лебедев", "Никитин", "Федоров", "Захаров", "Орлов", "Кузнецов",
    "Макаров", "Яковлев", "Зайцев", "Семёнов", "Голубев", "Виноградов", "Богданов",
    "Воробьёв", "Фролов", "Михайлов", "Беляев", "Тарасов", "Белов", "Комаров",
    "Титов", "Миронов", "Крылов", "Власов", "Коновалов", "Шестаков", "Блинов",
    "Щербаков", "Третьяков", "Коробов", "Рябов", "Матвеев", "Давыдов", "Назаров",
]

_RU_FEMALE_LAST = [
    "Смирнова", "Козлова", "Новикова", "Морозова", "Петрова", "Волкова", "Соколова",
    "Попова", "Лебедева", "Никитина", "Федорова", "Захарова", "Орлова", "Кузнецова",
    "Макарова", "Яковлева", "Зайцева", "Семёнова", "Голубева", "Виноградова",
    "Богданова", "Воробьёва", "Фролова", "Михайлова", "Беляева", "Тарасова",
    "Белова", "Комарова", "Деменока", "Хорошева", "Прохорова", "Тихонова",
]

_INTL_FIRST = [
    "Yaromir", "Ixtiyor", "Timur", "Rustam", "Aziz", "Bekzod", "Sherzod",
    "Jasur", "Nodir", "Ulugbek", "Dilnoza", "Nilufar", "Sabina", "Zulfiya",
    "Carlos", "Marco", "Viktor", "Stefan", "Adrian", "Bogdan", "Miroslav",
    "Alex", "Max", "Leo", "Nina", "Sandra", "Lola", "Diana", "Cons",
    "Mila", "Kira", "Vera", "Tina", "Lars", "Erik", "Kim", "Jan",
    "Daniil", "Artur", "Emre", "Kemal", "Aisha", "Fatima", "Omar", "Yusuf",
]

_INTL_LAST = [
    "Tiger", "Tanta", "Storm", "Dark", "Wolf", "Fox", "Stone", "Black",
    "White", "Silver", "Wild", "Free", "Sharp", "Strong", "Cool", "Frost",
    "A", "B", "K", "M", "V", "Z",  # single-letter last names like "Андрей А"
]

_SINGLE_NAMES = [
    "trreeya", "maloli", "Ixtiyor", "Lola", "Timur", "Kesha", "Tosha",
    "Lolik", "Kodik", "Zorik", "Modik", "Bolik", "Asel", "Aziza", "Kamil",
    "Damir", "Aliya", "Sania", "Leila", "Rano", "Zara", "Mia", "Lia",
    "trreeya", "maloli", "xzmrk", "kodik", "lolik", "nvlsk",
]

# ── Transliteration for usernames ─────────────────────────────────────────────

_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

_USERNAME_BASES = [
    "yatig", "xmrk", "treeya", "lolik", "kodik", "modik", "zorik",
    "malik", "damir", "timur", "amir", "artur", "maxim", "roma",
    "ivan", "alex", "masha", "katya", "anya", "dima", "sasha",
    "oleg", "vova", "danya", "kiri", "pasha", "vanya", "lesha",
    "stepa", "fedya", "kolya", "vitya", "senya", "grisha",
]


def _translit(text: str) -> str:
    return ''.join(_TRANSLIT.get(c, c) for c in text.lower())


def generate_display_name() -> tuple[str, str]:
    """Return (first_name, last_name). last_name may be empty string."""
    style = random.choices(
        ["ru_full", "ru_initial", "intl_full", "intl_single", "single_word"],
        weights=[38, 12, 22, 16, 12],
    )[0]

    if style == "ru_full":
        gender = random.choice(["m", "f"])
        if gender == "m":
            return random.choice(_RU_MALE_FIRST), random.choice(_RU_MALE_LAST)
        else:
            return random.choice(_RU_FEMALE_FIRST), random.choice(_RU_FEMALE_LAST)

    elif style == "ru_initial":
        gender = random.choice(["m", "f"])
        first = random.choice(_RU_MALE_FIRST if gender == "m" else _RU_FEMALE_FIRST)
        initial = random.choice("АБВГДЕЖЗИКЛМНОПРСТУФ")
        return first, initial

    elif style == "intl_full":
        first = random.choice(_INTL_FIRST)
        last = random.choice(_INTL_LAST) if random.random() > 0.35 else ""
        return first, last

    elif style == "intl_single":
        return random.choice(_INTL_FIRST), ""

    else:  # single_word — like "trreeya", "maloli"
        return random.choice(_SINGLE_NAMES), ""


def generate_username() -> str:
    """Generate a random Telegram-valid username (5–32 chars, a-z0-9_)."""
    style = random.randint(1, 5)

    if style == 1:
        # Transliterated Russian name + numbers: "dmitry92", "anastasia2024"
        name = random.choice(_RU_MALE_FIRST + _RU_FEMALE_FIRST)
        base = _translit(name)
        suffix = str(random.randint(1, 9999))
        result = base + suffix

    elif style == 2:
        # Base word + numbers: "yatigro777"
        base = random.choice(_USERNAME_BASES)
        extra = ''.join(random.choices(string.ascii_lowercase, k=random.randint(0, 3)))
        suffix = str(random.randint(10, 9999))
        result = base + extra + suffix

    elif style == 3:
        # Pure random lowercase letters
        result = ''.join(random.choices(string.ascii_lowercase, k=random.randint(7, 12)))

    elif style == 4:
        # Name + underscore + letter+numbers
        base = _translit(random.choice(_RU_MALE_FIRST + _RU_FEMALE_FIRST))
        suffix = random.choice(string.ascii_lowercase) + str(random.randint(10, 99))
        result = base + "_" + suffix

    else:
        # "trreeya" style — repeated/doubled letters in a word
        word = random.choice(["tree", "cool", "moon", "star", "fire", "rain", "wolf", "free"])
        letters = list(word)
        idx = random.randint(0, len(letters) - 1)
        letters.insert(idx, letters[idx])
        extra = str(random.randint(10, 99)) if random.random() > 0.4 else ""
        result = ''.join(letters) + extra

    # Sanitize: only a-z, 0-9, underscore; must start with a letter; 5–32 chars
    result = re.sub(r'[^a-z0-9_]', '', result.lower())
    if not result or not result[0].isalpha():
        result = "user" + result
    result = re.sub(r'_+', '_', result).strip('_')
    if len(result) < 5:
        result += str(random.randint(100, 9999))
    return result[:32]


async def randomize_account_profile(account_id: int) -> dict:
    """
    Apply a randomly generated name (and optionally username) to a Telegram account.
    Returns {"ok": True, "first_name": ..., "last_name": ..., "username": ...}
    or {"ok": False, "error": ...}.
    """
    from src.database import async_session_maker
    from src.models import Account
    import src.session_manager as sm

    try:
        async with async_session_maker() as db:
            account = await db.get(Account, account_id)
            if not account or not account.is_active:
                return {"ok": False, "error": "Аккаунт не найден"}
            session_str = account.session_string
            proxy = account.proxy

        if session_str == "DEMO":
            return {"ok": False, "error": "DEMO аккаунт"}

        client = await sm.get_client(account_id, session_str, proxy)

        first_name, last_name = generate_display_name()
        new_username = generate_username()

        from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest

        # Update name
        await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))

        # Try to update username (may fail if taken — that's fine)
        username_set = None
        try:
            await client(UpdateUsernameRequest(username=new_username))
            username_set = new_username
        except Exception as e:
            logger.debug("Username %s taken or failed for account %d: %s", new_username, account_id, e)
            # Try one more time with different username
            try:
                alt = generate_username()
                await client(UpdateUsernameRequest(username=alt))
                username_set = alt
            except Exception:
                pass

        # Update DB record
        async with async_session_maker() as db:
            acc = await db.get(Account, account_id)
            if acc:
                acc.first_name = first_name
                acc.label = f"{first_name} {last_name}".strip()
                if username_set:
                    acc.username = username_set
                await db.commit()

        logger.info(
            "Randomized account %d → '%s %s' @%s",
            account_id, first_name, last_name, username_set or "unchanged",
        )
        return {
            "ok": True,
            "first_name": first_name,
            "last_name": last_name,
            "username": username_set,
        }

    except Exception as e:
        logger.error("randomize_account_profile(%d) failed: %s", account_id, e)
        return {"ok": False, "error": str(e)[:200]}


async def randomize_all_accounts(account_ids: list[int]) -> None:
    """Background task: randomize profiles for all given account IDs with delays."""
    results = {"ok": 0, "failed": 0}
    for account_id in account_ids:
        result = await randomize_account_profile(account_id)
        if result["ok"]:
            results["ok"] += 1
        else:
            results["failed"] += 1
        # Rate-limit protection: 8–20 sec between accounts
        await asyncio.sleep(random.uniform(8, 20))
    logger.info("Bulk randomize done: %d ok, %d failed", results["ok"], results["failed"])
