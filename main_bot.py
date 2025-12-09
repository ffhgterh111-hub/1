import discord
from discord.ext import commands, tasks
import json
import time
import threading
import re
import asyncio
from typing import Dict, Any, List, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError 
from bs4 import BeautifulSoup, Tag
# НОВЫЕ ИМПОРТЫ ДЛЯ РАБОТЫ С ВРЕМЕННЫМИ ЗОНАМИ
from datetime import datetime, timezone, timedelta
import os

# =================================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# =================================================================

# !!! ВАЖНО: ЗАМЕНИТЕ ЭТО НА ВАШ ТОКЕН И УБЕДИТЕСЬ, ЧТО ОН ЗАКРЫТ ОДИНАРНОЙ КАВЫЧКОЙ !!!
BOT_TOKEN = os.environ.get('BOT_TOKEN') 

# URL для скрапинга. ИЗМЕНЕНИЕ: Форсируем UTC, чтобы время было независимо от хоста.
URL = 'https://browse.wf/arbys#days=30&tz=utc&hourfmt=24' 
CONFIG_FILE = 'config.json'
SCRAPE_INTERVAL_SECONDS = 300  # Скрапинг раз в 5 минут (обновление данных)
MISSION_UPDATE_INTERVAL_SECONDS = 10 # Безопасный интервал обновления Discord сообщений
MAX_UPCOMING_FIELD_LENGTH = 950 

# --- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ---
CURRENT_MISSION_STATE = {"ArbitrationSchedule": {}}
LAST_SCRAPE_TIME = 0 
CONFIG: Dict[str, Any] = {}

# --- КОНСТАНТЫ ЦВЕТОВ ТИРОВ ---
TIER_COLORS = {
    "S": 0x228BE6, "A": 0x40C057, "B": 0xFFEE58, "C": 0xFAB005, 
    "D": 0xF57F17, "F": 0xFA5252 
}
FALLBACK_COLOR = 0xAAAAAA

# --- КОНСТАНТЫ СТИЛИЗАЦИИ И ЭМОДЗИ ---
EMOJI_NAMES = {
    # Фракции
    "Гринир": "gren", "Корпус": "corp", "Зараженные": "infest", 
    "Орокин": "orokin", "Шёпот": "murmur",
    # Тиры
    "S": "S_", "A": "A_", "B": "B_", "C": "C_", "D": "D_", "F": "F_",
    # Новые (для шапки)
    "ВИТУС": "vitus", # Vitus
    "КУВА": "kuva"    # Kuva
}
# Словари для хранения реально найденных строк эмодзи (с ID)
RESOLVED_EMOJIS: Dict[str, str] = {}
FACTION_EMOJIS_FINAL: Dict[str, str] = {} 
TIER_EMOJIS_FINAL: Dict[str, str] = {}
FALLBACK_EMOJI = "❓" 

# Новые ключи для удобства
KUVA_EMOJI_KEY = "КУВА"
VITUS_EMOJI_KEY = "ВИТУС"

# --- КОНСТАНТЫ ФРАКЦИОННЫХ ИЗОБРАЖЕНИЙ (ДЛЯ ТАЙЛСЕТА) ---
FACTION_IMAGE_URLS = {
    "Зараженные": "https://images-ext-1.discordapp.net/external/9_z1utcRwJxSSw4n6ebRLAzqynWnAJAVJDphsjyrg9E/https/assets.empx.cc/Lotus/Interface/Graphics/WorldStatePanel/Infested.png?format=webp&quality=lossless",
    "Гринир": "https://images-ext-1.discordapp.net/external/Wmh0isPGDXG8s1_xJKjSW_F6CHl6aBQXoRIINUdvm0g/https/assets.empx.cc/Lotus/Interface/Graphics/WorldStatePanel/Grineer.png?format=webp&quality=lossless",
    "Корпус": "https://images-ext-1.discordapp.net/external/BUNqoLvclDjqa3OUzE04XI4E1nXvU8qR9f_IIb5AP7o/https/assets.empx.cc/Lotus/Interface/Graphics/WorldStatePanel/Corpus.png?format=webp&quality=lossless",
    "Орокин": "https://assets.empx.cc/Lotus/Interface/Graphics/WorldStatePanel/Corrupted.png",
    "Шёпот": "https://i.imgur.com/gK2oQ9Z.png"
}

# --- ПОЛНАЯ РУСИФИКАЦИЯ ТИПОВ МИССИЙ ---
MISSION_TYPE_TRANSLATIONS = {
    "Exterminate": "Зачистка", "Capture": "Захват", "Mobile Defense": "Мобильная оборона",
    "Defense": "Оборона", "Survival": "Выживание", "Interception": "Перехват",
    "Rescue": "Спасение", "Spy": "Шпионаж", "Sabotage": "Диверсия",
    "Extraction": "Извлечение", "Disruption": "Сбой", "Assault": "Штурм",
    "Crossfire": "Перестрелка", "Alchemy": "Алхимия", "Void Cascade": "Каскад Бездны",
    "Void Flood": "Потоп Бездны", "MD": "Мобильная оборона", 
    "Def": "Оборона", "Excavation": "Раскопки", "Conjunction Survival": "Сопряжённое выживание",
    "Defection": "Перебежчики", 
    "Unknown Mission": "Неизвестный тип"
}


# =================================================================
# 2. УТИЛИТЫ И КОНФИГУРАЦИЯ
# =================================================================

def save_config():
    """Сохраняет настройки в файл JSON."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(CONFIG, f, indent=4)

def load_config():
    """Загружает настройки из файла JSON."""
    DEFAULT_CONFIG = {
        "ARBITRATION_CHANNEL_ID": None, 
        'LAST_ARBITRATION_MESSAGE_ID': None,
        'LAST_MENTIONED_NODE': None # Отслеживание последней упомянутой ноды
    } 
    global CONFIG
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded_config = json.load(f)
            CONFIG.update(loaded_config)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    for key, default_value in DEFAULT_CONFIG.items():
        if key not in CONFIG:
            CONFIG[key] = default_value

    save_config()

def set_current_state(data, scrape_time):
    """Обновляет текущее состояние миссий и время скрапинга."""
    global CURRENT_MISSION_STATE, LAST_SCRAPE_TIME
    CURRENT_MISSION_STATE.update(data)
    LAST_SCRAPE_TIME = scrape_time

load_config()

def normalize_faction_name(race_name: str, location: str) -> str:
    """Унифицирует имя фракции/тайлсета."""
    norm_location = location.lower()
    norm_race = (race_name or '').lower()
    
    if 'гринир' in norm_race or 'grineer' in norm_race:
        return 'Гринир'
    
    if 'корпус' in norm_race or 'corpus' in norm_race:
        return 'Корпус'
        
    infestation_keywords = [
        'зараженные', 'infested', 'заражение', 'infest', 'инфест', 
        'инфестоид', 'инфестоиды', 'рой', 'mutalist', 'муталист', 
        'eris', 'эрида', 'ur', 'hieracon'
    ]
    if any(keyword in norm_race for keyword in infestation_keywords) or \
       any(keyword in norm_location for keyword in infestation_keywords): 
        return 'Зараженные'
    
    if 'орокин' in norm_race or 'corrupted' in norm_race or 'void' in norm_location or 'бездна' in norm_location:
        return 'Орокин'

    if 'шепот' in norm_race or 'murmur' in norm_race:
        return 'Шёпот'
        
    return 'N/A' 

def get_faction_image_url(faction_name: str) -> Optional[str]:
    """Возвращает URL изображения фракции или None."""
    return FACTION_IMAGE_URLS.get(faction_name)

def resolve_custom_emojis(bot: commands.Bot):
    """Находит все пользовательские эмодзи и сохраняет их."""
    global RESOLVED_EMOJIS, FACTION_EMOJIS_FINAL, TIER_EMOJIS_FINAL, FALLBACK_EMOJI
    
    print("Начало поиска эмодзи...")
    
    # 1. Находим все нужные эмодзи
    for key_name, emoji_name in EMOJI_NAMES.items():
        custom_emoji = discord.utils.get(bot.emojis, name=emoji_name)
        if custom_emoji:
            RESOLVED_EMOJIS[emoji_name] = str(custom_emoji)
        else:
            RESOLVED_EMOJIS[emoji_name] = f"❓{key_name}❓" 

    # 2. Определяем фоллбэк
    orokin_emoji_name = EMOJI_NAMES.get("Орокин")
    orokin_emoji = RESOLVED_EMOJIS.get(orokin_emoji_name, "❓")
    FALLBACK_EMOJI = orokin_emoji if not orokin_emoji.startswith("❓") else "❓"
    
    # 3. Заполняем финальный словарь фракций
    for key in ["Гринир", "Корпус", "Зараженные", "Орокин", "Шёпот"]:
        emoji_name = EMOJI_NAMES.get(key)
        final_emoji = RESOLVED_EMOJIS.get(emoji_name, FALLBACK_EMOJI)
        FACTION_EMOJIS_FINAL[key] = final_emoji if not final_emoji.startswith("❓") else FALLBACK_EMOJI
             
    # 4. Заполняем финальный словарь тиров
    for tier in ["S", "A", "B", "C", "D", "F"]:
        emoji_name = EMOJI_NAMES.get(tier)
        final_emoji = RESOLVED_EMOJIS.get(emoji_name, tier) 
        TIER_EMOJIS_FINAL[tier] = final_emoji if not final_emoji.startswith("❓") else tier
    
    print("Поиск эмодзи завершен.")

# =================================================================
# 3. ЛОГИКА СКРАПИНГА
# =================================================================

def parse_arbitration_schedule(soup: BeautifulSoup, current_scrape_time: float) -> Dict[str, Any]:
    """Парсит данные о расписании Арбитражей из блока #log."""
    schedule = {"Current": {}, "Upcoming": [], "Notable": []}
    
    log_div = soup.find('div', id='log')
    if not log_div:
        return schedule
        
    all_missions = log_div.find_all(['b', 'span'], attrs={'data-timestamp': True})
    
    parsed_missions = []
    # --- НОВЫЙ ОБЪЕКТ ЧАСОВОГО ПОЯСА МСК (UTC+3) ---
    msk_tz = timezone(timedelta(hours=3)) 
    
    for tag in all_missions:
        try:
            text_content = tag.text.strip()
            
            # Нам больше не нужно парсить '00:00 •' из строки, так как мы будем считать его сами
            
            tier_bonus_match = re.search(r'\((.+?)\s*tier(?:,\s*(.+?))?\)$', text_content)
            if not tier_bonus_match: continue
            
            tier = tier_bonus_match.group(1).strip().upper()
            bonus = tier_bonus_match.group(2).strip() if tier_bonus_match.group(2) else 'N/A'
            
            mission_info_raw = re.sub(r'^\d{2}:\d{2}\s*•\s*', '', text_content)
            mission_info_raw = re.sub(r'\s*\(.+\)$', '', mission_info_raw).strip()
            
            mission_match = re.search(r'(.+?)\s*-\s*(.+?)\s*@\s*(.+?),\s*(.+?)$', mission_info_raw)
            if not mission_match: continue
                
            mission_type_raw = mission_match.group(1).strip()
            faction_raw = mission_match.group(2).strip()
            node = mission_match.group(3).strip()
            planet = mission_match.group(4).strip()
            
            location_combined = f"{node}, {planet}" 

            start_timestamp = int(tag.attrs['data-timestamp'])
            end_timestamp = start_timestamp + 3600 # Missions last 1 hour
            
            # --- НОВОЕ: Конвертация времени UTC в МСК для отображения ---
            utc_dt = datetime.fromtimestamp(start_timestamp, tz=timezone.utc)
            msk_dt = utc_dt.astimezone(msk_tz)
            msk_start_time_display = msk_dt.strftime('%H:%M')
            # -----------------------------------------------------------
            
            parsed_missions.append({
                "Tier": tier,
                "Type": MISSION_TYPE_TRANSLATIONS.get(mission_type_raw, mission_type_raw),
                "Faction": normalize_faction_name(faction_raw, location_combined), 
                "Node": node,
                "Planet": planet,
                "Location": location_combined,
                "Bonus": bonus,
                "StartTimeDisplay": msk_start_time_display, # Используем МСК время
                "StartTimestamp": start_timestamp,
                "EndTimestamp": end_timestamp,
            })
        except Exception as e:
            continue

    # 4. Determine Current and Upcoming Missions
    now = current_scrape_time
    parsed_missions.sort(key=lambda m: m['StartTimestamp'])
    
    current_mission: Optional[Dict[str, Any]] = None
    upcoming_missions_list: List[Dict[str, Any]] = []
    
    for mission in parsed_missions:
        start = mission['StartTimestamp']
        end = mission['EndTimestamp']
        
        if start <= now < end:
            current_mission = mission
        elif start > now:
            upcoming_missions_list.append(mission)

    # --- Current / Next Mission ---
    target_mission = current_mission
    is_active = True
    
    if not target_mission:
        if upcoming_missions_list:
            target_mission = upcoming_missions_list.pop(0) 
            is_active = False

    if target_mission:
        # Расчет времени всегда точен, т.к. основан на разнице timestamp (секунды)
        time_diff = target_mission['EndTimestamp'] - now if is_active else target_mission['StartTimestamp'] - now
        
        hours = int(time_diff // 3600)
        minutes = int((time_diff % 3600) // 60)
        seconds = int(time_diff % 60)
        
        time_raw_display = f"{minutes}м {seconds}с"
        if hours > 0: time_raw_display = f"{hours}ч {time_raw_display}"

        time_status = f"осталось {time_raw_display}" if is_active else f"через {time_raw_display}"
        
        schedule["Current"] = {
            "Tier": target_mission["Tier"],
            "Name": target_mission["Type"], 
            "Location": target_mission["Location"],
            "Node": target_mission["Node"], 
            "Type": target_mission["Type"], 
            "Tileset": target_mission["Faction"], 
            "Bonus": target_mission["Bonus"],
            "TimeRaw": time_status,
            "StartTimestamp": target_mission["StartTimestamp"],
            "IsActive": is_active
        }
    else:
        schedule["Current"] = {"Tier": "N/A", "TimeRaw": "Нет данных", "IsActive": False, "Node": "N/A"}


    # --- Upcoming Missions ---
    
    for mission in upcoming_missions_list:
        time_until_start = mission['StartTimestamp'] - now
        
        if time_until_start > 0:
            hours = int(time_until_start // 3600)
            minutes = int((time_until_start % 3600) // 60)
            
            if hours > 0:
                time_raw_display = f"через {hours}:{minutes:02}"
            else:
                time_raw_display = f"через {minutes}м"

            schedule["Upcoming"].append({
                "Tier": mission["Tier"], 
                "Name": mission["Type"], 
                "Location": mission["Location"],
                "Faction": mission["Faction"],
                "StartTimeDisplay": mission["StartTimeDisplay"], 
                "TimeRaw": time_raw_display,
                "TimeInSeconds": time_until_start,
            })
            
    schedule["Upcoming"] = schedule["Upcoming"][:20] 
    
    return schedule

def parse_warframe_state():
    """Скрапинг данных с browse.wf и парсинг Арбитражей."""
    print(f"[{time.strftime('%H:%M:%S')}] 🔄 Запуск скрапинга Арбитража...")
    current_scrape_time = time.time()
    results = {"ArbitrationSchedule": {}}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(60000)
            page.goto(URL, wait_until="domcontentloaded") 
            page.wait_for_selector('#log', timeout=30000) 
            time.sleep(1.5) 
            soup = BeautifulSoup(page.content(), 'html.parser')
            browser.close()
            
            results["ArbitrationSchedule"] = parse_arbitration_schedule(soup, current_scrape_time)
            
    except PlaywrightTimeoutError:
        print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Таймаут при загрузке данных.")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 🚨 Критическая ошибка скрапинга: {e}")

    arb_tier = results["ArbitrationSchedule"]["Current"].get("Tier", "N/A")
    print(f"[{time.strftime('%H:%M:%S')}] ✅ Скрапинг завершен. Арбитраж: {arb_tier}.")
    set_current_state(results, current_scrape_time)
    return results

def mission_update_loop():
    """Постоянный цикл для периодического скрапинга в фоновом потоке."""
    while True:
        parse_warframe_state()
        time.sleep(SCRAPE_INTERVAL_SECONDS)

def start_scraper():
    """Запускает цикл скрапинга в отдельном потоке."""
    tracker_thread = threading.Thread(target=mission_update_loop, daemon=True)
    tracker_thread.start()


# =================================================================
# 4. ЛОГИКА ОБНОВЛЕНИЯ КАНАЛА
# =================================================================

async def send_or_edit_message(message_id_key: str, channel: discord.TextChannel, embed: discord.Embed, content: str = None):
    """Отправляет или редактирует сообщение в канале. Добавлен параметр content."""
    
    # Удаляем content, если он пустой, чтобы не редактировать сообщение без необходимости
    if content is None or content.strip() == "":
        content = None
    
    try:
        message_id = CONFIG.get(message_id_key) 
        
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(content=content, embed=embed, view=None)
                return
            except discord.NotFound:
                pass 
        
        # Передаем content здесь
        sent_message = await channel.send(content=content, embed=embed)
        CONFIG[message_id_key] = sent_message.id
        save_config()
        
    except discord.Forbidden:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Нет прав для отправки/редактирования в канале {channel.name}.")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 🚨 Ошибка при обновлении канала {channel.name}: {e}")
        if isinstance(e, discord.HTTPException) and e.status == 400:
             print(f"[{time.strftime('%H:%M:%S')}] 🚨 Ошибка HTTP 400: {e.text}")


async def update_arbitration_channel(bot: commands.Bot):
    """Обновляет канал с Расписанием Арбитражей (ротацией)."""
    arb_id = CONFIG.get('ARBITRATION_CHANNEL_ID')
    if not arb_id: return
    arb_channel = bot.get_channel(arb_id)
    if not arb_channel: return

    data = CURRENT_MISSION_STATE.get("ArbitrationSchedule", {})
    
    current_arb = data.get("Current", {})
    upcoming = data.get("Upcoming", [])
    
    # 1. Определение цвета, тира и статуса
    embed_tier = current_arb.get("Tier", "N/A").upper()
    embed_color = TIER_COLORS.get(embed_tier, FALLBACK_COLOR)
    tier_emoji = TIER_EMOJIS_FINAL.get(embed_tier, embed_tier) 
    time_raw = current_arb.get('TimeRaw', 'N/A')
    is_active = current_arb.get('IsActive', False)
    
    # 2. Эмодзи и Изображение Фракции
    faction_name = current_arb.get('Tileset', 'N/A')
    faction_emoji = FACTION_EMOJIS_FINAL.get(faction_name, FALLBACK_EMOJI)
    faction_url = get_faction_image_url(faction_name)
    
    # 3. Получение эмодзи Кувы и Витуса
    vitus_emoji_name = EMOJI_NAMES.get(VITUS_EMOJI_KEY)
    kuva_emoji_name = EMOJI_NAMES.get(KUVA_EMOJI_KEY)
    vitus_emoji = RESOLVED_EMOJIS.get(vitus_emoji_name, "⭐")
    kuva_emoji = RESOLVED_EMOJIS.get(kuva_emoji_name, "⚡️")

    # 4. Линковка роли (ДИНАМИЧЕСКИЙ ПОИСК И ЛОГИКА УВЕДОМЛЕНИЯ)
    content_to_send: Optional[str] = None
    node_name = current_arb.get('Node') 
    
    # --- Логика Уведомления и Удержания ---
    current_node_key = f"{node_name}_{current_arb.get('StartTimestamp')}" if is_active else None
    last_mentioned_key = CONFIG.get('LAST_MENTIONED_NODE')
    
    should_find_role = False
    
    if is_active and node_name and arb_channel.guild:
        
        if current_node_key != last_mentioned_key:
            # СЛУЧАЙ 1: НОВАЯ АКТИВНАЯ МИССИЯ (нужно уведомить и сохранить ключ)
            should_find_role = True
            CONFIG['LAST_MENTIONED_NODE'] = current_node_key
            save_config()
            print(f"[{time.strftime('%H:%M:%S')}] DEBUG: Активировано УВЕДОМЛЕНИЕ для ноды: {node_name}")
            
        elif current_node_key == last_mentioned_key:
            # СЛУЧАЙ 2: МИССИЯ ПРОДОЛЖАЕТСЯ (нужно только сохранить упоминание в сообщении)
            should_find_role = True
            
    elif not is_active and last_mentioned_key:
        # СЛУЧАЙ 3: МИССИЯ ЗАКОНЧИЛАСЬ (сбрасываем ключ, чтобы очистить упоминание)
        CONFIG['LAST_MENTIONED_NODE'] = None
        save_config()

    
    if should_find_role and node_name and arb_channel.guild:
        # Ищем роль по имени (точное совпадение)
        target_role = discord.utils.get(arb_channel.guild.roles, name=node_name)
        
        if target_role:
            # Устанавливаем упоминание, которое будет отображаться (и уведомит только в СЛУЧАЕ 1)
            content_to_send = f"{target_role.mention}" 
            print(f"[{time.strftime('%H:%M:%S')}] DEBUG: Роль найдена для ноды {node_name}. Mention: {content_to_send}")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] DEBUG: Роль НЕ НАЙДЕНА для ноды: {node_name}. Проверьте точное совпадение имени.")

    # --- 3. EMBED CONSTRUCTION ---
    embed = discord.Embed(
        title=f"{vitus_emoji} РАСПИСАНИЕ АРБИТРАЖЕЙ",
        url="https://browse.wf/arbys", 
        color=embed_color
    )
    
    # --- A. Current / Next Active Mission ---
    if current_arb.get("Name"):
        
        tier_display = f"{tier_emoji} Тир" if embed_tier != "N/A" else ""
        
        if not is_active:
            title_line = f"{kuva_emoji} **СЛЕДУЮЩИЙ АРБИТРАЖ ({tier_display}):**"
        else:
            # Заголовок без упоминания
            title_line = f"{kuva_emoji} **ТЕКУЩИЙ АРБИТРАЖ ({tier_display}):**" 
            
        description_value = (
            f"**{current_arb.get('Name', 'N/A')}**\n"
            f"Локация: **{current_arb.get('Location', 'N/A')}**\n"
            f"Враг: {faction_emoji} **{faction_name}**\n"
            f"Бонус: **{current_arb.get('Bonus', 'N/A')}**\n"
            f"Время: **`{time_raw}`**"
        )
        embed.add_field(name=title_line, value=description_value, inline=False)
        
        if faction_url:
            embed.set_thumbnail(url=faction_url)
        
    else:
        embed.description = "**Актуальное расписание миссий не найдено.**\nПожалуйста, подождите следующего скрапинга. (Тир: N/A)"
        embed.color = discord.Color.red()
        
    # --- B. Upcoming Missions ---
    upcoming_lines = []
    UPCOMING_LIMIT = 5 
    
    if upcoming:
        missions_to_display = upcoming[:UPCOMING_LIMIT] 
        
        for m in missions_to_display:
            upc_tier_emoji = TIER_EMOJIS_FINAL.get(m['Tier'], m['Tier'])
            upc_faction_emoji = FACTION_EMOJIS_FINAL.get(m['Faction'], FALLBACK_EMOJI)
            
            # ВНИМАНИЕ: Здесь m['StartTimeDisplay'] всегда в МСК, благодаря новой логике парсинга
            line = (
                f"{upc_tier_emoji} | {m['StartTimeDisplay']} • {upc_faction_emoji} ({m['Location']}) **{m['TimeRaw']}**"
            )
            upcoming_lines.append(line)
    
    if upcoming_lines:
        field_value = "\n".join(upcoming_lines)
    else:
        field_value = "Нет данных о грядущих миссиях."
        
    embed.add_field(
        name="\u200b\n— — — БЛИЖАЙШИЕ 5 МИССИЙ — — —", 
        value=field_value,
        inline=False
    )
    
    # --- C. Tier-Specific Highlights ---
    TIERS_TO_HIGHLIGHT = ["S", "A", "B"]

    embed.add_field(name="\u200b", value="— — — ВЫДЕЛЕННЫЕ ТИРЫ — — —", inline=False)

    for tier in TIERS_TO_HIGHLIGHT:
        next_mission = next((m for m in upcoming if m['Tier'].upper() == tier), None)
        
        tier_emoji = TIER_EMOJIS_FINAL.get(tier, tier)
        field_name = f"Ближайший {tier_emoji} Тир"
        
        if next_mission:
            upc_faction_emoji = FACTION_EMOJIS_FINAL.get(next_mission['Faction'], FALLBACK_EMOJI)
            field_value = (
                f"{upc_faction_emoji} ({next_mission['Location']})\n"
                f"в **{next_mission['StartTimeDisplay']}** ({next_mission['TimeRaw']})"
            )
            embed.add_field(name=field_name, value=field_value, inline=True)
        else:
            embed.add_field(name=field_name, value="Нет в ближайшем логе.", inline=True)


    embed.set_footer(text=f"Обновлено: {time.strftime('%H:%M:%S')} | Данные: browse.wf/arbys | Время: МСК (UTC+3)")
    
    # ОТПРАВКА: content_to_send будет содержать упоминание, если миссия активна
    await send_or_edit_message('LAST_ARBITRATION_MESSAGE_ID', arb_channel, embed, content=content_to_send)


# =================================================================
# 5. ОСНОВНОЙ КОД БОТА И КОМАНДЫ
# =================================================================

# Запуск скрапинга в отдельном потоке
start_scraper()

# Убедитесь, что намерение 'guilds' включено
intents = discord.Intents.default()
intents.message_content = True 
intents.guilds = True 
intents.emojis_and_stickers = True

bot = commands.Bot(command_prefix='!', intents=intents)

@tasks.loop(seconds=MISSION_UPDATE_INTERVAL_SECONDS)
async def mission_update_task():
    """Задача Discord Tasks для периодического обновления только канала Арбитража."""
    await update_arbitration_channel(bot)

@bot.event
async def on_ready():
    print(f'Бот готов: {bot.user}')
    
    # 1. Разрешение эмодзи
    resolve_custom_emojis(bot)
    
    # 2. Ожидаем завершения первого скрапинга
    while LAST_SCRAPE_TIME == 0:
        await asyncio.sleep(1) 
        
    # 3. Запуск цикла
    if CONFIG.get('ARBITRATION_CHANNEL_ID'):
        print(f"Канал Арбитража настроен. Запуск цикла обновления ({MISSION_UPDATE_INTERVAL_SECONDS}с)...")
        if not mission_update_task.is_running():
             mission_update_task.start()
    else:
        print("Канал Арбитража не настроен. Используйте !set_arbitration_channel.")


@bot.command(name='set_arbitration_channel')
@commands.has_permissions(manage_guild=True)
async def set_arbitration_channel(ctx):
    """Устанавливает текущий канал как канал Расписания Арбитражей."""
    CONFIG['ARBITRATION_CHANNEL_ID'] = ctx.channel.id
    save_config()
    
    if not mission_update_task.is_running():
        if not RESOLVED_EMOJIS: resolve_custom_emojis(bot) 
        while LAST_SCRAPE_TIME == 0:
            await asyncio.sleep(1)
        mission_update_task.start()
        
    await update_arbitration_channel(bot)
    await ctx.send(f"✅ Канал **Расписания Арбитражей** установлен на: {ctx.channel.mention} и запущен.", delete_after=10)

if __name__ == '__main__':
    try:
        if BOT_TOKEN == 'MTQ0MjczMTczNzQ1MTk4NzE2MA.GAaNCy.Y1as9m_1qxxUd8eWCONBo7md3Jd9iYwf3nXw0U':
            print("\n\n-- ВНИМАНИЕ --")
            print("Пожалуйста, замените BOT_TOKEN на ваш реальный Discord-токен.")
            
        bot.run(BOT_TOKEN) 
    except discord.errors.LoginFailure:
        print("\n\n-- ОШИБКА АВТОРИЗАЦИИ --")
        print("Проверьте, правильно ли вы вставили BOT_TOKEN!")
    except Exception as e:

        print(f"Произошла ошибка при запуске бота: {e}")
