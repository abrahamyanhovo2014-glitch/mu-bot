import os
import json
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

TOKEN = os.environ["BOT_TOKEN"]
FD_KEY = os.environ["FD_API_KEY"]
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
# Telegram ID Артура (секрет ALLOWED_ID). Пока он не задан, бот только показывает ID.
ALLOWED_ID = (os.environ.get("ALLOWED_ID") or "").strip()
TZ = ZoneInfo("Asia/Yerevan")  # армянское время
TG = f"https://api.telegram.org/bot{TOKEN}"
MAX_QUESTIONS_PER_RUN = 5
BIRTHDAY = (11, 19)  # (месяц, день)
# Ночью (с 23:00 до 08:00 по времени TZ) напоминания не отправляются
QUIET_START = 23
QUIET_END = 8

# Этапы напоминаний: за сутки, за 4 часа, за 1 час
STAGES = [timedelta(days=1), timedelta(hours=4), timedelta(hours=1)]

LANG_NAMES = {"ru": "русский", "hy": "армянский", "en": "английский"}

TEXTS = {
    "ru": {
        "left_h": "через {n} ч",
        "left_m": "через {n} мин",
        "title": "⚽ Матч {w}!",
        "at": "{c}, {d} в {t}",
        "set": "Язык: русский 🇷🇺",
    },
    "hy": {
        "left_h": "{n} ժամից",
        "left_m": "{n} րոպեից",
        "title": "⚽ Խաղը սկսվում է {w}!",
        "at": "{c}, {d}՝ ժամը {t}",
        "set": "Լեզուն՝ հայերեն 🇦🇲",
    },
    "en": {
        "left_h": "in {n} h",
        "left_m": "in {n} min",
        "title": "⚽ Match starts {w}!",
        "at": "{c}, {d} at {t}",
        "set": "Language: English 🇬🇧",
    },
}

GREETING_BIRTHDAY = (
    "Привет, Артур, с днём рождения! 🎉🎂\n"
    "Я буду напоминать тебе о матчах Манчестер Юнайтед ⚽🔴 "
    "и отвечать на любые вопросы о клубе!\n\n"
    "Բարև, Արթուր, շնորհավոր ծնունդդ։ 🎉🎂\n"
    "Ես կհիշեցնեմ քեզ Մանչեսթեր Յունայթեդի խաղերի մասին ⚽🔴 "
    "և կպատասխանեմ ակումբի մասին ցանկացած հարցի։\n\n"
    "Hi Artur, happy birthday! 🎉🎂\n"
    "I'll remind you about Manchester United matches ⚽🔴 "
    "and answer any questions about the club!\n\n"
    "🌐 /ru · /hy · /en"
)

GREETING = (
    "Привет, Артур! 👋\n"
    "Я буду напоминать тебе о матчах Манчестер Юнайтед ⚽🔴 "
    "и отвечать на любые вопросы о клубе!\n\n"
    "Բարև, Արթուր։ 👋\n"
    "Ես կհիշեցնեմ քեզ Մանչեսթեր Յունայթեդի խաղերի մասին ⚽🔴 "
    "և կպատասխանեմ ակումբի մասին ցանկացած հարցի։\n\n"
    "Hi Artur! 👋\n"
    "I'll remind you about Manchester United matches ⚽🔴 "
    "and answer any questions about the club!\n\n"
    "🌐 /ru · /hy · /en"
)

SYSTEM_PROMPT = (
    "Ты — Telegram-бот, фанат и эксперт по футбольному клубу Манчестер Юнайтед. "
    "Ты знаешь историю клуба, игроков, тренеров, трофеи, рекорды, Олд Траффорд и трансферы. "
    "Отвечай дружелюбно и коротко (до 8 предложений). "
    "Человек написал на языке: {lang}. Обязательно отвечай на этом же языке. "
    "Если не уверен в факте или вопрос про свежие события, честно скажи об этом "
    "и ничего не выдумывай. "
    "Если вопрос не про МЮ и не про футбол, мягко скажи, что ты бот про Манчестер Юнайтед."
)


def load():
    try:
        with open("state.json", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {"offset": 0, "chat_id": None, "notified": []}
    state.setdefault("lang", "ru")
    return state


def send(chat_id, text):
    requests.post(
        f"{TG}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000]},
        timeout=20,
    )


def detect_lang(text):
    """Определяем язык по буквам: армянские, кириллица или латиница."""
    counts = {
        "hy": sum("\u0531" <= ch <= "\u058f" for ch in text),
        "ru": sum("\u0400" <= ch <= "\u04ff" for ch in text),
        "en": sum(ch.isascii() and ch.isalpha() for ch in text),
    }
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None


def human_left(left, tx):
    """Сколько осталось до матча: минуты (если меньше полутора часов) или часы."""
    minutes = round(left.total_seconds() / 60)
    if minutes < 90:
        return tx["left_m"].format(n=max(minutes, 1))
    return tx["left_h"].format(n=round(minutes / 60))


def ask_gemini(question, context, lang):
    prompt = SYSTEM_PROMPT.format(lang=LANG_NAMES[lang]) + "\n" + context
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": prompt}]},
                "contents": [{"role": "user", "parts": [{"text": question}]}],
            },
            timeout=60,
        )
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or "🙈"
    except Exception:
        return "🙈 Error / Սխալ / Ошибка"


state = load()
questions = []
now = datetime.now(timezone.utc)

# 1. Читаем новые сообщения
updates = requests.get(
    f"{TG}/getUpdates",
    params={"offset": state["offset"], "timeout": 0},
    timeout=20,
).json()

for u in updates.get("result", []):
    state["offset"] = u["update_id"] + 1
    msg = u.get("message", {})
    text = msg.get("text", "")
    if not text:
        continue
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id")
    cmd = text.split()[0].split("@")[0].lower()

    # Личный бот: пока ID не задан, только показываем ID на /start
    if not ALLOWED_ID:
        if cmd == "/start":
            send(chat_id, f"Твой Telegram ID / Your Telegram ID: {user_id}")
        continue

    # Всех, кроме Артура, игнорируем
    if str(user_id) != ALLOWED_ID:
        continue

    if cmd == "/start":
        state["chat_id"] = chat_id
        today = now.astimezone(TZ)
        if (today.month, today.day) == BIRTHDAY:
            send(chat_id, GREETING_BIRTHDAY)
        else:
            send(chat_id, GREETING)
    elif cmd in ("/ru", "/hy", "/en"):
        state["lang"] = cmd[1:]
        send(chat_id, TEXTS[state["lang"]]["set"])
    else:
        qlang = detect_lang(text) or state["lang"]
        state["lang"] = qlang  # напоминания идут на языке последнего сообщения
        questions.append((chat_id, text, qlang))

lang = state["lang"]
tx = TEXTS[lang]

# 2. Календарь матчей
matches = []
if state["chat_id"]:
    resp = requests.get(
        "https://api.football-data.org/v4/teams/66/matches",
        params={"status": "SCHEDULED,TIMED"},
        headers={"X-Auth-Token": FD_KEY},
        timeout=20,
    ).json()
    matches = sorted(resp.get("matches", []), key=lambda m: m["utcDate"])

# 3. Напоминания о матчах (не ночью)
local_now = now.astimezone(TZ)
quiet = local_now.hour >= QUIET_START or local_now.hour < QUIET_END
for match in ([] if quiet else matches):
    start = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
    left = start - now
    if left <= timedelta(0):
        continue

    # Самый близкий этап, в который матч уже попал
    stage = None
    for i, delta in enumerate(STAGES):
        if left <= delta:
            stage = i
    if stage is None:
        continue

    key = f"{match['id']}:{stage}"
    if key in state["notified"]:
        continue

    local = start.astimezone(TZ)
    send(
        state["chat_id"],
        tx["title"].format(w=human_left(left, tx)) + "\n"
        f"{match['homeTeam']['name']} — {match['awayTeam']['name']}\n"
        + tx["at"].format(
            c=match["competition"]["name"],
            d=local.strftime("%d.%m"),
            t=local.strftime("%H:%M"),
        ),
    )
    state["notified"].append(key)

state["notified"] = state["notified"][-100:]

# 4. Ответы на вопросы (только Артуру)
if GEMINI_KEY and questions:
    next_games = "; ".join(
        f"{m['homeTeam']['name']} — {m['awayTeam']['name']} "
        f"({datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00')).astimezone(TZ).strftime('%d.%m %H:%M')})"
        for m in matches[:3]
    )
    context = f"Сегодня {now.astimezone(TZ).strftime('%d.%m.%Y')}. Ближайшие матчи МЮ: {next_games or 'нет данных'}."
    for chat_id, text, qlang in questions[:MAX_QUESTIONS_PER_RUN]:
        if chat_id == state["chat_id"]:
            send(chat_id, ask_gemini(text, context, qlang))

with open("state.json", "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False)
