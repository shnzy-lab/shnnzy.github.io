import json
import os
import re
import requests
from datetime import datetime, timezone

API_URL = "https://www.gamerpower.com/api/giveaways?sort-by=date"
ALLOWED_PLATFORM_KEYWORDS = ['pc', 'steam', 'epic', 'gog', 'playstation', 'ps4', 'ps5']
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ShnnzySaloonBot/1.0; +https://shnnzy.github.io)",
    "Accept": "application/json",
}

# GamerPower официально даёт только 3 типа: game / loot / beta.
# DLC, дополнения и сюжетные паки прячутся внутри "loot" вместе со скинами
# и внутриигровой валютой — их отличаем по ключевым словам в названии/описании.
DLC_KEYWORDS = [
    'dlc', 'expansion', 'add-on', 'addon', 'season pass',
    'content pack', 'story pack', 'chapter pack', 'expansion pass', 'bonus content'
]

# Всё, что не игра и не дополнение к игре: билеты, мерч, подписки, железо и т.п.
JUNK_KEYWORDS = [
    'concert', 'ticket', 'tickets', 'merch', 'merchandise', 'hoodie',
    't-shirt', 'tshirt', 'mug', 'poster', 'nft', 'gift card', 'giftcard',
    'subscription', 'keyboard', 'mouse', 'headset', 'monitor',
    'graphics card', 'gpu', 'laptop', 'smartphone', 'tour',
    'meet and greet', 'vip pass', 'convention', 'plush', 'figure',
    'collectible', 'artbook', 'art book', 'backpack', 'jacket', 'cap ', ' hat ',
    'mousepad', 'keycap', 'vinyl', 'soundtrack cd', 'physical edition',
    'statue', 'amiibo', 'controller', 'steering wheel', 'vr headset',
    'phone case', 'sticker', 'enamel pin', 'lanyard', 'festival',
    'expo pass', 'access pass', 'webinar', 'course', 'ebook', 'e-book',
    'voucher', 'coupon code', 'cashback', 'crypto', 'token airdrop'
]

# GamerPower обычно пишет реального раздатчика в скобках в конце заголовка:
# "Название (Раздатчик) Giveaway". Полностью исключаем эти источники —
# они не нужны на доске вообще, ни в одной вкладке.
EXCLUDED_SITE_KEYWORDS = ['itch.io', 'itchio', 'indiegala', 'stove']

def site_label_from(title):
    if not title:
        return ''
    matches = re.findall(r'\(([^)]+)\)', title)
    if not matches:
        return ''
    return matches[-1].strip().lower()

def is_excluded_source(title, description):
    site = site_label_from(title)
    if any(k in site for k in EXCLUDED_SITE_KEYWORDS):
        return True
    text = ((title or '') + ' ' + (description or '')).lower()
    # Alienware Arena часто прячется за "(Steam) Key Giveaway" — в скобках
    # платформа ключа, а не раздатчик. Ловим по их внутренней валюте ARP
    # (Arena Reward Points) и прямому упоминанию Alienware.
    if 'alienware' in text or 'arena reward point' in text or re.search(r'\barp\b', text):
        return True
    return False

# ================= РОЗЫСКНОЙ СПИСОК И УВЕДОМЛЕНИЯ В TELEGRAM =================
# wanted.json — список ключевых слов (названий игр), которые ищет владелец сайта.
# notified.json — id раздач, о которых уже отправлено уведомление (чтобы не дублировать).
# TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — секреты репозитория, см. README по настройке.

def load_wanted_list():
    try:
        with open('wanted.json', 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return [str(w).strip().lower() for w in raw if str(w).strip()]
    except Exception:
        return []

def load_notified_ids():
    try:
        with open('notified.json', 'r', encoding='utf-8') as f:
            return set(str(x) for x in json.load(f))
    except Exception:
        return set()

def save_notified_ids(ids):
    with open('notified.json', 'w', encoding='utf-8') as f:
        json.dump(sorted(ids), f)

def send_telegram_message(text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("Telegram не настроен (нет TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID в секретах) — уведомление пропущено.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"Telegram вернул ошибку {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"Не удалось отправить сообщение в Telegram: {e}")
        return False

def check_wanted_and_notify(games):
    wanted = load_wanted_list()
    if not wanted:
        print("wanted.json пуст или отсутствует — уведомления пропущены.")
        return
    notified = load_notified_ids()
    newly_notified = set(notified)
    hits = 0
    for g in games:
        gid = str(g.get('id'))
        if gid in notified:
            continue
        title_lower = (g.get('title') or '').lower()
        matched = next((w for w in wanted if w in title_lower), None)
        if not matched:
            continue
        message = (
            f"🤠 <b>Шериф нашёл то, что вы искали!</b>\n\n"
            f"<b>{g.get('title')}</b>\n"
            f"Совпадение по слову: «{matched}»\n"
            f"Награда: {g.get('worth') or 'уточняется'}\n"
            f"Забрать: {g.get('url') or ''}"
        )
        if send_telegram_message(message):
            hits += 1
        newly_notified.add(gid)
    if newly_notified != notified:
        save_notified_ids(newly_notified)
    print(f"Розыскной список: совпадений найдено — {hits}.")

api_games = None
try:
    response = requests.get(API_URL, headers=HEADERS, timeout=20)
    print(f"HTTP статус: {response.status_code}")
    response.raise_for_status()
    api_games = response.json()
    print(f"Получено от API: {len(api_games) if isinstance(api_games, list) else 'не список!'} записей")
except requests.exceptions.RequestException as e:
    print(f"Ошибка запроса к API: {e}")
except ValueError as e:
    print(f"Ответ пришёл, но это не JSON: {e}")
    print(f"Начало ответа: {response.text[:300]!r}")

current_games = []
skipped_status = 0
skipped_platform = 0
skipped_junk = 0
skipped_type = 0
skipped_source = 0

if isinstance(api_games, list):
    for g in api_games:
        status = str(g.get('status', 'active')).lower()
        if status != 'active':
            skipped_status += 1
            continue

        if is_excluded_source(g.get('title'), g.get('description')):
            skipped_source += 1
            continue

        platforms = (g.get('platforms') or '').lower()
        if not any(p in platforms for p in ALLOWED_PLATFORM_KEYWORDS):
            skipped_platform += 1
            continue

        text = ((g.get('title') or '') + ' ' + (g.get('description') or '')).lower()

        if any(j in text for j in JUNK_KEYWORDS):
            skipped_junk += 1
            continue

        gtype = (g.get('type') or '').lower()
        is_full_game = gtype == 'game'
        is_dlc = gtype == 'loot' and any(k in text for k in DLC_KEYWORDS)

        if not (is_full_game or is_dlc):
            skipped_type += 1
            continue

        current_games.append({
            "id": g.get('id'),
            "title": g.get('title'),
            "description": g.get('description'),
            "worth": g.get('worth'),
            "image": g.get('image'),
            "thumbnail": g.get('thumbnail'),
            "url": g.get('open_giveaway_url'),
            "platforms": g.get('platforms'),
            "end_date": g.get('end_date'),
            "type": "dlc" if is_dlc else "game",
        })
    print(f"Прошли фильтр: {len(current_games)} | по статусу: {skipped_status} | исключённые источники (Itch.io/IndieGala/Stove/Alienware): {skipped_source} | по платформе: {skipped_platform} | мусор по словам: {skipped_junk} | по типу (loot/beta без DLC-признаков): {skipped_type}")

if current_games:
    check_wanted_and_notify(current_games)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "giveaways": current_games[:40]
    }
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"База данных успешно обновлена! Раздач: {len(current_games)}")
else:
    print("Новых данных нет (API недоступен, заблокирован или пусто после фильтра) — data.json не тронут.")
