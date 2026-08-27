import json
import requests
from datetime import datetime, timezone

API_URL = "https://www.gamerpower.com/api/giveaways?sort-by=date"
ALLOWED_PLATFORM_KEYWORDS = ['pc', 'steam', 'epic', 'gog', 'playstation', 'ps4', 'ps5']
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ShnnzySaloonBot/1.0; +https://shnnzy.github.io)",
    "Accept": "application/json",
}

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

if isinstance(api_games, list):
    for g in api_games:
        status = str(g.get('status', 'active')).lower()
        if status != 'active':
            skipped_status += 1
            continue
        platforms = (g.get('platforms') or '').lower()
        if not any(p in platforms for p in ALLOWED_PLATFORM_KEYWORDS):
            skipped_platform += 1
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
            "type": g.get('type'),
        })
    print(f"Прошли фильтр: {len(current_games)} | отсеяно по статусу: {skipped_status} | отсеяно по платформе: {skipped_platform}")

if current_games:
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "giveaways": current_games[:40]
    }
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"База данных успешно обновлена! Раздач: {len(current_games)}")
else:
    print("Новых данных нет (API недоступен, заблокирован или пусто после фильтра) — data.json не тронут.")
