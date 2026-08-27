import json
import requests
from datetime import datetime, timezone

API_URL = "https://www.gamerpower.com/api/giveaways?sort-by=date"
ALLOWED_PLATFORM_KEYWORDS = ['pc', 'steam', 'epic', 'gog', 'playstation', 'ps4', 'ps5']

try:
    response = requests.get(API_URL, timeout=20)
    response.raise_for_status()
    api_games = response.json()
except Exception as e:
    print(f"Ошибка запроса к API: {e}")
    api_games = None

current_games = []
if isinstance(api_games, list):
    for g in api_games:
        # /giveaways и так отдаёт только активные, но на всякий случай подстрахуемся
        status = str(g.get('status', 'active')).lower()
        if status != 'active':
            continue
        platforms = (g.get('platforms') or '').lower()
        if not any(p in platforms for p in ALLOWED_PLATFORM_KEYWORDS):
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

if current_games:
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "giveaways": current_games[:40]
    }
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"База данных успешно обновлена! Раздач: {len(current_games)}")
else:
    # Если API недоступен или ничего не найдено — не затираем старый data.json пустышкой
    print("Новых данных нет (API недоступен или пусто) — data.json не тронут.")
