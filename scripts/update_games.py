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

# ================= РОЗЫСКНОЙ СПИСОК: ЛЮБОЙ ПОСЕТИТЕЛЬ МОЖЕТ ПОДПИСАТЬСЯ =================
# Посетитель сайта вводит название игры → сайт открывает Telegram-бота со
# специальной ссылкой t.me/<бот>?start=w_<код>. Бот получает эту команду,
# бот сохраняет подписку (subscribers.json) и дальше уведомляет ИМЕННО
# этого человека, когда игра появится на доске. Работает через обычный
# опрос getUpdates раз в 3 часа (тем же Action) — отдельный сервер не нужен.
#
# subscribers.json  — {"<chat_id>": ["ключевое слово", ...], ...}
# telegram_offset.json — {"offset": <последний обработанный update_id + 1>}
# notified.json     — {"<chat_id>": [<id раздачи>, ...], ...}  (кому что уже отправили)
# wanted.json + TELEGRAM_CHAT_ID — старый личный список владельца, для
#   совместимости он просто подмешивается как ещё один подписчик.

import base64

def load_json_file(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def save_json_file(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def decode_start_payload(payload):
    try:
        s = payload.replace('-', '+').replace('_', '/')
        s += '=' * (-len(s) % 4)
        return base64.b64decode(s).decode('utf-8').strip()
    except Exception:
        return None

def telegram_api(method, params=None):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        return None
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=params or {}, timeout=15)
        return resp.json()
    except Exception as e:
        print(f"Telegram API ошибка ({method}): {e}")
        return None

def send_telegram_message(chat_id, text):
    result = telegram_api('sendMessage', {
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": False,
    })
    return bool(result and result.get('ok'))

def poll_telegram_commands():
    """Читаем новые сообщения боту (команды /watch, /unwatch, /list, ссылки со старта
    сайта) и обновляем subscribers.json. Возвращает актуальный словарь подписчиков."""
    subs = load_json_file('subscribers.json', {})
    if not os.environ.get('TELEGRAM_BOT_TOKEN'):
        return subs

    state = load_json_file('telegram_offset.json', {"offset": 0})
    result = telegram_api('getUpdates', {'offset': state.get('offset', 0), 'timeout': 0})
    if not result or not result.get('ok'):
        return subs

    for upd in result.get('result', []):
        state['offset'] = upd['update_id'] + 1
        msg = upd.get('message') or upd.get('edited_message')
        if not msg or 'text' not in msg:
            continue
        chat_id = str(msg['chat']['id'])
        text = msg['text'].strip()

        if text.startswith('/start w_'):
            game = decode_start_payload(text[len('/start w_'):].strip())
            if game:
                subs.setdefault(chat_id, [])
                if game.lower() not in [g.lower() for g in subs[chat_id]]:
                    subs[chat_id].append(game)
                send_telegram_message(chat_id, f"🤠 Записал в твой розыскной список: «{game}».\nКак только раздача появится на доске — сразу дам знать сюда.")
        elif text.lower().startswith('/watch '):
            game = text[len('/watch '):].strip()
            if game:
                subs.setdefault(chat_id, [])
                if game.lower() not in [g.lower() for g in subs[chat_id]]:
                    subs[chat_id].append(game)
                send_telegram_message(chat_id, f"🤠 Добавил «{game}» в твой розыскной список.")
        elif text.lower().startswith('/unwatch '):
            game = text[len('/unwatch '):].strip().lower()
            if chat_id in subs:
                subs[chat_id] = [g for g in subs[chat_id] if g.lower() != game]
                send_telegram_message(chat_id, f"Убрал «{game}» из списка.")
        elif text.lower() == '/list':
            games = subs.get(chat_id, [])
            reply = 'Твой розыскной список пуст. Пришли /watch Название игры, чтобы добавить.' if not games \
                else 'Разыскиваются:\n' + '\n'.join(f'• {g}' for g in games)
            send_telegram_message(chat_id, reply)
        elif text.lower() in ('/start', '/help'):
            send_telegram_message(chat_id, (
                "🤠 Добро пожаловать в Салун Раздач!\n\n"
                "Команды:\n"
                "/watch Название игры — добавить в розыскной список\n"
                "/unwatch Название игры — убрать из списка\n"
                "/list — показать список\n\n"
                "Или просто впиши название на сайте в поле «Мой розыскной список» — я сам всё сделаю."
            ))

    save_json_file('telegram_offset.json', state)
    save_json_file('subscribers.json', subs)
    return subs

def check_wanted_and_notify(games):
    subscribers = poll_telegram_commands()

    # старый личный список владельца (wanted.json + секрет TELEGRAM_CHAT_ID)
    # подмешиваем как ещё одного подписчика — для обратной совместимости
    owner_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    owner_wanted = load_wanted_list()
    if owner_chat_id and owner_wanted:
        subscribers.setdefault(owner_chat_id, [])
        existing_lower = [g.lower() for g in subscribers[owner_chat_id]]
        for w in owner_wanted:
            if w not in existing_lower:
                subscribers[owner_chat_id].append(w)

    if not subscribers:
        print("Подписчиков розыскного списка нет — уведомления пропущены.")
        return

    notified = load_json_file('notified.json', {})
    total_hits = 0

    for chat_id, keywords in subscribers.items():
        keywords_lower = [k.lower() for k in keywords if k.strip()]
        if not keywords_lower:
            continue
        already = set(str(x) for x in notified.get(chat_id, []))
        for g in games:
            gid = str(g.get('id'))
            if gid in already:
                continue
            title_lower = (g.get('title') or '').lower()
            matched = next((k for k in keywords_lower if k in title_lower), None)
            if not matched:
                continue
            message = (
                f"🤠 <b>Шериф нашёл то, что вы искали!</b>\n\n"
                f"<b>{g.get('title')}</b>\n"
                f"Совпадение по слову: «{matched}»\n"
                f"Награда: {g.get('worth') or 'уточняется'}\n"
                f"Забрать: {g.get('url') or ''}"
            )
            if send_telegram_message(chat_id, message):
                total_hits += 1
            already.add(gid)
        notified[chat_id] = sorted(already)

    save_json_file('notified.json', notified)
    print(f"Розыскной список: подписчиков — {len(subscribers)}, отправлено уведомлений — {total_hits}.")

def load_wanted_list():
    try:
        with open('wanted.json', 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return [str(w).strip().lower() for w in raw if str(w).strip()]
    except Exception:
        return []

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
