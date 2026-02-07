import asyncio
import random
import json
import logging
import os
import sqlite3
import requests
import traceback
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from telethon import TelegramClient, events, functions, Button
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import SessionPasswordNeededError

# Импорт модуля управления конфигурацией
from config_manager import load_config, save_config, update_config_value, get_config_value

# Импорт модуля прогрева аккаунтов
from account_warmup import warmup_manager

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system env vars only

API_ID = 36053254
API_HASH = '4c63aee24cbc1be5e593329370712e7f'
BOT_TOKEN = '8544528676:AAGWL7WuTONeTo5Lse6AiATtg4nEcssKuWc'
BOT_OWNER_ID = 6730216440

# ============= PROFILE OPERATIONS PROTECTION =============
# Список проверенных рабочих аккаунтов (обновляется по результатам тестов)
WORKING_ACCOUNTS = [
    '+13434919340'  # Проверено: BIO ✅, NAME ✅, AVATAR ✅
]

# Аккаунты с FROZEN блокировкой (не использовать для profile operations)
FROZEN_ACCOUNTS = [
    '+13435909132',  # FROZEN: все методы заблокированы
    '+15482373234'   # FROZEN: все методы заблокированы
]

# Лог операций с профилем для rate limiting
profile_operations_log = {}  # {f"{phone}:{operation}": datetime}

# Лимиты операций (защита от блокировки)
PROFILE_OPERATION_LIMITS = {
    'bio': timedelta(hours=1),      # BIO: макс 1 раз в час
    'name': timedelta(hours=1),     # NAME: макс 1 раз в час
    'avatar': timedelta(hours=24)   # AVATAR: макс 1 раз в день
}

# ============= SUPER ADMINS =============
# Two super admins who can see global stats and manage other admins
SUPER_ADMINS = [6730216440, 5912533270]
# ============= END SUPER ADMINS =============

DB_NAME = 'bot_data.json'
SQLITE_DB = 'bot_advanced.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= RATE LIMITING & ROTATION SETTINGS =============
# Лимиты скорости отправки сообщений
MIN_MESSAGES_PER_HOUR = 20  # Минимум сообщений в час на аккаунт
MAX_MESSAGES_PER_HOUR = 40  # Максимум сообщений в час на аккаунт
DEFAULT_MESSAGES_PER_HOUR = 20  # По умолчанию используем консервативное значение

# Максимальное количество одновременно активных аккаунтов
DEFAULT_MAX_ACTIVE_ACCOUNTS = 2

# Интервал ротации аккаунтов (в секундах)
# По умолчанию: 4 часа (14400 секунд)
DEFAULT_ROTATION_INTERVAL = 14400

# Интервал между комментариями от разных аккаунтов в одном чате (в секундах)
# Используется случайное значение из диапазона для естественности
MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS = 180  # 3 минуты (минимум)
MAX_INTERVAL_BETWEEN_OWN_ACCOUNTS = 420  # 7 минут (максимум)

# Статусы аккаунтов
ACCOUNT_STATUS_ACTIVE = 'active'
ACCOUNT_STATUS_RESERVE = 'reserve'
ACCOUNT_STATUS_BROKEN = 'broken'
# ============= END RATE LIMITING & ROTATION SETTINGS =============

# YandexGPT configuration from environment variables
# Поддержка YC_API_KEY/YC_FOLDER_ID или старых названий
YANDEX_API_KEY = os.getenv('YC_API_KEY') or os.getenv('YANDEX_API_KEY', '')
YANDEX_FOLDER_ID = os.getenv('YC_FOLDER_ID') or os.getenv('YANDEX_FOLDER_ID', 'b1g4or5i5s66hklqfg06')
YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# RockAPI configuration (DeepSeek via RockAPI)
ROCKAPI_KEY = os.getenv('ROCKAPI_KEY', '')
ROCKAPI_MODEL = os.getenv('ROCKAPI_MODEL', 'deepseek-chat')
ROCKAPI_BASE_URL = os.getenv('ROCKAPI_BASE_URL', 'https://api.rockapi.ru/deepseek')

# Защита от использования дорогих моделей DeepSeek
# Список разрешённых недорогих моделей
ALLOWED_MODELS = ['deepseek-chat']
# Если указана неразрешённая модель, принудительно используем deepseek-chat
if ROCKAPI_MODEL not in ALLOWED_MODELS:
    logger = logging.getLogger('telegram_bot')
    logger.warning(f"⚠️ ROCKAPI_MODEL='{ROCKAPI_MODEL}' не в списке разрешённых моделей")
    logger.warning(f"   Разрешённые модели: {', '.join(ALLOWED_MODELS)}")
    logger.warning(f"   Принудительно используется 'deepseek-chat' для экономии")
    ROCKAPI_MODEL = 'deepseek-chat'

# Выбор провайдера для генерации комментариев: 'yandex' или 'rockapi'
COMMENT_PROVIDER = os.getenv('COMMENT_PROVIDER', 'rockapi').lower()

# Опция логирования комментариев для отладки промптов
ENABLE_COMMENT_LOGGING = os.getenv('LOG_COMMENTS', '').lower() in ('true', '1', 'yes')

def generate_neuro_comment(
    post_text: str,
    channel_theme: str = "general",
    temperature: float = 0.88,
    max_tokens: int = 100,
    comment_type: str = None,
) -> str:
    """
    Генерирует живой комментарий к посту от лица девушки с помощью YandexGPT.
    Стиль: непринуждённый женский, эмоциональный, живой.
    Длина: 6-15 слов.
    """
    # Fallback comments if API is not configured or fails (женский род, БЕЗ шаблонных начал)
    fallback_comments = [
        "Мне понравилось",
        "Полезная информация",
        "Рада, что прочитала",
        "Хорошо написано",
        "Не думала об этом раньше",
        "Возьму на заметку",
        "Познавательно",
        "Прямо в точку"
    ]
    
    # Check if API key is configured
    if not YANDEX_API_KEY:
        logger.warning("❌ YANDEX_API_KEY not configured, using fallback comments")
        logger.warning("   Причина: переменные окружения YC_API_KEY и YANDEX_API_KEY не установлены")
        logger.warning("   Решение: установите YC_API_KEY в systemd unit или .env файле")
        return random.choice(fallback_comments)
    
    # Типы реакций для разнообразия (женский род, живые эмоции)
    reaction_types = [
        ("впечатление", "отреагировать на содержание с удивлением или интересом (не ожидала, впечатлилась, мне понравилось)"),
        ("резонанс", "показать, что тема близка и знакома (тоже сталкивалась, прямо про меня, замечала)"),
        ("вопрос", "задать короткий живой вопрос из любопытства (а как, интересно, пробовала?)"),
        ("поддержка", "одобрить или поддержать идею автора (согласна, правильно, именно так)"),
        ("опыт", "упомянуть свой опыт кратко (пробовала, делала, использовала)"),
        ("оценка", "дать краткую оценку с конкретикой из поста (цифры впечатляют, результат хороший)")
    ]
    
    # Выбираем тип реакции (если не передан извне)
    if not comment_type:
        chosen_type, type_description = random.choice(reaction_types)
    else:
        # Находим описание для переданного типа
        type_description = next((desc for t, desc in reaction_types if t == comment_type), reaction_types[0][1])
        chosen_type = comment_type
    
    # Контроль эмодзи: использовать умеренно (~30% случаев)
    use_emoji = random.random() < 0.30
    
    # Промпт для живых комментариев от девушки (защита от спам-фильтров)
    prompt = f"""Напиши живой естественный комментарий к посту от имени девушки.

ОБЯЗАТЕЛЬНО: Только ЖЕНСКИЙ РОД! (видела, читала, думала, поняла, попробовала, заметила, сталкивалась)

СТИЛЬ: Непринуждённый, как девушка пишет знакомым в чате. Без шаблонов и штампов.

ТИП РЕАКЦИИ: {type_description}

ДЛИНА: 6-15 слов (не короче 6, не длиннее 15 слов).

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
• Реагируй на КОНКРЕТИКУ из поста (цифры, факты, детали)
• НЕ начинай с шаблонных слов (Интересно, Круто, Классно, Отлично, Супер, Ого)
• Используй разные начала: цифры из поста, вопросы, личный опыт, оценку
• Пиши естественно, без излишних восторгов
• {"Без эмодзи" if not use_emoji else "Можешь добавить 1 эмодзи в конце"}

СТРОГО ЗАПРЕЩЕНО - АНТИСПАМ:
❌ Мужской род (видел, читал, понял, сделал, думал)
❌ Слова-паразиты: "честно говоря", "на самом деле", "в общем", "как бы", "типа", "короче", "кстати", "вообще"
❌ Начинать со слов: "Интересно", "Круто", "Классно", "Отлично", "Супер", "Ого", "Вау"
❌ Спам-слова: "невероятно", "потрясающе", "фантастика", "100%", "гарантирую", "однозначно", "обязательно попробуй"
❌ Призывы: "жми", "переходи", "регистрируйся", "подпишись", "смотри", "читай обязательно"
❌ Излишние восклицания: "!!!", "???", "🔥🔥🔥"
❌ Формальности: "благодарю", "желаю успехов", "спасибо за информацию"

ПРИМЕРЫ ХОРОШИХ КОММЕНТАРИЕВ (разные начала):
✓ "40% ускорение — не думала что настолько"
✓ "Тоже сталкивалась с этим, прямо в точку"
✓ "Пробовала этот рецепт, получилось вкусно"
✓ "В 23 года запустить — смелая была 🔥"
✓ "А как с масштабированием на больших данных?"
✓ "Заметила похожий эффект у себя"
✓ "15 минут на приготовление — быстро и удобно"

ПЛОХИЕ ПРИМЕРЫ (так НЕ пиши):
❌ "Интересно, не знала!" (шаблонное начало)
❌ "Круто, обязательно попробую!" (шаблон + призыв)
❌ "Честно говоря, впечатлилась" (слово-паразит)
❌ "Невероятно! Потрясающе! 🔥🔥🔥" (спам-слова + много эмодзи)
❌ "Видел похожее" (мужской род)

Тема: {channel_theme}

Пост:
{post_text[:800]}

Твой комментарий (начни БЕЗ шаблонных слов):"""

    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
        "completionOptions": {
            "stream": False,
            "temperature": float(temperature),
            "maxTokens": int(max_tokens),
        },
        "messages": [
            {
                "role": "user",
                "text": prompt,
            }
        ],
    }

    # Подробное логирование запроса
    logger.info("🤖 YANDEX GPT: начинаем генерацию комментария")
    logger.info(f"   Model URI: {payload['modelUri']}")
    logger.info(f"   Temperature: {temperature}, Max tokens: {max_tokens}")
    logger.info(f"   Prompt length: {len(prompt)} chars")
    logger.info(f"   Post text length: {len(post_text)} chars")
    logger.info(f"   Channel theme: {channel_theme}")
    
    try:
        logger.info("📡 Отправляем запрос к YandexGPT API...")
        response = requests.post(YANDEX_GPT_URL, headers=headers, json=payload, timeout=30)
        
        logger.info(f"📥 Получен ответ от YandexGPT: HTTP {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"❌ YandexGPT API error: HTTP {response.status_code}")
            logger.error(f"   Response headers: {dict(response.headers)}")
            
            try:
                error_data = response.json()
                logger.error(f"   Error response body: {json.dumps(error_data, ensure_ascii=False, indent=2)}")
                
                # Детальный анализ ошибки
                if response.status_code == 400:
                    logger.error("   Причина: Неверный запрос (проверьте folder_id и формат запроса)")
                elif response.status_code == 401:
                    logger.error("   Причина: Неверный API ключ или нет доступа")
                elif response.status_code == 403:
                    logger.error("   Причина: Доступ запрещён (проверьте права на folder_id)")
                elif response.status_code == 429:
                    logger.error("   Причина: Превышен лимит запросов (rate limit)")
                else:
                    logger.error(f"   Причина: Неизвестная ошибка API")
            except:
                logger.error(f"   Response text: {response.text[:500]}")
            
            logger.warning("⚠️  Использую fallback шаблоны из-за ошибки API")
            return random.choice(fallback_comments)
        
        # Парсим успешный ответ
        try:
            data = response.json()
            logger.info("✅ JSON успешно распарсен")
            
            # Проверяем структуру ответа
            if "result" not in data:
                logger.error(f"❌ Неожиданная структура ответа (нет 'result'): {json.dumps(data, ensure_ascii=False)[:500]}")
                logger.warning("⚠️  Использую fallback шаблоны")
                return random.choice(fallback_comments)
            
            if "alternatives" not in data["result"]:
                logger.error(f"❌ Неожиданная структура ответа (нет 'alternatives'): {json.dumps(data, ensure_ascii=False)[:500]}")
                logger.warning("⚠️  Использую fallback шаблоны")
                return random.choice(fallback_comments)
            
            raw_comment = data["result"]["alternatives"][0]["message"]["text"].strip()
            logger.info(f"📝 Сырой комментарий от YandexGPT: '{raw_comment}'")
            
            # Постобработка для "человечности"
            final_comment = humanize_comment(raw_comment)
            logger.info(f"✨ Финальный комментарий после обработки: '{final_comment}'")
            
            # Логирование (если включено)
            if ENABLE_COMMENT_LOGGING:
                logger.info(f"[COMMENT_GEN] Raw: {raw_comment}")
                logger.info(f"[COMMENT_GEN] Final: {final_comment}")
            
            logger.info("🎉 YandexGPT: комментарий успешно сгенерирован")
            return final_comment
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON ответа: {e}")
            logger.error(f"   Response text: {response.text[:500]}")
            logger.warning("⚠️  Использую fallback шаблоны")
            return random.choice(fallback_comments)
        except KeyError as e:
            logger.error(f"❌ Отсутствует ожидаемое поле в ответе: {e}")
            logger.error(f"   Response data: {json.dumps(data, ensure_ascii=False)[:500]}")
            logger.warning("⚠️  Использую fallback шаблоны")
            return random.choice(fallback_comments)
            
    except requests.exceptions.Timeout:
        logger.error("❌ YandexGPT API timeout (30 секунд)")
        logger.error("   Причина: API не ответил в течение 30 секунд")
        logger.warning("⚠️  Использую fallback шаблоны")
        return random.choice(fallback_comments)
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ YandexGPT connection error: {e}")
        logger.error("   Причина: не удалось подключиться к API (проверьте интернет)")
        logger.warning("⚠️  Использую fallback шаблоны")
        return random.choice(fallback_comments)
    except Exception as e:
        logger.error(f"❌ YandexGPT unexpected error: {e}")
        logger.error(f"   Traceback: {traceback.format_exc()}")
        logger.warning("⚠️  Использую fallback шаблоны")
        return random.choice(fallback_comments)

def humanize_comment(text: str) -> str:
    """
    Постобработка комментария для большей естественности.
    Убирает шаблонные начала, слова-паразиты, спам-фразы.
    Контролирует количество эмодзи.
    Защита от антиспам систем Telegram.
    """
    # Убираем лишние пробелы
    text = " ".join(text.split())
    
    # ===== УБИРАЕМ ШАБЛОННЫЕ НАЧАЛА =====
    # Если комментарий начинается с шаблонных слов, убираем их
    template_starts = [
        r'^Интересно[,!\s]+',
        r'^Круто[,!\s]+',
        r'^Классно[,!\s]+',
        r'^Отлично[,!\s]+',
        r'^Супер[,!\s]+',
        r'^Ого[,!\s]+',
        r'^Вау[,!\s]+',
        r'^Клёво[,!\s]+',
        r'^Здорово[,!\s]+',
        r'^Прикольно[,!\s]+',
    ]
    
    for pattern in template_starts:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # ===== КОНТРОЛЬ ЭМОДЗИ =====
    # Находим все эмодзи в тексте
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "]+"
    )
    
    emojis = emoji_pattern.findall(text)
    
    # Если эмодзи больше 1 или есть "стек" (повторяющиеся)
    if len(emojis) > 1 or any(len(e) > 1 for e in emojis):
        # Убираем все эмодзи
        text = emoji_pattern.sub('', text).strip()
        
        # С вероятностью 20% оставляем один случайный эмодзи в конце
        if random.random() < 0.2 and emojis:
            # Берём первый символ из первого эмодзи
            single_emoji = emojis[0][0] if emojis[0] else ''
            if single_emoji:
                text = text.rstrip() + ' ' + single_emoji
    
    # С вероятностью 75% убираем эмодзи вообще (даже если был один)
    elif emojis and random.random() < 0.75:
        text = emoji_pattern.sub('', text).strip()
    
    # Сначала удаляем формальные фразы (самые приоритетные)
    formal_replacements = {
        "Желаю вам успехов": "",
        "Желаю успехов": "",
        "Желаю удачи": "",
        "Благодарю за пост": "",
        "Спасибо за пост": "",
        "Спасибо за информацию": "",
        "Здорово, что вы": "",
        "Здорово что вы": "",
        "Рада за вас": "",
        "Рад за вас": "",
        "Это вдохновляет": "",
    }
    
    for formal, replacement in formal_replacements.items():
        if formal.lower() in text.lower():
            text = re.sub(re.escape(formal), replacement, text, flags=re.IGNORECASE)
    
    # Удаляем слова-паразиты и вводные конструкции
    filler_patterns = [
        r'\bчестно говоря,?\s*',
        r'\bна самом деле,?\s*',
        r'\bв общем,?\s*',
        r'\bв принципе,?\s*',
        r'\bкак бы,?\s+',
        r'\bтипа,?\s+',
        r'\bкороче,?\s*',
        r'\bвообще,?\s*',
        r'\bкстати,?\s*',
        r'\bпо сути,?\s*',
        r'\bдействительно,?\s*',
        r'\bбезусловно,?\s*',
    ]
    
    for pattern in filler_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Убираем спам-фразы (антиспам защита)
    spam_patterns = [
        r'\bневероятно\b',
        r'\bпотрясающе\b',
        r'\bфантастика\b',
        r'\b100%\b',
        r'\bгарантирую\b',
        r'\bоднозначно\b',
        r'\bобязательно попробуй\b',
        r'\bобязательно попробуйте\b',
        r'\bжми\b',
        r'\bпереходи\b',
        r'\bрегистрируйся\b',
        r'\bподпишись\b',
        r'\bсмотри обязательно\b',
        r'\bчитай обязательно\b',
    ]
    
    for pattern in spam_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Упрощаем длинные конструкции
    text = text.replace("Очень интересно", "Интересно")
    text = text.replace("Очень круто", "Круто")
    text = text.replace("Действительно интересно", "Интересно")
    
    # Иногда убираем запятые перед союзами (делаем более разговорным)
    if random.random() < 0.4:
        text = text.replace(", а ", " а ").replace(", но ", " но ").replace(", и ", " и ")
    
    # Иногда заменяем длинные конструкции на короткие
    if random.random() < 0.3:
        text = text.replace("является ", "— ")
        text = text.replace("представляет собой ", "— ")
        text = text.replace("не могу не сказать", "")
        text = text.replace("хочется отметить", "")
        text = text.replace("стоит отметить", "")
    
    # Убираем множественные пробелы и лишние знаки
    text = re.sub(r'\s+', ' ', text)  # Любое количество пробелов → 1
    text = re.sub(r'\s+([.,!?])', r'\1', text)  # Пробел перед знаком
    text = re.sub(r'^[.,!?\s]+', '', text)  # Знаки в начале
    
    # Убираем множественные знаки препинания (антиспам: !!! → !, ??? → ?)
    text = re.sub(r'!{2,}', '!', text)  # Много ! → один !
    text = re.sub(r'\?{2,}', '?', text)  # Много ? → один ?
    text = re.sub(r'\.{2,}', '', text)  # Убираем многоточия полностью
    
    # Убираем знаки в конце (добавим правильный позже)
    text = re.sub(r'[.,!?\s]+$', '', text)
    
    # Восстанавливаем один знак в конце если нужно
    if text and not text[-1] in '.!?':
        # Если это вопрос, добавляем ?
        if any(word in text.lower() for word in ['как', 'что', 'где', 'когда', 'почему', 'зачем', 'какой', 'сколько']):
            text += '?'
    
    # Если текст стал слишком коротким или пустым
    text = text.strip()
    if not text or len(text) < 3:
        return "Интересно"
    
    # Делаем первую букву заглавной
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    
    return text


def generate_comment_rockapi(
    post_text: str,
    channel_theme: str = "general",
    temperature: float = 0.88,
    max_tokens: int = 100,
    comment_type: str = None,
) -> str:
    """
    Генерирует живой комментарий к посту от лица девушки с помощью RockAPI (DeepSeek).
    Использует тот же промпт и параметры, что и YandexGPT.
    Стиль: непринуждённый женский, эмоциональный, живой.
    Длина: 6-15 слов.
    """
    # Fallback comments if API is not configured or fails (женский род, БЕЗ шаблонных начал)
    fallback_comments = [
        "Мне понравилось",
        "Полезная информация",
        "Рада, что прочитала",
        "Хорошо написано",
        "Не думала об этом раньше",
        "Возьму на заметку",
        "Познавательно",
        "Прямо в точку"
    ]
    
    # Check if API key is configured
    if not ROCKAPI_KEY:
        logger.warning("❌ ROCKAPI_KEY not configured, using fallback comments")
        logger.warning("   Причина: переменная окружения ROCKAPI_KEY не установлена")
        logger.warning("   Решение: установите ROCKAPI_KEY в systemd unit или .env файле")
        return random.choice(fallback_comments)
    
    # Типы реакций для разнообразия (женский род, живые эмоции)
    reaction_types = [
        ("впечатление", "отреагировать на содержание с удивлением или интересом (не ожидала, впечатлилась, мне понравилось)"),
        ("резонанс", "показать, что тема близка и знакома (тоже сталкивалась, прямо про меня, замечала)"),
        ("вопрос", "задать короткий живой вопрос из любопытства (а как, интересно, пробовала?)"),
        ("поддержка", "одобрить или поддержать идею автора (согласна, правильно, именно так)"),
        ("опыт", "упомянуть свой опыт кратко (пробовала, делала, использовала)"),
        ("оценка", "дать краткую оценку с конкретикой из поста (цифры впечатляют, результат хороший)")
    ]
    
    # Выбираем тип реакции (если не передан извне)
    if not comment_type:
        chosen_type, type_description = random.choice(reaction_types)
    else:
        # Находим описание для переданного типа
        type_description = next((desc for t, desc in reaction_types if t == comment_type), reaction_types[0][1])
        chosen_type = comment_type
    
    # Контроль эмодзи: использовать умеренно (~30% случаев)
    use_emoji = random.random() < 0.30
    
    # Промпт для живых комментариев от девушки (защита от спам-фильтров)
    # ИСПОЛЬЗУЕМ ТОТ ЖЕ ПРОМПТ, ЧТО И В generate_neuro_comment
    prompt = f"""Напиши живой естественный комментарий к посту от имени девушки.

ОБЯЗАТЕЛЬНО: Только ЖЕНСКИЙ РОД! (видела, читала, думала, поняла, попробовала, заметила, сталкивалась)

СТИЛЬ: Непринуждённый, как девушка пишет знакомым в чате. Без шаблонов и штампов.

ТИП РЕАКЦИИ: {type_description}

ДЛИНА: 6-15 слов (не короче 6, не длиннее 15 слов).

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
• Реагируй на КОНКРЕТИКУ из поста (цифры, факты, детали)
• НЕ начинай с шаблонных слов (Интересно, Круто, Классно, Отлично, Супер, Ого)
• Используй разные начала: цифры из поста, вопросы, личный опыт, оценку
• Пиши естественно, без излишних восторгов
• {"Без эмодзи" if not use_emoji else "Можешь добавить 1 эмодзи в конце"}

СТРОГО ЗАПРЕЩЕНО - АНТИСПАМ:
❌ Мужской род (видел, читал, понял, сделал, думал)
❌ Слова-паразиты: "честно говоря", "на самом деле", "в общем", "как бы", "типа", "короче", "кстати", "вообще"
❌ Начинать со слов: "Интересно", "Круто", "Классно", "Отлично", "Супер", "Ого", "Вау"
❌ Спам-слова: "невероятно", "потрясающе", "фантастика", "100%", "гарантирую", "однозначно", "обязательно попробуй"
❌ Призывы: "жми", "переходи", "регистрируйся", "подпишись", "смотри", "читай обязательно"
❌ Излишние восклицания: "!!!", "???", "🔥🔥🔥"
❌ Формальности: "благодарю", "желаю успехов", "спасибо за информацию"

ПРИМЕРЫ ХОРОШИХ КОММЕНТАРИЕВ (разные начала):
✓ "40% ускорение — не думала что настолько"
✓ "Тоже сталкивалась с этим, прямо в точку"
✓ "Пробовала этот рецепт, получилось вкусно"
✓ "В 23 года запустить — смелая была 🔥"
✓ "А как с масштабированием на больших данных?"
✓ "Заметила похожий эффект у себя"
✓ "15 минут на приготовление — быстро и удобно"

ПЛОХИЕ ПРИМЕРЫ (так НЕ пиши):
❌ "Интересно, не знала!" (шаблонное начало)
❌ "Круто, обязательно попробую!" (шаблон + призыв)
❌ "Честно говоря, впечатлилась" (слово-паразит)
❌ "Невероятно! Потрясающе! 🔥🔥🔥" (спам-слова + много эмодзи)
❌ "Видел похожее" (мужской род)

Тема: {channel_theme}

Пост:
{post_text[:800]}

Твой комментарий (начни БЕЗ шаблонных слов):"""

    # RockAPI использует OpenAI-совместимый формат
    headers = {
        "Authorization": f"Bearer {ROCKAPI_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": ROCKAPI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }

    # Подробное логирование запроса
    logger.info("🤖 ROCKAPI: начинаем генерацию комментария")
    logger.info(f"   Model: {ROCKAPI_MODEL}")
    logger.info(f"   Temperature: {temperature}, Max tokens: {max_tokens}")
    logger.info(f"   Prompt length: {len(prompt)} chars")
    logger.info(f"   Post text length: {len(post_text)} chars")
    logger.info(f"   Channel theme: {channel_theme}")
    
    try:
        api_url = f"{ROCKAPI_BASE_URL}/v1/chat/completions"
        logger.info(f"📡 Отправляем запрос к RockAPI: {api_url}")
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        
        logger.info(f"📥 Получен ответ от RockAPI: HTTP {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"❌ RockAPI error: HTTP {response.status_code}")
            logger.error(f"   Response headers: {dict(response.headers)}")
            
            try:
                error_data = response.json()
                logger.error(f"   Error response body: {json.dumps(error_data, ensure_ascii=False, indent=2)}")
            except:
                logger.error(f"   Response text: {response.text[:500]}")
            
            logger.warning("⚠️  Использую fallback шаблоны из-за ошибки API")
            return random.choice(fallback_comments)
        
        # Парсим успешный ответ (OpenAI-совместимый формат)
        try:
            data = response.json()
            logger.info("✅ JSON успешно распарсен")
            
            # OpenAI format: {"choices": [{"message": {"content": "..."}}]}
            if "choices" not in data or not data["choices"]:
                logger.error(f"❌ Неожиданная структура ответа (нет 'choices'): {json.dumps(data, ensure_ascii=False)[:500]}")
                logger.warning("⚠️  Использую fallback шаблоны")
                return random.choice(fallback_comments)
            
            raw_comment = data["choices"][0]["message"]["content"].strip()
            logger.info(f"📝 Сырой комментарий от RockAPI: '{raw_comment}'")
            
            # Постобработка для "человечности" (используем ту же функцию)
            final_comment = humanize_comment(raw_comment)
            logger.info(f"✨ Финальный комментарий после обработки: '{final_comment}'")
            
            # Логирование (если включено)
            if ENABLE_COMMENT_LOGGING:
                logger.info(f"[COMMENT_GEN_ROCKAPI] Raw: {raw_comment}")
                logger.info(f"[COMMENT_GEN_ROCKAPI] Final: {final_comment}")
            
            logger.info("🎉 RockAPI: комментарий успешно сгенерирован")
            return final_comment
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON ответа: {e}")
            logger.error(f"   Response text: {response.text[:500]}")
            logger.warning("⚠️  Использую fallback шаблоны")
            return random.choice(fallback_comments)
        except (KeyError, IndexError) as e:
            logger.error(f"❌ Отсутствует ожидаемое поле в ответе: {e}")
            logger.error(f"   Response data: {json.dumps(data, ensure_ascii=False)[:500]}")
            logger.warning("⚠️  Использую fallback шаблоны")
            return random.choice(fallback_comments)
            
    except requests.exceptions.Timeout:
        logger.error("❌ RockAPI timeout (30 секунд)")
        logger.error("   Причина: API не ответил в течение 30 секунд")
        logger.warning("⚠️  Использую fallback шаблоны")
        return random.choice(fallback_comments)
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ RockAPI request error: {e}")
        logger.warning("⚠️  Использую fallback шаблоны")
        return random.choice(fallback_comments)
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при вызове RockAPI: {e}")
        logger.error(f"   Traceback: {traceback.format_exc()}")
        logger.warning("⚠️  Использую fallback шаблоны")
        return random.choice(fallback_comments)


def normalize_account_id(phone_or_id):
    """
    Преобразует любой формат телефона в короткий ID (код страны)
    
    Примеры:
    +15178979270 → +1
    +79261234567 → +7
    +442071234567 → +44
    +380991234567 → +380
    +1 → +1 (уже короткий)
    1 → +1
    """
    if not phone_or_id:
        return None
    
    # Убираем пробелы
    phone_or_id = str(phone_or_id).strip()
    
    # Если уже короткий формат (+1, +7, +44, +380)
    if phone_or_id.startswith('+') and len(phone_or_id) <= 4:
        return phone_or_id
    
    # Если просто цифры без + (1, 7, 44, 380)
    if phone_or_id.isdigit() and len(phone_or_id) <= 3:
        return f"+{phone_or_id}"
    
    # Если полный номер - извлекаем код страны
    if phone_or_id.startswith('+'):
        digits = phone_or_id[1:]  # Убираем +
    else:
        digits = phone_or_id
    
    # Определяем код страны по первым цифрам
    # Проверяем в порядке: сначала более длинные коды (3 цифры), затем 2 цифры, затем 1 цифру
    
    # 3-цифровые коды
    if digits.startswith('380'):  # Украина
        return '+380'
    elif digits.startswith('371'):  # Латвия
        return '+371'
    elif digits.startswith('370'):  # Литва
        return '+370'
    
    # 2-цифровые коды
    elif digits.startswith('86'):  # Китай
        return '+86'
    elif digits.startswith('44'):  # UK
        return '+44'
    elif digits.startswith('49'):  # Германия
        return '+49'
    
    # 1-цифровые коды
    elif digits.startswith('1'):  # США/Канада
        return '+1'
    elif digits.startswith(('7', '8')):  # Россия/Казахстан (8 старый формат)
        return '+7'
    # Добавляем другие коды стран по необходимости
    else:
        # Общая логика: если длина > 10, берём 1-3 первые цифры
        if len(digits) >= 10:
            # Пробуем 3 цифры
            if digits[:3] in ['380', '371', '370']:
                return f"+{digits[:3]}"
            # Пробуем 2 цифры
            elif digits[:2] in ['20', '30', '31', '32', '33', '34', '36', '39', '40', '41', '43', '44', '45', '46', '47', '48', '49']:
                return f"+{digits[:2]}"
            # По умолчанию 1 цифра
            else:
                return f"+{digits[0]}"
        
        return f"+{phone_or_id}"

class UltimateCommentBot:
    def __init__(self):
        import uuid
        self._instance_id = str(uuid.uuid4())[:8]
        print(f"🆔 ComapcBot instance created: {self._instance_id}")
        
        # ============= ЗАГРУЗКА КОНФИГУРАЦИИ =============
        logger.info("📋 Загрузка конфигурации...")
        self.config = load_config()
        logger.info("✅ Конфигурация загружена")
        # ============= END ЗАГРУЗКА КОНФИГУРАЦИИ =============
        
        # ============= YANDEX GPT ENVIRONMENT CHECK =============
        logger.info("="*60)
        logger.info("🔍 ПРОВЕРКА YANDEX GPT ОКРУЖЕНИЯ")
        logger.info("="*60)
        
        # Проверяем YC_API_KEY
        yc_api_key_found = bool(os.getenv('YC_API_KEY'))
        yandex_api_key_found = bool(os.getenv('YANDEX_API_KEY'))
        
        if yc_api_key_found:
            key_value = os.getenv('YC_API_KEY', '')
            masked_key = key_value[:8] + '***' + key_value[-4:] if len(key_value) > 12 else '***'
            logger.info(f"✅ YC_API_KEY найден: {masked_key}")
            logger.info(f"   Источник: переменная окружения YC_API_KEY")
        elif yandex_api_key_found:
            key_value = os.getenv('YANDEX_API_KEY', '')
            masked_key = key_value[:8] + '***' + key_value[-4:] if len(key_value) > 12 else '***'
            logger.info(f"✅ YANDEX_API_KEY найден: {masked_key}")
            logger.info(f"   Источник: переменная окружения YANDEX_API_KEY")
        else:
            logger.error("❌ API KEY НЕ НАЙДЕН!")
            logger.error("   Проверьте переменные окружения: YC_API_KEY или YANDEX_API_KEY")
            logger.error("   YandexGPT будет ОТКЛЮЧЕН, комментарии будут использовать шаблоны")
        
        # Проверяем YC_FOLDER_ID
        yc_folder_found = bool(os.getenv('YC_FOLDER_ID'))
        yandex_folder_found = bool(os.getenv('YANDEX_FOLDER_ID'))
        
        if yc_folder_found:
            folder_id = os.getenv('YC_FOLDER_ID', '')
            logger.info(f"✅ YC_FOLDER_ID найден: {folder_id}")
            logger.info(f"   Источник: переменная окружения YC_FOLDER_ID")
        elif yandex_folder_found:
            folder_id = os.getenv('YANDEX_FOLDER_ID', '')
            logger.info(f"✅ YANDEX_FOLDER_ID найден: {folder_id}")
            logger.info(f"   Источник: переменная окружения YANDEX_FOLDER_ID")
        else:
            logger.warning(f"⚠️  FOLDER_ID не найден в окружении, используется дефолтный: {YANDEX_FOLDER_ID}")
        
        # Итоговый статус
        yandex_gpt_enabled = bool(YANDEX_API_KEY)
        if yandex_gpt_enabled:
            logger.info("")
            logger.info("✅ YANDEX GPT: ВКЛЮЧЁН")
            logger.info(f"   Model URI: gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest")
            logger.info(f"   Endpoint: {YANDEX_GPT_URL}")
        else:
            logger.error("")
            logger.error("❌ YANDEX GPT: ОТКЛЮЧЁН (нет API ключа)")
            logger.error("   Все комментарии будут использовать шаблоны")
        
        logger.info("="*60)
        # ============= END YANDEX GPT ENVIRONMENT CHECK =============
        
        # ============= ЗАЩИТА: Один клиент на один session-файл =============
        logger.info("🔧 Создание основного бот-клиента (bot_session)...")
        self.bot_client = TelegramClient('bot_session', API_ID, API_HASH)
        self._bot_client_created = True  # Флаг для защиты от повторного создания
        logger.info("✅ Бот-клиент создан (session: bot_session)")
        self.client = self.bot_client  # Единый клиент для всех операций
        # ============= END ЗАЩИТА =============
        self.accounts_data = {}
        self.channels = []
        # Загружаем из конфига
        self.max_parallel_accounts = self.config.get('max_parallel_accounts', DEFAULT_MAX_ACTIVE_ACCOUNTS)
        self.templates = [
            'Отличный пост! 👍', 'Интересно! Спасибо!', 'Супер контент! 🔥',
            'Класс! 👌', 'Огонь! 🔥🔥', 'Согласен! 💯', 'Спасибо за контент! 🙌',
            'Супер! 👏', 'Круто! 💎', 'Лучший канал! 👑'
        ]
        self.bio_links = []
        self.admins = []
        self.monitoring = False
        self.monitoring_start_time = None  # Track when monitoring started
        self.stats = {
            'total_comments': 0,
            'blocked_accounts': [],
            'daily_comments': 0,
            'blocked_channels': []
        }
        # Track failed attempts: {channel_username: {phone1, phone2, ...}}
        self.channel_failed_attempts = {}
        # Track commented posts: {channel_username: {post_id1, post_id2, ...}}
        self.commented_posts = {}
        
        # ============= NEW: FLOODWAIT & BLACKLIST TRACKING =============
        # Track FloodWait history: {phone: {channel: {'timestamp': float, 'wait_seconds': int, 'expires_at': float}}}
        self.floodwait_history = {}
        # Blacklist channels per account: {phone: {channel1, channel2, ...}} - каналы с 3+ постоянными ошибками
        self.account_channel_blacklist = {}
        # Hot channels - каналы с недавним FloodWait (избегаем на 2 часа)
        # {channel_username: {'timestamp': float, 'phone': str, 'reason': str}}
        self.hot_channels = {}
        # История инцидентов по каналам для статистики
        # {channel_username: [{'timestamp': float, 'phone': str, 'reason': str, 'cooldown_until': float, 'resolved': bool}, ...]}
        self.channel_incidents = {}
        # История инцидентов по аккаунтам - за что получил удар
        # {phone: [{'timestamp': float, 'channel': str, 'reason': str, 'wait_seconds': int, 'action_taken': str}, ...]}
        self.account_incidents = {}
        # Global delay multiplier (увеличивается при частых FloodWait)
        self.global_delay_multiplier = 1.0
        # ============= END NEW =============
        # Channel queue for round-robin distribution
        self.channel_queue = []
        self.channel_queue_index = 0
        self.conn = None
        # State management for account profiles management
        self.user_states = {}  # {user_id: {'state': 'waiting_avatar', 'account_num': 1, 'data': {}}}
        self.account_cache = {}  # Cache for account info from env
        # Authorization state management
        self.pending_auth = {}  # {chat_id: {'phone': '+123', 'proxy': ..., 'client': ..., 'message_id': 123, 'state': 'waiting_code'/'waiting_2fa', 'event': ...}}
        
        # ============= NEW: RATE LIMITING & ROTATION (из конфига) =============
        # Настройки лимитов скорости
        self.messages_per_hour = self.config.get('speed', DEFAULT_MESSAGES_PER_HOUR)
        self.rotation_interval = self.config.get('rotation_interval', DEFAULT_ROTATION_INTERVAL)
        
        # Worker mode: 'cyclic' (all workers process all channels) or 'distributed' (channels divided)
        self.worker_mode = self.config.get('worker_mode', 'distributed')
        self.max_cycles_per_worker = self.config.get('max_cycles_per_worker', 1)  # 1 цикл = ~2.5 часа → ротация
        
        # Worker tracking for automatic recovery
        self.active_worker_tasks = []  # Список активных воркеров
        self.worker_recovery_enabled = self.config.get('worker_recovery_enabled', True)
        
        # Хранение распределения каналов для горячей замены: {worker_index: {'phone': phone, 'channels': [...], 'mode': 'distributed'}}
        self.worker_slots = {}
        
        # Отслеживание активности аккаунтов: {phone: {'messages': [(timestamp1, channel1), ...], 'status': 'active/reserve/broken'}}
        self.account_activity = {}
        
        # Отслеживание последних комментариев в чатах: {channel_username: {'phone': phone, 'timestamp': timestamp}}
        self.last_comment_per_channel = {}
        
        # Время последней ротации
        self.last_rotation_time = None
        
        # Индекс для циклической ротации
        self.rotation_index = 0
        
        # Флаг для отслеживания ротации (для health_check)
        self.rotation_in_progress = False
        self.workers_completing_cycles = set()  # Набор телефонов воркеров, завершающих циклы
        
        # ============= ПРОГРЕСС КОММЕНТИНГА (сохраняется при остановке) =============
        self.commenting_progress = self.config.get('commenting_progress', {})
        # {'processed_channels': ['channel1', 'channel2', ...], 'last_channel_index': 42}
        # ============= END ПРОГРЕСС =============
        
        # ============= TEST MODE (из конфига) =============
        self.test_mode = self.config.get('test_mode', False)
        self.test_channels = self.config.get('test_channels', [])
        self.test_mode_speed_limit = self.config.get('test_mode_speed_limit', 10)
        # ============= END TEST MODE =============
        # ============= END NEW =============
        
        # Словарь для переиспользования клиентов (один клиент на аккаунт)
        self.account_clients = {}  # {phone: TelegramClient}
        
        # ============= ANTI-SPAM & DEDUPLICATION =============
        # Хранилище последних комментариев для дедупликации
        # {channel_username: [(comment_text, timestamp, phone), ...]}
        self.recent_comments = {}
        self.recent_comments_limit = 20  # Храним последние 20 комментариев на канал
        # ============= END ANTI-SPAM & DEDUPLICATION =============
        
        self.init_database()
        self.load_stats()
        self.load_data()
        self.init_account_statuses()  # Инициализация статусов аккаунтов
        self.sync_active_accounts_with_config()  # Синхронизация активных аккаунтов с конфигом
    
    async def can_do_profile_operation(self, phone, operation_type):
        """
        Проверяет можно ли выполнить операцию с профилем (rate limiting)
        
        Args:
            phone: Номер телефона аккаунта
            operation_type: Тип операции ('bio', 'name', 'avatar')
        
        Returns:
            (can_do: bool, wait_time: timedelta|None, reason: str)
        """
        now = datetime.now()
        key = f"{phone}:{operation_type}"
        
        # Проверяем не заморожен ли аккаунт
        if phone in FROZEN_ACCOUNTS:
            logger.warning(f"PROFILE: Account {phone} is FROZEN, operation denied")
            return False, None, f"Аккаунт {phone} заблокирован Telegram (FROZEN)"
        
        # Проверяем лимиты
        if key in profile_operations_log:
            last_op = profile_operations_log[key]
            limit = PROFILE_OPERATION_LIMITS.get(operation_type, timedelta(hours=1))
            
            if now - last_op < limit:
                wait_time = (last_op + limit) - now
                logger.info(f"PROFILE: Rate limit for {phone}:{operation_type}, wait {wait_time}")
                return False, wait_time, "Rate limit"
        
        # Операция разрешена
        profile_operations_log[key] = now
        logger.info(f"PROFILE: Operation {operation_type} allowed for {phone}")
        return True, None, "OK"
    
    async def get_working_account_for_profile(self, preferred_phone=None):
        """
        Выбирает рабочий аккаунт для операций с профилем
        
        Args:
            preferred_phone: Предпочтительный номер (если пользователь выбрал)
        
        Returns:
            phone номер рабочего аккаунта или None
        """
        accounts = self.load_bot_data().get('accounts', {})
        
        # Если указан предпочтительный - проверяем его
        if preferred_phone:
            if preferred_phone in FROZEN_ACCOUNTS:
                logger.warning(f"PROFILE: Preferred account {preferred_phone} is FROZEN")
                return None
            if preferred_phone in accounts:
                return preferred_phone
        
        # Ищем рабочий аккаунт
        for phone in WORKING_ACCOUNTS:
            if phone in accounts:
                status = accounts[phone].get('status')
                if status in ['active', 'reserve']:
                    logger.info(f"PROFILE: Selected working account {phone}")
                    return phone
        
        logger.warning("PROFILE: No working accounts available!")
        return None
    
    def init_database(self):
        """Initialize SQLite database with required tables"""
        try:
            self.conn = sqlite3.connect(SQLITE_DB)
            cursor = self.conn.cursor()
            
            # Create blocked_accounts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocked_accounts (
                    phone TEXT PRIMARY KEY,
                    block_date TEXT,
                    reason TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create comment_history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comment_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    channel TEXT,
                    comment TEXT,
                    date TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create parsed_channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parsed_channels (
                    username TEXT PRIMARY KEY,
                    theme TEXT,
                    source TEXT DEFAULT 'parsed',
                    added_date TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create blocked_channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocked_channels (
                    username TEXT PRIMARY KEY,
                    block_date TEXT,
                    reason TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create profile_changes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profile_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    change_type TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    change_date TEXT,
                    success INTEGER DEFAULT 1,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create account_stats table for detailed statistics
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    channel TEXT,
                    event_type TEXT,
                    timestamp TEXT,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    admin_id INTEGER DEFAULT NULL
                )
            ''')
            
            # Create index for faster queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_account_stats_phone 
                ON account_stats(phone)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_account_stats_timestamp 
                ON account_stats(timestamp)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_account_stats_channel 
                ON account_stats(channel)
            ''')
            
            # ============= MIGRATION: Add admin_id columns to existing tables =============
            # Try to add admin_id column to existing tables (will fail silently if already exists)
            tables_to_migrate = [
                'blocked_accounts', 'comment_history', 'parsed_channels',
                'blocked_channels', 'profile_changes', 'account_stats'
            ]
            
            for table in tables_to_migrate:
                try:
                    cursor.execute(f'ALTER TABLE {table} ADD COLUMN admin_id INTEGER DEFAULT NULL')
                    logger.info(f"Added admin_id column to {table}")
                except sqlite3.OperationalError:
                    # Column already exists, skip
                    pass
            # ============= END MIGRATION =============
            
            self.conn.commit()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database init error: {e}")
    
    def load_data(self):
        """
        Загружает данные БЕЗОПАСНО - не перезаписывает при ошибках.
        Автоматически мигрирует из старой структуры 'accounts' в 'accounts_data'.
        """
        try:
            with open(DB_NAME, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # МИГРАЦИЯ: Если есть старая структура 'accounts', используем её
                # Новая структура 'accounts_data' имеет приоритет
                if 'accounts_data' in data and data['accounts_data']:
                    self.accounts_data = data['accounts_data']
                    logger.info(f"✅ Loading from new structure 'accounts_data'")
                elif 'accounts' in data and data['accounts']:
                    self.accounts_data = data['accounts']
                    logger.warning(f"⚠️ Loading from OLD structure 'accounts' - will migrate on save")
                else:
                    self.accounts_data = {}
                    logger.warning(f"⚠️ No accounts found in data file")
                
                self.channels = data.get('channels', [])
                self.templates = data.get('templates', self.templates)
                self.bio_links = data.get('bio_links', [])
                self.admins = data.get('admins', [])
                raw_test_channels = data.get('test_channels', [])
                self.test_channels = [self._normalize_channel_username(ch) for ch in raw_test_channels if self._normalize_channel_username(ch)]
                logger.info(f"✅ Loaded {len(self.accounts_data)} accounts, {len(self.channels)} channels, {len(self.templates)} templates")
        except FileNotFoundError:
            logger.warning(f"⚠️ {DB_NAME} not found - starting with empty data")
            logger.warning(f"⚠️ If this is a production server, restore from backup!")
            # НЕ создаём новый файл автоматически - это может быть ошибка
            # Пользователь должен явно восстановить из бэкапа или авторизовать аккаунты
        except json.JSONDecodeError as e:
            logger.error(f"❌ {DB_NAME} corrupted: {e}")
            logger.error(f"❌ CRITICAL: Data file is corrupted!")
            logger.error(f"❌ Restore from backup: bot_data.json.autobak or bot_data.json.manual_backup_*")
            # НЕ перезаписываем испорченный файл - можем потерять данные!
            raise  # Останавливаем бота - требуется вмешательство
        except Exception as e:
            logger.error(f"❌ Error loading data: {e}")
            logger.error(f"❌ Check file permissions and integrity")
            raise  # Останавливаем бота
    

    
    def save_data(self):
        """
        Сохраняет данные с атомарной записью и автоматическим бэкапом.
        БЕЗОПАСНО: создаёт бэкап перед каждым сохранением.
        Использует НОВУЮ структуру 'accounts_data' (старая 'accounts' больше не сохраняется).
        """
        data = {
            'accounts_data': self.accounts_data,  # НОВАЯ структура
            'channels': self.channels,
            'templates': self.templates,
            'bio_links': self.bio_links,
            'admins': self.admins,
            'test_channels': self.test_channels,
            'commenting_progress': self.commenting_progress  # Прогресс комментинга
        }
        
        # Создаём бэкап текущего файла (если существует)
        if os.path.exists(DB_NAME):
            try:
                backup_name = f'{DB_NAME}.autobak'
                import shutil
                shutil.copy2(DB_NAME, backup_name)
                logger.debug(f"Created automatic backup: {backup_name}")
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")
        
        # Сохраняем во временный файл сначала (атомарная запись)
        temp_file = f'{DB_NAME}.tmp'
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Только после успешной записи перезаписываем основной файл
            import shutil
            shutil.move(temp_file, DB_NAME)
            logger.debug("Data saved successfully")
        except Exception as e:
            logger.error(f"❌ Failed to save data: {e}")
            # Удаляем временный файл при ошибке
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            raise
    
    def load_stats(self):
        try:
            with open('stats.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.stats = data.get('stats', self.stats)
        except:
            self.save_stats()
    
    def save_stats(self):
        data = {'stats': self.stats}
        with open('stats.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    async def verify_account_auth(self, phone, session_string, proxy=None, timeout=10):
        """
        Проверяет валидность сессии аккаунта без полной переавторизации.
        
        Args:
            phone: Номер телефона
            session_string: Строка сессии из bot_data.json
            proxy: Прокси (опционально)
            timeout: Таймаут подключения
        
        Returns:
            dict: {'authorized': bool, 'name': str, 'username': str} или None при ошибке
        """
        if not session_string or session_string.strip() == '':
            logger.warning(f"❌ {phone}: пустая сессия")
            return {'authorized': False, 'name': None, 'username': None, 'error': 'empty_session'}
        
        try:
            logger.debug(f"🔌 [{phone}] Создание временного клиента для проверки (StringSession)...")
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH, proxy=proxy)
            logger.debug(f"🔌 [{phone}] Подключение временного клиента...")
            await asyncio.wait_for(client.connect(), timeout=timeout)
            
            if await client.is_user_authorized():
                try:
                    me = await asyncio.wait_for(client.get_me(), timeout=timeout)
                    result = {
                        'authorized': True,
                        'name': me.first_name or 'Без имени',
                        'username': getattr(me, 'username', None),
                        'user_id': me.id  # Добавляем ID пользователя для защиты от самокомментирования
                    }
                    logger.info(f"✅ {phone}: авторизован как {result['name']} (ID: {me.id})")
                    logger.debug(f"🔌 [{phone}] Отключение временного клиента (success)...")
                    await client.disconnect()
                    return result
                except Exception as e:
                    logger.error(f"❌ {phone}: ошибка get_me: {e}")
                    try:
                        logger.debug(f"🔌 [{phone}] Отключение временного клиента (error)...")
                        await client.disconnect()
                    except Exception as disconnect_err:
                        logger.warning(f"⚠️ [{phone}] Ошибка при отключении клиента: {disconnect_err}")
                    return {'authorized': False, 'name': None, 'username': None, 'error': str(e)}
            else:
                logger.warning(f"❌ {phone}: сессия невалидна (not authorized)")
                try:
                    logger.debug(f"🔌 [{phone}] Отключение временного клиента (not authorized)...")
                    await client.disconnect()
                except Exception as disconnect_err:
                    logger.warning(f"⚠️ [{phone}] Ошибка при отключении клиента: {disconnect_err}")
                return {'authorized': False, 'name': None, 'username': None, 'error': 'not_authorized'}
                
        except asyncio.TimeoutError:
            logger.error(f"❌ {phone}: таймаут подключения ({timeout}s)")
            try:
                logger.debug(f"🔌 [{phone}] Отключение временного клиента (timeout)...")
                await client.disconnect()
            except Exception as disconnect_err:
                logger.warning(f"⚠️ [{phone}] Ошибка при отключении клиента: {disconnect_err}")
            return {'authorized': False, 'name': None, 'username': None, 'error': 'timeout'}
        except Exception as e:
            logger.error(f"❌ {phone}: ошибка проверки авторизации: {e}")
            try:
                logger.debug(f"🔌 [{phone}] Отключение временного клиента (exception)...")
                await client.disconnect()
            except Exception as disconnect_err:
                logger.warning(f"⚠️ [{phone}] Ошибка при отключении клиента: {disconnect_err}")
            return {'authorized': False, 'name': None, 'username': None, 'error': str(e)}
    
    def init_account_statuses(self):
        """Инициализация статусов аккаунтов при запуске (синхронная часть)"""
        # Проверяем и устанавливаем статусы для всех аккаунтов
        active_count = 0
        migrated_count = 0
        
        # ВАЖНО: используем list() чтобы избежать RuntimeError при изменении словаря во время итерации
        accounts_to_normalize = {}  # {old_phone: new_phone}
        
        for phone, data in list(self.accounts_data.items()):
            # Нормализация телефона (добавляем + если отсутствует)
            if not phone.startswith('+'):
                new_phone = f"+{phone}"
                logger.info(f"🔧 Нормализация номера: {phone} → {new_phone}")
                accounts_to_normalize[phone] = new_phone
                data['phone'] = new_phone
            
            # МИГРАЦИЯ: Удаляем старое поле 'active' если оно есть (конфликт со 'status')
            if 'active' in data:
                old_active = data.pop('active')  # Удаляем и получаем значение
                logger.info(f"🔄 Удалено старое поле 'active={old_active}' для {data.get('name', phone)}")
            
            # Если у аккаунта нет статуса, присваиваем его
            if 'status' not in data or not data['status']:
                # Определяем статус на основе наличия сессии
                if data.get('session'):
                    # Есть сессия - делаем reserve (безопасно, пользователь сам активирует)
                    data['status'] = ACCOUNT_STATUS_RESERVE
                    migrated_count += 1
                    logger.info(f"🔄 Миграция {data.get('name', phone)}: пустой статус → reserve")
                else:
                    # Нет сессии - broken
                    data['status'] = ACCOUNT_STATUS_BROKEN
                    logger.warning(f"⚠️ {phone}: нет сессии, помечен как broken")
                    migrated_count += 1
            elif data['status'] == ACCOUNT_STATUS_ACTIVE:
                active_count += 1
            
            # Проверяем корректность статуса
            valid_statuses = [ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_RESERVE, ACCOUNT_STATUS_BROKEN]
            if data['status'] not in valid_statuses:
                logger.warning(f"⚠️ {phone}: неизвестный статус '{data['status']}', изменён на reserve")
                data['status'] = ACCOUNT_STATUS_RESERVE
                migrated_count += 1
            
            # Инициализируем структуру отслеживания активности
            current_phone = accounts_to_normalize.get(phone, phone)
            if current_phone not in self.account_activity:
                self.account_activity[current_phone] = {
                    'messages': [],  # [(timestamp, channel), ...]
                    'status': data.get('status', ACCOUNT_STATUS_RESERVE)
                }
        
        # Применяем нормализацию номеров (переименовываем ключи в словаре)
        for old_phone, new_phone in accounts_to_normalize.items():
            if new_phone not in self.accounts_data:
                self.accounts_data[new_phone] = self.accounts_data[old_phone]
            del self.accounts_data[old_phone]
        
        # Если активных аккаунтов больше чем max_parallel_accounts, переводим лишние в резерв
        if active_count > self.max_parallel_accounts:
            logger.warning(f"⚠️ Found {active_count} active accounts, but max is {self.max_parallel_accounts}. Moving extras to reserve.")
            count = 0
            for phone, data in list(self.accounts_data.items()):
                if data.get('status') == ACCOUNT_STATUS_ACTIVE:
                    count += 1
                    if count > self.max_parallel_accounts:
                        data['status'] = ACCOUNT_STATUS_RESERVE
                        self.account_activity[phone]['status'] = ACCOUNT_STATUS_RESERVE
                        logger.info(f"🔄 Account {data.get('name', phone)} moved to reserve (over limit)")
        
        # Если активных меньше чем max_parallel_accounts, активируем резервные (массово)
        elif active_count < self.max_parallel_accounts:
            needed = self.max_parallel_accounts - active_count
            logger.info(f"📊 Only {active_count} active accounts, activating {needed} more from reserve")
            reserve_valid = [p for p, d in self.accounts_data.items() if d.get('status') == ACCOUNT_STATUS_RESERVE and d.get('session')]
            for phone in reserve_valid[:needed]:
                self.accounts_data[phone]['status'] = ACCOUNT_STATUS_ACTIVE
                self.account_activity[phone]['status'] = ACCOUNT_STATUS_ACTIVE
                logger.info(f"✅ Account {self.accounts_data[phone].get('name', phone)} activated from reserve")
        
        self.save_data()
        
        if migrated_count > 0:
            logger.info(f"✅ Миграция завершена: {migrated_count} аккаунтов переведены в новый формат")
        
        logger.info(f"✅ Account statuses initialized: {self.get_status_counts()}")
        logger.info("💡 Используйте /verify_sessions для проверки авторизации")
        logger.info("💡 Используйте /toggleaccount +номер для активации аккаунтов")
    
    async def verify_all_accounts(self):
        """
        Асинхронная проверка авторизации всех аккаунтов после запуска бота.
        Вызывается автоматически из start() для валидации сессий.
        """
        logger.info("🔍 Начинается проверка авторизации всех аккаунтов...")
        
        if not self.accounts_data:
            logger.warning("⚠️ Нет аккаунтов для проверки")
            return
        
        verified_count = 0
        failed_count = 0
        broken_count = 0
        
        for phone, data in self.accounts_data.items():
            session_str = data.get('session', '')
            
            if not session_str or session_str.strip() == '':
                logger.warning(f"⚠️ {phone}: пустая сессия, помечаю как broken")
                self.set_account_status(phone, ACCOUNT_STATUS_BROKEN, "пустая сессия")
                broken_count += 1
                continue
            
            # Проверяем авторизацию
            result = await self.verify_account_auth(phone, session_str, data.get('proxy'))
            
            if result and result.get('authorized'):
                # Обновляем данные аккаунта
                if result.get('name'):
                    data['name'] = result['name']
                if result.get('username') is not None:
                    data['username'] = result['username']
                if result.get('user_id'):  # Сохраняем user_id для защиты от самокомментирования
                    data['user_id'] = result['user_id']
                
                # Если был broken, переводим в reserve
                if data.get('status') == ACCOUNT_STATUS_BROKEN:
                    self.set_account_status(phone, ACCOUNT_STATUS_RESERVE, "восстановлен")
                    logger.info(f"✅ {phone}: восстановлен (был broken)")
                
                verified_count += 1
                logger.info(f"✅ {phone}: авторизован ({verified_count}/{len(self.accounts_data)})")
            else:
                # Сессия невалидна
                error = result.get('error', 'unknown') if result else 'unknown'
                logger.error(f"❌ {phone}: невалидная сессия ({error})")
                
                # Помечаем как broken только если ещё не помечен
                if data.get('status') != ACCOUNT_STATUS_BROKEN:
                    self.set_account_status(phone, ACCOUNT_STATUS_BROKEN, f"невалидная сессия: {error}")
                
                failed_count += 1
            
            # Небольшая задержка между проверками
            await asyncio.sleep(1)
        
        # Сохраняем обновлённые данные
        self.save_data()
        
        # Итоговый отчёт
        logger.info(f"✅ Проверка завершена: {verified_count} OK, {failed_count} невалидных, {broken_count} без сессии")
        
        if failed_count > 0:
            logger.warning(f"⚠️ {failed_count} аккаунтов требуют переавторизации (/auth)")
        
        return {
            'verified': verified_count,
            'failed': failed_count,
            'broken': broken_count,
            'total': len(self.accounts_data)
        }
    
    def get_status_counts(self):
        """Получить количество аккаунтов по статусам"""
        counts = {
            ACCOUNT_STATUS_ACTIVE: 0,
            ACCOUNT_STATUS_RESERVE: 0,
            ACCOUNT_STATUS_BROKEN: 0
        }
        for data in self.accounts_data.values():
            status = data.get('status', ACCOUNT_STATUS_RESERVE)
            counts[status] = counts.get(status, 0) + 1
        return counts
    
    def get_account_status(self, phone):
        """Получить статус аккаунта"""
        if phone in self.accounts_data:
            return self.accounts_data[phone].get('status', ACCOUNT_STATUS_RESERVE)
        return None
    
    def set_account_status(self, phone, status, reason=""):
        """Установить статус аккаунта с логированием"""
        if phone not in self.accounts_data:
            logger.error(f"❌ Cannot set status for unknown account: {phone}")
            return False
        
        old_status = self.accounts_data[phone].get('status', ACCOUNT_STATUS_RESERVE)
        if old_status == status:
            return True  # Статус не изменился
        
        self.accounts_data[phone]['status'] = status
        if phone in self.account_activity:
            self.account_activity[phone]['status'] = status
        
        account_name = self.accounts_data[phone].get('name', phone)
        reason_str = f" ({reason})" if reason else ""
        logger.info(f"🔄 Account {account_name}: {old_status} → {status}{reason_str}")
        
        self.save_data()
        # Синхронизация с конфигом
        self.sync_active_accounts_with_config()
        return True
    
    def sync_active_accounts_with_config(self):
        """
        Синхронизирует список активных аккаунтов с config.json
        Вызывается при изменении статусов аккаунтов
        """
        active_phones = [
            phone for phone, data in self.accounts_data.items()
            if data.get('status') == ACCOUNT_STATUS_ACTIVE
        ]
        
        # Обновляем конфиг
        self.config['active_accounts'] = active_phones
        save_config(self.config)
        logger.debug(f"💾 Синхронизация: {len(active_phones)} активных аккаунтов сохранено в конфиг")
    
    def get_my_account_ids(self):
        """
        Получить список ID всех своих аккаунтов (для защиты от самокомментирования)
        Возвращает словарь {phone: {'user_id': int, 'username': str}}
        """
        my_accounts = {}
        for phone, data in self.accounts_data.items():
            user_id = data.get('user_id')
            username = data.get('username', '')
            if user_id or username:
                my_accounts[phone] = {
                    'user_id': user_id,
                    'username': username
                }
        return my_accounts
    
    def is_my_account(self, user_id=None, username=None):
        """
        Проверить, является ли пользователь одним из моих аккаунтов
        """
        for phone, data in self.accounts_data.items():
            if user_id and data.get('user_id') == user_id:
                return True, phone
            if username and data.get('username') == username:
                return True, phone
        return False, None
    
    async def get_recent_thread_authors(self, client, discussion_entity, limit=5):
        """
        Получить список авторов последних комментариев в треде
        Возвращает список {'user_id': int, 'username': str, 'phone': str (если свой)}
        """
        try:
            msgs = await client.get_messages(discussion_entity, limit=limit)
            authors = []
            
            for msg in msgs:
                if not msg.sender_id:
                    continue
                    
                # Проверяем, свой ли это аккаунт
                is_mine, phone = self.is_my_account(user_id=msg.sender_id)
                
                author_info = {
                    'user_id': msg.sender_id,
                    'username': getattr(msg.sender, 'username', None) if hasattr(msg, 'sender') else None,
                    'is_mine': is_mine,
                    'phone': phone if is_mine else None,
                    'message_id': msg.id
                }
                authors.append(author_info)
            
            return authors
        except Exception as e:
            logger.error(f"Ошибка получения авторов треда: {e}")
            return []
    
    def can_account_comment_on_post(self, phone, discussion_entity_id, recent_authors):
        """
        Проверить, можно ли аккаунту комментировать на основе недавних авторов
        
        Логика:
        1. Не комментировать, если аккаунт уже писал в последних 3 сообщениях
        2. Не комментировать, если последние 2-3 сообщения только от моих аккаунтов
        3. Не отвечать самому себе
        
        Возвращает: (can_comment: bool, reason: str)
        """
        if not recent_authors:
            return True, "ok"
        
        # Получаем user_id для данного phone
        my_user_id = self.accounts_data.get(phone, {}).get('user_id')
        if not my_user_id:
            return True, "ok"  # Если не можем определить ID, разрешаем
        
        # Проверка 1: Аккаунт не должен комментировать, если он уже писал в последних 3 сообщениях
        last_3_authors = recent_authors[:3]
        if any(author['user_id'] == my_user_id for author in last_3_authors):
            return False, "account_already_commented_recently"
        
        # Проверка 2: Если последние 2+ сообщения только от моих аккаунтов - пауза
        last_2_authors = recent_authors[:2]
        if len(last_2_authors) >= 2:
            all_mine = all(author['is_mine'] for author in last_2_authors)
            if all_mine:
                return False, "too_many_own_accounts_in_row"
        
        # Проверка 3: Не отвечать сразу после другого своего аккаунта (чередование)
        if recent_authors and recent_authors[0]['is_mine'] and recent_authors[0]['phone'] != phone:
            # Последний комментарий от другого моего аккаунта - лучше подождать
            # Разрешаем только если прошло достаточно времени или есть внешние комментарии
            if len(recent_authors) >= 2:
                # Если предпоследний комментарий НЕ от моих аккаунтов - можно
                if not recent_authors[1]['is_mine']:
                    return True, "ok"
            return False, "avoid_own_account_loop"
        
        return True, "ok"
    
    def is_comment_duplicate(self, channel_username, comment_text, min_word_count=5):
        """
        Проверить, не является ли комментарий дубликатом недавних
        
        Args:
            channel_username: Имя канала
            comment_text: Текст комментария для проверки
            min_word_count: Минимальное количество слов для валидации
        
        Returns:
            (is_duplicate: bool, reason: str)
        """
        # Проверка минимальной длины
        words = comment_text.split()
        if len(words) < min_word_count:
            return True, f"comment_too_short_{len(words)}_words"
        
        # Нормализуем текст для сравнения (убираем пробелы, приводим к нижнему регистру)
        normalized_new = re.sub(r'\s+', ' ', comment_text.lower().strip())
        
        # Убираем эмодзи из нормализованного текста для сравнения
        emoji_pattern = re.compile(
            "["
            "\\U0001F600-\\U0001F64F"
            "\\U0001F300-\\U0001F5FF"
            "\\U0001F680-\\U0001F6FF"
            "\\U0001F1E0-\\U0001F1FF"
            "\\U00002702-\\U000027B0"
            "\\U000024C2-\\U0001F251"
            "\\U0001F900-\\U0001F9FF"
            "]+"
        )
        normalized_new = emoji_pattern.sub('', normalized_new).strip()
        
        if channel_username not in self.recent_comments:
            return False, "ok"
        
        # Проверяем на совпадение с недавними комментариями
        for old_comment, timestamp, phone in self.recent_comments[channel_username]:
            normalized_old = re.sub(r'\\s+', ' ', old_comment.lower().strip())
            normalized_old = emoji_pattern.sub('', normalized_old).strip()
            
            # Точное совпадение
            if normalized_new == normalized_old:
                return True, f"exact_duplicate_from_{phone}"
            
            # Очень похожие (более 80% совпадения)
            if len(normalized_new) > 10 and len(normalized_old) > 10:
                # Простая проверка на похожесть по количеству общих слов
                words_new = set(normalized_new.split())
                words_old = set(normalized_old.split())
                if words_new and words_old:
                    common_words = words_new & words_old
                    similarity = len(common_words) / max(len(words_new), len(words_old))
                    if similarity > 0.8:
                        return True, f"similar_duplicate_{int(similarity*100)}%_from_{phone}"
        
        return False, "ok"
    
    def add_comment_to_history(self, channel_username, comment_text, phone):
        """
        Добавить комментарий в историю для дедупликации
        """
        if channel_username not in self.recent_comments:
            self.recent_comments[channel_username] = []
        
        timestamp = datetime.now().timestamp()
        self.recent_comments[channel_username].append((comment_text, timestamp, phone))
        
        # Ограничиваем размер истории
        if len(self.recent_comments[channel_username]) > self.recent_comments_limit:
            self.recent_comments[channel_username] = self.recent_comments[channel_username][-self.recent_comments_limit:]
    
    # ============= NEW: FLOODWAIT & BLACKLIST MANAGEMENT =============
    
    def record_floodwait(self, phone, channel, wait_seconds):
        """
        Записать FloodWait для аккаунта на канале
        
        Args:
            phone: Телефон аккаунта
            channel: Имя канала
            wait_seconds: Сколько секунд нужно ждать
        """
        current_time = datetime.now().timestamp()
        expires_at = current_time + wait_seconds
        
        if phone not in self.floodwait_history:
            self.floodwait_history[phone] = {}
        
        self.floodwait_history[phone][channel] = {
            'timestamp': current_time,
            'wait_seconds': wait_seconds,
            'expires_at': expires_at
        }
        
        logger.warning(
            f"📝 FloodWait recorded: phone={phone[-10:]}, channel={channel}, "
            f"wait={wait_seconds}s, expires_at={datetime.fromtimestamp(expires_at).strftime('%H:%M:%S')}"
        )
        
        # Увеличиваем глобальный множитель задержки при частых FloodWait
        self.adjust_global_delay_on_floodwait()
    
    def has_recent_floodwait(self, phone, channel, within_minutes=30):
        """
        Проверить, был ли недавний FloodWait для аккаунта на канале
        
        Args:
            phone: Телефон аккаунта
            channel: Имя канала
            within_minutes: В течение скольких минут проверять
        
        Returns:
            bool: True если FloodWait еще активен или был недавно
        """
        if phone not in self.floodwait_history:
            return False
        
        if channel not in self.floodwait_history[phone]:
            return False
        
        fw_data = self.floodwait_history[phone][channel]
        current_time = datetime.now().timestamp()
        
        # Проверяем, не истек ли FloodWait
        if current_time < fw_data['expires_at']:
            remaining = int(fw_data['expires_at'] - current_time)
            logger.info(
                f"⏳ FloodWait still active: phone={phone[-10:]}, channel={channel}, "
                f"remaining={remaining}s"
            )
            return True
        
        # Проверяем, был ли недавно (в пределах within_minutes)
        time_since_floodwait = current_time - fw_data['timestamp']
        if time_since_floodwait < (within_minutes * 60):
            logger.info(
                f"⚠️ Recent FloodWait detected: phone={phone[-10:]}, channel={channel}, "
                f"was {int(time_since_floodwait/60)} min ago"
            )
            return True
        
        return False
    
    def cleanup_expired_floodwaits(self):
        """
        Очистить истекшие записи FloodWait (вызывается периодически)
        """
        current_time = datetime.now().timestamp()
        cleaned_count = 0
        
        for phone in list(self.floodwait_history.keys()):
            for channel in list(self.floodwait_history[phone].keys()):
                fw_data = self.floodwait_history[phone][channel]
                # Удаляем записи старше 1 часа
                if current_time - fw_data['timestamp'] > 3600:
                    del self.floodwait_history[phone][channel]
                    cleaned_count += 1
            
            # Удаляем пустые записи для phone
            if not self.floodwait_history[phone]:
                del self.floodwait_history[phone]
        
        if cleaned_count > 0:
            logger.info(f"🧹 Cleaned {cleaned_count} expired FloodWait records")
    
    def adjust_global_delay_on_floodwait(self):
        """
        Адаптивно увеличивать глобальную задержку при частых FloodWait
        """
        # Подсчитываем активные FloodWait
        current_time = datetime.now().timestamp()
        active_floodwaits = 0
        
        for phone in self.floodwait_history:
            for channel, fw_data in self.floodwait_history[phone].items():
                if current_time < fw_data['expires_at']:
                    active_floodwaits += 1
        
        # Если больше 3 активных FloodWait - увеличиваем задержку
        if active_floodwaits >= 3:
            old_multiplier = self.global_delay_multiplier
            self.global_delay_multiplier = min(2.0, self.global_delay_multiplier * 1.2)
            if old_multiplier != self.global_delay_multiplier:
                logger.warning(
                    f"⚠️ High FloodWait activity ({active_floodwaits} active), "
                    f"increasing global delay: {old_multiplier:.2f} → {self.global_delay_multiplier:.2f}x"
                )
        elif active_floodwaits == 0 and self.global_delay_multiplier > 1.0:
            # Постепенно снижаем множитель, если нет активных FloodWait
            old_multiplier = self.global_delay_multiplier
            self.global_delay_multiplier = max(1.0, self.global_delay_multiplier * 0.95)
            if abs(old_multiplier - self.global_delay_multiplier) > 0.01:
                logger.info(
                    f"✅ No active FloodWaits, reducing global delay: "
                    f"{old_multiplier:.2f} → {self.global_delay_multiplier:.2f}x"
                )
    
    def blacklist_channel_for_account(self, phone, channel, reason):
        """
        Добавить канал в блэклист для конкретного аккаунта
        
        Args:
            phone: Телефон аккаунта
            channel: Имя канала
            reason: Причина блокировки
        """
        if phone not in self.account_channel_blacklist:
            self.account_channel_blacklist[phone] = {}
        
        self.account_channel_blacklist[phone][channel] = {
            'reason': reason,
            'timestamp': datetime.now().timestamp()
        }
        
        logger.warning(
            f"🚫 Channel blacklisted for account: phone={phone[-10:]}, "
            f"channel={channel}, reason={reason}"
        )
    
    def is_channel_blacklisted_for_account(self, phone, channel):
        """
        Проверить, находится ли канал в блэклисте для аккаунта
        
        Returns:
            (bool, str): (is_blacklisted, reason)
        """
        if phone not in self.account_channel_blacklist:
            return False, ""
        
        if channel not in self.account_channel_blacklist[phone]:
            return False, ""
        
        blacklist_data = self.account_channel_blacklist[phone][channel]
        return True, blacklist_data['reason']
    
    # ============= END NEW =============
    
    def save_config_value(self, key, value):
        """
        Удобный метод для сохранения одного значения в конфиг
        """
        self.config[key] = value
        save_config(self.config)
        logger.info(f"💾 Сохранено в конфиг: {key} = {value}")
    
    def can_account_send_message(self, phone):
        """Проверить, может ли аккаунт отправить сообщение с учетом лимитов скорости"""
        if phone not in self.account_activity:
            return True, 0
        
        current_time = datetime.now().timestamp()
        activity = self.account_activity[phone]
        
        # Проверяем статус аккаунта
        if activity['status'] != ACCOUNT_STATUS_ACTIVE:
            return False, 0
        
        # Очищаем старые записи (старше 1 часа)
        hour_ago = current_time - 3600
        activity['messages'] = [(ts, ch) for ts, ch in activity['messages'] if ts > hour_ago]
        
        # Проверяем лимит
        messages_last_hour = len(activity['messages'])
        if messages_last_hour >= self.messages_per_hour:
            # Вычисляем время до следующего возможного отправления
            oldest_msg_time = min(ts for ts, _ in activity['messages']) if activity['messages'] else current_time
            wait_time = int((oldest_msg_time + 3600) - current_time)
            return False, max(wait_time, 0)
        
        return True, 0
    
    def register_message_sent(self, phone, channel):
        """Зарегистрировать отправленное сообщение для отслеживания лимитов"""
        if phone not in self.account_activity:
            self.account_activity[phone] = {'messages': [], 'status': ACCOUNT_STATUS_ACTIVE}
        
        current_time = datetime.now().timestamp()
        self.account_activity[phone]['messages'].append((current_time, channel))
        
        # Обновляем последний комментарий в канале
        self.last_comment_per_channel[channel] = {
            'phone': phone,
            'timestamp': current_time
        }
    
    def can_account_comment_in_channel(self, phone, channel):
        """Проверить, может ли аккаунт комментировать в канале (защита от спама своими аккаунтами)"""
        if channel not in self.last_comment_per_channel:
            return True, 0
        
        last_comment = self.last_comment_per_channel[channel]
        last_phone = last_comment['phone']
        last_timestamp = last_comment['timestamp']
        
        # Если последний комментарий был от другого нашего аккаунта
        if last_phone != phone and last_phone in self.accounts_data:
            current_time = datetime.now().timestamp()
            time_since_last = current_time - last_timestamp
            
            # Случайный интервал между MIN и MAX для естественности
            import random
            required_interval = random.randint(MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS, MAX_INTERVAL_BETWEEN_OWN_ACCOUNTS)
            
            if time_since_last < required_interval:
                wait_time = int(required_interval - time_since_last)
                return False, wait_time
        
        return True, 0
    
    def mark_channel_as_hot(self, channel_username, phone, reason="FloodWait"):
        """Пометить канал как горячий (избегать 2 часа после FloodWait)"""
        now = datetime.now().timestamp()
        cooldown_until = now + (2 * 3600)  # 2 часа
        
        self.hot_channels[channel_username] = {
            'timestamp': now,
            'phone': phone,
            'reason': reason
        }
        
        # Сохраняем инцидент в историю
        if channel_username not in self.channel_incidents:
            self.channel_incidents[channel_username] = []
        
        self.channel_incidents[channel_username].append({
            'timestamp': now,
            'phone': phone,
            'reason': reason,
            'cooldown_until': cooldown_until,
            'resolved': False
        })
        
        logger.warning(f"🔥 Channel @{channel_username} marked as HOT (reason: {reason}, phone: {phone[-4:]})")
    
    def is_channel_hot(self, channel_username, cooldown_hours=2):
        """Проверить, является ли канал горячим (недавний FloodWait)"""
        if channel_username not in self.hot_channels:
            return False, None
        
        hot_info = self.hot_channels[channel_username]
        current_time = datetime.now().timestamp()
        time_since_hot = current_time - hot_info['timestamp']
        cooldown_seconds = cooldown_hours * 3600
        
        if time_since_hot < cooldown_seconds:
            remaining_minutes = int((cooldown_seconds - time_since_hot) / 60)
            return True, remaining_minutes
        else:
            # Помечаем последний неразрешенный инцидент как resolved
            if channel_username in self.channel_incidents and self.channel_incidents[channel_username]:
                for incident in reversed(self.channel_incidents[channel_username]):
                    if not incident['resolved']:
                        incident['resolved'] = True
                        break
            
            # Прошло достаточно времени - убираем из горячих
            del self.hot_channels[channel_username]
            logger.info(f"❄️ Channel @{channel_username} cooled down, removed from hot list")
            return False, None
    
    def record_account_incident(self, phone, channel, reason, wait_seconds=0, action_taken=""):
        """Записать инцидент для аккаунта (FloodWait, бан и т.д.)"""
        if phone not in self.account_incidents:
            self.account_incidents[phone] = []
        
        self.account_incidents[phone].append({
            'timestamp': datetime.now().timestamp(),
            'channel': channel,
            'reason': reason,
            'wait_seconds': wait_seconds,
            'action_taken': action_taken
        })
        
        # Ограничиваем историю последними 50 инцидентами
        if len(self.account_incidents[phone]) > 50:
            self.account_incidents[phone] = self.account_incidents[phone][-50:]
    
    async def check_spam_status(self, phone, account_data):
        """Проверить статус ограничений аккаунта через @SpamBot"""
        client = None
        try:
            account_name = account_data.get('name', phone[-4:])
            
            # Создаем клиент
            session_string = account_data.get('session')
            if not session_string:
                return f"❌ **{account_name}**: нет сессии"
            
            proxy = account_data.get('proxy')
            client = TelegramClient(
                StringSession(session_string),
                API_ID,
                API_HASH,
                proxy=proxy
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                return f"❌ **{account_name}**: не авторизован"
            
            # Получаем @SpamBot
            try:
                spambot = await client.get_entity('SpamBot')
            except Exception as e:
                return f"❌ **{account_name}**: не удалось найти @SpamBot: {str(e)}"
            
            # Отправляем /start
            await client.send_message(spambot, '/start')
            
            # Ждем ответ (обычно приходит сразу)
            response = None
            async for message in client.iter_messages(spambot, limit=1):
                response = message.text
                break
            
            await asyncio.sleep(1)  # Даем время на обработку
            
            # Получаем самое свежее сообщение
            async for message in client.iter_messages(spambot, limit=1):
                if message.date.timestamp() > (datetime.now().timestamp() - 10):
                    response = message.text
                    break
            
            await client.disconnect()
            
            if not response:
                return f"⚠️ **{account_name}**: @SpamBot не ответил"
            
            # Анализируем ответ
            text = f"📱 **{account_name}** (`{phone[-4:]}`)\n\n"
            
            if "Good news" in response or "not limited" in response.lower():
                text += "✅ **НЕТ ОГРАНИЧЕНИЙ**\n\n"
                text += "Аккаунт работает нормально"
            elif "limited" in response.lower() or "restricted" in response.lower():
                text += "⚠️ **ЕСТЬ ОГРАНИЧЕНИЯ**\n\n"
                text += f"```\n{response}\n```"
            else:
                text += "📋 **Ответ от @SpamBot:**\n\n"
                text += f"```\n{response}\n```"
            
            return text
            
        except Exception as e:
            logger.error(f"Error checking spam status for {phone}: {e}")
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            return f"❌ **{account_data.get('name', phone[-4:])}**: ошибка проверки: {str(e)}"
    
    async def add_comment_stat(self, phone, success=True, channel=None, error_message=None, admin_id=None):
        self.stats['total_comments'] += 1
        if success:
            self.stats['daily_comments'] += 1
        else:
            self.stats['blocked_accounts'].append(phone)
        if len(self.stats['blocked_accounts']) > 50:
            self.stats['blocked_accounts'] = self.stats['blocked_accounts'][-20:]
        
        # Save detailed stat to DB with admin_id
        if self.conn and phone:
            try:
                # If admin_id not provided, try to get it from account data
                if admin_id is None:
                    account_data = self.accounts_data.get(phone, {})
                    admin_id = account_data.get('admin_id')
                
                cursor = self.conn.cursor()
                event_type = 'comment_sent' if success else 'comment_failed'
                cursor.execute(
                    "INSERT INTO account_stats (phone, channel, event_type, timestamp, success, error_message, admin_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (phone, channel or '', event_type, datetime.now().isoformat(), 1 if success else 0, error_message or '', admin_id)
                )
                self.conn.commit()
            except Exception as e:
                logger.error(f"Error saving account stat: {e}")
        
        self.save_stats()
    
    async def mark_channel_failed_for_account(self, username, phone, reason):
        """Mark that this account failed to comment on this channel"""
        try:
            if username not in self.channel_failed_attempts:
                self.channel_failed_attempts[username] = {}
            
            # Track failures per account with reason
            if phone not in self.channel_failed_attempts[username]:
                self.channel_failed_attempts[username][phone] = {'count': 0, 'reasons': []}
            
            self.channel_failed_attempts[username][phone]['count'] += 1
            self.channel_failed_attempts[username][phone]['reasons'].append(reason)
            
            failure_count = self.channel_failed_attempts[username][phone]['count']
            
            # ============= NEW: BLACKLIST CHANNEL AFTER 3+ PERMANENT FAILURES =============
            # Если 3+ постоянных ошибок - добавляем канал в блэклист для этого аккаунта
            if failure_count >= 3:
                # Проверяем, что это постоянные ошибки, а не временные
                permanent_error_keywords = [
                    'CHAT_WRITE_FORBIDDEN', 'CHAT_SEND_PLAIN_FORBIDDEN',
                    'CHANNEL_PRIVATE', 'CHAT_RESTRICTED', 'Comments forbidden',
                    'No discussion group', 'Access error'
                ]
                
                is_permanent = any(keyword in reason for keyword in permanent_error_keywords)
                
                if is_permanent:
                    self.blacklist_channel_for_account(phone, username, f"3+ failures: {reason}")
                    logger.warning(
                        f"🚫 [{phone[-10:]}] Channel {username} BLACKLISTED after {failure_count} failures"
                    )
            # ============= END NEW =============
            
            # Record error in DB for stats with admin_id
            if self.conn:
                try:
                    # Get admin_id from account data
                    account_data = self.accounts_data.get(phone, {})
                    admin_id = account_data.get('admin_id')
                    
                    cursor = self.conn.cursor()
                    cursor.execute(
                        "INSERT INTO account_stats (phone, channel, event_type, timestamp, success, error_message, admin_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (phone, username, 'comment_failed', datetime.now().isoformat(), 0, reason, admin_id)
                    )
                    self.conn.commit()
                except Exception as e:
                    logger.error(f"Error saving failure stat: {e}")
            
            # Count active accounts (NEW: use status instead of 'active' field)
            active_accounts = [p for p, data in self.accounts_data.items() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE]
            failed_phones = len(self.channel_failed_attempts[username])
            
            # Count how many accounts have failed multiple times (3+ times means persistent issue)
            persistent_failures = sum(1 for data in self.channel_failed_attempts[username].values() 
                                    if data['count'] >= 3)
            
            logger.info(f"Channel {username}: {failed_phones}/{len(active_accounts)} accounts failed, "
                       f"{persistent_failures} with persistent issues")
            
            # Block channel only if:
            # 1. At least 50% of active accounts failed persistently (3+ times each)
            # 2. OR all active accounts failed at least once with same error
            threshold = max(2, len(active_accounts) // 2)  # At least 2 accounts or 50%
            
            if persistent_failures >= threshold:
                # Get most common reason
                all_reasons = []
                for data in self.channel_failed_attempts[username].values():
                    all_reasons.extend(data['reasons'])
                most_common = max(set(all_reasons), key=all_reasons.count) if all_reasons else reason
                await self.block_channel(username, f"{most_common} (confirmed by {persistent_failures} accounts)")
            elif failed_phones >= len(active_accounts) and len(active_accounts) > 0:
                # All accounts failed at least once
                logger.warning(f"Channel {username}: All accounts failed once, but not blocking yet (need 3 failures per account)")
        except Exception as e:
            logger.error(f"Error marking failed attempt for {username}: {e}")
    
    async def handle_account_ban(self, phone, reason):
        """Handle account ban by deactivating it and activating a reserve account"""
        logger.warning(f"🚫 Account ban detected: {phone} - {reason}")
        
        # Записываем инцидент бана
        self.record_account_incident(
            phone=phone,
            channel="ALL_CHANNELS",
            reason=f"Account banned: {reason}",
            wait_seconds=0,
            action_taken="marked_broken"
        )
        
        await self.replace_broken_account(phone, reason)
    
    async def block_channel(self, username, reason):
        """Block channel that doesn't allow comments from ALL accounts and remove from active list"""
        try:
            # Add to stats if not already there
            if username not in self.stats.get('blocked_channels', []):
                if 'blocked_channels' not in self.stats:
                    self.stats['blocked_channels'] = []
                self.stats['blocked_channels'].append(username)
                self.save_stats()
            
            # Add to database
            if self.conn:
                cursor = self.conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO blocked_channels (username, block_date, reason) VALUES (?, ?, ?)",
                    (username, datetime.now().isoformat(), reason)
                )
                self.conn.commit()
            
            # Remove from active channels list
            self.channels = [
                ch for ch in self.channels
                if (ch.get('username') if isinstance(ch, dict) else str(ch)) != username
            ]
            self.save_data()
            logger.info(f"Blocked and removed channel: {username} - Reason: {reason} (all accounts failed)")
            
            # Clean up failed attempts tracking
            if username in self.channel_failed_attempts:
                del self.channel_failed_attempts[username]
        except Exception as e:
            logger.error(f"Error blocking channel {username}: {e}")
    
    async def rotate_accounts(self):
        """Ротация аккаунтов: выводит часть активных в резерв и активирует следующие из резерва"""
        try:
            # Получаем списки аккаунтов по статусам
            active_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')]
            reserve_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                              if data.get('status') == ACCOUNT_STATUS_RESERVE and data.get('session')]
            
            if not reserve_accounts:
                logger.info("⚠️ No reserve accounts available for rotation")
                return
            
            if not active_accounts:
                logger.warning("⚠️ No active accounts to rotate")
                return
            
            # Определяем, сколько аккаунтов ротировать (минимум 1, максимум половину активных)
            num_to_rotate = max(1, min(len(active_accounts) // 2, len(reserve_accounts)))
            
            logger.info(f"🔄 Starting account rotation: {num_to_rotate} accounts")
            

            # Деактивируем выбранные аккаунты
            accounts_to_deactivate = []
            for i in range(num_to_rotate):
                if i < len(active_accounts):
                    phone, data = active_accounts[i]
                    self.set_account_status(phone, ACCOUNT_STATUS_RESERVE, "Scheduled rotation")
                    accounts_to_deactivate.append((phone, data))
                    logger.info(f"  🔵 {data.get('name', phone)} → RESERVE")

            # Активируем столько же резервных аккаунтов (циклическая логика)
            accounts_to_activate = []
            exclude_phones = {p for p, _ in accounts_to_deactivate}
            for _ in range(num_to_rotate):
                new_phone = await self.activate_next_reserve_account(exclude_phones=exclude_phones)
                if not new_phone:
                    break
                new_data = self.accounts_data.get(new_phone, {})
                accounts_to_activate.append((new_phone, new_data))
                exclude_phones.add(new_phone)
                logger.info(f"  🟢 {new_data.get('name', new_phone)} → ACTIVE")

            # Обновляем время последней ротации
            self.last_rotation_time = datetime.now().timestamp()

            # Уведомляем владельца (компактно)
            try:
                deactivated_names = ", ".join([data.get('name', phone) for phone, data in accounts_to_deactivate])
                activated_names = ", ".join([data.get('name', phone) for phone, data in accounts_to_activate])
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"🔄 Ротация: {deactivated_names} → резерв | {activated_names} → активные"
                )
            except Exception as notify_err:
                logger.error(f"Failed to notify owner about rotation: {notify_err}")

            logger.info(f"✅ Rotation completed. Current status: {self.get_status_counts()}")

        except Exception as e:
            logger.error(f"Error during account rotation: {e}")
    
    async def check_and_rotate_if_needed(self):
        """Проверить, нужна ли ротация, и выполнить её"""
        if self.last_rotation_time is None:
            self.last_rotation_time = datetime.now().timestamp()
            return
        
        current_time = datetime.now().timestamp()
        time_since_rotation = current_time - self.last_rotation_time
        
        if time_since_rotation >= self.rotation_interval:
            logger.info(f"⏰ Rotation interval reached ({time_since_rotation:.0f}s >= {self.rotation_interval}s)")
            await self.rotate_accounts()
    
    async def activate_next_reserve_account(self, exclude_phone=None, exclude_phones=None):
        """Активировать следующий резервный аккаунт для ротации (возвращает phone активированного)
        
        Args:
            exclude_phone: Телефон аккаунта, который нужно исключить из выбора (недавно деактивированный)
            exclude_phones: Набор телефонов для исключения из выбора (например, уже деактивированные в текущей ротации)
        """
        try:
            exclude_set = set(exclude_phones) if exclude_phones else set()
            if exclude_phone:
                exclude_set.add(exclude_phone)

            # Ищем резервный аккаунт для активации (ИСКЛЮЧАЯ недавно деактивированный)
            reserve_accounts = [(p, data) for p, data in self.accounts_data.items()
                              if data.get('status') == ACCOUNT_STATUS_RESERVE
                              and data.get('session')
                              and p not in exclude_set]

            # Подробное логирование для диагностики
            logger.info("="*60)
            logger.info("🔍 ПОИСК РЕЗЕРВНОГО АККАУНТА ДЛЯ АКТИВАЦИИ")
            logger.info(f"   Всего аккаунтов в системе: {len(self.accounts_data)}")
            if exclude_set:
                logger.info(f"   Исключены из выбора: {', '.join(sorted(exclude_set))}")
            logger.info(f"   Найдено резервных с сессией: {len(reserve_accounts)}")

            # Покажем все статусы для диагностики
            status_counts = self.get_status_counts()
            logger.info(f"   Статусы: {status_counts}")

            if not reserve_accounts:
                logger.warning("⚠️ No reserve accounts available for rotation!")
                logger.warning("   Все аккаунты либо ACTIVE, либо BROKEN, либо без сессий")
                logger.warning("   Рекомендация: добавьте больше аккаунтов или проверьте статусы")
                return None

            # ============= ЦИКЛИЧЕСКАЯ РОТАЦИЯ: выбираем следующий по кругу =============
            # Получаем ПОЛНЫЙ список ВСЕХ аккаунтов с сессиями (для определения порядка)
            all_accounts = [(p, data) for p, data in self.accounts_data.items()
                          if data.get('session') and data.get('status') != ACCOUNT_STATUS_BROKEN]

            # Находим позицию последнего активированного в полном списке
            last_phone = getattr(self, 'last_activated_phone', None)
            start_pos = 0
            if last_phone:
                for i, (p, _) in enumerate(all_accounts):
                    if p == last_phone:
                        start_pos = i + 1  # Начинаем со следующего после последнего
                        logger.info(f"   🔍 Последний активированный найден на позиции {i+1}/{len(all_accounts)}")
                        break

            # Ищем первый RESERVE (не exclude_phone) начиная с start_pos
            selected_phone = None
            selected_data = None
            attempts = 0
            for offset in range(len(all_accounts)):
                idx = (start_pos + offset) % len(all_accounts)
                phone, data = all_accounts[idx]
                attempts += 1
                if data.get('status') == ACCOUNT_STATUS_RESERVE and phone not in exclude_set:
                    selected_phone = phone
                    selected_data = data
                    logger.info(f"   🔄 Циклический выбор: позиция {idx + 1}/{len(all_accounts)} (проверено {attempts} аккаунтов)")
                    break

            if not selected_phone:
                logger.error("❌ Не найден резервный аккаунт для активации")
                logger.error(f"   Проверено {attempts} аккаунтов, все либо ACTIVE/BROKEN, либо excluded")
                return None

            reserve_phone = selected_phone
            reserve_data = selected_data
            reserve_name = reserve_data.get('name', reserve_phone)

            # Сохраняем для следующей ротации
            self.last_activated_phone = reserve_phone

            logger.info(f"   ✅ Выбран для активации: {reserve_name} ({reserve_phone})")
            logger.info(f"   📌 Последний активированный сохранен для следующей ротации")
            logger.info("="*60)
            # ============= END ЦИКЛИЧЕСКАЯ РОТАЦИЯ =============

            self.set_account_status(reserve_phone, ACCOUNT_STATUS_ACTIVE, "Rotation activation")

            logger.info(f"✅ Activated next reserve account: {reserve_name} ({reserve_phone})")
            logger.info(f"📊 Current status: {self.get_status_counts()}")

            # Уведомляем владельца (компактно)
            try:
                status = self.get_status_counts()
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"✅ Активирован: {reserve_name} | А:{status.get('active',0)} Р:{status.get('reserve',0)}"
                )
            except Exception as notify_err:
                logger.error(f"Failed to notify owner: {notify_err}")

            return reserve_phone

        except Exception as e:
            logger.error(f"Error activating next reserve account: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def launch_replacement_worker(self, worker_index, old_channels, mode, old_total_workers):
        """Запустить нового worker'а на замену завершившемуся (горячая замена)
        
        ВАЖНО: Используем old_channels (осиротевшие каналы) для продолжения работы с того же места!
        """
        try:
            # ============= ИСПОЛЬЗУЕМ ОСИРОТЕВШИЕ КАНАЛЫ =============
            # Новый воркер продолжает с тех каналов, которые обрабатывал старый
            orphaned_channels = old_channels if old_channels else []
            
            # Получаем АКТУАЛЬНОЕ количество активных аккаунтов
            active_accounts = [(p, data) for p, data in self.accounts_data.items() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')]
            current_total_workers = min(len(active_accounts), self.max_parallel_accounts)
            
            logger.info("="*80)
            logger.info(f"🔄 ЗАПУСК REPLACEMENT WORKER С ОСИРОТЕВШИМИ КАНАЛАМИ")
            logger.info(f"   Осиротевших каналов: {len(orphaned_channels)} (продолжим с них)")
            logger.info(f"   Воркеров было: {old_total_workers}, стало: {current_total_workers}")
            logger.info(f"   Активных аккаунтов: {len(active_accounts)}")
            logger.info(f"   max_parallel_accounts: {self.max_parallel_accounts}")
            logger.info("="*80)
            # ============= END ПЕРЕСЧЁТ =============
            
            if not orphaned_channels:
                logger.warning(f"⚠️ No orphaned channels to process in slot {worker_index}")
                return False
            
            if not active_accounts:
                logger.error(f"❌ Cannot launch replacement worker: no active accounts")
                # Если нет активных, перераспределяем каналы между существующими
                await self.redistribute_channels_to_active_workers(worker_index, orphaned_channels)
                return False
            
            # Ищем аккаунт, который не имеет активного worker'а (недавно активированный)
            existing_worker_phones = set(slot.get('phone') for slot in self.worker_slots.values() if slot.get('phone'))
            
            replacement_phone = None
            replacement_data = None
            for phone, data in active_accounts:
                if phone not in existing_worker_phones:
                    replacement_phone = phone
                    replacement_data = data
                    break
            
            if not replacement_phone:
                logger.warning(f"⚠️ No available account for replacement worker in slot {worker_index}")
                logger.warning(f"   Все активные аккаунты уже имеют worker'ов")
                # Перераспределяем каналы между существующими workers
                await self.redistribute_channels_to_active_workers(worker_index, orphaned_channels)
                return False
            
            account_name = replacement_data.get('name', replacement_phone[-10:])
            
            logger.info("="*80)
            logger.info(f"🔄 LAUNCHING REPLACEMENT WORKER")
            logger.info(f"   Slot: {worker_index}")
            logger.info(f"   Account: {account_name} ({replacement_phone})")
            logger.info(f"   Channels: {len(orphaned_channels)} (ОСИРОТЕВШИЕ каналы - продолжаем с них!)")
            logger.info(f"   Total workers: {current_total_workers}")
            logger.info(f"   Mode: {mode}")
            logger.info("="*80)
            
            # Создаём новую задачу worker'а с ОСИРОТЕВШИМИ каналами!
            task = asyncio.create_task(
                self.account_worker(
                    replacement_phone, 
                    replacement_data, 
                    orphaned_channels,  # ОСИРОТЕВШИЕ каналы - продолжаем с того места!
                    worker_index, 
                    current_total_workers,
                    mode=mode
                )
            )
            task.set_name(f"worker_{worker_index}_{replacement_phone[-10:]}_replacement")
            
            # Добавляем в список активных задач
            self.active_worker_tasks.append(task)
            
            logger.info(f"✅ Replacement worker launched: {task.get_name()} (id={id(task)})")
            logger.info(f"📊 Total active workers: {len(self.active_worker_tasks)}")
            
            # Уведомляем владельца (компактное сообщение)
            try:
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"🔄 Замена: слот {worker_index} → {account_name} | {len(orphaned_channels)} каналов | воркеров: {current_total_workers}"
                )
            except Exception as notify_err:
                logger.error(f"Failed to notify owner: {notify_err}")
            
            return True  # Успешный запуск
                
        except Exception as e:
            logger.error(f"❌ Error launching replacement worker: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def redistribute_channels_to_active_workers(self, empty_slot_index, orphaned_channels):
        """
        Перераспределить каналы из пустого слота между активными workers
        Вызывается когда нет резервных аккаунтов для замены
        """
        try:
            logger.info("="*80)
            logger.info(f"🔄 REDISTRIBUTING CHANNELS FROM EMPTY SLOT {empty_slot_index}")
            logger.info(f"   Orphaned channels: {len(orphaned_channels)}")
            logger.info("="*80)
            
            # Получаем активные слоты (исключая пустой)
            active_slots = {idx: slot for idx, slot in self.worker_slots.items() 
                          if idx != empty_slot_index and slot.get('phone')}
            
            # КРИТИЧНО: Проверяем реальные живые воркеры, а не только слоты!
            alive_workers = sum(1 for task in self.active_worker_tasks if not task.done())
            
            logger.info(f"📊 Worker status:")
            logger.info(f"   Active slots: {len(active_slots)}")
            logger.info(f"   Alive workers: {alive_workers}")
            
            if not active_slots:
                # Проверяем, есть ли на самом деле живые воркеры
                if alive_workers > 0:
                    logger.warning(f"⚠️ No active slots BUT {alive_workers} workers are alive!")
                    logger.warning(f"   This is likely a temporary state during rotation")
                    logger.warning(f"   Waiting 3 seconds for slots to be populated...")
                    await asyncio.sleep(3)
                    
                    # Перепроверяем после задержки
                    active_slots = {idx: slot for idx, slot in self.worker_slots.items() 
                                  if idx != empty_slot_index and slot.get('phone')}
                    
                    if active_slots:
                        logger.info(f"✅ Slots populated after wait: {len(active_slots)} slots found")
                        # Продолжаем нормальную обработку ниже
                    else:
                        logger.error(f"❌ Still no active slots after wait, but workers exist")
                        logger.error(f"   This indicates worker_slots desync!")
                        return
                else:
                    # Действительно критическая ситуация - нет ни слотов, ни воркеров
                    logger.error(f"❌ CRITICAL: No active workers AND no active slots!")
                    try:
                        await self.bot_client.send_message(
                            BOT_OWNER_ID,
                            f"🚨 **КРИТИЧЕСКАЯ СИТУАЦИЯ**\n\n"
                            f"❌ Нет активных workers!\n"
                            f"📢 Каналов без обработки: {len(orphaned_channels)}\n\n"
                            f"⚠️ Добавьте резервные аккаунты СРОЧНО!\n"
                            f"💡 Или остановите и перезапустите мониторинг"
                        )
                    except:
                        pass
                    return
            
            # Распределяем каналы равномерно между активными workers
            channels_per_worker = len(orphaned_channels) // len(active_slots)
            remainder = len(orphaned_channels) % len(active_slots)
            
            logger.info(f"📊 Distributing to {len(active_slots)} active workers:")
            logger.info(f"   Base: {channels_per_worker} channels per worker")
            logger.info(f"   Extra: {remainder} workers get +1 channel")
            
            channel_index = 0
            for slot_idx, slot_info in active_slots.items():
                # Сколько каналов добавить этому worker'у
                extra = 1 if slot_idx < remainder else 0
                channels_to_add = channels_per_worker + extra
                
                if channels_to_add > 0:
                    new_channels = orphaned_channels[channel_index:channel_index + channels_to_add]
                    channel_index += channels_to_add
                    
                    # Добавляем каналы к существующим
                    current_channels = slot_info.get('channels', [])
                    updated_channels = current_channels + new_channels
                    slot_info['channels'] = updated_channels
                    
                    phone = slot_info.get('phone')
                    account_name = self.accounts_data.get(phone, {}).get('name', phone[-10:] if phone else 'Unknown')
                    
                    logger.info(f"  ✅ Slot {slot_idx} ({account_name}): +{len(new_channels)} channels "
                              f"(total: {len(updated_channels)})")
            
            # Удаляем пустой слот
            if empty_slot_index in self.worker_slots:
                del self.worker_slots[empty_slot_index]
                logger.info(f"🗑️  Removed empty slot {empty_slot_index}")
            
            logger.info("="*80)
            logger.info(f"✅ REDISTRIBUTION COMPLETE")
            logger.info(f"   Active slots: {len(self.worker_slots)}")
            logger.info(f"   Channels redistributed: {channel_index}/{len(orphaned_channels)}")
            logger.info("="*80)
            
            # Уведомляем владельца (компактно)
            try:
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"📊 Перераспределение: {len(orphaned_channels)} каналов → {len(self.worker_slots)} воркеров"
                )
            except Exception as notify_err:
                logger.error(f"Failed to notify owner: {notify_err}")
                
        except Exception as e:
            logger.error(f"❌ Error redistributing channels: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def replace_broken_account(self, phone, reason):
        """Заменить сломанный аккаунт на резервный (с горячей заменой worker'а)"""
        try:
            # Помечаем аккаунт как broken
            self.set_account_status(phone, ACCOUNT_STATUS_BROKEN, reason)
            account_name = self.accounts_data[phone].get('name', phone)
            
            # Находим slot этого worker'а (если есть)
            worker_slot_index = None
            worker_channels = None
            worker_mode = None
            worker_total = None
            
            for slot_idx, slot_info in self.worker_slots.items():
                if slot_info.get('phone') == phone:
                    worker_slot_index = slot_idx
                    worker_channels = slot_info.get('channels')
                    worker_mode = slot_info.get('mode')
                    worker_total = slot_info.get('total_workers')
                    logger.info(f"🔍 Found worker slot {slot_idx} for broken account {phone[-10:]}")
                    break
            
            # Ищем резервный аккаунт для замены
            reserve_accounts = [(p, data) for p, data in self.accounts_data.items() 
                              if data.get('status') == ACCOUNT_STATUS_RESERVE and data.get('session')]
            
            if reserve_accounts:
                # Активируем первый доступный резервный аккаунт
                reserve_phone, reserve_data = reserve_accounts[0]
                self.set_account_status(reserve_phone, ACCOUNT_STATUS_ACTIVE, f"Replacing {account_name}")
                reserve_name = reserve_data.get('name', reserve_phone)
                
                logger.info(f"✅ Replaced broken account: {account_name} → {reserve_name}")
                
                # ============= ГОРЯЧАЯ ЗАМЕНА: Запускаем replacement worker =============
                if worker_slot_index is not None and worker_channels and self.monitoring:
                    logger.info(f"🔥 Initiating HOT SWAP for broken account in slot {worker_slot_index}")
                    try:
                        success = await self.launch_replacement_worker(
                            worker_slot_index, 
                            worker_channels, 
                            worker_mode or 'distributed', 
                            worker_total or self.max_parallel_accounts
                        )
                        
                        if success:
                            logger.info(f"✅ Hot swap completed for slot {worker_slot_index}")
                            
                            # Уведомляем владельца об успешной горячей замене
                            try:
                                await self.bot_client.send_message(
                                    BOT_OWNER_ID,
                                    f"🔥 **Горячая замена после бана**\n\n"
                                    f"🔴 Забанен: `{account_name}` ({phone[-10:]})\n"
                                    f"Причина: {reason}\n\n"
                                    f"✅ Активирован: `{reserve_name}` ({reserve_phone[-10:]})\n"
                                    f"🔄 Worker перезапущен в слоте {worker_slot_index}\n"
                                    f"📢 Каналов: {len(worker_channels) if worker_channels else 0}\n\n"
                                    f"📊 Состояние: {self.get_status_counts()}\n\n"
                                    f"✅ Комментирование продолжается без простоя!"
                                )
                            except Exception as notify_err:
                                logger.error(f"Failed to notify owner: {notify_err}")
                        else:
                            logger.warning(f"⚠️ Hot swap failed, channels were redistributed")
                            # Уведомление уже отправлено в redistribute_channels_to_active_workers
                        
                    except Exception as swap_err:
                        logger.error(f"❌ Hot swap failed: {swap_err}, falling back to full restart")
                        # Fallback: полный перезапуск если горячая замена не удалась
                        if self.worker_recovery_enabled:
                            logger.info("🔄 Scheduling monitoring restart in 10 seconds...")
                            asyncio.create_task(self.restart_monitoring_after_replacement())
                else:
                    # Если worker не найден или мониторинг остановлен - обычный путь
                    logger.warning(f"⚠️ Worker slot not found or monitoring stopped, using standard replacement")
                    
                    # Уведомляем владельца
                    try:
                        await self.bot_client.send_message(
                            BOT_OWNER_ID,
                            f"⚠️ **Автоматическая замена аккаунта**\n\n"
                            f"🔴 Сломан: `{account_name}` ({phone})\n"
                            f"Причина: {reason}\n\n"
                            f"✅ Активирован резервный: `{reserve_name}` ({reserve_phone})\n\n"
                            f"📊 Состояние: {self.get_status_counts()}\n\n"
                            f"🔄 Система автоматически перезапустится через 10 секунд"
                        )
                    except Exception as notify_err:
                        logger.error(f"Failed to notify owner: {notify_err}")
                    
                    # Автоматический перезапуск
                    if self.monitoring and self.worker_recovery_enabled:
                        logger.info("🔄 Scheduling monitoring restart in 10 seconds...")
                        asyncio.create_task(self.restart_monitoring_after_replacement())
                # ============= END ГОРЯЧАЯ ЗАМЕНА =============
                
                return True
            else:
                logger.error(f"❌ No reserve accounts available to replace {account_name}!")
                try:
                    await self.bot_client.send_message(
                        BOT_OWNER_ID,
                        f"🚨 **ВНИМАНИЕ: Нет резервных аккаунтов!**\n\n"
                        f"🔴 Сломан: `{account_name}` ({phone})\n"
                        f"Причина: {reason}\n\n"
                        f"❌ Все резервные аккаунты уже активны или отсутствуют.\n\n"
                        f"📊 Состояние: {self.get_status_counts()}"
                    )
                except Exception as notify_err:
                    logger.error(f"Failed to notify owner: {notify_err}")
                
                return False
                
        except Exception as e:
            logger.error(f"Error replacing broken account: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def restart_monitoring_after_replacement(self):
        """Перезапускает мониторинг после замены аккаунта"""
        try:
            await asyncio.sleep(10)  # Даём время на завершение старых воркеров
            
            if not self.monitoring:
                logger.info("⚠️ Monitoring already stopped, skipping restart")
                return
            
            logger.info("="*80)
            logger.info("🔄 RESTARTING MONITORING AFTER ACCOUNT REPLACEMENT")
            logger.info("="*80)
            
            # Останавливаем текущие воркеры
            logger.info("⏸️ Stopping current workers...")
            self.monitoring = False
            
            # Ждём завершения старых воркеров
            if self.active_worker_tasks:
                logger.info(f"⏳ Waiting for {len(self.active_worker_tasks)} workers to finish...")
                await asyncio.sleep(5)
                self.active_worker_tasks.clear()
            
            # Перезапускаем
            logger.info("🚀 Starting new workers with updated accounts...")
            self.monitoring = True
            asyncio.create_task(self.pro_auto_comment())
            
            logger.info("✅ Monitoring restarted successfully")
            
            # Уведомляем владельца (компактно)
            try:
                status = self.get_status_counts()
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"✅ Мониторинг перезапущен | активных: {status.get('active', 0)} | резервных: {status.get('reserve', 0)}"
                )
            except Exception as notify_err:
                logger.error(f"Failed to notify owner: {notify_err}")
                
        except Exception as e:
            logger.error(f"Error restarting monitoring: {e}")
            try:
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"❌ **Ошибка перезапуска мониторинга**\n\n"
                    f"Причина: {str(e)}\n\n"
                    f"💡 Используйте /stopmon и /startmon вручную"
                )
            except:
                pass
    
    async def health_check_worker(self):
        """Периодически проверяет количество воркеров и восстанавливает при необходимости"""
        logger.info("🏥 Health check worker started")
        
        while self.monitoring:
            try:
                await asyncio.sleep(120)  # Проверка каждые 2 минуты
                
                if not self.monitoring:
                    break
                
                # ============= NEW: ОЧИСТКА ИСТОРИИ FLOODWAIT =============
                # Очищаем истекшие FloodWait каждую проверку
                self.cleanup_expired_floodwaits()
                # ============= END NEW =============
                
                # Подсчёт активных аккаунтов
                active_accounts = {phone: data for phone, data in self.accounts_data.items()
                                 if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')}
                
                expected_workers = min(len(active_accounts), self.max_parallel_accounts)
                
                # Подсчёт живых воркеров - КРИТИЧНО для диагностики!
                alive_workers = 0
                dead_workers = []
                for task in self.active_worker_tasks:
                    if task.done():
                        dead_workers.append((task.get_name(), task))
                    else:
                        alive_workers += 1
                
                # Логируем статус каждого воркера
                logger.debug(f"🏥 Worker status check:")
                logger.debug(f"   Total tracked: {len(self.active_worker_tasks)}")
                logger.debug(f"   Alive: {alive_workers}")
                logger.debug(f"   Dead: {len(dead_workers)}")
                
                if dead_workers:
                    logger.warning(f"💀 Dead workers detected: {len(dead_workers)}")
                    for task_name, task in dead_workers:
                        try:
                            exc = task.exception()
                            logger.warning(f"   {task_name}: {exc}")
                        except Exception as e:
                            logger.warning(f"   {task_name}: Cancelled or completed")
                    
                    # Очищаем мертвые таски из списка
                    logger.info(f"🧹 Cleaning up {len(dead_workers)} dead workers from tracking list")
                    self.active_worker_tasks = [task for task in self.active_worker_tasks if not task.done()]
                    logger.info(f"✅ Active workers list updated: {len(self.active_worker_tasks)} tasks remaining")
                
                # ============= УЛУЧШЕНИЕ: Проверяем нормальное завершение ротации =============
                if alive_workers < expected_workers:
                    # Проверяем, не завершились ли воркеры по нормальной ротации
                    if self.workers_completing_cycles:
                        logger.info(f"ℹ️ Workers completing cycles: {len(self.workers_completing_cycles)}")
                        logger.info(f"   This is NORMAL rotation, not a crash!")
                        logger.info(f"   Replacement workers should already be running...")
                        self.workers_completing_cycles.clear()
                        
                        # Даём время на запуск replacement workers
                        logger.info(f"⏳ Waiting 5 seconds for replacement workers to start...")
                        await asyncio.sleep(5)
                        
                        # Перечитываем alive workers после задержки
                        alive_workers_after = 0
                        for task in self.active_worker_tasks:
                            if not task.done():
                                alive_workers_after += 1
                        
                        logger.info(f"📊 Workers after rotation: {alive_workers_after}/{expected_workers}")
                        
                        if alive_workers_after >= expected_workers:
                            logger.info(f"✅ Rotation completed successfully, all slots filled")
                            continue
                        else:
                            logger.warning(f"⚠️ Some replacement workers missing: {alive_workers_after}/{expected_workers}")
                            # Продолжаем нормальную логику восстановления ниже
                    # ============= END УЛУЧШЕНИЕ =============
                    
                    # Проверяем, не временное ли это состояние (воркеры в процессе запуска)
                    logger.info(f"⏳ Waiting 3 seconds to verify worker count issue...")
                    await asyncio.sleep(3)
                    
                    # Повторная проверка
                    alive_workers_recheck = sum(1 for task in self.active_worker_tasks if not task.done())
                    
                    if alive_workers_recheck >= expected_workers:
                        logger.info(f"✅ False alarm: workers restored to {alive_workers_recheck}/{expected_workers}")
                        continue
                    
                    logger.warning("="*80)
                    logger.warning(f"⚠️ WORKER COUNT MISMATCH DETECTED!")
                    logger.warning(f"   Expected: {expected_workers} workers")
                    logger.warning(f"   Running: {alive_workers_recheck} workers")
                    logger.warning(f"   Missing: {expected_workers - alive_workers_recheck} workers")
                    logger.warning("="*80)
                    
                    if self.worker_recovery_enabled:
                        logger.info("🔄 Initiating automatic recovery...")
                        
                        # Уведомляем владельца ТОЛЬКО ЕСЛИ ДЕЙСТВИТЕЛЬНО ПРОБЛЕМА
                        try:
                            await self.bot_client.send_message(
                                BOT_OWNER_ID,
                                f"⚠️ **Обнаружена проблема с воркерами**\n\n"
                                f"Ожидается: {expected_workers}\n"
                                f"Работает: {alive_workers_recheck}\n"
                                f"Недостаёт: {expected_workers - alive_workers_recheck}\n\n"
                                f"🔄 Автоматическое восстановление через 10 секунд"
                            )
                        except:
                            pass
                        
                        # Перезапуск
                        await self.restart_monitoring_after_replacement()
                        break  # Выходим, новый health check запустится с новым мониторингом
                else:
                    logger.debug(f"✅ Health check OK: {alive_workers}/{expected_workers} workers")
                    
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(60)
        
        logger.info("🏥 Health check worker stopped")
    
    def is_super_admin(self, user_id):
        """Check if user is a super admin (can see global stats and manage admins)"""
        return user_id in SUPER_ADMINS
    
    async def is_admin(self, user_id):
        """Check if user is any admin (super admin or regular admin)"""
        return user_id in SUPER_ADMINS or user_id in self.admins
    
    def get_admin_id(self, user_id):
        """Get admin_id for filtering data. Super admins can see all data."""
        if self.is_super_admin(user_id):
            return None  # None means "all admins" for super admins
        return user_id  # Regular admins see only their own data
    
    async def authorize_account(self, phone, proxy=None, event=None):
        """Начинает процесс авторизации и сохраняет состояние в pending_auth"""
        try:
            session_string = ''
            assert API_ID is not None, "api_id is None"
            assert API_HASH is not None, "api_hash is None"
            assert phone is not None, "phone is None"
            assert session_string is not None, "session is None"

            api_hash_masked = f"{API_HASH[:4]}...{API_HASH[-4:]}" if API_HASH else None
            if proxy and len(proxy) >= 3:
                proxy_safe = (proxy[0], proxy[1], proxy[2])
            else:
                proxy_safe = proxy
            logger.info(
                "AUTH PARAMS: api_id=%s api_hash=%s phone=%s proxy=%s",
                API_ID,
                api_hash_masked,
                phone,
                proxy_safe
            )

            client = TelegramClient(StringSession(session_string), API_ID, API_HASH, proxy=proxy)
            await client.connect()
            
            logger.info("AUTH START: phone=%r client=%s", phone, type(client))
            is_connected = client.is_connected() if hasattr(client, 'is_connected') else "N/A"
            logger.info("AUTH CLIENT CONNECTED: %s", is_connected)
            
            if not await client.is_user_authorized():
                try:
                    result = await client.send_code_request(phone)
                    logger.info("AUTH CODE REQUEST SUCCESS: %s", result)
                except Exception as e:
                    logger.exception("AUTH CODE REQUEST FAILED")
                    raise
                logger.info(f"Код отправлен на {phone}")
                
                if event:
                    # Отправляем сообщение и сохраняем состояние
                    msg = await event.respond(f"📱 Код отправлен на `{phone}`\n\nОтветьте на это сообщение с кодом авторизации (5 цифр)")
                    
                    # Сохраняем состояние ожидания кода
                    self.pending_auth[event.chat_id] = {
                        'phone': phone,
                        'proxy': proxy,
                        'client': client,
                        'message_id': msg.id,
                        'state': 'waiting_code',
                        'event': event
                    }
                    logger.info(f"Сохранено состояние авторизации для chat_id={event.chat_id}, phone={phone}, msg_id={msg.id}")
                    
                    # Возвращаем None, чтобы показать, что процесс не завершен
                    return 'pending'
                else:
                    # Fallback на консоль (если нет event)
                    print(f"Код отправлен на {phone}")
                    code = input("Введите код из Telegram: ")
                    try:
                        await client.sign_in(phone, code)
                    except SessionPasswordNeededError:
                        password = input("Введите пароль 2FA: ")
                        await client.sign_in(password=password)
                    
                    me = await client.get_me()
                    session = client.session.save()
                    await client.disconnect()
                    
                    # Determine admin_id: None for super admins, user_id for regular admins
                    admin_id = None if (event and self.is_super_admin(event.sender_id)) else (event.sender_id if event else None)
                    
                    return {
                        'session': session,
                        'active': True,
                        'name': me.first_name or 'Без имени',
                        'username': getattr(me, 'username', None),
                        'phone': phone,
                        'proxy': proxy,
                        'admin_id': admin_id
                    }
            else:
                # Уже авторизован
                me = await client.get_me()
                session = client.session.save()
                await client.disconnect()
                
                # Determine admin_id: None for super admins, user_id for regular admins
                admin_id = None if (event and self.is_super_admin(event.sender_id)) else (event.sender_id if event else None)
                
                return {
                    'session': session,
                    'active': True,
                    'name': me.first_name or 'Без имени',
                    'username': getattr(me, 'username', None),
                    'phone': phone,
                    'proxy': proxy,
                    'admin_id': admin_id
                }
                
        except TypeError as e:
            logger.exception("AUTH TYPEERROR: %s", e)
            logger.exception("Auth error")
            if event:
                await event.respond("⚠️ Ошибка авторизации, проверь номер и попробуй ещё раз.")
            # Очистка состояния при ошибке
            if event and event.chat_id in self.pending_auth:
                try:
                    await self.pending_auth[event.chat_id]['client'].disconnect()
                except:
                    pass
                del self.pending_auth[event.chat_id]
            return None
        except Exception as e:
            logger.exception("Auth error")
            if event:
                await event.respond("⚠️ Ошибка авторизации, проверь номер и попробуй ещё раз.")
            # Очистка состояния при ошибке
            if event and event.chat_id in self.pending_auth:
                try:
                    await self.pending_auth[event.chat_id]['client'].disconnect()
                except:
                    pass
                del self.pending_auth[event.chat_id]
            return None
    
    async def set_account_bio(self, session_data, bio_text):
        try:
            client = TelegramClient(StringSession(session_data['session']), API_ID, API_HASH, proxy=session_data.get('proxy'))
            await client.connect()
            if await client.is_user_authorized():
                await client(UpdateProfileRequest(about=bio_text))
                await client.disconnect()
                return True
        except:
            pass
        return False
    
    # ============= PROFILE MANAGEMENT FUNCTIONS =============
    
    def get_all_accounts_from_env(self):
        """
        Динамически получает все аккаунты из переменных окружения.
        Ищет ACCOUNT_N_PHONE, ACCOUNT_N_SESSION, ACCOUNT_N_PROXY (где N = 1, 2, 3...)
        Возвращает список кортежей: [(номер, телефон, сессия, прокси), ...]
        """
        if self.account_cache:
            return self.account_cache.get('accounts', [])
        
        accounts = []
        n = 1
        while True:
            phone_key = f'ACCOUNT_{n}_PHONE'
            phone = os.getenv(phone_key)
            
            if not phone:
                break  # Нет больше аккаунтов
            
            session = os.getenv(f'ACCOUNT_{n}_SESSION', '')
            proxy_str = os.getenv(f'ACCOUNT_{n}_PROXY', '')
            
            # Parse proxy if exists (format: socks5:host:port:rdns:user:pass OR socks5:host:port:user:pass)
            proxy = None
            if proxy_str:
                try:
                    parts = proxy_str.split(':')
                    # Telethon expects: (type, host, port, rdns, username, password)
                    if len(parts) == 6:
                        # Full format: socks5:host:port:rdns:user:pass
                        proxy = (parts[0], parts[1], int(parts[2]), 
                                parts[3].lower() == 'true', parts[4], parts[5])
                    elif len(parts) >= 5:
                        # Short format: socks5:host:port:user:pass (rdns=True by default)
                        proxy = (parts[0], parts[1], int(parts[2]), True, parts[3], parts[4])
                except Exception as e:
                    logger.warning(f"Failed to parse proxy for ACCOUNT_{n}: {e}")
            
            accounts.append((n, phone, session, proxy))
            n += 1
        
        # Cache results
        self.account_cache['accounts'] = accounts
        logger.info(f"Found {len(accounts)} accounts in environment variables")
        return accounts
    
    def create_accounts_keyboard(self, page=0, per_page=5):
        """
        Создаёт inline клавиатуру со списком аккаунтов с пагинацией.
        """
        accounts = self.get_all_accounts_from_env()
        
        if not accounts:
            return [[Button.inline("❌ Аккаунты не найдены", b"no_accounts")]]
        
        total_accounts = len(accounts)
        total_pages = (total_accounts + per_page - 1) // per_page
        page = max(0, min(page, total_pages - 1))  # Validate page
        
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, total_accounts)
        
        buttons = []
        
        # Account buttons
        for i in range(start_idx, end_idx):
            num, phone, session, proxy = accounts[i]
            status = "✅" if session else "❌"
            button_text = f"{status} Аккаунт {num} - {phone}"
            buttons.append([Button.inline(button_text, f"acc_{num}".encode())])
        
        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(Button.inline("◀️ Назад", f"acc_page_{page-1}".encode()))
        
        if total_pages > 1:
            nav_buttons.append(Button.inline(f"📄 {page+1}/{total_pages}", b"page_info"))
        
        if page < total_pages - 1:
            nav_buttons.append(Button.inline("Вперёд ▶️", f"acc_page_{page+1}".encode()))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        # Main menu button
        buttons.append([Button.inline("🏠 Главное меню", b"main_menu")])
        
        return buttons
    
    def create_account_menu_keyboard(self, account_num):
        """
        Создаёт меню для конкретного аккаунта с кнопками:
        - Аватарка
        - Имя и Фамилия
        - О себе (Био)
        - Назад
        """
        buttons = [
            [Button.inline("📷 Аватарка", f"acc_{account_num}_avatar".encode())],
            [Button.inline("👤 Имя и Фамилия", f"acc_{account_num}_name".encode())],
            [Button.inline("📝 О себе (Био)", f"acc_{account_num}_bio".encode())],
            [Button.inline("◀️ Назад к списку", b"back_to_accounts")],
            [Button.inline("🏠 Главное меню", b"main_menu")]
        ]
        return buttons
    
    async def get_account_info(self, account_num):
        """
        Получает информацию об аккаунте из переменных окружения
        и пытается получить текущие данные профиля из Telegram.
        """
        accounts = self.get_all_accounts_from_env()
        account_data = None
        
        for num, phone, session, proxy in accounts:
            if num == account_num:
                account_data = {
                    'num': num,
                    'phone': phone,
                    'session': session,
                    'proxy': proxy
                }
                break
        
        if not account_data:
            return None
        
        # Try to get current profile info
        if account_data['session']:
            try:
                client = TelegramClient(
                    StringSession(account_data['session']), 
                    API_ID, 
                    API_HASH,
                    proxy=account_data.get('proxy')
                )
                await client.connect()
                
                if await client.is_user_authorized():
                    me = await client.get_me()
                    account_data['first_name'] = me.first_name or ''
                    account_data['last_name'] = me.last_name or ''
                    account_data['username'] = me.username or ''
                    
                    # Get full user info to retrieve bio
                    try:
                        full_user = await client(GetFullUserRequest(me))
                        account_data['bio'] = full_user.full_user.about or ''
                    except Exception:
                        account_data['bio'] = ''
                    
                    account_data['authorized'] = True
                else:
                    account_data['authorized'] = False
                
                await client.disconnect()
            except Exception as e:
                logger.error(f"Error getting account info for {account_num}: {e}")
                account_data['authorized'] = False
        else:
            account_data['authorized'] = False
        
        return account_data
    
    async def apply_account_changes(self, account_num, avatar_file=None, first_name=None, last_name=None, bio=None):
        """
        Применяет изменения к профилю аккаунта:
        - avatar_file: путь к файлу изображения
        - first_name: новое имя
        - last_name: новая фамилия
        - bio: новая информация о себе
        
        Возвращает (success: bool, message: str)
        """
        try:
            account_info = await self.get_account_info(account_num)
            
            if not account_info:
                return False, f"❌ Аккаунт {account_num} не найден"
            
            if not account_info.get('authorized'):
                return False, f"❌ Аккаунт {account_num} не авторизован"
            
            # Create client
            client = TelegramClient(
                StringSession(account_info['session']), 
                API_ID, 
                API_HASH,
                proxy=account_info.get('proxy')
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, f"❌ Аккаунт {account_num} потерял авторизацию"
            
            results = []
            
            # Update avatar
            if avatar_file and os.path.exists(avatar_file):
                try:
                    await client(UploadProfilePhotoRequest(
                        file=await client.upload_file(avatar_file)
                    ))
                    results.append("✅ Аватарка обновлена")
                    logger.info(f"Avatar updated for account {account_num}")
                except Exception as e:
                    results.append(f"❌ Ошибка загрузки аватарки: {str(e)[:50]}")
                    logger.error(f"Avatar upload error for account {account_num}: {e}")
            
            # Update name and/or bio
            if first_name is not None or last_name is not None or bio is not None:
                try:
                    # Get current values if not provided
                    if first_name is None:
                        first_name = account_info.get('first_name', '')
                    if last_name is None:
                        last_name = account_info.get('last_name', '')
                    if bio is None:
                        bio = account_info.get('bio', '')
                    
                    await client(UpdateProfileRequest(
                        first_name=first_name or '',
                        last_name=last_name or '',
                        about=bio or ''
                    ))
                    
                    if first_name is not None or last_name is not None:
                        results.append(f"✅ Имя обновлено: {first_name} {last_name}")
                    if bio is not None:
                        results.append(f"✅ Био обновлено")
                    
                    logger.info(f"Profile updated for account {account_num}")
                except Exception as e:
                    results.append(f"❌ Ошибка обновления профиля: {str(e)[:50]}")
                    logger.error(f"Profile update error for account {account_num}: {e}")
            
            await client.disconnect()
            
            if results:
                return True, "\n".join(results)
            else:
                return False, "❌ Нечего обновлять"
                
        except Exception as e:
            logger.error(f"Error applying changes to account {account_num}: {e}")
            return False, f"❌ Ошибка: {str(e)[:100]}"
    
    async def clear_user_state(self, user_id):
        """Очищает состояние пользователя"""
        if user_id in self.user_states:
            # Clean up temp files if any
            state = self.user_states[user_id]
            if 'temp_avatar' in state.get('data', {}):
                temp_file = state['data']['temp_avatar']
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
            
            del self.user_states[user_id]
    
    async def save_temp_avatar(self, user_id, file_path):
        """Сохраняет временный файл аватарки"""
        # Create temp directory if not exists
        temp_dir = Path("/tmp/bot_avatars")
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"avatar_{user_id}_{datetime.now().timestamp()}.jpg"
        temp_path = temp_dir / filename
        
        # Copy file
        import shutil
        shutil.copy(file_path, temp_path)
        
        return str(temp_path)
    
    async def log_profile_change(self, phone, change_type, old_value, new_value, success=True):
        """Логирует изменение профиля в БД"""
        try:
            if self.conn:
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO profile_changes (phone, change_type, old_value, new_value, change_date, success)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (phone, change_type, old_value or '', new_value or '', 
                      datetime.now().isoformat(), 1 if success else 0))
                self.conn.commit()
                logger.info(f"Profile change logged: {phone} - {change_type}")
        except Exception as e:
            logger.error(f"Error logging profile change: {e}")
    
    # ============= END PROFILE MANAGEMENT FUNCTIONS =============
    
    # ============= PROFILE CHANNEL FUNCTIONS =============
    
    async def create_profile_channel(self, phone, title, about=''):
        """
        Создать новый канал от имени аккаунта.
        
        Returns: (success: bool, result: dict/str)
            result может быть dict с информацией о канале или строкой с ошибкой
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден"
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            # Создаём USER-клиент для операции (bot не может создавать каналы!)
            user_client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Создаём канал через MTProto
            from telethon.tl.functions.channels import CreateChannelRequest
            from telethon.tl.types import Channel
            
            result = await user_client(CreateChannelRequest(
                title=title,
                about=about,
                broadcast=True,  # broadcast channel (not megagroup)
                megagroup=False
            ))
            
            # Получаем информацию о созданном канале
            created_channel = result.chats[0]
            
            if not isinstance(created_channel, Channel):
                await user_client.disconnect()
                return False, "❌ Не удалось создать канал"
            
            # Получаем username канала (может быть None)
            channel_username = getattr(created_channel, 'username', None)
            channel_id = created_channel.id
            
            channel_info = {
                'channel_id': channel_id,
                'title': title,
                'username': channel_username,
                'about': about,
                'created': datetime.now().isoformat()
            }
            
            # Сохраняем в аккаунте
            account_data['showcase_channel'] = channel_info
            self.save_data()
            
            await user_client.disconnect()
            
            logger.info(f"✅ Profile channel created for {phone}: {channel_info}")
            return True, channel_info
            
        except Exception as e:
            logger.error(f"Error creating profile channel for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}"
    
    async def link_existing_channel(self, phone, channel_identifier):
        """
        Привязать существующий канал к профилю аккаунта.
        Проверяет, что аккаунт является админом канала.
        
        channel_identifier: @username или ID канала
        
        Returns: (success: bool, result: dict/str)
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден"
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            # Создаём USER-клиент (bot не имеет доступа к admin-правам каналов)
            user_client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Получаем информацию о канале
            from telethon.tl.types import Channel, PeerChannel
            
            try:
                # Если channel_identifier - число, используем PeerChannel для корректной типизации
                if isinstance(channel_identifier, int):
                    entity = await user_client.get_entity(PeerChannel(channel_identifier))
                else:
                    entity = await user_client.get_entity(channel_identifier)
            except Exception as e:
                await user_client.disconnect()
                return False, f"❌ Канал не найден: {str(e)}"
            
            if not isinstance(entity, Channel):
                await user_client.disconnect()
                return False, f"❌ {channel_identifier} не является каналом"
            
            # Проверяем права админа
            from telethon.tl.functions.channels import GetParticipantRequest
            from telethon.tl.types import ChannelParticipantCreator, ChannelParticipantAdmin
            
            try:
                me = await user_client.get_me()
                participant = await user_client(GetParticipantRequest(
                    channel=entity,
                    participant=me
                ))
                
                # Проверяем, что пользователь - создатель или админ
                is_admin = isinstance(participant.participant, (ChannelParticipantCreator, ChannelParticipantAdmin))
                
                if not is_admin:
                    await user_client.disconnect()
                    return False, f"❌ Вы не являетесь админом канала {channel_identifier}"
                    
            except Exception as e:
                await user_client.disconnect()
                return False, f"❌ Не удалось проверить права: {str(e)}"
            
            # Получаем полную информацию о канале
            from telethon.tl.functions.channels import GetFullChannelRequest
            full_channel = await user_client(GetFullChannelRequest(channel=entity))
            
            channel_username = getattr(entity, 'username', None)
            channel_info = {
                'channel_id': entity.id,
                'title': entity.title,
                'username': channel_username,
                'about': full_channel.full_chat.about or '',
                'linked': datetime.now().isoformat()
            }
            
            # Сохраняем в аккаунте
            account_data['showcase_channel'] = channel_info
            self.save_data()
            
            await user_client.disconnect()
            
            logger.info(f"✅ Profile channel linked for {phone}: {channel_info}")
            return True, channel_info
            
        except Exception as e:
            logger.error(f"Error linking profile channel for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}"
    
    async def set_profile_channel_avatar(self, phone, avatar_file):
        """
        Установить аватар для profile_channel.
        
        Returns: (success: bool, message: str)
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден"
            
            profile_channel = account_data.get('showcase_channel')
            if not profile_channel:
                return False, f"❌ У аккаунта {phone} нет привязанного канала"
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            # Создаём USER-клиент (bot не может редактировать каналы)
            user_client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Получаем канал
            from telethon.tl.types import PeerChannel
            from telethon.tl.functions.channels import EditPhotoRequest
            
            channel_id = profile_channel['channel_id']
            peer = PeerChannel(channel_id)
            entity = await user_client.get_entity(peer)
            
            # Загружаем аватар
            
            uploaded_file = await user_client.upload_file(avatar_file)
            await user_client(EditPhotoRequest(
                channel=entity,
                photo=uploaded_file
            ))
            
            await user_client.disconnect()
            
            logger.info(f"✅ Avatar set for profile channel of {phone}")
            return True, "✅ Аватар канала обновлён"
            
        except Exception as e:
            logger.error(f"Error setting profile channel avatar for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}"
    
    async def create_profile_channel_post(self, phone, text, pin=False):
        """
        Создать пост в profile_channel.
        
        Args:
            phone: номер телефона аккаунта
            text: текст поста
            pin: закрепить ли пост
        
        Returns: (success: bool, message: str, post_id: int)
        """
        try:
            account_data = self.accounts_data.get(phone)
            if not account_data:
                return False, f"❌ Аккаунт {phone} не найден", None
            
            profile_channel = account_data.get('showcase_channel')
            if not profile_channel:
                return False, f"❌ У аккаунта {phone} нет привязанного канала", None
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован", None
            
            # Создаём USER-клиент (bot не может постить в каналы от имени user)
            user_client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию", None
            
            # Получаем канал
            from telethon.tl.types import PeerChannel
            
            channel_id = profile_channel['channel_id']
            peer = PeerChannel(channel_id)
            entity = await user_client.get_entity(peer)
            
            # Отправляем пост
            message = await user_client.send_message(entity, text)
            post_id = message.id
            
            # Закрепляем если нужно
            if pin:
                from telethon.tl.functions.messages import UpdatePinnedMessageRequest
                await user_client(UpdatePinnedMessageRequest(
                    peer=entity,
                    id=post_id,
                    unpin=False,
                    pm_oneside=False
                ))
            
            await user_client.disconnect()
            
            logger.info(f"✅ Post created in profile channel of {phone}, post_id={post_id}, pinned={pin}")
            return True, "✅ Пост создан" + (" и закреплён" if pin else ""), post_id
            
        except Exception as e:
            logger.error(f"Error creating post in profile channel for {phone}: {e}")
            return False, f"❌ Ошибка: {str(e)}", None
    
    async def update_profile_channel_info(self, phone, title=None, about=None):
        """
        Обновляет информацию витрины (только сохраняет в bot_data)
        НЕ пытается редактировать через Telegram API!
        """
        try:
            logger.info(f"📝 Обновляю информацию витрины для {phone}")

            # Ищем аккаунт
            account_key = None
            if phone in self.accounts_data:
                account_key = phone
            else:
                for key, acc_data in self.accounts_data.items():
                    if acc_data.get('phone') == phone:
                        account_key = key
                        break

            if not account_key:
                logger.error(f"Аккаунт {phone} не найден")
                return False

            account_data = self.accounts_data[account_key]

            # Проверяем витрину
            showcase = account_data.get('showcase_channel')
            if not showcase:
                logger.error(f"У аккаунта {phone} нет витрины")
                return False

            # Обновляем ТОЛЬКО в памяти и в bot_data.json
            if title:
                logger.info(f"  Обновляю title: {showcase.get('title')} → {title}")
                showcase['title'] = title

            if about:
                logger.info(f"  Обновляю about: {showcase.get('about', '')} → {about}")
                showcase['about'] = about

            # Сохраняем в bot_data
            self.accounts_data[account_key]['showcase_channel'] = showcase
            self.save_data()

            logger.info("✅ Витрина обновлена в bot_data.json")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка при обновлении витрины: {e}", exc_info=True)
            return False

    async def edit_channel_in_telegram(self, phone, title=None, about=None, photo_path=None):
        """
        Редактирует канал в Telegram (название, описание, фото)
        """
        try:
            logger.info(f"📝 Редактирую канал для {phone}")

            # 1. Ищем аккаунт
            account_key = None
            if phone in self.accounts_data:
                account_key = phone
            else:
                for key, acc_data in self.accounts_data.items():
                    if acc_data.get('phone') == phone:
                        account_key = key
                        break

            if not account_key:
                logger.error(f"Аккаунт {phone} не найден")
                return False

            account_data = self.accounts_data[account_key]
            showcase = account_data.get('showcase_channel')

            if not showcase:
                logger.error(f"У {phone} нет витрины")
                return False

            channel_username = showcase.get('username')
            channel_id = showcase.get('channel_id')

            if not channel_username and not channel_id:
                logger.error("Нет username/id канала")
                return False

            # 2. Создаём клиент с сессией аккаунта
            session_data = account_data.get('session')
            if not session_data:
                logger.error(f"Нет сессии для {phone}")
                return False

            from telethon.sessions import StringSession

            proxy = account_data.get('proxy')

            # Создаём временный клиент
            temp_client = TelegramClient(
                StringSession(session_data),
                api_id=API_ID,
                api_hash=API_HASH,
                proxy=proxy
            )

            success = True

            async with temp_client:
                # Проверяем авторизацию
                if not await temp_client.is_user_authorized():
                    logger.error(f"Сессия {phone} не авторизована")
                    return False

                # Получаем entity канала
                try:
                    if channel_username:
                        username = channel_username if channel_username.startswith('@') else f"@{channel_username}"
                        entity = await temp_client.get_entity(username)
                    else:
                        from telethon.tl.types import PeerChannel
                        entity = await temp_client.get_entity(PeerChannel(channel_id))
                except Exception as e:
                    logger.error(f"Не найден канал: {e}")
                    return False

                from telethon.tl.types import InputChannel

                input_channel = InputChannel(
                    channel_id=entity.id,
                    access_hash=entity.access_hash
                )

                # Меняем title
                if title:
                    try:
                        logger.info(f"  Меняю title на: {title}")
                        from telethon.tl.functions.channels import EditTitleRequest

                        await temp_client(EditTitleRequest(
                            channel=input_channel,
                            title=title
                        ))
                        logger.info("  ✅ Title изменён")
                    except Exception as e:
                        success = False
                        logger.error(f"  ❌ Ошибка title: {e}")

                # Меняем about
                if about:
                    try:
                        logger.info(f"  Меняю about на: {about}")
                        try:
                            from telethon.tl.functions.channels import EditAboutRequest

                            await temp_client(EditAboutRequest(
                                channel=input_channel,
                                about=about
                            ))
                            logger.info("  ✅ About изменён")
                        except ImportError:
                            logger.warning("❌ EditAboutRequest не найден в channels")
                            success = False
                        except Exception as e:
                            logger.error(f"  ❌ Ошибка about: {e}")
                            success = False
                    except Exception as e:
                        success = False
                        logger.error(f"  ❌ Ошибка about: {e}")

                # Меняем фото
                if photo_path:
                    try:
                        logger.info(f"  Меняю фото: {photo_path}")
                        from telethon.tl.functions.channels import EditPhotoRequest

                        # Загружаем файл
                        uploaded = await temp_client.upload_file(photo_path)

                        try:
                            await temp_client(EditPhotoRequest(
                                channel=input_channel,
                                photo=uploaded
                            ))
                            logger.info("  ✅ Фото изменено")
                        except Exception as e:
                            logger.warning(f"  ⚠️ Прямой upload не прошёл, пробую InputChatUploadedPhoto: {e}")
                            from telethon.tl.types import InputChatUploadedPhoto

                            await temp_client(EditPhotoRequest(
                                channel=input_channel,
                                photo=InputChatUploadedPhoto(file=uploaded)
                            ))
                            logger.info("  ✅ Фото изменено")
                    except Exception as e:
                        success = False
                        logger.error(f"  ❌ Ошибка фото: {e}")

            if success:
                logger.info("✅ Канал обновлён в Telegram")
            else:
                logger.warning("⚠️ Канал обновлён в Telegram частично или с ошибками")

            return success

        except Exception as e:
            logger.error(f"❌ Ошибка редактирования канала: {e}", exc_info=True)
            return False
    
    # ============= SHOWCASE HELPER METHODS =============

    def _resolve_account_key(self, raw_phone):
        """Определяет ключ аккаунта в accounts_data по полному номеру или phone полю."""
        if not raw_phone:
            return None, None

        raw_phone = str(raw_phone).strip()

        if raw_phone in self.accounts_data:
            return raw_phone, raw_phone

        for key, data in self.accounts_data.items():
            if data.get('phone') == raw_phone:
                return key, raw_phone

        return None, raw_phone

    def _get_display_phone(self, account_key, account_data):
        """Возвращает удобный для отображения номер аккаунта."""
        if account_data and account_data.get('phone'):
            return account_data['phone']
        return account_key

    def _get_showcase_from_account(self, account_data):
        """Возвращает данные витрины из аккаунта (showcase_channel)."""
        if not account_data:
            return None
        return account_data.get('showcase_channel')

    def _normalize_channel_username(self, raw_username):
        if not raw_username:
            return None
        import re

        name = str(raw_username).strip()
        if not name:
            return None

        # Удаляем markdown-ссылки вида (https://t.me/...)
        name = re.sub(r"\(https?://t\.me/[^)]+\)", "", name, flags=re.IGNORECASE)

        # Удаляем квадратные скобки
        name = name.replace("[", "").replace("]", "")

        name = name.strip()
        if not name:
            return None

        # Удаляем лидирующие @ и все недопустимые символы
        name = name.lstrip("@")
        name = re.sub(r"[^A-Za-z0-9_]", "", name)

        if not name:
            return None

        return f"@{name.upper()}"

    def _get_channel_username_normalized(self, channel):
        """
        Извлекает и нормализует username из channel объекта.
        channel может быть словарем {'username': '@channel'} или строкой '@channel'
        Возвращает нормализованный username БЕЗ @ и в нижнем регистре
        """
        if isinstance(channel, dict):
            username = channel.get('username') or channel.get('name')
        else:
            username = str(channel)
        
        if not username:
            return None
        
        # Нормализуем: убираем @, приводим к нижнему регистру, оставляем только允许 символы
        username = str(username).strip().lstrip('@').lower()
        return username if username else None

    def _find_channel_in_list(self, username_norm, entity_id=None):
        """Ищет канал в self.channels по username или id. Возвращает (index, data) или (None, None)."""
        if not self.channels:
            return None, None

        for idx, ch in enumerate(self.channels, 1):
            if isinstance(ch, dict):
                ch_username = ch.get('username') or ch.get('channel') or ch.get('name')
                ch_id = ch.get('id') or ch.get('channel_id') or ch.get('chat_id')
            else:
                ch_username = ch
                ch_id = None

            ch_username_norm = self._normalize_channel_username(ch_username) if ch_username else None

            if username_norm and ch_username_norm == username_norm:
                return idx, ch

            if entity_id and ch_id is not None:
                try:
                    if int(ch_id) == int(entity_id):
                        return idx, ch
                except (ValueError, TypeError):
                    pass

        return None, None

    def _find_showcase_bindings(self, username_norm, entity_id=None):
        """Возвращает список строк с аккаунтами, где канал привязан как витрина."""
        bindings = []

        for account_key, account_data in self.accounts_data.items():
            showcase = self._get_showcase_from_account(account_data) or {}
            sc_username = showcase.get('username')
            sc_id = showcase.get('channel_id')

            sc_username_norm = self._normalize_channel_username(sc_username) if sc_username else None
            match_by_username = username_norm and sc_username_norm == username_norm
            match_by_id = entity_id is not None and sc_id is not None and str(sc_id) == str(entity_id)

            if match_by_username or match_by_id:
                display_phone = self._get_display_phone(account_key, account_data)
                account_username = account_data.get('username') or account_data.get('name')
                if account_username:
                    bindings.append(f"{display_phone} ({account_username})")
                else:
                    bindings.append(f"{display_phone}")

        return bindings

    async def test_mode_bulk_channels(self, event, usernames: list[str]):
        """Массовая проверка каналов для /testmode on. Только чтение, без изменений."""
        if not usernames:
            await event.respond(
                "❌ Укажите список каналов.\n\n"
                "Пример:\n"
                "`/testmode on @chan1 @chan2`\n"
                "или\n"
                "`/testmode on`\n"
                "`@chan1 @chan2`"
            )
            return

        normalized_usernames = []
        seen = set()
        for raw in usernames:
            norm = self._normalize_channel_username(raw)
            if not norm:
                continue
            if norm not in seen:
                seen.add(norm)
                normalized_usernames.append(norm)

        if not normalized_usernames:
            await event.respond(
                "❌ Не удалось распознать список каналов.\n\n"
                "Пример: `/testmode on @chan1 @chan2`"
            )
            return

        reports = []

        for username_norm in normalized_usernames:
            found = False
            entity_id = None
            title = None
            access_hash = None
            entity_username = None
            error_text = None

            try:
                entity = await self.client.get_entity(username_norm)
                entity_id = getattr(entity, 'id', None)
                title = getattr(entity, 'title', None)
                access_hash = getattr(entity, 'access_hash', None)
                entity_username = getattr(entity, 'username', None)
                found = True
            except Exception as e:
                error_text = str(e)

            index_in_list, channel_data = self._find_channel_in_list(username_norm, entity_id)
            in_channels = index_in_list is not None

            showcase_bindings = self._find_showcase_bindings(username_norm, entity_id)

            ready_for_live = bool(found and in_channels)

            if found:
                found_text = "да"
            else:
                found_text = "нет"
                if error_text:
                    found_text += f" (ошибка: {error_text[:120]})"

            if in_channels:
                if isinstance(channel_data, dict):
                    in_channels_text = f"да (индекс {index_in_list}, данные: {channel_data})"
                else:
                    in_channels_text = f"да (индекс {index_in_list})"
            else:
                in_channels_text = "нет"

            if showcase_bindings:
                showcase_text = "да: " + ", ".join(showcase_bindings)
            else:
                showcase_text = "нет"

            display_username = f"@{entity_username}" if entity_username else username_norm

            report = (
                f"📌 Канал: `{display_username}`\n"
                f"• Найден: {found_text}\n"
                f"• Title: {title or '—'}\n"
                f"• ID: {entity_id or '—'}\n"
                f"• Access hash: {access_hash or '—'}\n"
                f"• В self.channels: {in_channels_text}\n"
                f"• Привязан как витрина: {showcase_text}\n"
                f"• Готов к боевому режиму: {'да' if ready_for_live else 'нет'}"
            )

            reports.append(report)

            log_showcase = ",".join(showcase_bindings) if showcase_bindings else "нет"
            logger.info(
                f"🔍 /testmode on: канал {username_norm} — "
                f"{'найден' if found else 'не найден'}, "
                f"id={entity_id}, showcase={log_showcase}, "
                f"index_in_listchannels={index_in_list}"
            )

        header = f"🧪 **TESTMODE ON: массовая проверка каналов**\n\nКаналов: {len(normalized_usernames)}"
        chunks = []
        current = header
        for report in reports:
            if len(current) + len(report) + 2 > 3500:
                chunks.append(current)
                current = report
            else:
                current = f"{current}\n\n{report}"
        if current:
            chunks.append(current)

        for chunk in chunks:
            await event.respond(chunk)
    
    async def _showcase_create(self, event, args_str):
        """Создать канал-витрину для аккаунта"""
        logger.info(f"📺 /showcase create: инициирован admin {event.sender_id}, args={args_str}")
        
        try:
            parts = args_str.split(maxsplit=1)
            
            if len(parts) < 2:
                await event.respond(
                    "**🎨 СОЗДАНИЕ КАНАЛА-ВИТРИНЫ**\n\n"
                    "Формат: `/showcase create <phone> <название>`\n\n"
                    "**Пример:**\n"
                    "`/showcase create +13434919340 Мой Магазин`\n\n"
                    "Канал создаётся от имени указанного аккаунта."
                )
                return
            
            raw_phone = parts[0]
            title = parts[1]
            
            # Загружаем актуальные данные
            self.load_data()

            account_key, search_id = self._resolve_account_key(raw_phone)

            logger.info(f"Looking for account: {search_id} (raw={raw_phone})")
            logger.info(f"Resolved account key: {account_key}")
            logger.info(f"Available accounts: {list(self.accounts_data.keys())}")
            logger.info(f"Account data: {self.accounts_data.get(account_key, {})}")
            
            # Проверяем что аккаунт принадлежит админу
            account_data = self.accounts_data.get(account_key) if account_key else None
            if not account_data:
                await event.respond(f"❌ Аккаунт `{raw_phone}` не найден")
                return

            display_phone = self._get_display_phone(account_key, account_data)
            
            # Проверяем права доступа
            if not self.is_super_admin(event.sender_id):
                if account_data.get('admin_id') != event.sender_id:
                    await event.respond("❌ Вы можете создавать каналы только для своих аккаунтов")
                    return
            
            # Проверяем, нет ли уже канала
            existing = self._get_showcase_from_account(account_data)
            if existing:
                username_raw = existing.get('username')
                username = f"@{username_raw}" if username_raw else 'без username'
                channel_id = existing.get('channel_id')
                await event.respond(
                    f"⚠️ У аккаунта уже есть канал-витрина:\n"
                    f"• Название: `{existing.get('title')}`\n"
                    f"• Username: `{username}`\n"
                    f"• ID: `{channel_id}`\n\n"
                    f"Используйте `/showcase unlink {display_phone}` чтобы отвязать"
                )
                return
            
            await event.respond(f"⏳ Создаю канал `{title}` для аккаунта `{display_phone}`...")
            
            # Создаём канал
            success, result = await self.create_profile_channel(account_key, title)
            
            if success:
                channel_info = result
                username = channel_info.get('username', None)
                username_display = f"@{username}" if username else 'пока нет username'
                
                text = f"""✅ **КАНАЛ-ВИТРИНА СОЗДАН**

📱 Аккаунт: `{display_phone}`
📺 Канал: `{channel_info['title']}`
🆔 ID: `{channel_info['channel_id']}`
👤 Username: `{username_display}`

🎨 **Следующие шаги:**
• `/showcase set {display_phone} avatar` - установить аватар
• `/showcase set {display_phone} post "Текст"` - создать пост

💡 Используйте `/showcase info {display_phone}` для просмотра информации"""
                
                await event.respond(text)
                logger.info(f"📺 /showcase create: успешно создан канал для {display_phone} (admin {event.sender_id})")
            else:
                await event.respond(result)
                
        except Exception as e:
            logger.error(f"Showcase create error: {e}")
            await event.respond(f"❌ Ошибка: {str(e)[:200]}")
    
    async def _showcase_link(self, event, args_str):
        """Привязать существующий канал к профилю аккаунта"""
        logger.info(f"📺 /showcase link: инициирован admin {event.sender_id}, args={args_str}")
        
        try:
            parts = args_str.split(maxsplit=1)
            
            if len(parts) < 2:
                await event.respond(
                    "**🔗 ПРИВЯЗКА СУЩЕСТВУЮЩЕГО КАНАЛА**\n\n"
                    "Формат: `/showcase link <phone> <@channel>`\n\n"
                    "**Пример:**\n"
                    "`/showcase link +13434919340 @myshowcase`\n\n"
                    "⚠️ Аккаунт должен быть админом канала!"
                )
                return
            
            raw_phone = parts[0]
            channel_identifier = parts[1].lstrip('@')  # Убираем @ если есть
            
            # Загружаем актуальные данные
            self.load_data()

            account_key, search_id = self._resolve_account_key(raw_phone)

            logger.info(f"Looking for account: {search_id} (raw={raw_phone})")
            logger.info(f"Resolved account key: {account_key}")
            logger.info(f"Available accounts: {list(self.accounts_data.keys())}")
            logger.info(f"Account data: {self.accounts_data.get(account_key, {})}")
            
            # Проверяем что аккаунт принадлежит админу
            account_data = self.accounts_data.get(account_key) if account_key else None
            if not account_data:
                await event.respond(f"❌ Аккаунт `{raw_phone}` не найден")
                return

            display_phone = self._get_display_phone(account_key, account_data)
            
            # Проверяем права доступа
            if not self.is_super_admin(event.sender_id):
                if account_data.get('admin_id') != event.sender_id:
                    await event.respond("❌ Вы можете привязывать каналы только к своим аккаунтам")
                    return
            
            # Проверяем, нет ли уже канала
            existing = self._get_showcase_from_account(account_data)
            if existing:
                username_raw = existing.get('username')
                username = f"@{username_raw}" if username_raw else 'без username'
                await event.respond(
                    f"⚠️ У аккаунта уже есть канал-витрина:\n"
                    f"• Название: `{existing.get('title')}`\n"
                    f"• Username: `{username}`\n\n"
                    f"Используйте `/showcase unlink {display_phone}` чтобы отвязать"
                )
                return
            
            await event.respond(f"⏳ Привязываю канал `{channel_identifier}` к аккаунту `{display_phone}`...")
            
            # Привязываем канал
            success, result = await self.link_existing_channel(account_key, channel_identifier)
            
            if success:
                channel_info = result
                username = channel_info.get('username', None)
                username_display = f"@{username}" if username else 'без username'
                
                text = f"""✅ **КАНАЛ ПРИВЯЗАН К ПРОФИЛЮ**

📱 Аккаунт: `{display_phone}`
📺 Канал: `{channel_info['title']}`
👤 Username: `{username_display}`
🆔 ID: `{channel_info['channel_id']}`
📝 Описание: {channel_info.get('about', 'не задано')}

🎨 **Управление:**
• `/showcase set {display_phone} avatar` - изменить аватар
• `/showcase set {display_phone} post "Текст"` - создать пост
• `/showcase set {display_phone} title "Новое"` - изменить название"""
                
                await event.respond(text)
                logger.info(f"📺 /showcase link: успешно привязан {channel_identifier} к {display_phone} (admin {event.sender_id})")
            else:
                await event.respond(result)
                
        except Exception as e:
            logger.error(f"Showcase link error: {e}")
            await event.respond(f"❌ Ошибка: {str(e)[:200]}")
    
    async def _showcase_unlink(self, event, args_str):
        """Отвязать канал-витрину от аккаунта"""
        logger.info(f"📺 /showcase unlink: инициирован admin {event.sender_id}, args={args_str}")
        
        try:
            raw_phone = args_str.strip()
            
            if not raw_phone:
                await event.respond("Формат: `/showcase unlink <phone>`")
                return
            
            # Загружаем актуальные данные
            self.load_data()

            account_key, search_id = self._resolve_account_key(raw_phone)

            logger.info(f"Looking for account: {search_id} (raw={raw_phone})")
            logger.info(f"Resolved account key: {account_key}")
            logger.info(f"Available accounts: {list(self.accounts_data.keys())}")
            logger.info(f"Account data: {self.accounts_data.get(account_key, {})}")
            
            # Проверяем что аккаунт принадлежит админу
            account_data = self.accounts_data.get(account_key) if account_key else None
            if not account_data:
                await event.respond(f"❌ Аккаунт `{raw_phone}` не найден")
                return

            display_phone = self._get_display_phone(account_key, account_data)
            
            # Проверяем права доступа
            if not self.is_super_admin(event.sender_id):
                if account_data.get('admin_id') != event.sender_id:
                    await event.respond("❌ Вы можете отвязывать каналы только у своих аккаунтов")
                    return
            
            # Проверяем, есть ли канал
            showcase = self._get_showcase_from_account(account_data)
            if not showcase or not showcase.get('channel_id'):
                await event.respond(f"❌ У аккаунта `{display_phone}` нет витрины")
                return

            channel_info = showcase
            username_raw = channel_info.get('username')
            username = f"@{username_raw}" if username_raw else 'без username'
            
            # Отвязываем
            if 'showcase_channel' in account_data:
                del account_data['showcase_channel']
            self.save_data()
            
            await event.respond(
                f"✅ Канал отвязан от аккаунта\n\n"
                f"📺 Канал: `{channel_info.get('title')}`\n"
                f"👤 Username: `{username}`\n"
                f"🆔 ID: `{channel_info.get('channel_id')}`\n\n"
                f"💡 Канал продолжает существовать, но больше не связан с аккаунтом в боте"
            )
            logger.info(f"📺 /showcase unlink: канал отвязан от {display_phone} (admin {event.sender_id})")
            
        except Exception as e:
            logger.error(f"Showcase unlink error: {e}")
            await event.respond(f"❌ Ошибка: {str(e)[:200]}")
    
    async def _showcase_list(self, event):
        """Показать все каналы-витрины"""
        logger.info(f"📺 /showcase list: запрошен admin {event.sender_id}")
        
        try:
            # Фильтруем аккаунты по админу
            admin_id = self.get_admin_id(event.sender_id)
            
            self.load_data()

            channels_list = []
            for phone, account_data in self.accounts_data.items():
                # Проверяем права доступа
                if admin_id is not None and account_data.get('admin_id') != admin_id:
                    continue

                showcase = self._get_showcase_from_account(account_data)
                if showcase:
                    channels_list.append((phone, account_data, showcase))
            
            if not channels_list:
                await event.respond("📺 У ваших аккаунтов пока нет каналов-витрин")
                return
            
            text = f"**📺 КАНАЛЫ-ВИТРИНЫ ({len(channels_list)})**\n\n"
            
            for idx, (phone, account_data, channel) in enumerate(channels_list, 1):
                display_phone = self._get_display_phone(phone, account_data)
                account_name = account_data.get('name', display_phone[-10:])
                channel_username_raw = channel.get('username')
                channel_username = f"@{channel_username_raw}" if channel_username_raw else 'без username'
                channel_id = channel.get('channel_id')
                
                text += f"{idx}. **{account_name}** (`{display_phone}`)\n"
                text += f"   📺 `{channel['title']}`\n"
                text += f"   👤 {channel_username}\n"
                text += f"   🆔 ID: `{channel_id}`\n\n"
            
            text += "💡 Команды: `/showcase info <phone>` для подробностей"
            
            await event.respond(text)
            
        except Exception as e:
            logger.error(f"Showcase list error: {e}")
            await event.respond(f"❌ Ошибка: {str(e)[:200]}")
    
    async def _showcase_info(self, event, args_str):
        """Показать информацию о витрине конкретного аккаунта"""
        logger.info(f"📺 /showcase info: запрошен admin {event.sender_id}, args={args_str}")
        
        try:
            raw_phone = args_str.strip()
            
            if not raw_phone:
                await event.respond("Формат: `/showcase info <phone>`")
                return
            
            # Загружаем актуальные данные
            self.load_data()

            account_key, search_id = self._resolve_account_key(raw_phone)

            logger.info(f"Looking for account: {search_id} (raw={raw_phone})")
            logger.info(f"Resolved account key: {account_key}")
            logger.info(f"Available accounts: {list(self.accounts_data.keys())}")
            logger.info(f"Account data: {self.accounts_data.get(account_key, {})}")
            
            # Проверяем что аккаунт принадлежит админу
            account_data = self.accounts_data.get(account_key) if account_key else None
            if not account_data:
                await event.respond(f"❌ Аккаунт `{raw_phone}` не найден")
                return

            display_phone = self._get_display_phone(account_key, account_data)
            
            # Проверяем права доступа
            admin_id = self.get_admin_id(event.sender_id)
            if admin_id is not None and account_data.get('admin_id') != admin_id:
                await event.respond("❌ У вас нет доступа к этому аккаунту")
                return
            
            # Проверяем, есть ли канал
            showcase = self._get_showcase_from_account(account_data)
            if not showcase or not showcase.get('channel_id'):
                await event.respond(f"❌ У аккаунта `{display_phone}` нет витрины")
                return

            profile_channel = showcase
            
            account_name = account_data.get('name', display_phone[-10:])
            channel_username_raw = profile_channel.get('username')
            channel_username = f"@{channel_username_raw}" if channel_username_raw else 'без username'
            about = profile_channel.get('about', 'не задано')
            
            text = f"""**📺 ИНФОРМАЦИЯ О ВИТРИНЕ**

👤 **Аккаунт:** {account_name} (`{display_phone}`)

📺 **Канал:**
• Название: `{profile_channel['title']}`
• Username: `{channel_username}`
• ID: `{profile_channel.get('channel_id')}`
• Описание: {about}
• Создан: {profile_channel.get('created', 'неизвестно')}

🎨 **Управление:**
• `/showcase set {display_phone} avatar` - изменить аватар
• `/showcase set {display_phone} title "Новое название"`
• `/showcase set {display_phone} about "Новое описание"`
• `/showcase set {display_phone} post "Текст поста"`
• `/showcase unlink {display_phone}` - отвязать канал"""
            
            await event.respond(text)
            
        except Exception as e:
            logger.error(f"Showcase info error: {e}")
            await event.respond(f"❌ Ошибка: {str(e)[:200]}")
    
    async def _showcase_set(self, event, args_str):
        """Установить различные параметры витрины"""
        logger.info(f"📺 /showcase set: инициирован admin {event.sender_id}, args={args_str}")
        
        try:
            logger.info(f"🔍 _showcase_set: args_str = {repr(args_str)}")
            parts = args_str.split(maxsplit=2)

            if len(parts) < 2:
                await event.respond(
                    "**⚙️ НАСТРОЙКА ВИТРИНЫ**\n\n"
                    "Формат: `/showcase set <параметр> <phone> [значение]`\n\n"
                    "**Параметры:**\n"
                    "`avatar` - установить аватар (затем отправьте фото)\n"
                    "`photo <путь/URL>` - установить фото напрямую\n"
                    "`title \"Название\"` - изменить название\n"
                    "`about \"Описание\"` - изменить описание\n"
                    "`info title:Название|about:Описание` - обновить всё сразу\n"
                    "`post \"Текст\"` - создать пост\n"
                    "`post_pin \"Текст\"` - создать закреплённый пост"
                )
                return
            
            param = parts[0].lower()
            raw_phone = parts[1]
            value = parts[2] if len(parts) > 2 else ""

            def _looks_like_phone(value_str: str) -> bool:
                if not value_str:
                    return False
                value_str = value_str.strip()
                return value_str.startswith('+') or value_str.isdigit()

            known_params = {"avatar", "photo", "title", "about", "info", "post", "post_pin"}

            # Поддерживаем оба формата: <param> <phone> и <phone> <param>
            if param in known_params and not _looks_like_phone(raw_phone):
                if raw_phone in known_params and _looks_like_phone(param):
                    param, raw_phone = raw_phone, param
            elif param not in known_params and raw_phone in known_params and _looks_like_phone(param):
                param, raw_phone = raw_phone, param

            photo_file = None
            if param in ("photo", "avatar"):
                photo_file = value
                param = "photo"

            logger.info(f"🔍 _showcase_set: param={param}, phone={raw_phone}, value={value}")
            
            # ЛОГИРОВАНИЕ 1
            logger.info(f"🔍 _showcase_set: Ищем аккаунт {raw_phone}")
            logger.info(f"📊 Доступные ключи (до reload): {list(self.accounts_data.keys())}")

            # Загружаем актуальные данные
            self.load_data()

            logger.info(f"📊 Доступные ключи (после reload): {list(self.accounts_data.keys())}")

            account_key, search_id = self._resolve_account_key(raw_phone)

            logger.info(f"Looking for account: {search_id} (raw={raw_phone})")
            logger.info(f"Resolved account key: {account_key}")
            logger.info(f"Available accounts: {list(self.accounts_data.keys())}")
            logger.info(f"Account data: {self.accounts_data.get(account_key, {})}")
            
            # Проверяем что аккаунт принадлежит админу
            account_data = self.accounts_data.get(account_key) if account_key else None
            if not account_data:
                logger.error(f"Account {raw_phone} not in accounts_data")
                await event.respond(f"❌ Аккаунт `{raw_phone}` не найден")
                return

            display_phone = self._get_display_phone(account_key, account_data)
            logger.info(f"Account data: {account_data}")
            logger.info(f"📋 Данные аккаунта: {list(account_data.keys())}")
            logger.info(f"📺 showcase_channel: {account_data.get('showcase_channel')}")
            
            # Проверяем права доступа
            if not self.is_super_admin(event.sender_id):
                if account_data.get('admin_id') != event.sender_id:
                    await event.respond("❌ Вы можете управлять каналами только своих аккаунтов")
                    return
            
            # Проверяем, есть ли канал
            showcase = self._get_showcase_from_account(account_data)
            if not showcase or not showcase.get('channel_id'):
                logger.error(f"❌ У аккаунта {display_phone} нет showcase_channel")
                await event.respond(f"❌ У аккаунта `{display_phone}` нет привязанного канала")
                return

            profile_channel = showcase
            logger.info(f"🎯 Обновляю витрину: {showcase}")
            
            # Обработка разных параметров
            if param == "photo":
                if not photo_file:
                    # Ждём изображение
                    msg = await event.respond(
                        f"📸 **УСТАНОВКА АВАТАРА**\n\n"
                        f"Отправьте изображение (reply на это сообщение)\n\n"
                        f"⚠️ Ограничения:\n"
                        f"• Максимум: 10 MB\n"
                        f"• Форматы: JPG, PNG, WebP"
                    )
                    
                    # Сохраняем состояние ожидания
                    self.user_states[event.sender_id] = {
                        'action': 'waiting_profile_channel_avatar',
                        'phone': account_key,
                        'message_id': msg.id
                    }
                else:
                    await event.respond("⏳ Обновляю фото канала...")
                    telegram_success = await self.edit_channel_in_telegram(
                        phone=account_key,
                        title=None,
                        about=None,
                        photo_path=photo_file
                    )

                    if telegram_success:
                        await event.respond("✅ Фото обновлено в Telegram!")
                    else:
                        await event.respond("❌ Не удалось обновить фото в Telegram")
            
            elif param == "title":
                if not value:
                    await event.respond("❌ Укажите новое название: `/showcase set <phone> title \"Новое название\"`")
                    return
                
                if len(value) > 128:
                    await event.respond(f"❌ Название слишком длинное!\n\nМаксимум: 128 символов\nУ вас: {len(value)} символов")
                    return
                
                await event.respond("⏳ Обновляю название канала...")
                telegram_success = await self.edit_channel_in_telegram(
                    phone=account_key,
                    title=value,
                    about=None
                )
                json_success = await self.update_profile_channel_info(account_key, title=value, about=None)

                if telegram_success:
                    await event.respond("✅ Канал обновлён в Telegram и bot_data!")
                elif json_success:
                    await event.respond("⚠️ Сохранено в bot_data, но Telegram не обновлён")
                else:
                    await event.respond("❌ Ошибка сохранения")

                if json_success:
                    logger.info(f"📺 /showcase set title: обновлено для {display_phone} (admin {event.sender_id})")
            
            elif param == "about":
                if not value:
                    await event.respond("❌ Укажите описание: `/showcase set <phone> about \"Описание канала\"`")
                    return
                
                if len(value) > 255:
                    await event.respond(f"❌ Описание слишком длинное!\n\nМаксимум: 255 символов\nУ вас: {len(value)} символов")
                    return
                
                await event.respond("⏳ Обновляю описание канала...")
                telegram_success = await self.edit_channel_in_telegram(
                    phone=account_key,
                    title=None,
                    about=value
                )
                json_success = await self.update_profile_channel_info(account_key, title=None, about=value)

                if telegram_success:
                    await event.respond("✅ Канал обновлён в Telegram и bot_data!")
                elif json_success:
                    await event.respond("⚠️ Сохранено в bot_data, но Telegram не обновлён")
                else:
                    await event.respond("❌ Ошибка сохранения")

                if json_success:
                    logger.info(f"📺 /showcase set about: обновлено для {display_phone} (admin {event.sender_id})")
            
            elif param == "info":
                # Обработка формата: title:Новое|about:Описание
                if not value:
                    await event.respond("❌ Укажите параметры: `/showcase set <phone> info title:Название|about:Описание`")
                    return
                
                logger.info(f"📺 Парсинг info параметров: {value}")
                
                # Парсим параметры
                info_params = {}
                try:
                    # Разделяем по |
                    pairs = value.split('|')
                    logger.info(f"📺 Разделено на пары: {pairs}")
                    
                    for pair in pairs:
                        if ':' in pair:
                            key, val = pair.split(':', 1)
                            key = key.strip().lower()
                            val = val.strip()
                            
                            if key in ['title', 'about']:
                                info_params[key] = val
                                logger.info(f"📺 Извлечено: {key} = {val}")
                    
                    if not info_params:
                        await event.respond("❌ Не удалось распарсить параметры!\n\nФормат: `title:Название|about:Описание`")
                        return
                    
                    # Валидация
                    if 'title' in info_params and len(info_params['title']) > 128:
                        await event.respond(f"❌ Название слишком длинное!\n\nМаксимум: 128 символов\nУ вас: {len(info_params['title'])} символов")
                        return
                    
                    if 'about' in info_params and len(info_params['about']) > 255:
                        await event.respond(f"❌ Описание слишком длинное!\n\nМаксимум: 255 символов\nУ вас: {len(info_params['about'])} символов")
                        return
                    
                    # Обновляем информацию о канале
                    await event.respond("⏳ Обновляю информацию канала...")

                    title = info_params.get('title')
                    about = info_params.get('about')

                    logger.info(f"📺 Вызов update_profile_channel_info: phone={display_phone}, title={title}, about={about}")

                    telegram_success = await self.edit_channel_in_telegram(
                        phone=account_key,
                        title=title,
                        about=about
                    )
                    json_success = await self.update_profile_channel_info(account_key, title=title, about=about)

                    if telegram_success:
                        response_text = "✅ **ИНФОРМАЦИЯ ОБНОВЛЕНА**\n\n"
                        if title:
                            response_text += f"📝 Название: `{title}`\n"
                        if about:
                            response_text += f"📄 Описание: `{about}`\n"

                        await event.respond(response_text)
                        logger.info(f"📺 /showcase set info: успешно обновлено для {display_phone} (admin {event.sender_id})")
                    elif json_success:
                        await event.respond("⚠️ Сохранено в bot_data, но Telegram не обновлён")
                        logger.warning(f"📺 /showcase set info: Telegram не обновлён для {display_phone}")
                    else:
                        await event.respond("❌ Ошибка сохранения")
                        logger.error(f"📺 /showcase set info: ошибка для {display_phone}")
                        
                except Exception as e:
                    logger.error(f"📺 Ошибка парсинга info параметров: {e}")
                    import traceback
                    traceback.print_exc()
                    await event.respond(f"❌ Ошибка парсинга параметров: {str(e)}\n\nФормат: `title:Название|about:Описание`")
                    return
            
            elif param in ["post", "post_pin"]:
                if not value:
                    await event.respond(f"❌ Укажите текст поста: `/showcase set <phone> {param} \"Текст\"`")
                    return
                
                if len(value) > 4096:
                    await event.respond(f"❌ Пост слишком длинный!\n\nМаксимум: 4096 символов\nУ вас: {len(value)} символов")
                    return
                
                pin = (param == "post_pin")
                await event.respond(f"⏳ Создаю пост в канале `{profile_channel['title']}`...")
                
                # Создаём пост
                success, message, post_id = await self.create_profile_channel_post(account_key, value, pin)
                
                if success:
                    channel_username_raw = profile_channel.get('username')
                    channel_username = f"@{channel_username_raw}" if channel_username_raw else 'без username'
                    
                    text = f"""✅ **ПОСТ СОЗДАН**

📺 Канал: `{profile_channel['title']}`
👤 Username: `{channel_username}`
🆔 Post ID: `{post_id}`
📌 Закреплён: {"Да" if pin else "Нет"}

📝 Текст:
{value[:100]}{"..." if len(value) > 100 else ""}"""
                    
                    await event.respond(text)
                    logger.info(f"📺 /showcase set {param}: пост создан в {display_phone} (admin {event.sender_id})")
                else:
                    await event.respond(message)
            
            else:
                await event.respond(f"❌ Неизвестный параметр: `{param}`\n\nИспользуйте `/showcase set` для справки")
                
        except Exception as e:
            logger.error(f"Showcase set error: {e}")
            await event.respond(f"❌ Ошибка: {str(e)[:200]}")
    
    # ============= END SHOWCASE HELPER METHODS =============
    
    async def create_showcase_channel(self, account_num, base_username='showcase'):
        """
        Создать уникальный публичный канал-витрину для конкретного аккаунта
        и добавить его в витрину профиля.
        
        Args:
            account_num: номер аккаунта (1-10) или полный номер телефона
            base_username: базовый юзернейм для канала (по умолчанию "showcase")
        
        Returns:
            (success: bool, result: dict/str)
            - success=True: {'username': str, 'channel_id': int, 'phone': str}
            - success=False: описание ошибки
        """
        import string
        
        try:
            # Определяем номер телефона
            if isinstance(account_num, int) or (isinstance(account_num, str) and account_num.isdigit()):
                # Это номер аккаунта (1-10)
                account_key = f"ACCOUNT{account_num}_SESSION"
                session_str = os.getenv(account_key)
                
                if not session_str:
                    return False, f"❌ Переменная окружения {account_key} не найдена"
                
                # Ищем телефон для этого аккаунта
                phone = None
                for p, data in self.accounts_data.items():
                    if data.get('session') == session_str:
                        phone = p
                        break
                
                if not phone:
                    return False, f"❌ Аккаунт #{account_num} не найден в базе"
            else:
                # Это полный номер телефона
                phone = account_num if account_num.startswith('+') else '+' + account_num
                
                if phone not in self.accounts_data:
                    return False, f"❌ Аккаунт {phone} не найден"
            
            account_data = self.accounts_data[phone]
            
            if not account_data.get('session'):
                return False, f"❌ Аккаунт {phone} не авторизован"
            
            # Проверяем, нет ли уже showcase канала
            if account_data.get('showcase_channel'):
                existing = account_data['showcase_channel']
                return False, f"❌ У аккаунта уже есть showcase-канал: @{existing.get('username')} (ID: {existing.get('channel_id')})"
            
            logger.info(f"🎨 Создание showcase-канала для {phone} с базовым username '{base_username}'")
            
            # Создаём USER-клиент (bot НЕ МОЖЕТ создавать каналы!)
            user_client = TelegramClient(
                StringSession(account_data['session']), 
                API_ID, 
                API_HASH,
                proxy=account_data.get('proxy')
            )
            
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.disconnect()
                return False, f"❌ Аккаунт {phone} потерял авторизацию"
            
            # Генерируем варианты юзернейма и проверяем доступность
            from telethon.tl.functions.channels import CreateChannelRequest, CheckUsernameRequest, UpdateUsernameRequest
            from telethon.tl.functions.account import UpdateProfileRequest as AccountUpdateProfileRequest
            from telethon.errors import UsernameOccupiedError, UsernameInvalidError, FloodWaitError
            from telethon.tl.types import Channel
            
            username_variants = [
                base_username,  # showcase
                f"{base_username}{account_num if isinstance(account_num, (int, str)) and str(account_num).isdigit() else phone[-4:]}",  # showcase1 или showcase1234
                f"{base_username}_{account_num if isinstance(account_num, (int, str)) and str(account_num).isdigit() else phone[-4:]}",  # showcase_1 или showcase_1234
            ]
            
            # Добавляем случайные варианты
            for _ in range(7):
                random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
                username_variants.append(f"{base_username}_{random_suffix}")
            
            # Валидация и очистка username-ов
            valid_username_variants = []
            for variant in username_variants:
                # Удаляем недопустимые символы (только буквы, цифры и underscore)
                cleaned = ''.join(c for c in variant if c.isalnum() or c == '_')
                # Проверяем длину (5-32 символа для Telegram)
                if 5 <= len(cleaned) <= 32:
                    valid_username_variants.append(cleaned)
                    logger.debug(f"✅ Username variant validated: {cleaned}")
                else:
                    logger.warning(f"⚠️ Username variant rejected (length {len(cleaned)}): {cleaned}")
            
            free_username = None
            
            for variant in valid_username_variants:
                try:
                    logger.info(f"🔍 Проверка доступности username: @{variant}")
                    
                    # Проверяем доступность через CheckUsernameRequest
                    # Создаём временный канал для проверки
                    try:
                        entity = await user_client.get_entity(variant)
                        logger.info(f"❌ Username @{variant} занят (канал существует)")
                        continue  # Юзернейм занят
                    except ValueError:
                        # ValueError означает что канал не найден - юзернейм свободен!
                        logger.info(f"✅ Username @{variant} свободен!")
                        free_username = variant
                        break
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка при проверке @{variant}: {e}")
                        continue
                        
                except FloodWaitError as e:
                    logger.warning(f"⚠️ FloodWait при проверке @{variant}: нужно подождать {e.seconds}с")
                    await asyncio.sleep(e.seconds)
                    continue
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка при проверке @{variant}: {e}")
                    continue
            
            if not free_username:
                await user_client.disconnect()
                return False, f"❌ Не удалось найти свободный username после {len(username_variants)} попыток"
            
            logger.info(f"🎯 Найден свободный username: @{free_username}")
            
            # Создаём канал БЕЗ username (сначала)
            account_name = account_data.get('name', phone[-4:])
            channel_title = f"Showcase {account_name}"
            
            logger.info(f"📺 Создание канала '{channel_title}'...")
            
            result = await user_client(CreateChannelRequest(
                title=channel_title,
                about="",  # Пустое описание
                broadcast=True,  # Публичный канал
                megagroup=False
            ))
            
            created_channel = result.chats[0]
            
            if not isinstance(created_channel, Channel):
                await user_client.disconnect()
                return False, "❌ Не удалось создать канал (неверный тип)"
            
            channel_id = created_channel.id
            logger.info(f"✅ Канал создан с ID: {channel_id}")
            
            # Теперь устанавливаем username для канала
            try:
                logger.info(f"🔧 Установка username @{free_username} для канала...")
                await user_client(UpdateUsernameRequest(
                    channel=created_channel,
                    username=free_username
                ))
                logger.info(f"✅ Username @{free_username} установлен")
            except UsernameOccupiedError:
                logger.error(f"❌ Username @{free_username} внезапно стал занят")
                await user_client.disconnect()
                return False, f"❌ Username @{free_username} был занят между проверкой и установкой"
            except UsernameInvalidError:
                logger.error(f"❌ Username [{free_username}] некорректен (length: {len(free_username)}, chars: {repr(free_username)})")
                await user_client.disconnect()
                return False, f"❌ Username [{free_username}] некорректен"
            except Exception as e:
                logger.error(f"❌ Ошибка при установке username: {e}")
                await user_client.disconnect()
                return False, f"❌ Ошибка при установке username: {str(e)}"
            
            # Добавляем канал в витрину профиля АВТОМАТИЧЕСКИ
            try:
                from telethon.tl.functions.channels import GetChannelsRequest
                from telethon.tl.functions.account import UpdatePersonalChannelRequest
                from telethon.tl.types import InputChannel
                
                logger.info(f"🎯 Добавление канала @{free_username} в витрину профиля...")
                
                # Получаем полную информацию о канале для access_hash
                full_channel = await user_client(GetChannelsRequest([created_channel]))
                
                if full_channel and full_channel.chats:
                    channel_entity = full_channel.chats[0]
                    
                    # Получаем access_hash для InputChannel
                    access_hash = getattr(channel_entity, 'access_hash', None)
                    
                    if access_hash:
                        # Создаём InputChannel для UpdatePersonalChannelRequest
                        input_channel = InputChannel(
                            channel_id=channel_id,
                            access_hash=access_hash
                        )
                        
                        # АВТОМАТИЧЕСКИ добавляем в витрину профиля!
                        await user_client(UpdatePersonalChannelRequest(channel=input_channel))
                        
                        logger.info(f"✅ Канал @{free_username} АВТОМАТИЧЕСКИ ДОБАВЛЕН в витрину профиля аккаунта {phone}")
                        logger.info(f"🎉 Витрина профиля обновлена! Канал виден в профиле.")
                    else:
                        logger.warning(f"⚠️ Не удалось получить access_hash для канала")
                        logger.info(f"💡 Добавьте канал @{free_username} в витрину профиля вручную")
                    
            except Exception as e:
                logger.warning(f"⚠️ Не удалось добавить в витрину автоматически: {e}")
                logger.info(f"💡 Добавьте канал @{free_username} в витрину профиля вручную")
                import traceback
                traceback.print_exc()
            
            # Сохраняем информацию в bot_data
            showcase_info = {
                'username': free_username,
                'channel_id': channel_id,
                'title': channel_title,
                'created': datetime.now().isoformat()
            }
            
            account_data['showcase_channel'] = showcase_info
            self.save_data()
            
            await user_client.disconnect()
            
            logger.info(f"✅ Showcase-канал создан: @{free_username} (ID: {channel_id})")
            
            return True, {
                'username': free_username,
                'channel_id': channel_id,
                'phone': phone,
                'title': channel_title
            }
            
        except FloodWaitError as e:
            logger.error(f"FloodWait: нужно подождать {e.seconds} секунд")
            return False, f"❌ Слишком частые запросы. Подождите {e.seconds} секунд"
        except Exception as e:
            logger.error(f"Error creating showcase channel: {e}")
            import traceback
            traceback.print_exc()
            return False, f"❌ Ошибка: {str(e)}"
    
    # ============= END PROFILE CHANNEL FUNCTIONS =============
    
    async def start(self):
        # ============= ЗАЩИТА: Проверка единственности bot_client =============
        if not hasattr(self, '_bot_client_created') or not self._bot_client_created:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: bot_client не был правильно создан!")
            raise RuntimeError("Bot client not properly initialized")
        logger.info("🚀 Подключение основного бот-клиента (bot_session)...")
        # ============= END ЗАЩИТА =============
        await self.bot_client.start(bot_token=BOT_TOKEN)
        self.setup_handlers()
        logger.info("✅ @comapc_bot ULTIMATE ЗАПУЩЕН! (один клиент, один session-файл)")
        
        # НЕ запускаем автоматическую проверку при старте (слишком агрессивно)
        # Используйте /verify_sessions для ручной проверки
        if self.accounts_data:
            logger.info(f"✅ Загружено {len(self.accounts_data)} аккаунтов. Используйте /verify_sessions для проверки авторизации.")
        else:
            logger.warning("⚠️ Нет аккаунтов для проверки. Используйте /auth для добавления.")
    
    def setup_handlers(self):
        logger.info("=" * 80)
        logger.info("REGISTERING COMMAND HANDLERS...")
        logger.info("Bot client: %s", type(self.bot_client))
        logger.info("Handlers will be registered via Telethon @client.on() decorators")
        logger.info("Commands: /start, /help, /auth, /testmode, /listaccounts, /addchannel, /startmon, /stopmon, etc.")
        logger.info("=" * 80)
        
        # Log all incoming messages for debugging
        @self.bot_client.on(events.NewMessage())
        async def log_all_messages(event):
            if event.is_private:
                logger.info("INCOMING MSG: sender_id=%s text=%r", 
                            event.sender_id, event.text[:100] if event.text else None)
        
        @self.bot_client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            # Only owner and admins can use the bot
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            text = f"""**@comapc_bot ULTIMATE**
=

Владелец: `{BOT_OWNER_ID}`
Админов: `{len(self.admins)}`

Аккаунтов: `{len(self.accounts_data)}`
Каналов: `{len(self.channels)}`
Шаблонов: `{len(self.templates)}`

**/help** - все команды"""
            await event.respond(text)
        
        logger.warning(f"🔥 /help DECORATOR ATTACHED")
        @self.bot_client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            logger.warning(f"🔥 /help HANDLER TRIGGERED from {event.sender_id}, text={event.raw_text!r}")
            if not await self.is_admin(event.sender_id): return
            
            # Разбиваем на несколько сообщений из-за лимита Telegram
            text1 = """**📱 АККАУНТЫ:**
`/auth +79123456789 [socks5:host:port:user:pass]` - авторизовать
`/verify_sessions` - проверить авторизацию всех аккаунтов 🆕
`/accounts` - управление профилями (аватар, имя, био) 🆕
`/listaccounts` - все аккаунты (🟢 active / 🔵 reserve / 🔴 broken)
`/activeaccounts` - только активные ✅
`/reserveaccounts` - только резервные 🔄
`/blockedaccounts` - сломанные/заблокированные 🚫
`/delaccount +79123456789` - удалить
`/toggleaccount +79123456789` - переключить active ⇄ reserve
`/qrauth Имя` - добавить аккаунт через QR код (САМЫЙ ПРОСТОЙ!) 🆕
`/importsession +79... StringSession Имя` - импорт готовой сессии (для RU) 🆕

**👤 УПРАВЛЕНИЕ ПРОФИЛЕМ:**
`/setname` - изменить имя (выбор аккаунта → ввод имени)
`/setbio` - изменить био (выбор аккаунта → ввод био)
`/setavatar` - загрузить аватар (выбор аккаунта → отправка фото)
`/profile` - показать профили всех активных аккаунтов

**🔥 ПРОГРЕВ АККАУНТОВ (4 дня):**
`/warmup` - справка по прогреву
`/warmup_start +79123456789` - начать прогрев аккаунта
`/warmup_stop +79123456789` - остановить прогрев
`/warmup_status` - статус всех прогревов
`/warmup_run +79123456789` - запустить цикл вручную
⚠️ Аккаунты в прогреве автоматически исключены из работы!

**⚙️ НАСТРОЙКИ:**
`/config` - показать все настройки (сохраняются между перезапусками) 🆕
`/setparallel 2` - кол-во одновременно активных аккаунтов
`/getparallel` - текущие настройки
`/setratelimit 20` - лимит сообщений/час на аккаунт (20-40) 🆕
`/getratelimit` - текущий лимит скорости 🆕
`/setrotation 14400` - интервал ротации в секундах (по умолчанию 4ч) 🆕
`/getrotation` - текущий интервал ротации 🆕
`/rotatenow` - выполнить ротацию немедленно 🆕
`/accountstats` - статистика активности аккаунтов 🆕

**🔄 РЕЖИМ РАБОТЫ (для 100+ каналов):**
`/setworkermode distributed` - каналы делятся между аккаунтами 🆕
`/setworkermode cyclic` - каждый аккаунт проходит все каналы 🆕
`/setmaxcycles 3` - лимит циклов перед ротацией (0=∞) 🆕
`/getworkersettings` - посмотреть все настройки воркеров 🆕
`/togglerecovery` - вкл/выкл автовосстановление после бана 🆕"""
            
            text2 = """**📢 КАНАЛЫ:**
`/addchannel @username1 @username2 ...` - добавить каналы (можно сразу несколько)
`/listchannels` - список
`/delchannel @username` - удалить
`/syncchannels` - синхронизировать с БД (для корректной статистики) 🆕
`/searchchannels тема` - поиск по теме
`/addparsed тема 10` - добавить найденные в работу

**📺 КАНАЛЫ-ВИТРИНЫ:**
`/showcase create +1234 Название` - создать новый канал
`/showcase link +1234 @channel` - привязать существующий
`/showcase list` - список всех витрин
`/showcase set avatar +1234` - установить аватар
`/showcase set post +1234 Текст` - создать пост (+ pin для закрепления)
`/showcase set info +1234 title:Новое|about:Описание` - обновить инфо
`/showcase unlink +1234` - отвязать канал
`/showcase info +1234` - информация о канале

**🎨 ИНДИВИДУАЛЬНЫЕ ВИТРИНЫ:**
`/createshowcase <аккаунт> [username]` - создать showcase-канал 🆕
  Примеры: `/createshowcase 1` или `/createshowcase +1234567890`
  ⚡ Канал автоматически добавляется в витрину профиля!"""
            
            text3 = """**💬 КОММЕНТАРИИ:**
`/listtemplates` - шаблоны
`/addtemplate Текст!` - новый
`/edittemplate 1 Текст` - изменить
`/del-template 2` - удалить
`/cleartemplates` - очистить

**🤖 АВТО:**
`/startmon` - ЗАПУСТИТЬ (с автоматической ротацией)
`/stopmon` - остановить
`/safetyinfo` - настройки безопасности
`/showprogress` - показать прогресс комментирования 🆕
`/resetprogress` - сбросить прогресс (начать с начала) 🆕

**📊 СТАТИСТИКА:**
`/stats` - подробная статистика
`/listparsed` - спарсенные каналы
`/listbans` - заблокированные аккаунты
`/listblockedchannels` - каналы без комментариев
`/history` - история комментариев
`/resetfails` - сбросить счетчики неудач
`/showfails` - показать текущие неудачи
`/showblacklist` - показать блэклист каналов для аккаунтов 🆕
`/clearblacklist` - очистить блэклист 🆕
`/incidents +79123456789` - история инцидентов аккаунта (FloodWait/баны) 🆕
`/incidents all` - статистика по всем аккаунтам 🆕
`/checkspam +79123456789` - проверить ограничения через @SpamBot 🆕
`/checkspam all` - проверить все BROKEN аккаунты 🆕

**🧪 ТЕСТОВЫЙ РЕЖИМ:**
`/testmode` - статус тестового режима
`/testmode <selector>` - включить на один канал (номер или username)
`/testmode on @channel1 @channel2` - массовый тест-режим
`/testmode on` + новой строкой список каналов
`/testmode off` - выключить
`/testmode speed 10` - установить скорость (комм/час)

**🔗 BIO:**
`/addbio t.me/link` - добавить
`/setbioall` - применить всем активным

**👑 АДМИНЫ:**
`/addadmin 123456789` - новый админ

**💾 ЗАЩИТА ДАННЫХ:**
`/backup` - ручной бэкап (каналы/шаблоны)
`/listbackups` - список ручных бэкапов
`/autobackups` - автоматические бэкапы (каждые 30 мин) 🆕
`/restore` - восстановить каналы/шаблоны

⚠️ **ВАЖНО:** Сессии восстанавливаются из bot_data.json!"""
            
            await event.respond(text1)
            await event.respond(text2)
            await event.respond(text3)
        
        # ============= SESSION PROTECTION COMMANDS =============
        @self.bot_client.on(events.NewMessage(pattern='/backup'))
        async def manual_backup(event):
            """
            Создаёт резервную копию ДАННЫХ (каналы, шаблоны).
            КРИТИЧНО: НИКОГДА не бэкапирует сессии аккаунтов!
            """
            if not await self.is_admin(event.sender_id): return
            
            try:
                from datetime import datetime
                
                # ============= ЗАЩИТА: Бэкапируем ТОЛЬКО данные, НЕ сессии! =============
                backup_data = {
                    'channels': self.channels,
                    'templates': self.templates,
                    'bio_links': self.bio_links,
                    'admins': self.admins,
                    # ВАЖНО: НЕ включаем 'accounts' - там сессии!
                }
                
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_name = f'bot_data_safe.backup_{timestamp}.json'
                
                # Сохраняем только данные (без сессий)
                with open(backup_name, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, indent=2, ensure_ascii=False)
                
                # Также создаём быстрый бэкап
                with open('bot_data_safe.bak.json', 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, indent=2, ensure_ascii=False)
                # ============= END ЗАЩИТА =============
                
                await event.respond(
                    f"✅ **Безопасная резервная копия создана**\n\n"
                    f"📁 Файл: `{backup_name}`\n"
                    f"📊 Каналов: {len(self.channels)}\n"
                    f"💬 Шаблонов: {len(self.templates)}\n"
                    f"🔗 Bio-ссылок: {len(self.bio_links)}\n"
                    f"👑 Админов: {len(self.admins)}\n\n"
                    f"🔒 **Сессии аккаунтов НЕ включены** (безопасно!)\n\n"
                    f"💡 Используйте `/listbackups` для просмотра всех бэкапов"
                )
                logger.info(f"Safe backup created by user {event.sender_id}: {backup_name} (NO SESSIONS)")
                
            except Exception as e:
                await event.respond(f"❌ Ошибка создания бэкапа: {str(e)}")
                logger.error(f"Manual backup error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listbackups'))
        async def list_backups(event):
            """Показывает список всех доступных безопасных бэкапов (без сессий)"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Ищем безопасные бэкапы (без сессий)
                safe_backups = sorted([f for f in os.listdir('.') if f.startswith('bot_data_safe.backup_')], reverse=True)
                
                # .bak файл
                bak_file = 'bot_data_safe.bak.json' if os.path.exists('bot_data_safe.bak.json') else None
                
                if not safe_backups and not bak_file:
                    await event.respond(
                        "❌ Безопасные бэкапы не найдены\n\n"
                        "💡 Создайте первый бэкап: `/backup`\n\n"
                        "🔒 Новые бэкапы НЕ содержат сессий (безопасно!)"
                    )
                    return
                
                text = "💾 **БЕЗОПАСНЫЕ РЕЗЕРВНЫЕ КОПИИ**\n"
                text += "🔒 Содержат только данные (каналы, шаблоны)\n"
                text += "✅ Сессии аккаунтов НЕ включены\n\n"
                
                if bak_file:
                    file_size = os.path.getsize(bak_file) / 1024  # KB
                    file_time = datetime.fromtimestamp(os.path.getmtime(bak_file))
                    text += f"📌 **Последний бэкап (.bak):**\n"
                    text += f"   `{bak_file}`\n"
                    text += f"   📅 {file_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    text += f"   💾 {file_size:.1f} KB\n\n"
                
                if safe_backups:
                    text += f"🖐️ **Все бэкапы ({len(safe_backups)}):**\n"
                    for backup in safe_backups[:10]:  # Показываем последние 10
                        file_size = os.path.getsize(backup) / 1024
                        file_time = datetime.fromtimestamp(os.path.getmtime(backup))
                        # Извлекаем timestamp из имени
                        timestamp_part = backup.replace('bot_data_safe.backup_', '').replace('.json', '')
                        text += f"• `{timestamp_part}`\n"
                        text += f"  📅 {file_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        text += f"  💾 {file_size:.1f} KB\n"
                    if len(safe_backups) > 10:
                        text += f"\n... и ещё {len(safe_backups) - 10} бэкапов\n"
                    text += "\n"
                
                text += "💡 **Команды:**\n"
                text += "`/restore` - восстановить данные из последнего бэкапа\n"
                text += "`/backup` - создать новый бэкап\n"
                text += "`/autobackups` - показать автоматические бэкапы 🆕\n\n"
                text += "⚠️ **Важно:** При восстановлении сессии НЕ затрагиваются!"
                
                await event.respond(text)
                
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
                logger.error(f"List backups error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/autobackups'))
        async def list_auto_backups(event):
            """Показывает список автоматических timestamped бэкапов"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                BACKUP_DIR = 'backups'
                
                if not os.path.exists(BACKUP_DIR):
                    await event.respond(
                        f"📁 Папка `{BACKUP_DIR}/` ещё не создана\n\n"
                        f"Автоматические бэкапы будут создаваться каждые 30 минут после запуска бота."
                    )
                    return
                
                # Список всех автобэкапов
                auto_backups = sorted([
                    f for f in os.listdir(BACKUP_DIR) 
                    if f.startswith('bot_data_') and f.endswith('.json')
                ], reverse=True)
                
                if not auto_backups:
                    await event.respond(
                        f"📁 Папка `{BACKUP_DIR}/` пуста\n\n"
                        f"Первый автобэкап будет создан через ~30 минут"
                    )
                    return
                
                text = f"💾 **АВТОМАТИЧЕСКИЕ БЭКАПЫ** ({len(auto_backups)})\n"
                text += f"📁 Папка: `{BACKUP_DIR}/`\n"
                text += f"⏱️ Интервал: каждые 30 минут\n"
                text += f"🗂️ Хранится: последние 48 бэкапов (24 часа)\n\n"
                
                # Показываем последние 15 бэкапов
                for backup in auto_backups[:15]:
                    backup_path = os.path.join(BACKUP_DIR, backup)
                    file_stat = os.stat(backup_path)
                    file_time = datetime.fromtimestamp(file_stat.st_mtime)
                    file_size = file_stat.st_size / 1024  # KB
                    
                    # Извлекаем timestamp из имени (bot_data_YYYYMMDD_HHMMSS.json)
                    timestamp_part = backup.replace('bot_data_', '').replace('.json', '')
                    text += f"• `{timestamp_part}`\n"
                    text += f"  📅 {file_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    text += f"  💾 {file_size:.1f} KB\n"
                
                if len(auto_backups) > 15:
                    text += f"\n... и ещё {len(auto_backups) - 15} бэкапов\n"
                
                text += f"\n💡 **Восстановление:**\n"
                text += f"```bash\n"
                text += f"cd /root/bot\n"
                text += f"cp backups/bot_data_TIMESTAMP.json bot_data.json\n"
                text += f"pkill -f python3\n"
                text += f"nohup python3 main.py > bot_logs.txt 2>&1 &\n"
                text += f"```"
                
                await event.respond(text)
                
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
                logger.error(f"List auto backups error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/restore'))
        async def restore_backup(event):
            """
            Восстанавливает ТОЛЬКО данные (каналы, шаблоны) из бэкапа.
            КРИТИЧНО: НИКОГДА не трогает сессии аккаунтов!
            """
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Находим последний безопасный бэкап (без сессий)
                backup_file = None
                
                # Проверяем .bak файл
                if os.path.exists('bot_data_safe.bak.json'):
                    backup_file = 'bot_data_safe.bak.json'
                
                # Проверяем безопасные бэкапы
                if not backup_file:
                    safe_backups = sorted([f for f in os.listdir('.') if f.startswith('bot_data_safe.backup_')], reverse=True)
                    if safe_backups:
                        backup_file = safe_backups[0]
                
                if not backup_file:
                    await event.respond(
                        "❌ Безопасные бэкапы не найдены\n\n"
                        "💡 Создайте бэкап: `/backup`\n\n"
                        "🔒 Новые бэкапы безопасны (без сессий)"
                    )
                    return
                
                # Загружаем данные из бэкапа
                with open(backup_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
                
                # Проверяем структуру
                if 'channels' not in backup_data and 'templates' not in backup_data:
                    await event.respond(f"❌ Файл `{backup_file}` не содержит данных")
                    return
                
                # Сохраняем текущее состояние для сравнения
                old_channels = len(self.channels)
                old_templates = len(self.templates)
                
                # ============= ЗАЩИТА: Восстанавливаем ТОЛЬКО данные, НЕ трогаем accounts! =============
                # Восстанавливаем каналы
                if 'channels' in backup_data:
                    self.channels = backup_data['channels']
                
                # Восстанавливаем шаблоны
                if 'templates' in backup_data:
                    self.templates = backup_data['templates']
                
                # Восстанавливаем bio_links
                if 'bio_links' in backup_data:
                    self.bio_links = backup_data['bio_links']
                
                # Восстанавливаем admins
                if 'admins' in backup_data:
                    self.admins = backup_data['admins']
                
                # ВАЖНО: self.accounts_data НЕ трогаем - сессии остаются нетронутыми!
                # ============= END ЗАЩИТА =============
                
                # Сохраняем изменения (включая нетронутые accounts)
                self.save_data()
                
                await event.respond(
                    f"✅ **Данные восстановлены**\n\n"
                    f"📁 Из файла: `{backup_file}`\n\n"
                    f"📊 Каналов: {old_channels} → {len(self.channels)}\n"
                    f"💬 Шаблонов: {old_templates} → {len(self.templates)}\n"
                    f"🔗 Bio-ссылок: {len(self.bio_links)}\n"
                    f"👑 Админов: {len(self.admins)}\n\n"
                    f"🔒 **Сессии аккаунтов НЕ затронуты!**\n"
                    f"👥 Все аккаунты ({len(self.accounts_data)}) остались авторизованы\n\n"
                    f"✅ Можно сразу продолжать работу или `/startmon`"
                )
                logger.info(f"Safe restore from {backup_file} by user {event.sender_id} (SESSIONS PRESERVED)")
                
            except json.JSONDecodeError as e:
                await event.respond(f"❌ Файл бэкапа повреждён: {str(e)}")
                logger.error(f"Backup restore JSON error: {e}")
            except Exception as e:
                await event.respond(f"❌ Ошибка восстановления: {str(e)}")
                logger.error(f"Backup restore error: {e}")
        
        # ============= END SESSION PROTECTION COMMANDS =============
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/addsession'))
        async def add_session(event):
            """Добавляет аккаунт по готовой сессии StringSession"""
            if not await self.is_admin(event.sender_id):
                return
            
            try:
                parts = event.text.split(maxsplit=2)
                if len(parts) < 3:
                    await event.respond(
                        "❌ Неверный формат.\n\n"
                        "**Использование:**\n"
                        "`/addsession +79991112233 1AaBbCcDd...сессия...`\n\n"
                        "**Как получить сессию:**\n"
                        "1. На телефоне с этим номером откройте Telegram\n"
                        "2. Напишите мне команду `/exportsession +79991112233`\n"
                        "3. Скопируйте полученную строку сессии"
                    )
                    return
                
                phone = parts[1].strip()
                session_string = parts[2].strip()
                
                # Очистка номера
                phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                logger.info(f"ADDSESSION: Attempting to add account phone={phone}, session_len={len(session_string)}")
                
                # Проверяем сессию
                await event.respond(f"🔄 Проверяю сессию для `{phone}`...")
                
                try:
                    from telethon.sessions import StringSession
                    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        await client.disconnect()
                        await event.respond(
                            f"❌ **Сессия невалидна или истекла**\n\n"
                            f"Сессия для `{phone}` не авторизована.\n\n"
                            f"Попробуйте:\n"
                            f"1. Получить новую сессию через `/exportsession {phone}`\n"
                            f"2. Или использовать `/auth {phone}` (для не-RU номеров)"
                        )
                        logger.warning(f"ADDSESSION: Session not authorized for {phone}")
                        return
                    
                    # Получаем данные пользователя
                    me = await client.get_me()
                    await client.disconnect()
                    
                    # Определяем admin_id
                    admin_id = None if self.is_super_admin(event.sender_id) else event.sender_id
                    
                    # Создаём структуру аккаунта
                    account_data = {
                        'session': session_string,
                        'active': True,
                        'name': me.first_name or 'Без имени',
                        'username': getattr(me, 'username', None),
                        'phone': phone,
                        'proxy': None,
                        'admin_id': admin_id,
                        'status': 'active'
                    }
                    
                    # Сохраняем
                    self.accounts_data[phone] = account_data
                    self.save_data()
                    
                    logger.info(f"ADDSESSION: Successfully added account {phone}, name={account_data['name']}")
                    
                    await event.respond(
                        f"✅ **Аккаунт успешно добавлен!**\n\n"
                        f"👤 **{account_data['name']}**\n"
                        f"@{account_data.get('username', 'нет')}\n"
                        f"📱 `{phone}`\n"
                        f"🟢 Статус: ACTIVE\n\n"
                        f"Аккаунт готов к работе!"
                    )
                    
                except Exception as e:
                    logger.exception(f"ADDSESSION: Error validating session for {phone}")
                    await event.respond(
                        f"❌ **Ошибка проверки сессии**\n\n"
                        f"Телефон: `{phone}`\n"
                        f"Ошибка: {str(e)[:200]}\n\n"
                        f"Возможные причины:\n"
                        f"• Сессия повреждена при копировании\n"
                        f"• Сессия истекла\n"
                        f"• Неверный формат\n\n"
                        f"Попробуйте получить новую сессию."
                    )
                    
            except Exception as e:
                logger.exception("ADDSESSION: Handler exception")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/exportsession'))
        async def export_session(event):
            """Экспортирует сессию для указанного номера (создаёт новую авторизацию)"""
            if not await self.is_admin(event.sender_id):
                return
            
            try:
                parts = event.text.split()
                if len(parts) < 2:
                    await event.respond(
                        "❌ Укажите номер телефона.\n\n"
                        "**Использование:**\n"
                        "`/exportsession +79991112233`\n\n"
                        "Вы получите строку сессии для этого номера."
                    )
                    return
                
                phone = parts[1].strip()
                phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                logger.info(f"EXPORTSESSION: Starting for phone={phone}, user={event.sender_id}")
                
                # Проверяем, не RU ли номер
                if phone.startswith('+7') or phone.startswith('7'):
                    await event.respond(
                        f"⚠️ **Номер начинается на +7 (Россия)**\n\n"
                        f"Для RU номеров используйте `/auth {phone}` и команду **GETCODE**.\n\n"
                        f"Или продолжите здесь - я попробую отправить код автоматически."
                    )
                
                await event.respond(f"🔄 Начинаю процесс экспорта сессии для `{phone}`...")
                
                try:
                    from telethon.sessions import StringSession
                    client = TelegramClient(StringSession(), API_ID, API_HASH)
                    await client.connect()
                    
                    logger.info(f"EXPORTSESSION: Sending code request to {phone}")
                    result = await client.send_code_request(phone)
                    logger.info(f"EXPORTSESSION: Code sent, result: {result}")
                    
                    msg = await event.respond(
                        f"📱 **Код отправлен на `{phone}`**\n\n"
                        f"Проверьте Telegram на телефоне с этим номером.\n"
                        f"Отправьте мне код в ответ на это сообщение."
                    )
                    
                    # Сохраняем состояние для экспорта
                    self.pending_auth[event.chat_id] = {
                        'phone': phone,
                        'proxy': None,
                        'client': client,
                        'message_id': msg.id,
                        'state': 'export_waiting_code',
                        'event': event
                    }
                    
                    logger.info(f"EXPORTSESSION: Waiting for code, chat_id={event.chat_id}")
                    
                except Exception as e:
                    logger.exception(f"EXPORTSESSION: Error sending code to {phone}")
                    await event.respond(
                        f"❌ **Ошибка отправки кода**\n\n"
                        f"Телефон: `{phone}`\n"
                        f"Ошибка: {str(e)[:200]}\n\n"
                        f"Для RU номеров (+7) используйте:\n"
                        f"1. `/auth {phone}`\n"
                        f"2. Отправьте **GETCODE**\n"
                        f"3. Введите код из приложения"
                    )
                    if 'client' in locals():
                        try:
                            await client.disconnect()
                        except:
                            pass
                    
            except Exception as e:
                logger.exception("EXPORTSESSION: Handler exception")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/auth'))

        async def auth_account(event):
            logger.info("=" * 60)
            logger.info("TELETHON AUTH EVENT FIRED")
            logger.info("sender_id=%s chat_id=%s text=%r", 
                        event.sender_id, event.chat_id, event.text)
            logger.info("=" * 60)
            
            try:
                if not await self.is_admin(event.sender_id): 
                    logger.info("AUTH: Access denied - user %s is not admin", event.sender_id)
                    return
                parts = event.text.split()
                if len(parts) < 2 or not parts[1].strip():
                    await event.respond("❌ Укажите номер. Пример: `/auth +79991112233`")
                    return
                phone = parts[1].strip()
                # Убираем любые символы, кроме цифр и "+"
                phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                logger.info("AUTH: cleaned phone=%r", phone)
                
                # Проверка на российский номер (+7)
                if phone.startswith('+7') or phone.startswith('7'):
                    logger.warning(f"AUTH: RU number detected: {phone}")
                    await event.respond(
                        f"⚠️ **Номер начинается на +7 (Россия)**\n\n"
                        f"Telegram заблокировал автоматическую отправку кода для RU номеров в API.\n\n"
                        f"✅ **Решение:**\n"
                        f"1. Откройте Telegram на телефоне с номером `{phone}`\n"
                        f"2. Отправьте мне сообщение **GETCODE** (я получу код и отправлю его вам)\n"
                        f"3. Или вы можете сами ввести код, который пришёл в приложение\n\n"
                        f"Код я буду отправлять в этот чат автоматически."
                    )
                    # Сохраняем состояние ожидания GETCODE для RU номера
                    self.pending_auth[event.chat_id] = {
                        'phone': phone,
                        'proxy': None,
                        'state': 'waiting_getcode',
                        'event': event
                    }
                    return
                
                proxy = None
                if len(parts) > 2:
                    proxy_parts = parts[2].split(':')
                    # Telethon expects: (type, host, port, rdns, username, password)
                    if len(proxy_parts) == 6:
                        # Full format: socks5:host:port:rdns:user:pass
                        proxy = (proxy_parts[0], proxy_parts[1], int(proxy_parts[2]), 
                                proxy_parts[3].lower() == 'true', proxy_parts[4], proxy_parts[5])
                    elif len(proxy_parts) == 5:
                        # Short format: socks5:host:port:user:pass (rdns=True by default)
                        proxy = (proxy_parts[0], proxy_parts[1], int(proxy_parts[2]), 
                                True, proxy_parts[3], proxy_parts[4])
                await event.respond(f"🔄 Начинаем авторизацию: `{phone}`")
                
                logger.info("AUTH: calling authorize_account for phone=%r", phone)
                result = await self.authorize_account(phone, proxy, event)
                logger.info("AUTH: authorize_account returned: %s", type(result).__name__)
                
                # Если результат 'pending', значит ждём ввода кода через обработчик сообщений
                if result == 'pending':
                    logger.info(f"Авторизация {phone} в режиме ожидания кода")
                    # Не отвечаем здесь - ответим после получения кода
                elif result:
                    # Успешная авторизация (уже был авторизован)
                    self.accounts_data[phone] = result
                    self.save_data()
                    await event.respond(f"✅ **{result['name']}** авторизован!\n@{result.get('username', 'нет')}\n`{phone}` ✅ АКТИВЕН")
                else:
                    await event.respond("⚠️ Ошибка авторизации, проверь номер и попробуй ещё раз.")
            except Exception as e:
                logger.exception("AUTH HANDLER EXCEPTION")
                await event.respond("⚠️ Ошибка авторизации, проверь номер и попробуй ещё раз.")
        
        # Обработчик для входящих сообщений (для перехвата кодов авторизации и паролей 2FA)
        @self.bot_client.on(events.NewMessage(func=lambda e: not e.text.startswith('/')))
        async def handle_auth_code(event):
            """Обрабатывает входящие сообщения для авторизации"""
            if not await self.is_admin(event.sender_id):
                return
            
            chat_id = event.chat_id
            
            # Специальная обработка команды GETCODE для RU номеров
            if event.text and event.text.strip().upper() == 'GETCODE':
                logger.info("GETCODE command received from user_id=%s", event.sender_id)
                
                if chat_id not in self.pending_auth:
                    await event.respond("❌ Нет активного процесса авторизации.\n\nСначала используйте `/auth +79991112233`")
                    return
                
                auth_data = self.pending_auth[chat_id]
                if auth_data.get('state') != 'waiting_getcode':
                    logger.warning("GETCODE received but state is not waiting_getcode: %s", auth_data.get('state'))
                    return
                
                phone = auth_data['phone']
                proxy = auth_data.get('proxy')
                
                logger.info("GETCODE: Attempting to send code to RU number: %s", phone)
                
                try:
                    # Создаём клиент и отправляем запрос кода
                    from telethon.sessions import StringSession
                    client = TelegramClient(StringSession(), API_ID, API_HASH, proxy=proxy)
                    await client.connect()
                    
                    logger.info("GETCODE: Client connected, sending code request...")
                    result = await client.send_code_request(phone)
                    logger.info("GETCODE: Code request result: %s", result)
                    
                    # Отправляем сообщение пользователю
                    msg = await event.respond(
                        f"✅ Запрос кода отправлен на `{phone}`\n\n"
                        f"📱 Проверьте Telegram на телефоне с этим номером\n"
                        f"🔢 Отправьте мне код в ответ на это сообщение"
                    )
                    
                    # Обновляем состояние
                    auth_data['state'] = 'waiting_code'
                    auth_data['client'] = client
                    auth_data['message_id'] = msg.id
                    
                    logger.info("GETCODE: State updated to waiting_code, message_id=%s", msg.id)
                    
                except Exception as e:
                    logger.exception("GETCODE: Error sending code request")
                    await event.respond(f"❌ Ошибка при отправке кода: {str(e)[:200]}")
                    if 'client' in locals():
                        try:
                            await client.disconnect()
                        except:
                            pass
                
                return
            
            # Проверяем, есть ли ожидание авторизации для этого чата
            if chat_id not in self.pending_auth:
                # Нет ожидания - игнорируем
                return
            
            auth_data = self.pending_auth[chat_id]
            logger.info(f"Получено сообщение в чате с pending_auth: chat_id={chat_id}, user_id={event.sender_id}")
            logger.info(f"pending_auth[{chat_id}] = {{'phone': '{auth_data['phone']}', 'state': '{auth_data['state']}', 'message_id': {auth_data['message_id']}}}")
            
            # Проверяем, что это ответ на наше сообщение
            if not event.reply_to_msg_id:
                logger.warning(f"Сообщение не является ответом (reply_to_msg_id=None), игнорируем")
                return
            
            if event.reply_to_msg_id != auth_data['message_id']:
                logger.warning(f"Ответ на другое сообщение: reply_to={event.reply_to_msg_id}, ожидаем={auth_data['message_id']}")
                return
            
            # Получаем данные
            phone = auth_data['phone']
            proxy = auth_data['proxy']
            client = auth_data['client']
            state = auth_data['state']
            code_or_password = event.text.strip()
            
            # Логирование ввода
            logger.info("AUTH CODE INPUT: user_id=%s code_text=%r", event.sender_id, event.text)
            
            try:
                if state == 'export_waiting_code':
                    # Специальная обработка для экспорта сессии
                    logger.info(f"EXPORTSESSION: Получен код для {phone}: {code_or_password}")
                    
                    try:
                        assert phone is not None, "phone is None"
                        assert code_or_password is not None, "code is None"
                        
                        await client.sign_in(phone, code_or_password)
                        logger.info(f"EXPORTSESSION: Account {phone} successfully authorized")
                        
                        # Получаем данные и сессию
                        me = await client.get_me()
                        session_string = client.session.save()
                        await client.disconnect()
                        
                        # Очищаем состояние
                        del self.pending_auth[chat_id]
                        
                        # Отправляем сессию пользователю
                        await event.respond(
                            f"✅ **Сессия успешно создана!**\n\n"
                            f"👤 **{me.first_name or 'Без имени'}**\n"
                            f"@{getattr(me, 'username', 'нет')}\n"
                            f"📱 `{phone}`\n\n"
                            f"🔑 **Строка сессии:**\n"
                            f"```\n{session_string}\n```\n\n"
                            f"📋 **Скопируйте и используйте:**\n"
                            f"`/addsession {phone} {session_string}`"
                        )
                        
                        logger.info(f"EXPORTSESSION: Session exported for {phone}")
                        
                    except SessionPasswordNeededError:
                        # Нужен пароль 2FA
                        logger.info(f"EXPORTSESSION: 2FA required for {phone}")
                        msg = await event.respond(
                            f"🔐 **Требуется пароль 2FA**\n\n"
                            f"Отправьте пароль двухфакторной аутентификации в ответ на это сообщение"
                        )
                        
                        # Обновляем состояние
                        auth_data['state'] = 'export_waiting_2fa'
                        auth_data['message_id'] = msg.id
                        logger.info(f"EXPORTSESSION: State updated to export_waiting_2fa")
                        
                    except Exception as e:
                        logger.exception(f"EXPORTSESSION: Error during sign_in for {phone}")
                        await event.respond(
                            f"❌ **Ошибка авторизации**\n\n"
                            f"Код неверный или истёк.\n"
                            f"Попробуйте снова: `/exportsession {phone}`"
                        )
                        await client.disconnect()
                        del self.pending_auth[chat_id]
                
                elif state == 'export_waiting_2fa':
                    # 2FA для экспорта сессии
                    logger.info(f"EXPORTSESSION: Получен пароль 2FA для {phone}")
                    
                    try:
                        await client.sign_in(password=code_or_password)
                        logger.info(f"EXPORTSESSION: Account {phone} authorized with 2FA")
                        
                        # Получаем данные и сессию
                        me = await client.get_me()
                        session_string = client.session.save()
                        await client.disconnect()
                        
                        # Очищаем состояние
                        del self.pending_auth[chat_id]
                        
                        # Отправляем сессию
                        await event.respond(
                            f"✅ **Сессия успешно создана!**\n\n"
                            f"👤 **{me.first_name or 'Без имени'}**\n"
                            f"@{getattr(me, 'username', 'нет')}\n"
                            f"📱 `{phone}`\n\n"
                            f"🔑 **Строка сессии:**\n"
                            f"```\n{session_string}\n```\n\n"
                            f"📋 **Скопируйте и используйте:**\n"
                            f"`/addsession {phone} {session_string}`"
                        )
                        
                        logger.info(f"EXPORTSESSION: Session exported for {phone} with 2FA")
                        
                    except Exception as e:
                        logger.exception(f"EXPORTSESSION: Error with 2FA for {phone}")
                        await event.respond(
                            f"❌ **Ошибка 2FA**\n\n"
                            f"Пароль неверный.\n"
                            f"Попробуйте снова: `/exportsession {phone}`"
                        )
                        await client.disconnect()
                        del self.pending_auth[chat_id]
                
                elif state == 'waiting_code':
                    logger.info(f"Получен код авторизации для {phone}: {code_or_password}")
                    
                    try:
                        assert phone is not None, "phone is None"
                        assert code_or_password is not None, "code is None"
                        logger.info("AUTH CODE SENDING: code=%r", code_or_password)
                        await client.sign_in(phone, code_or_password)
                        logger.info(f"Аккаунт {phone} успешно авторизован")
                        
                        # Успешная авторизация!
                        me = await client.get_me()
                        session = client.session.save()
                        await client.disconnect()
                        
                        result = {
                            'session': session,
                            'active': True,
                            'name': me.first_name or 'Без имени',
                            'username': getattr(me, 'username', None),
                            'phone': phone,
                            'proxy': proxy
                        }
                        
                        # Сохраняем в базу
                        self.accounts_data[phone] = result
                        self.save_data()
                        
                        # Очищаем состояние
                        del self.pending_auth[chat_id]
                        
                        await event.respond(f"✅ **{result['name']}** авторизован!\n@{result.get('username', 'нет')}\n`{phone}` ✅ АКТИВЕН")
                        
                    except SessionPasswordNeededError:
                        # Нужен пароль 2FA
                        logger.info(f"Для {phone} требуется пароль 2FA")
                        msg = await event.respond(f"🔐 Требуется пароль 2FA\n\nОтветьте на это сообщение с паролем двухфакторной аутентификации")
                        
                        # Обновляем состояние
                        auth_data['state'] = 'waiting_2fa'
                        auth_data['message_id'] = msg.id
                        logger.info(f"Обновлено состояние на waiting_2fa, новый message_id={msg.id}")
                    except Exception as e:
                        logger.exception("AUTH CODE ERROR: %s", e)
                        await event.respond("⚠️ Ошибка при вводе кода. Попробуй ещё раз.")
                        # Очистка при ошибке
                        try:
                            await client.disconnect()
                        except:
                            pass
                        if chat_id in self.pending_auth:
                            del self.pending_auth[chat_id]
                        return
                        
                elif state == 'waiting_2fa':
                    logger.info(f"Получен пароль 2FA для {phone}")
                    
                    try:
                        assert code_or_password is not None, "password is None"
                        logger.info("AUTH 2FA SENDING: password=%r", code_or_password)
                        await client.sign_in(password=code_or_password)
                        logger.info(f"Аккаунт {phone} успешно авторизован (с 2FA)")
                        
                        # Успешная авторизация!
                        me = await client.get_me()
                        session = client.session.save()
                        await client.disconnect()
                        
                        result = {
                            'session': session,
                            'active': True,
                            'name': me.first_name or 'Без имени',
                            'username': getattr(me, 'username', None),
                            'phone': phone,
                            'proxy': proxy
                        }
                        
                        # Сохраняем в базу
                        self.accounts_data[phone] = result
                        self.save_data()
                        
                        # Очищаем состояние
                        del self.pending_auth[chat_id]
                        
                        await event.respond(f"✅ **{result['name']}** авторизован (с 2FA)!\n@{result.get('username', 'нет')}\n`{phone}` ✅ АКТИВЕН")
                    except Exception as e:
                        logger.exception("AUTH 2FA ERROR: %s", e)
                        await event.respond("⚠️ Ошибка при вводе пароля 2FA. Попробуй ещё раз.")
                        # Очистка при ошибке
                        try:
                            await client.disconnect()
                        except:
                            pass
                        if chat_id in self.pending_auth:
                            del self.pending_auth[chat_id]
                        return
                    
            except TypeError as e:
                logger.exception("AUTH TYPEERROR: %s", e)
                logger.exception("Auth error")
                await event.respond("⚠️ Ошибка авторизации, проверь номер и попробуй ещё раз.")
                # Очистка при ошибке
                try:
                    await client.disconnect()
                except:
                    pass
                if chat_id in self.pending_auth:
                    del self.pending_auth[chat_id]
            except Exception as e:
                logger.exception("Auth error")
                await event.respond("⚠️ Ошибка авторизации, проверь номер и попробуй ещё раз.")
                
                # Очистка при ошибке
                try:
                    await client.disconnect()
                except:
                    pass
                if chat_id in self.pending_auth:
                    del self.pending_auth[chat_id]
        
        @self.bot_client.on(events.NewMessage(pattern='/listaccounts'))
        async def list_accounts(event):
            """Вывод списка всех аккаунтов с их статусами (ОДИН ответ без противоречий)
            
            ⚠️ ВАЖНО: Эта команда НЕ ДОЛЖНА выводить 'Нет авторизованных аккаунтов'!
            Она просто показывает структуру из bot_data.json со статусами.
            """
            if not await self.is_admin(event.sender_id): return
            
            logger.info("="*80)
            logger.info("📋 /listaccounts HANDLER STARTED")
            logger.info(f"📋 Пользователь: {event.sender_id}")
            logger.info(f"📋 Всего аккаунтов в системе: {len(self.accounts_data)}")
            logger.info("📋 ⚠️ ВНИМАНИЕ: Этот обработчик НЕ должен вызывать другие функции проверки!")
            logger.info("📋 ⚠️ ВНИМАНИЕ: Этот обработчик НЕ должен отправлять 'Нет авторизованных аккаунтов'!")
            
            # Determine admin_id for filtering
            admin_id = self.get_admin_id(event.sender_id)
            
            # Filter accounts by admin_id
            if admin_id is None:  # Super admin - show all
                filtered_accounts = self.accounts_data
                logger.info(f"   Super admin - показываем все {len(self.accounts_data)} аккаунтов")
            else:  # Regular admin - show only their accounts
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == admin_id}
                logger.info(f"   Админ {admin_id} - показываем {len(filtered_accounts)} аккаунтов")
            
            if not filtered_accounts:
                logger.info("📋 ℹ️ У данного админа нет аккаунтов (filtered_accounts пустой)")
                logger.info("📋 Отправляю сообщение: 'У вас нет аккаунтов'")
                await event.respond("ℹ️ У вас пока нет аккаунтов в системе\n\n💡 Используйте `/auth +номер` для добавления")
                logger.info("📋 /listaccounts HANDLER FINISHED (empty accounts)")
                logger.info("="*80)
                return
            
            logger.info(f"📋 ✅ Найдено аккаунтов для отображения: {len(filtered_accounts)}")
            logger.info(f"📋 ⚠️ ВАЖНО: /listaccounts НЕ проверяет реальную авторизацию через Telethon!")
            logger.info(f"📋 ⚠️ Показываются данные из bot_data.json, для проверки сессий используйте /verify_sessions")
            
            # Подсчёт статусов для общей статистики
            status_counts = {'active': 0, 'reserve': 0, 'broken': 0}
            for data in filtered_accounts.values():
                status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                if status_val == ACCOUNT_STATUS_ACTIVE:
                    status_counts['active'] += 1
                elif status_val == ACCOUNT_STATUS_BROKEN:
                    status_counts['broken'] += 1
                else:
                    status_counts['reserve'] += 1
            
            logger.info(f"📋 Статусы: ✅ {status_counts['active']} | 🔵 {status_counts['reserve']} | 🔴 {status_counts['broken']}")
            
            # Show all accounts, split into multiple messages if needed
            total = len(filtered_accounts)
            accounts_per_msg = 20
            accounts_list = list(filtered_accounts.items())
            
            logger.info(f"📋 Начинаю отправку {total} аккаунтов...")
            
            for batch_num in range(0, total, accounts_per_msg):
                batch_accounts = accounts_list[batch_num:batch_num + accounts_per_msg]
                
                # В первом сообщении добавляем общую статистику
                if batch_num == 0:
                    text = f"📱 **АККАУНТЫ** ({total}):\n"
                    text += f"✅ Active: {status_counts['active']} | "
                    text += f"🔵 Reserve: {status_counts['reserve']} | "
                    text += f"🔴 Broken: {status_counts['broken']}\n\n"
                else:
                    text = f"АККАУНТЫ ({total}) - Часть {batch_num//accounts_per_msg + 1}:\n\n"
                
                for i, (phone, data) in enumerate(batch_accounts, batch_num + 1):
                    # NEW: Используем новые статусы
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅ ACTIVE"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴 BROKEN"
                    else:
                        status = "🔵 RESERVE"
                    
                    name = data.get('name', 'Не авторизован')
                    username = data.get('username', 'нет')
                    text += f"{i}. {status} `{name}` (@{username})\n`   {phone}`\n"
                
                await event.respond(text)
                logger.info(f"📋 📤 Отправлена часть {batch_num//accounts_per_msg + 1} (аккаунтов в части: {len(batch_accounts)})")
                # Small delay between messages to avoid flood
                if batch_num + accounts_per_msg < total:
                    await asyncio.sleep(0.5)
            
            logger.info("📋 /listaccounts HANDLER FINISHED SUCCESSFULLY")
            logger.info("="*80)
        
        @self.bot_client.on(events.NewMessage(pattern='/delaccount'))
        async def del_account(event):
            """
            Удаляет аккаунт с подтверждением для защиты от случайного удаления сессий.
            КРИТИЧНО: Требует явного подтверждения 'CONFIRM' для безопасности.
            """
            if not await self.is_admin(event.sender_id): return
            try:
                parts = event.text.split(maxsplit=2)
                if len(parts) < 2:
                    await event.respond(
                        "**❌ Неверный формат**\n\n"
                        "**Использование:**\n"
                        "`/delaccount +79123456789 CONFIRM`\n\n"
                        "⚠️ **ВНИМАНИЕ:** Эта команда УДАЛИТ аккаунт и его сессию!\n"
                        "Потребуется заново авторизоваться через `/auth`\n\n"
                        "💡 Для отключения аккаунта без удаления используйте:\n"
                        "`/toggleaccount +79123456789`"
                    )
                    return
                
                phone_input = parts[1]
                
                # Ищем аккаунт по разным форматам номера
                phone = None
                logger.info(f"🔍 /delaccount: поиск аккаунта '{phone_input}'")
                logger.info(f"   Доступные ключи: {list(self.accounts_data.keys())}")
                
                # Нормализуем введённый номер (удаляем всё кроме цифр)
                normalized_input = ''.join(c for c in phone_input if c.isdigit())
                logger.info(f"   Нормализованный ввод: '{normalized_input}'")
                
                for p in self.accounts_data.keys():
                    # Нормализуем ключ из словаря (только цифры)
                    normalized_key = ''.join(c for c in p if c.isdigit())
                    logger.info(f"   Сравниваем: '{normalized_input}' == '{normalized_key}' ({p})")
                    if normalized_key == normalized_input:
                        phone = p
                        logger.info(f"   ✅ НАЙДЕН: {p}")
                        break
                
                if not phone:
                    logger.error(f"   ❌ НЕ НАЙДЕН среди {len(self.accounts_data)} аккаунтов")
                    await event.respond(
                        f"❌ Аккаунт не найден: `{phone_input}`\n\n"
                        f"📋 Доступные номера:\n" + 
                        "\n".join([f"• `{p}`" for p in list(self.accounts_data.keys())[:10]]) +
                        f"\n\n💡 Используйте `/listaccounts` для полного списка"
                    )
                    return
                
                # Требуем явного подтверждения
                if len(parts) < 3 or parts[2].upper() != 'CONFIRM':
                    account_name = self.accounts_data[phone].get('name', phone)
                    await event.respond(
                        f"⚠️ **ПОДТВЕРДИТЕ УДАЛЕНИЕ**\n\n"
                        f"Аккаунт: `{account_name}`\n"
                        f"Телефон: `{phone}`\n\n"
                        f"**Будет удалено:**\n"
                        f"• Сессия аккаунта (потребуется переавторизация)\n"
                        f"• Все настройки и статистика\n\n"
                        f"**Для подтверждения отправьте:**\n"
                        f"`/delaccount {phone} CONFIRM`\n\n"
                        f"💡 **Альтернатива:** Используйте `/toggleaccount {phone}` чтобы просто отключить аккаунт"
                    )
                    return
                
                # Удаляем только после подтверждения
                account_name = self.accounts_data[phone].get('name', phone)
                
                # ============= ЗАЩИТА: Создаём бэкап перед удалением =============
                import shutil
                from datetime import datetime
                backup_name = f'bot_data.json.before_delete_{phone.replace("+", "")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                shutil.copy2(DB_NAME, backup_name)
                logger.warning(f"🔴 DELETING ACCOUNT: {phone} ({account_name}) by user {event.sender_id}, backup: {backup_name}")
                # ============= END ЗАЩИТА =============
                
                del self.accounts_data[phone]
                self.save_data()
                
                await event.respond(
                    f"✅ **Аккаунт удалён**\n\n"
                    f"Имя: `{account_name}`\n"
                    f"Телефон: `{phone}`\n\n"
                    f"💾 Резервная копия создана:\n"
                    f"`{backup_name}`\n\n"
                    f"⚠️ Для восстановления используйте `/restore`"
                )
            except Exception as e:
                logger.error(f"Error in /delaccount: {e}")
                await event.respond(
                    f"❌ Ошибка: `{str(e)[:100]}`\n\n"
                    "**Формат:**\n"
                    "`/delaccount +79123456789 CONFIRM`"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/toggleaccount'))
        async def toggle_account(event):
            """Toggle account between active and reserve mode"""
            if not await self.is_admin(event.sender_id): return
            try:
                phone_input = event.text.split(maxsplit=1)[1]
                
                # Ищем аккаунт по разным форматам номера (только цифры)
                phone = None
                normalized_input = ''.join(c for c in phone_input if c.isdigit())
                
                for p in self.accounts_data.keys():
                    normalized_key = ''.join(c for c in p if c.isdigit())
                    if normalized_key == normalized_input:
                        phone = p
                        break
                
                if not phone:
                    await event.respond(
                        f"❌ Аккаунт не найден: `{phone_input}`\n\n"
                        f"💡 Используйте `/listaccounts` чтобы увидеть все аккаунты"
                    )
                    return
                
                # NEW: Используем новые статусы
                current_status = self.accounts_data[phone].get('status', ACCOUNT_STATUS_RESERVE)
                
                # Переключаем между active и reserve (игнорируем broken)
                if current_status == ACCOUNT_STATUS_ACTIVE:
                    new_status = ACCOUNT_STATUS_RESERVE
                    status_text = "🔵 RESERVE"
                elif current_status == ACCOUNT_STATUS_BROKEN:
                    # Если аккаунт broken, переводим в reserve
                    new_status = ACCOUNT_STATUS_RESERVE
                    status_text = "🔵 RESERVE (восстановлен из broken)"
                else:
                    new_status = ACCOUNT_STATUS_ACTIVE
                    status_text = "✅ ACTIVE"
                
                self.set_account_status(phone, new_status, "Manual toggle")
                account_name = self.accounts_data[phone].get('name', phone)
                
                await event.respond(
                    f"Аккаунт `{account_name}` ({phone})\n"
                    f"Статус изменен: {status_text}\n\n"
                    f"📊 Текущее состояние: {self.get_status_counts()}"
                )
            except:
                await event.respond(
                    "Формат: `/toggleaccount +79123456789`\n\n"
                    "⚠️ Эта команда переключает статус ОДНОГО аккаунта:\n"
                    "✅ ACTIVE → 🔵 RESERVE\n"
                    "🔵 RESERVE → ✅ ACTIVE\n"
                    "🔴 BROKEN → 🔵 RESERVE"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/addaccount'))
        async def add_account(event):
            """Добавление аккаунта через StringSession с поддержкой прокси"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split(maxsplit=4)
                if len(parts) < 3:
                    await event.respond(
                        "**📱 ДОБАВЛЕНИЕ АККАУНТА**\n\n"
                        "Добавляет аккаунт через готовую StringSession.\n"
                        "Поддерживает любые источники сессий:\n"
                        "• Auth Key (через convert_session.py)\n"
                        "• tdata (через convert_session.py)\n"
                        "• Готовая StringSession\n\n"
                        "**Формат:**\n"
                        "`/addaccount +номер StringSession [Имя] [прокси]`\n\n"
                        "**Примеры:**\n"
                        "1. Без прокси:\n"
                        "`/addaccount +79991112233 1BVtsOHsBu... Александр`\n\n"
                        "2. С прокси:\n"
                        "`/addaccount +79991112233 1BVtsOHsBu... Александр socks5:host:1080:user:pass`\n\n"
                        "**💡 Как получить StringSession:**\n"
                        "• Из Auth Key или tdata: `python3 convert_session.py`\n"
                        "• Вручную: `python3 manual_auth_russia.py`\n"
                        "• Экспорт существующей: `/exportsession +номер`"
                    )
                    return
                
                phone = parts[1]
                session_string = parts[2]
                name = parts[3] if len(parts) > 3 else phone[-10:]
                proxy_str = parts[4] if len(parts) > 4 else None
                
                # Парсим прокси если указан
                proxy = None
                if proxy_str:
                    try:
                        proxy_parts = proxy_str.split(':')
                        if len(proxy_parts) == 6:
                            # Full format: socks5:host:port:rdns:user:pass
                            proxy = (proxy_parts[0], proxy_parts[1], int(proxy_parts[2]), 
                                    proxy_parts[3].lower() == 'true', proxy_parts[4], proxy_parts[5])
                        elif len(proxy_parts) >= 5:
                            # Short format: socks5:host:port:user:pass
                            proxy = (proxy_parts[0], proxy_parts[1], int(proxy_parts[2]), 
                                    True, proxy_parts[3], proxy_parts[4])
                        else:
                            await event.respond("⚠️ Неверный формат прокси. Используйте: `socks5:host:port:user:pass`")
                            return
                        
                        logger.info(f"Parsed proxy: {proxy[0]}://{proxy[1]}:{proxy[2]}")
                    except Exception as e:
                        await event.respond(f"❌ Ошибка парсинга прокси: {str(e)[:100]}")
                        return
                
                # Нормализуем номер
                phone_digits = ''.join(c for c in phone if c.isdigit())
                if not phone.startswith('+'):
                    phone = '+' + phone_digits
                
                logger.info(f"📥 /addaccount: phone={phone}, name={name}, has_proxy={proxy is not None}, user={event.sender_id}")
                
                # Проверяем что сессия валидна
                await event.respond(f"🔍 Проверка сессии для `{phone}`...")
                
                from telethon.sessions import StringSession
                test_client = TelegramClient(StringSession(session_string), API_ID, API_HASH, proxy=proxy)
                
                try:
                    await test_client.connect()
                    
                    if not await test_client.is_user_authorized():
                        await event.respond("❌ Сессия невалидна или аккаунт не авторизован")
                        await test_client.disconnect()
                        return
                    
                    # Получаем информацию об аккаунте
                    me = await test_client.get_me()
                    username = me.username or ""
                    first_name = me.first_name or ""
                    last_name = me.last_name or ""
                    user_id = me.id
                    
                    # Если имя не указано, берём из аккаунта
                    if name == phone[-10:]:
                        name = f"{first_name} {last_name}".strip() or username or phone[-10:]
                    
                    await test_client.disconnect()
                    
                    logger.info(f"✅ Session valid: {phone} -> {name} (@{username})")
                    
                    # Добавляем в bot_data
                    self.accounts_data[phone] = {
                        'session': session_string,
                        'name': name,
                        'username': username,
                        'status': ACCOUNT_STATUS_RESERVE,
                        'user_id': user_id,
                        'admin_id': self.get_admin_id(event.sender_id),
                        'proxy': proxy
                    }
                    
                    self.save_data()
                    
                    proxy_info = f"🌐 Прокси: {proxy[0]}://{proxy[1]}:{proxy[2]}" if proxy else "🌐 Прокси: нет"
                    
                    await event.respond(
                        f"✅ **Аккаунт успешно добавлен!**\n\n"
                        f"👤 Имя: `{name}`\n"
                        f"📱 Телефон: `{phone}`\n"
                        f"🆔 Username: @{username}\n"
                        f"{proxy_info}\n"
                        f"🔵 Статус: **RESERVE** (не активен)\n\n"
                        f"💡 Используйте `/toggleaccount {phone}` для активации\n"
                        f"📊 Проверьте: `/listaccounts`"
                    )
                    
                    logger.info(f"✅ Account added: {phone} -> {name}")
                    
                except Exception as e:
                    logger.error(f"Add account error: {e}")
                    await event.respond(f"❌ Ошибка проверки сессии:\n`{str(e)[:200]}`")
                    try:
                        await test_client.disconnect()
                    except:
                        pass
                    
            except Exception as e:
                logger.error(f"/addaccount error: {e}")
                await event.respond(f"❌ Ошибка: `{str(e)[:200]}`")
        
        @self.bot_client.on(events.NewMessage(pattern='/importsession'))
        async def import_session(event):
            """Импорт готовой StringSession для российских номеров (старая команда, используйте /addaccount)"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split(maxsplit=3)
                if len(parts) < 3:
                    await event.respond(
                        "**📱 ИМПОРТ ГОТОВОЙ СЕССИИ**\n\n"
                        "⚠️ Эта команда устарела, используйте `/addaccount`\n\n"
                        "**Новая команда:**\n"
                        "`/addaccount +номер StringSession Имя [прокси]`\n\n"
                        "**Примеры:**\n"
                        "• `/addaccount +79991112233 1BVtsOHsBu... Александр`\n"
                        "• `/addaccount +79991112233 1BVtsOHsBu... Александр socks5:host:1080:user:pass`"
                    )
                    return
                
                phone = parts[1]
                session_string = parts[2]
                name = parts[3] if len(parts) > 3 else phone[-10:]
                
                # Нормализуем номер
                phone_digits = ''.join(c for c in phone if c.isdigit())
                if not phone.startswith('+'):
                    phone = '+' + phone_digits
                
                logger.info(f"📥 /importsession: phone={phone}, name={name}, user={event.sender_id}")
                
                # Проверяем что сессия валидна (подключаемся)
                await event.respond(f"🔍 Проверка сессии для `{phone}`...")
                
                from telethon.sessions import StringSession
                test_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
                
                try:
                    await test_client.connect()
                    
                    if not await test_client.is_user_authorized():
                        await event.respond("❌ Сессия невалидна или аккаунт не авторизован")
                        await test_client.disconnect()
                        return
                    
                    # Получаем информацию об аккаунте
                    me = await test_client.get_me()
                    username = me.username or ""
                    first_name = me.first_name or ""
                    last_name = me.last_name or ""
                    user_id = me.id
                    
                    # Если имя не указано, берём из аккаунта
                    if name == phone[-10:]:
                        name = f"{first_name} {last_name}".strip() or username or phone[-10:]
                    
                    await test_client.disconnect()
                    
                    logger.info(f"✅ Session valid: {phone} -> {name} (@{username})")
                    
                    # Добавляем в bot_data
                    self.accounts_data[phone] = {
                        'session': session_string,
                        'name': name,
                        'username': username,
                        'status': ACCOUNT_STATUS_RESERVE,
                        'user_id': user_id,
                        'admin_id': self.get_admin_id(event.sender_id)
                    }
                    
                    self.save_data()
                    
                    await event.respond(
                        f"✅ **Аккаунт успешно импортирован!**\n\n"
                        f"👤 Имя: `{name}`\n"
                        f"📱 Телефон: `{phone}`\n"
                        f"🆔 Username: @{username}\n"
                        f"🔵 Статус: **RESERVE** (не активен)\n\n"
                        f"💡 Используйте `/toggleaccount {phone}` для активации\n"
                        f"📊 Проверьте: `/listaccounts`"
                    )
                    
                    logger.info(f"✅ Account imported: {phone} -> {name}")
                    
                except Exception as e:
                    logger.error(f"Import session error: {e}")
                    await event.respond(f"❌ Ошибка проверки сессии:\n`{str(e)[:200]}`")
                    try:
                        await test_client.disconnect()
                    except:
                        pass
                    
            except Exception as e:
                logger.error(f"/importsession error: {e}")
                await event.respond(f"❌ Ошибка: `{str(e)[:200]}`")
        
        @self.bot_client.on(events.NewMessage(pattern='/qrauth'))
        async def qrauth_handler(event):
            """Авторизация аккаунта через QR код"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Парсим параметры: /qrauth Имя_аккаунта
                params = event.text.split(maxsplit=1)
                
                if len(params) < 2:
                    await event.respond(
                        "📱 **Авторизация через QR код**\n\n"
                        "Использование: `/qrauth Имя_аккаунта`\n\n"
                        "**Пример:**\n"
                        "`/qrauth Лена`\n\n"
                        "После отправки команды:\n"
                        "1️⃣ Вы получите QR код\n"
                        "2️⃣ Откройте Telegram Desktop\n"
                        "3️⃣ Settings → Devices → Link Desktop Device\n"
                        "4️⃣ Отсканируйте QR код\n"
                        "5️⃣ Аккаунт автоматически добавится в бот!"
                    )
                    return
                
                account_name = params[1].strip()
                
                logger.info(f"📱 /qrauth: начало авторизации через QR для '{account_name}'")
                
                msg = await event.respond(
                    f"📱 **QR авторизация: {account_name}**\n\n"
                    "⏳ Генерирую QR код...\n"
                    "Не закрывайте Telegram Desktop!"
                )
                
                # Создаём временную сессию
                temp_client = TelegramClient(
                    StringSession(), 
                    API_ID, 
                    API_HASH
                )
                
                try:
                    await temp_client.connect()
                    
                    # Запрашиваем QR код
                    qr_login = await temp_client.qr_login()
                    
                    # Получаем URL для QR кода
                    qr_url = qr_login.url
                    
                    # Генерируем QR код как изображение
                    import qrcode
                    import tempfile
                    import os
                    
                    qr = qrcode.QRCode(version=1, box_size=10, border=4)
                    qr.add_data(qr_url)
                    qr.make(fit=True)
                    
                    img = qr.make_image(fill_color="black", back_color="white")
                    
                    # Сохраняем во временный файл
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                    img.save(temp_file.name)
                    temp_file.close()
                    
                    # Отправляем QR код как фото
                    await self.bot_client.send_file(
                        event.chat_id,
                        temp_file.name,
                        force_document=False,  # Отправляем как фото, а не файл
                        caption=(
                            f"📱 **QR код для: {account_name}**\n\n"
                            "**Инструкция:**\n"
                            "1️⃣ Откройте Telegram на ТЕЛЕФОНЕ\n"
                            "2️⃣ Настройки → Устройства → Привязать устройство\n"
                            "3️⃣ Наведите камеру на этот QR код\n\n"
                            "⏱️ Ожидаю сканирования (таймаут 2 минуты)..."
                        )
                    )
                    
                    # Удаляем временный файл
                    try:
                        os.unlink(temp_file.name)
                    except:
                        pass
                    
                    await msg.delete()
                    
                    # Ожидаем авторизацию
                    try:
                        await qr_login.wait(timeout=120)
                        
                        # Получаем информацию об аккаунте
                        me = await temp_client.get_me()
                        
                        # Получаем StringSession
                        session_string = StringSession.save(temp_client.session)
                        
                        # Нормализуем телефон
                        phone = f"+{me.phone}"
                        
                        # Проверяем, не добавлен ли уже этот аккаунт
                        if phone in self.accounts_data:
                            await event.respond(
                                f"⚠️ **Аккаунт уже существует**\n\n"
                                f"📱 Телефон: `{phone}`\n"
                                f"👤 Имя в боте: {self.accounts_data[phone].get('name', 'нет')}\n"
                                f"📊 Статус: {self.accounts_data[phone].get('status', 'неизвестно')}\n\n"
                                f"💡 Используйте `/toggleaccount {phone}` для управления"
                            )
                            await temp_client.disconnect()
                            return
                        
                        # Сохраняем аккаунт
                        self.accounts_data[phone] = {
                            'session': session_string,
                            'name': account_name,
                            'username': me.username or '',
                            'user_id': me.id,
                            'status': ACCOUNT_STATUS_RESERVE
                        }
                        
                        self.save_accounts_data()
                        
                        await event.respond(
                            f"✅ **Аккаунт успешно добавлен!**\n\n"
                            f"📱 Телефон: `{phone}`\n"
                            f"👤 Имя: {me.first_name or ''} {me.last_name or ''}\n"
                            f"🆔 Username: @{me.username}\n" if me.username else ""
                            f"🔢 User ID: `{me.id}`\n"
                            f"🏷️ Имя в боте: **{account_name}**\n"
                            f"📊 Статус: **RESERVE** (резерв)\n\n"
                            f"💡 Для активации: `/toggleaccount {phone}`"
                        )
                        
                        logger.info(f"✅ QR auth success: {phone} -> {account_name}")
                        
                    except asyncio.TimeoutError:
                        await event.respond(
                            "❌ **Таймаут!**\n\n"
                            "QR код не был отсканирован в течение 2 минут.\n"
                            "Попробуйте ещё раз: `/qrauth Имя`"
                        )
                        logger.warning(f"⏱️ QR auth timeout for {account_name}")
                    
                    await temp_client.disconnect()
                    
                except Exception as e:
                    logger.error(f"QR auth error: {e}")
                    await event.respond(f"❌ Ошибка при генерации QR кода:\n`{str(e)[:200]}`")
                    try:
                        await temp_client.disconnect()
                    except:
                        pass
                    
            except Exception as e:
                logger.error(f"/qrauth error: {e}")
                await event.respond(f"❌ Ошибка: `{str(e)[:200]}`")
        
        @self.bot_client.on(events.NewMessage(pattern='/verify_sessions'))
        async def verify_sessions_handler(event):
            """Ручная проверка авторизации всех аккаунтов"""
            if not await self.is_admin(event.sender_id): return
            
            if not self.accounts_data:
                logger.info("⚠️ /verify_sessions: нет аккаунтов в базе")
                await event.respond("ℹ️ В системе нет аккаунтов для проверки\n\n💡 Используйте `/auth +номер` для добавления")
                return
            
            logger.info(f"🔍 /verify_sessions: начинаю проверку {len(self.accounts_data)} аккаунтов через Telethon...")
            
            msg = await event.respond(f"🔍 Начинаю проверку {len(self.accounts_data)} аккаунтов...\nЭто может занять ~{len(self.accounts_data)} секунд")
            

            # Запускаем проверку
            result = await self.verify_all_accounts()

            # После проверки: активируем новые валидные аккаунты, если их статус RESERVE и есть свободные слоты
            max_active = self.max_parallel_accounts
            active_now = [p for p, d in self.accounts_data.items() if d.get('status') == ACCOUNT_STATUS_ACTIVE and d.get('session')]
            reserve_valid = [p for p, d in self.accounts_data.items() if d.get('status') == ACCOUNT_STATUS_RESERVE and d.get('session')]
            slots = max_active - len(active_now)
            activated = []
            if slots > 0:
                for phone in reserve_valid[:slots]:
                    self.set_account_status(phone, ACCOUNT_STATUS_ACTIVE, "Auto-activation after verify_sessions")
                    activated.append(phone)
            
            # Формируем отчёт
            verified = result['verified']
            failed = result['failed']
            broken = result['broken']
            total = result['total']

            status_text = f"""✅ **ПРОВЕРКА ЗАВЕРШЕНА**

📊 **Результаты:**
✅ Авторизованы: `{verified}`
❌ Невалидные сессии: `{failed}`
⚠️ Без сессий: `{broken}`
📱 Всего: `{total}`

📈 **Текущие статусы:**
{self.get_status_counts()}"""
            if activated:
                status_text += f"\n\n🟢 Автоматически активированы: {', '.join(activated)}"
            if failed > 0:
                status_text += f"\n\n⚠️ **{failed} аккаунтов требуют переавторизации**\nИспользуйте `/auth +номер` для каждого"
            if verified == total:
                status_text += "\n\n🎉 **Все аккаунты авторизованы!**"
            await event.respond(status_text)
        
        @self.bot_client.on(events.NewMessage(pattern='/activeaccounts'))
        async def active_accounts(event):
            """Show only active accounts"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Используем новые статусы
            active = {phone: data for phone, data in self.accounts_data.items() 
                     if data.get('status') == ACCOUNT_STATUS_ACTIVE}
            
            if not active:
                await event.respond("❌ Нет активных аккаунтов")
                return
            
            text = f"✅ **АКТИВНЫЕ АККАУНТЫ** ({len(active)}/{self.max_parallel_accounts}):\n\n"
            for i, (phone, data) in enumerate(active.items(), 1):
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                
                # Показываем статистику сообщений
                if phone in self.account_activity:
                    msgs_count = len(self.account_activity[phone]['messages'])
                    text += f"{i}. `{name}` (@{username})\n   `{phone}` (💬 {msgs_count}/h)\n"
                else:
                    text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
            
            text += f"\n📊 Лимит: {self.messages_per_hour} сообщ/час на аккаунт"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/reserveaccounts'))
        async def reserve_accounts(event):
            """Show only reserve accounts"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Используем новые статусы
            reserve = {phone: data for phone, data in self.accounts_data.items() 
                      if data.get('status') == ACCOUNT_STATUS_RESERVE and data.get('session')}
            
            if not reserve:
                await event.respond(
                    "❌ Нет резервных аккаунтов\n\n"
                    "💡 Используйте `/toggleaccount +номер` чтобы перевести аккаунт в резерв"
                )
                return
            
            text = f"🔵 **РЕЗЕРВНЫЕ АККАУНТЫ** ({len(reserve)}):\n\n"
            for i, (phone, data) in enumerate(reserve.items(), 1):
                name = data.get('name', 'Не авторизован')
                username = data.get('username', 'нет')
                text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
            
            text += f"\n💡 Эти аккаунты автоматически активируются при бане активных\n"
            text += f"🔄 Ротация каждые {self.rotation_interval // 3600} часов"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/blockedaccounts'))
        async def blocked_accounts_cmd(event):
            """Show blocked/broken accounts with reasons from database"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Показываем аккаунты со статусом BROKEN
            broken = {phone: data for phone, data in self.accounts_data.items() 
                     if data.get('status') == ACCOUNT_STATUS_BROKEN}
            
            text = f"🔴 **СЛОМАННЫЕ АККАУНТЫ** ({len(broken)}):\n\n"
            
            if not broken:
                text += "✅ Нет сломанных аккаунтов\n\n"
            else:
                for i, (phone, data) in enumerate(broken.items(), 1):
                    name = data.get('name', 'Не авторизован')
                    username = data.get('username', 'нет')
                    text += f"{i}. `{name}` (@{username})\n   `{phone}`\n"
                text += "\n"
            
            # Также проверяем БД для истории блокировок
            if self.conn:
                try:
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 10")
                    blocked = cursor.fetchall()
                    
                    if blocked:
                        text += f"\n📜 **История блокировок** (последние 10):\n\n"
                        for phone, block_date, reason in blocked:
                            date_str = block_date[:10] if block_date else "N/A"
                            text += f"• `{phone}`\n  📅 {date_str}\n  ℹ️ {reason}\n\n"
                except Exception as e:
                    text += f"\n⚠️ Ошибка чтения БД: {e}"
            
            text += "\n💡 Используйте `/toggleaccount +номер` чтобы восстановить аккаунт в резерв"
            
            await event.respond(text)
            
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 50")
                blocked = cursor.fetchall()
                
                if not blocked:
                    await event.respond("✅ Нет заблокированных аккаунтов")
                    return
                
                text = f"🚫 **ЗАБЛОКИРОВАННЫЕ АККАУНТЫ** ({len(blocked)}):\n\n"
                for i, (phone, block_date, reason) in enumerate(blocked, 1):
                    # Format date
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(block_date)
                        date_str = dt.strftime("%d.%m.%Y %H:%M")
                    except:
                        date_str = block_date[:16]
                    
                    # Get account name if exists
                    name = self.accounts_data.get(phone, {}).get('name', 'Неизвестен')
                    
                    text += f"{i}. `{name}` ({phone})\n"
                    text += f"   📅 {date_str}\n"
                    text += f"   ⚠️ {reason}\n\n"
                
                await event.respond(text)
            except Exception as e:
                logger.error(f"Blocked accounts error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/setparallel'))
        async def set_parallel(event):
            """Set number of parallel working accounts"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                num = int(event.text.split(maxsplit=1)[1])
                if num < 1 or num > 10:
                    await event.respond("❌ Число должно быть от 1 до 10")
                    return
                
                self.max_parallel_accounts = num
                # Сохраняем в конфиг
                self.save_config_value('max_parallel_accounts', num)
                
                await event.respond(
                    f"✅ Количество параллельных аккаунтов установлено: **{num}**\n\n"
                    f"⚠️ Изменения вступят в силу после перезапуска мониторинга (`/stopmon` → `/startmon`)\n"
                    f"💾 Настройка сохранена в config.json"
                )
            except (IndexError, ValueError):
                await event.respond("Формат: `/setparallel 3`\n\n📊 Рекомендации:\n• 1-2 аккаунта - безопасно\n• 3-4 аккаунта - средний риск\n• 5+ аккаунтов - высокий риск банов")
        
        @self.bot_client.on(events.NewMessage(pattern='/getparallel'))
        async def get_parallel(event):
            """Show current number of parallel accounts"""
            if not await self.is_admin(event.sender_id): return
            
            # NEW: Используем новые статусы
            active_count = sum(1 for d in self.accounts_data.values() if d.get('status') == ACCOUNT_STATUS_ACTIVE)
            actual_parallel = min(active_count, self.max_parallel_accounts)
            
            text = f"📊 **НАСТРОЙКИ ПАРАЛЛЕЛЬНОЙ РАБОТЫ:**\n\n"
            text += f"⚙️ Установлено: {self.max_parallel_accounts} аккаунтов\n"
            text += f"✅ Активных аккаунтов: {active_count}\n"
            text += f"🚀 Реально работает: {actual_parallel} аккаунтов\n\n"
            
            if actual_parallel < self.max_parallel_accounts:
                text += f"💡 Для использования {self.max_parallel_accounts} аккаунтов нужно иметь минимум {self.max_parallel_accounts} активных"
            
            await event.respond(text)
        
        # ============= NEW RATE LIMITING COMMANDS =============
        @self.bot_client.on(events.NewMessage(pattern='/setratelimit'))
        async def set_rate_limit(event):
            """Set messages per hour limit for each account"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                limit = int(event.text.split(maxsplit=1)[1])
                if limit < MIN_MESSAGES_PER_HOUR or limit > MAX_MESSAGES_PER_HOUR:
                    await event.respond(
                        f"❌ Лимит должен быть от {MIN_MESSAGES_PER_HOUR} до {MAX_MESSAGES_PER_HOUR} сообщений/час\n\n"
                        f"📊 Рекомендации:\n"
                        f"• 20 msg/h - максимально безопасно (по умолчанию)\n"
                        f"• 30 msg/h - средний режим\n"
                        f"• 40 msg/h - агрессивный режим (риск флуда)"
                    )
                    return
                
                self.messages_per_hour = limit
                # Сохраняем в конфиг
                self.save_config_value('speed', limit)
                
                await event.respond(
                    f"✅ Лимит установлен: **{limit} сообщений/час** на аккаунт\n\n"
                    f"⏱️ Это означает ~{3600 // limit} секунд между сообщениями\n"
                    f"⚠️ Изменения применяются немедленно ко всем активным аккаунтам\n"
                    f"💾 Настройка сохранена в config.json"
                )
                logger.info(f"Rate limit set to {limit} messages/hour")
            except (IndexError, ValueError):
                await event.respond(
                    f"Формат: `/setratelimit 20`\n\n"
                    f"Диапазон: {MIN_MESSAGES_PER_HOUR}-{MAX_MESSAGES_PER_HOUR} сообщений/час\n"
                    f"Текущий лимит: {self.messages_per_hour} msg/h"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/getratelimit'))
        async def get_rate_limit(event):
            """Show current rate limit settings"""
            if not await self.is_admin(event.sender_id): return
            
            avg_interval = 3600 // self.messages_per_hour if self.messages_per_hour > 0 else 0
            
            text = f"⚡ **ЛИМИТЫ СКОРОСТИ:**\n\n"
            text += f"📊 Лимит: **{self.messages_per_hour} сообщений/час** на аккаунт\n"
            text += f"⏱️ Средний интервал: ~{avg_interval} сек между сообщениями\n"
            text += f"🛡️ **Защита от спама:**\n"
            text += f"   • Интервал между своими аккаунтами: {MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS}-{MAX_INTERVAL_BETWEEN_OWN_ACCOUNTS} сек (случайный)\n"
            text += f"   • Горячие каналы (с FloodWait): избегаем 2 часа\n\n"
            text += f"💡 Диапазон: {MIN_MESSAGES_PER_HOUR}-{MAX_MESSAGES_PER_HOUR} msg/h"
            
            await event.respond(text)
        

        # ============= NEW: WORKER MODE & CYCLES COMMANDS =============
        @self.bot_client.on(events.NewMessage(pattern='/setworkermode'))
        async def set_worker_mode(event):
            """Set worker mode: cyclic or distributed"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                mode = event.text.split(maxsplit=1)[1].lower()
                if mode not in ['cyclic', 'distributed']:
                    await event.respond(
                        "❌ Режим должен быть: `cyclic` или `distributed`\n\n"
                        "🔄 **CYCLIC** - каждый аккаунт проходит ВСЕ каналы\n"
                        "   • Для тестов и 5-20 каналов\n"
                        "   • Предсказуемое поведение\n\n"
                        "📊 **DISTRIBUTED** - каналы делятся между аккаунтами\n"
                        "   • Для продакшна с 50+ каналами\n"
                        "   • Быстрая обработка больших списков"
                    )
                    return
                
                self.worker_mode = mode
                # Сохраняем в конфиг
                self.save_config_value('worker_mode', mode)
                
                await event.respond(
                    f"✅ Режим установлен: **{mode.upper()}**\n\n"
                    f"{'🔄' if mode == 'cyclic' else '📊'} "
                    f"{'Каждый аккаунт проходит ВСЕ каналы' if mode == 'cyclic' else 'Каналы делятся между аккаунтами'}\n"
                    f"⚠️ Изменения вступят в силу после перезапуска (`/stopmon` → `/startmon`)\n"
                    f"💾 Настройка сохранена в config.json"
                )
                logger.info(f"Worker mode set to: {mode}")
            except (IndexError, ValueError):
                await event.respond(
                    f"Формат: `/setworkermode distributed` или `/setworkermode cyclic`\n\n"
                    f"Текущий режим: **{self.worker_mode}**"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/setmaxcycles'))
        async def set_max_cycles(event):
            """Set maximum cycles per worker before rotation"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                cycles = int(event.text.split(maxsplit=1)[1])
                if cycles < 0 or cycles > 100:
                    await event.respond("❌ Количество циклов должно быть от 0 до 100\n\n0 = бесконечно")
                    return
                
                self.max_cycles_per_worker = cycles
                # Сохраняем в конфиг
                self.save_config_value('max_cycles_per_worker', cycles)
                
                if cycles == 0:
                    await event.respond(
                        f"✅ Воркеры будут работать **бесконечно**\n\n"
                        f"🔄 Циклы не ограничены\n"
                        f"⚠️ Ротация аккаунтов отключена\n"
                        f"💾 Настройка сохранена в config.json"
                    )
                else:
                    await event.respond(
                        f"✅ Максимум циклов: **{cycles}**\n\n"
                        f"🔄 Каждый воркер отработает {cycles} циклов\n"
                        f"🔄 Потом уйдёт в резерв (если есть резервные)\n"
                        f"⚠️ Изменения вступят в силу после перезапуска\n"
                        f"💾 Настройка сохранена в config.json"
                    )
                logger.info(f"Max cycles per worker set to: {cycles}")
            except (IndexError, ValueError):
                await event.respond(
                    f"Формат: `/setmaxcycles 3`\n\n"
                    f"Текущее значение: **{self.max_cycles_per_worker}** (0=бесконечно)"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/getworkersettings'))
        async def get_worker_settings(event):
            """Show all worker settings"""
            if not await self.is_admin(event.sender_id): return
            
            active_count = sum(1 for d in self.accounts_data.values() if d.get('status') == ACCOUNT_STATUS_ACTIVE)
            
            text = f"⚙️ **НАСТРОЙКИ ВОРКЕРОВ:**\n\n"
            
            text += f"📊 **Режим:** {self.worker_mode.upper()}\n"
            if self.worker_mode == 'cyclic':
                text += f"   • Каждый аккаунт проходит ВСЕ каналы\n"
                text += f"   • Идеально для 5-20 каналов\n"
            else:
                text += f"   • Каналы делятся между аккаунтами\n"
                text += f"   • Оптимально для 50+ каналов\n"
            
            text += f"\n🔄 **Макс циклов:** {self.max_cycles_per_worker if self.max_cycles_per_worker > 0 else 'бесконечно'}\n"
            if self.max_cycles_per_worker > 0:
                text += f"   • Каждый воркер = {self.max_cycles_per_worker} циклов\n"
                text += f"   • Потом уходит в резерв\n"
            else:
                text += f"   • Ротация отключена\n"
            
            text += f"\n🚀 **Параллельность:** {self.max_parallel_accounts}\n"
            text += f"✅ **Активных:** {active_count}\n"
            text += f"⚡ **Скорость:** {self.messages_per_hour} msg/h\n"
            
            text += f"\n📊 **Каналов:** {len(self.channels)}\n"
            if self.worker_mode == 'distributed' and active_count > 0:
                channels_per_worker = len(self.channels) // min(active_count, self.max_parallel_accounts)
                text += f"   • На воркер: ~{channels_per_worker}\n"
            
            text += f"\n📄 **Команды:**\n"
            text += f"`/setworkermode distributed` - для 100+ каналов\n"
            text += f"`/setworkermode cyclic` - для тестов\n"
            text += f"`/setmaxcycles 3` - лимит циклов (0=∞)\n"
            text += f"`/setparallel 2` - кол-во воркеров\n"
            text += f"`/togglerecovery` - вкл/выкл автовосстановление"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/togglerecovery'))
        async def toggle_recovery(event):
            """Toggle automatic worker recovery"""
            if not await self.is_admin(event.sender_id): return
            
            self.worker_recovery_enabled = not self.worker_recovery_enabled
            # Сохраняем в конфиг
            self.save_config_value('worker_recovery_enabled', self.worker_recovery_enabled)
            
            status = "✅ Включено" if self.worker_recovery_enabled else "❌ Выключено"
            
            await event.respond(
                f"🔄 **Автовосстановление воркеров:** {status}\n\n"
                f"{'📌 Система автоматически перезапустится при замене аккаунта' if self.worker_recovery_enabled else '⚠️ Требуется ручной перезапуск после бана'}\n\n"
                f"💡 Health check проверяет воркеры каждые 2 минуты\n"
                f"💾 Настройка сохранена в config.json"
            )
            logger.info(f"Worker recovery {'enabled' if self.worker_recovery_enabled else 'disabled'}")
        
        @self.bot_client.on(events.NewMessage(pattern='/config'))
        async def show_config(event):
            """Показать текущую конфигурацию бота"""
            if not await self.is_admin(event.sender_id): return
            
            active_count = sum(1 for d in self.accounts_data.values() if d.get('status') == ACCOUNT_STATUS_ACTIVE)
            
            text = "⚙️ **ТЕКУЩАЯ КОНФИГУРАЦИЯ БОТА:**\n\n"
            
            # Основные настройки
            text += "📊 **ОСНОВНЫЕ НАСТРОЙКИ:**\n"
            text += f"  • Скорость: `{self.messages_per_hour}` комм/час на аккаунт\n"
            text += f"  • Параллельность: `{self.max_parallel_accounts}` аккаунтов\n"
            text += f"  • Ротация: `{self.rotation_interval}` сек ({self.rotation_interval // 3600}ч)\n\n"
            
            # Режим воркеров
            text += "🔄 **РЕЖИМ ВОРКЕРОВ:**\n"
            text += f"  • Режим: `{self.worker_mode}`\n"
            text += f"  • Макс циклов: `{self.max_cycles_per_worker if self.max_cycles_per_worker > 0 else '∞'}`\n"
            text += f"  • Автовосстановление: `{'✅ Вкл' if self.worker_recovery_enabled else '❌ Выкл'}`\n\n"
            
            # Тестовый режим
            text += "🧪 **ТЕСТОВЫЙ РЕЖИМ:**\n"
            text += f"  • Статус: `{'🟢 Включен' if self.test_mode else '🔴 Выключен'}`\n"
            if self.test_mode:
                text += f"  • Тест-каналы: `{len(self.test_channels)}`\n"
                text += f"  • Лимит: `{self.test_mode_speed_limit}` комм/час\n"
            text += "\n"
            
            # Аккаунты
            text += "👥 **АККАУНТЫ:**\n"
            text += f"  • Активных: `{active_count}` / `{self.max_parallel_accounts}`\n"
            text += f"  • Всего: `{len(self.accounts_data)}`\n"
            if self.config.get('active_accounts'):
                text += f"  • В конфиге: `{len(self.config['active_accounts'])}`\n"
            text += "\n"
            
            # Данные
            text += "📁 **ДАННЫЕ:**\n"
            text += f"  • Каналов: `{len(self.channels)}`\n"
            text += f"  • Шаблонов: `{len(self.templates)}`\n"
            text += f"  • Админов: `{len(self.admins)}`\n\n"
            
            # Информация о файлах
            import os
            config_exists = os.path.exists('config.json')
            bot_data_exists = os.path.exists('bot_data.json')
            
            text += "💾 **ФАЙЛЫ:**\n"
            text += f"  • config.json: `{'✅ Есть' if config_exists else '❌ Нет'}`\n"
            text += f"  • bot_data.json: `{'✅ Есть' if bot_data_exists else '❌ Нет'}`\n"
            
            if self.config.get('last_updated'):
                from datetime import datetime
                try:
                    updated = datetime.fromisoformat(self.config['last_updated'])
                    text += f"  • Обновлен: `{updated.strftime('%d.%m.%Y %H:%M')}`\n"
                except:
                    pass
            
            text += f"\n💡 Версия конфига: `{self.config.get('version', '1.0')}`"
            
            await event.respond(text)
        
        # ============= END NEW COMMANDS =============

        @self.bot_client.on(events.NewMessage(pattern='/setrotation'))
        async def set_rotation_interval(event):
            """Set account rotation interval in seconds"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                interval = int(event.text.split(maxsplit=1)[1])
                if interval < 3600:  # Minimum 1 hour
                    await event.respond(
                        "❌ Интервал не может быть меньше 1 часа (3600 секунд)\n\n"
                        "📊 Рекомендации:\n"
                        "• 14400 сек (4 часа) - по умолчанию\n"
                        "• 21600 сек (6 часов) - средний\n"
                        "• 28800 сек (8 часов) - долгий"
                    )
                    return
                
                self.rotation_interval = interval
                # Сохраняем в конфиг
                self.save_config_value('rotation_interval', interval)
                
                hours = interval // 3600
                await event.respond(
                    f"✅ Интервал ротации установлен: **{interval} секунд** ({hours}ч)\n\n"
                    f"🔄 Следующая ротация через ~{hours}ч\n"
                    f"⚠️ Изменения применяются немедленно\n"
                    f"💾 Настройка сохранена в config.json"
                )
                logger.info(f"Rotation interval set to {interval} seconds ({hours}h)")
            except (IndexError, ValueError):
                current_hours = self.rotation_interval // 3600
                await event.respond(
                    f"Формат: `/setrotation 14400`\n\n"
                    f"Текущий интервал: {self.rotation_interval} сек ({current_hours}ч)\n"
                    f"Минимум: 3600 сек (1ч)"
                )
        
        @self.bot_client.on(events.NewMessage(pattern='/getrotation'))
        async def get_rotation_info(event):
            """Show rotation interval and status"""
            if not await self.is_admin(event.sender_id): return
            
            hours = self.rotation_interval // 3600
            
            text = f"🔄 **РОТАЦИЯ АККАУНТОВ:**\n\n"
            text += f"⚙️ Интервал: **{self.rotation_interval} сек** ({hours}ч)\n"
            
            if self.last_rotation_time:
                from datetime import datetime
                last_rot = datetime.fromtimestamp(self.last_rotation_time)
                time_since = datetime.now().timestamp() - self.last_rotation_time
                time_until = self.rotation_interval - time_since
                
                text += f"🕐 Последняя ротация: {last_rot.strftime('%H:%M:%S')}\n"
                text += f"⏳ Прошло: {int(time_since // 60)} мин\n"
                
                if time_until > 0:
                    text += f"⏰ Следующая через: {int(time_until // 60)} мин\n"
                else:
                    text += f"⚠️ Ротация просрочена на {int(-time_until // 60)} мин\n"
            else:
                text += f"❌ Ротация еще не выполнялась\n"
            
            text += f"\n💡 Используйте `/rotatenow` для немедленной ротации"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/rotatenow'))
        async def rotate_now(event):
            """Perform account rotation immediately"""
            if not await self.is_admin(event.sender_id): return
            
            await event.respond("🔄 Выполняю ротацию аккаунтов...")
            await self.rotate_accounts()
            await event.respond("✅ Ротация выполнена успешно!")
        
        @self.bot_client.on(events.NewMessage(pattern='/accountstats'))
        async def account_stats(event):
            """Show detailed account activity statistics"""
            if not await self.is_admin(event.sender_id): return
            
            text = f"📊 **СТАТИСТИКА АКТИВНОСТИ АККАУНТОВ:**\n\n"
            
            active_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE]
            
            if not active_accounts:
                text += "❌ Нет активных аккаунтов\n"
            else:
                for phone, data in active_accounts:
                    name = data.get('name', phone)
                    
                    if phone in self.account_activity:
                        activity = self.account_activity[phone]
                        msgs_last_hour = len(activity['messages'])
                        
                        can_send, wait_time = self.can_account_send_message(phone)
                        status_icon = "✅" if can_send else "⏳"
                        
                        text += f"{status_icon} **{name}**\n"
                        text += f"   📱 `{phone}`\n"
                        text += f"   💬 {msgs_last_hour}/{self.messages_per_hour} сообщений за час\n"
                        
                        if not can_send:
                            text += f"   ⏱️ Ожидание: {wait_time // 60} мин {wait_time % 60} сек\n"
                        
                        text += "\n"
                    else:
                        text += f"⚪ **{name}** - нет активности\n\n"
            
            text += f"\n📈 Лимит: {self.messages_per_hour} msg/h на аккаунт"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/incidents'))
        async def incidents_command(event):
            """Показать историю инцидентов (FloodWait, баны) для аккаунта"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split()
                if len(parts) < 2:
                    await event.respond("❌ Формат: `/incidents +79123456789` или `/incidents all`")
                    return
                
                if parts[1].lower() == 'all':
                    # Показываем статистику по всем аккаунтам
                    text = "🚨 **ИСТОРИЯ ИНЦИДЕНТОВ (ВСЕ АККАУНТЫ):**\n\n"
                    
                    if not self.account_incidents:
                        text += "✅ Нет зарегистрированных инцидентов"
                    else:
                        for phone, incidents in sorted(self.account_incidents.items(), key=lambda x: len(x[1]), reverse=True):
                            name = self.accounts_data.get(phone, {}).get('name', phone[-4:])
                            text += f"📱 **{name}** (`{phone[-4:]}`): {len(incidents)} инцидентов\n"
                    
                    await event.respond(text)
                    return
                
                # Показываем инциденты конкретного аккаунта
                phone = parts[1].strip()
                
                if phone not in self.accounts_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                account_name = self.accounts_data[phone].get('name', phone[-4:])
                incidents = self.account_incidents.get(phone, [])
                
                text = f"🚨 **ИСТОРИЯ ИНЦИДЕНТОВ**\n"
                text += f"📱 Аккаунт: **{account_name}** (`{phone[-4:]}`)\n"
                text += f"📊 Всего инцидентов: {len(incidents)}\n\n"
                
                if not incidents:
                    text += "✅ Нет зарегистрированных инцидентов"
                else:
                    # Показываем последние 20 инцидентов
                    recent_incidents = incidents[-20:]
                    
                    for idx, incident in enumerate(reversed(recent_incidents), 1):
                        timestamp = incident['timestamp']
                        dt = datetime.fromtimestamp(timestamp)
                        time_str = dt.strftime('%d.%m %H:%M')
                        
                        channel = incident['channel']
                        reason = incident['reason']
                        wait_sec = incident.get('wait_seconds', 0)
                        action = incident.get('action_taken', '')
                        
                        text += f"{idx}. **{time_str}** - `@{channel}`\n"
                        text += f"   ⚠️ {reason}\n"
                        
                        if wait_sec > 0:
                            wait_min = wait_sec // 60
                            text += f"   ⏱️ Ожидание: {wait_min}м {wait_sec % 60}с\n"
                        
                        if action:
                            action_text = {
                                'marked_hot': '🔥 Канал помечен HOT',
                                'worker_stopped': '⛔ Воркер остановлен',
                                'marked_broken': '🔴 Аккаунт помечен BROKEN'
                            }.get(action, action)
                            text += f"   🔧 Действие: {action_text}\n"
                        
                        text += "\n"
                    
                    if len(incidents) > 20:
                        text += f"_(Показаны последние 20 из {len(incidents)})_\n\n"
                    
                    # Статистика
                    floodwaits = sum(1 for i in incidents if 'FloodWait' in i['reason'])
                    bans = sum(1 for i in incidents if 'banned' in i['reason'].lower())
                    
                    text += f"📊 **Статистика:**\n"
                    text += f"  • FloodWait: {floodwaits}\n"
                    text += f"  • Баны: {bans}\n"
                
                await event.respond(text)
                
            except Exception as e:
                logger.error(f"Incidents command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)}")
        
        @self.bot_client.on(events.NewMessage(pattern='/checkspam'))
        async def checkspam_command(event):
            """Проверить статус ограничений через @SpamBot"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                parts = event.text.split()
                if len(parts) < 2:
                    await event.respond(
                        "❌ Формат: `/checkspam +79123456789` или `/checkspam all`\n\n"
                        "Проверяет статус ограничений аккаунта через @SpamBot"
                    )
                    return
                
                if parts[1].lower() == 'all':
                    # Проверяем все BROKEN аккаунты
                    broken_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                                     if data.get('status') == ACCOUNT_STATUS_BROKEN and data.get('session')]
                    
                    if not broken_accounts:
                        await event.respond("✅ Нет аккаунтов со статусом BROKEN")
                        return
                    
                    await event.respond(f"🔍 Проверяю {len(broken_accounts)} broken аккаунтов через @SpamBot...")
                    
                    for phone, data in broken_accounts:
                        name = data.get('name', phone[-4:])
                        await event.respond(f"📱 Проверяю **{name}**...")
                        
                        spam_status = await self.check_spam_status(phone, data)
                        await event.respond(spam_status)
                        
                        await asyncio.sleep(2)  # Задержка между проверками
                    
                    return
                
                # Проверяем конкретный аккаунт
                phone = parts[1].strip()
                
                if phone not in self.accounts_data:
                    await event.respond(f"❌ Аккаунт `{phone}` не найден")
                    return
                
                data = self.accounts_data[phone]
                if not data.get('session'):
                    await event.respond(f"❌ Аккаунт `{phone}` не авторизован")
                    return
                
                name = data.get('name', phone[-4:])
                await event.respond(f"🔍 Проверяю **{name}** через @SpamBot...")
                
                spam_status = await self.check_spam_status(phone, data)
                await event.respond(spam_status)
                
            except Exception as e:
                logger.error(f"Checkspam command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)}")
        
        # ============= END NEW COMMANDS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/addchannel'))
        async def add_channel(event):
            if not await self.is_admin(event.sender_id):
                logger.info(f"Unauthorized access attempt from {event.sender_id}")
                return
            try:
                # Извлекаем текст после команды
                text_parts = event.text.split(maxsplit=1)
                if len(text_parts) < 2:
                    await event.respond("❌ Формат: `/addchannel @username1 @username2 ...`")
                    return
                
                channels_text = text_parts[1]
                # Разделяем по пробелам и переносам строк
                usernames = channels_text.replace('\n', ' ').split()
                
                # Обрабатываем каждый канал
                added = []
                already_exist = []
                errors = []
                
                existing_usernames = [ch.get('username') if isinstance(ch, dict) else ch for ch in self.channels]
                
                for username in usernames:
                    username = username.strip()
                    if not username:
                        continue
                    
                    # Ensure @ prefix for consistency
                    if not username.startswith('@'):
                        username = '@' + username
                    
                    logger.info(f"Trying to add channel: {username}")
                    
                    # Check if channel already exists
                    if username not in existing_usernames:
                        self.channels.append({'username': username})
                        existing_usernames.append(username)  # Обновляем локальный список
                        
                        # Также добавляем в таблицу parsed_channels для статистики
                        if self.conn:
                            try:
                                cursor = self.conn.cursor()
                                cursor.execute(
                                    """INSERT OR IGNORE INTO parsed_channels 
                                    (username, theme, source, added_date, admin_id) 
                                    VALUES (?, ?, ?, ?, ?)""",
                                    (username, 'manual', 'addchannel', datetime.now().isoformat(), event.sender_id)
                                )
                                self.conn.commit()
                                logger.info(f"Channel {username} added to parsed_channels table")
                            except Exception as db_err:
                                logger.warning(f"Failed to add to parsed_channels table: {db_err}")
                        
                        logger.info(f"Channel {username} added successfully")
                        added.append(username)
                    else:
                        logger.info(f"Channel {username} already exists")
                        already_exist.append(username)
                
                # Сохраняем данные один раз после всех добавлений
                if added:
                    self.save_data()
                
                # Формируем ответ
                response_parts = []
                if added:
                    response_parts.append(f"✅ Добавлено каналов: {len(added)}\n" + "\n".join(f"  • `{ch}`" for ch in added))
                if already_exist:
                    response_parts.append(f"⚠️ Уже существуют: {len(already_exist)}\n" + "\n".join(f"  • `{ch}`" for ch in already_exist))
                if not added and not already_exist:
                    response_parts.append("❌ Не удалось добавить ни одного канала")
                
                await event.respond("\n\n".join(response_parts))
                
            except Exception as e:
                logger.error(f"Error adding channel: {e}")
                await event.respond("❌ Формат: `/addchannel @username1 @username2 ...`")
        
        @self.bot_client.on(events.NewMessage(pattern='/syncchannels'))
        async def sync_channels(event):
            """Синхронизирует каналы из bot_data.json с таблицей parsed_channels"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                if not self.conn:
                    await event.respond("❌ База данных недоступна")
                    return
                
                synced = 0
                cursor = self.conn.cursor()
                
                for ch in self.channels:
                    username = ch.get('username') if isinstance(ch, dict) else ch
                    if username:
                        try:
                            cursor.execute(
                                """INSERT OR IGNORE INTO parsed_channels 
                                (username, theme, source, added_date, admin_id) 
                                VALUES (?, ?, ?, ?, ?)""",
                                (username, 'manual', 'sync', datetime.now().isoformat(), event.sender_id)
                            )
                            if cursor.rowcount > 0:
                                synced += 1
                        except Exception as e:
                            logger.error(f"Error syncing channel {username}: {e}")
                
                self.conn.commit()
                
                # Подсчёт каналов в БД
                cursor.execute("SELECT COUNT(*) FROM parsed_channels")
                total_in_db = cursor.fetchone()[0]
                
                await event.respond(
                    f"✅ **Синхронизация завершена:**\n\n"
                    f"📊 Каналов в памяти: `{len(self.channels)}`\n"
                    f"📊 Каналов в БД: `{total_in_db}`\n"
                    f"➕ Добавлено новых: `{synced}`\n\n"
                    f"💡 Теперь статистика `/stats` будет показывать корректные данные"
                )
                
            except Exception as e:
                logger.error(f"Error syncing channels: {e}")
                await event.respond(f"❌ Ошибка синхронизации: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/searchchannels (.+)'))
        async def search_channels(event):
            if not await self.is_admin(event.sender_id): return
            try:
                query = event.pattern_match.group(1).strip()
                await event.respond(f"🔍 Ищу каналы по '{query}'...")
                
                # Use user account instead of bot (bots can't search)
                logger.info(f"🔍 /searchchannels: ищем аккаунт с сессией для поиска...")
                user_account = None
                for phone, data in self.accounts_data.items():
                    if data.get('session'):
                        user_account = (phone, data)
                        logger.info(f"   ✅ Найден аккаунт с сессией: {phone}")
                        break
                
                if not user_account:
                    logger.warning("   ⚠️ Нет аккаунтов с сохранённой session-строкой")
                    await event.respond(
                        "ℹ️ Для поиска каналов нужен хотя бы один аккаунт с активной сессией\n\n"
                        f"📊 Всего аккаунтов: {len(self.accounts_data)}\n"
                        "❌ С сессиями: 0\n\n"
                        "💡 Используйте `/auth +номер` для авторизации аккаунта"
                    )
                    return
                
                phone, account_data = user_account
                client = TelegramClient(StringSession(account_data['session']), API_ID, API_HASH, proxy=account_data.get('proxy'))
                
                try:
                    await client.connect()
                    if not await client.is_user_authorized():
                        await event.respond(f"❌ Аккаунт {phone} не авторизован")
                        await client.disconnect()
                        return
                    
                    result = await client(functions.contacts.SearchRequest(q=query, limit=50))
                    channels = []
                    for chat in result.chats:
                        if hasattr(chat, 'username') and chat.username and chat.username.strip():
                            channels.append(chat.username)
                    
                    if channels:
                        msg = f"✅ Найдено {len(channels)} каналов по '{query}':\n\n"
                        for i, ch in enumerate(channels[:15], 1):
                            msg += f"{i}. @{ch}\n"
                        
                        if len(channels) > 15:
                            msg += f"\n... и еще {len(channels)-15}"
                        
                        msg += f"\n\n💡 Используйте:\n"
                        msg += f"`/addparsed {query} 10` - добавить 10 каналов в работу\n"
                        msg += f"`/addparsed {query} all` - добавить все каналы"
                        
                        await event.respond(msg)
                        
                        # Save to parsed_channels database
                        if self.conn:
                            cursor = self.conn.cursor()
                            added_count = 0
                            for ch in channels:
                                try:
                                    # Add @ prefix to channel username
                                    ch_with_at = ch if ch.startswith('@') else '@' + ch
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO parsed_channels (username, theme, source, added_date) VALUES (?, ?, ?, ?)",
                                        (ch_with_at, query, 'search', datetime.now().isoformat())
                                    )
                                    if cursor.rowcount > 0:
                                        added_count += 1
                                except Exception as e:
                                    logger.error(f"DB insert error: {e}")
                            self.conn.commit()
                            await event.respond(f"💾 Сохранено {added_count} новых каналов в БД\n\nИспользуйте `/addparsed {query} 10` чтобы добавить их в работу")
                    else:
                        await event.respond("❌ Каналы не найдены")
                except Exception as e:
                    logger.error(f"Search error: {e}")
                    await event.respond(f"❌ Ошибка поиска: {str(e)[:100]}")
                finally:
                    try:
                        await client.disconnect()
                    except:
                        pass
            except Exception as outer_e:
                logger.error(f"Outer search error: {outer_e}")
                await event.respond("Формат: `/searchchannels новости`")
        
        @self.bot_client.on(events.NewMessage(pattern='/addparsed'))
        async def add_parsed(event):
            """Add parsed channels from database to active channel list"""
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                parts = event.text.split()
                if len(parts) < 2:
                    await event.respond("Формат: `/addparsed [тема] [количество|all]`\n\nПример:\n`/addparsed новости 10` - добавить 10 каналов\n`/addparsed all 20` - добавить 20 из всех тем\n`/addparsed новости all` - добавить все каналы темы")
                    return
                
                theme = parts[1]
                limit = parts[2] if len(parts) > 2 else "10"
                
                cursor = self.conn.cursor()
                
                # Get parsed channels
                if theme.lower() == 'all':
                    cursor.execute("SELECT username FROM parsed_channels")
                else:
                    cursor.execute("SELECT username FROM parsed_channels WHERE theme LIKE ?", (f"%{theme}%",))
                
                parsed = cursor.fetchall()
                
                if not parsed:
                    await event.respond(f"❌ Нет спарсенных каналов по теме '{theme}'\n\nИспользуйте `/listparsed` для просмотра всех")
                    return
                
                # Determine how many to add
                if limit.lower() == 'all':
                    channels_to_add = [p[0] for p in parsed]
                else:
                    try:
                        count = int(limit)
                        channels_to_add = [p[0] for p in parsed[:count]]
                    except ValueError:
                        await event.respond("❌ Неверное количество. Используйте число или 'all'")
                        return
                
                # Get existing channel usernames
                existing = {ch.get('username') if isinstance(ch, dict) else ch for ch in self.channels}
                
                # Add new channels
                added = 0
                for username in channels_to_add:
                    if username not in existing:
                        self.channels.append({'username': username})
                        added += 1
                
                self.save_data()
                
                msg = f"✅ Добавлено каналов: {added}\n"
                msg += f"📊 Всего каналов теперь: {len(self.channels)}\n\n"
                
                if added > 0:
                    msg += f"💡 Новые каналы:\n"
                    for i, username in enumerate([u for u in channels_to_add if u not in existing][:10], 1):
                        # Display with @ (add if not present)
                        display_name = username if username.startswith('@') else '@' + username
                        msg += f"{i}. {display_name}\n"
                    if added > 10:
                        msg += f"... и еще {added - 10}\n"
                
                await event.respond(msg)
                
            except Exception as e:
                logger.error(f"Add parsed error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/findchannels'))
        async def find_channels(event):
            """Find channels with 50k+ subscribers and open comments"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                # Parse command: /findchannels @channel1 @channel2 @channel3
                text_parts = event.text.split()
                
                if len(text_parts) < 2:
                    await event.respond(
                        "**🔍 ПОИСК ПОДХОДЯЩИХ КАНАЛОВ**\n\n"
                        "Формат: `/findchannels @channel1 @channel2 @channel3 ...`\n\n"
                        "**Критерии поиска:**\n"
                        "✅ От 50,000 подписчиков\n"
                        "✅ Публичные каналы (без вступления)\n"
                        "✅ Открытые комментарии\n\n"
                        "**Пример:**\n"
                        "`/findchannels @durov @telegram @channel`"
                    )
                    return
                
                # Extract channel usernames
                channels_to_check = [ch.strip() for ch in text_parts[1:]]
                
                if not channels_to_check:
                    await event.respond("❌ Укажите хотя бы один канал для проверки")
                    return
                
                # Get active account
                user_account = None
                for phone, data in self.accounts_data.items():
                    if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session'):
                        user_account = (phone, data)
                        break
                
                if not user_account:
                    await event.respond("❌ Нет активных аккаунтов для проверки каналов")
                    return
                
                phone, account_data = user_account
                
                await event.respond(
                    f"🔍 Начинаю проверку {len(channels_to_check)} каналов...\n"
                    f"Используется аккаунт: {account_data.get('name', phone)}\n\n"
                    f"⏳ Это может занять несколько минут..."
                )
                
                # Create client
                client = TelegramClient(StringSession(account_data['session']), API_ID, API_HASH, proxy=account_data.get('proxy'))
                
                try:
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        await event.respond("❌ Аккаунт не авторизован")
                        return
                    
                    found_channels = []
                    
                    for i, channel_username in enumerate(channels_to_check, 1):
                        try:
                            # Get channel entity
                            entity = await client.get_entity(channel_username)
                            
                            # Check if it's a channel
                            from telethon.tl.types import Channel
                            if not isinstance(entity, Channel):
                                logger.info(f"❌ {channel_username}: не является каналом")
                                continue
                            
                            # Check subscribers
                            participants_count = getattr(entity, 'participants_count', 0)
                            
                            if participants_count < 50000:
                                logger.info(f"❌ {channel_username}: только {participants_count} подписчиков")
                                continue
                            
                            # Check if public
                            if entity.broadcast and not entity.megagroup:
                                join_request = getattr(entity, 'join_request', False)
                                
                                if join_request:
                                    logger.info(f"❌ {channel_username}: требуется заявка")
                                    continue
                                
                                # Check comments
                                messages = await client.get_messages(entity, limit=5)
                                
                                has_comments = False
                                for msg in messages:
                                    if hasattr(msg, 'replies') and msg.replies:
                                        if hasattr(msg.replies, 'comments') and msg.replies.comments:
                                            has_comments = True
                                            break
                                
                                if has_comments:
                                    found_channels.append({
                                        'username': channel_username,
                                        'title': entity.title,
                                        'subscribers': participants_count,
                                        'link': f"https://t.me/{channel_username}"
                                    })
                                    logger.info(f"✅ {channel_username}: ПОДХОДИТ!")
                                else:
                                    logger.info(f"❌ {channel_username}: комментарии недоступны")
                            
                        except Exception as e:
                            logger.error(f"❌ {channel_username}: ошибка - {e}")
                        
                        # Delay between checks
                        await asyncio.sleep(2)
                        
                        # Progress update every 5 channels
                        if i % 5 == 0:
                            await event.respond(f"⏳ Проверено {i}/{len(channels_to_check)}...")
                    
                    # Send results
                    if found_channels:
                        result_text = f"✅ **НАЙДЕНО ПОДХОДЯЩИХ КАНАЛОВ: {len(found_channels)}**\n\n"
                        
                        for i, ch in enumerate(found_channels, 1):
                            result_text += f"{i}. **@{ch['username']}**\n"
                            result_text += f"   {ch['title']}\n"
                            result_text += f"   👥 {ch['subscribers']:,} подписчиков\n"
                            result_text += f"   🔗 {ch['link']}\n\n"
                        
                        result_text += "\n📋 **СПИСОК ДЛЯ КОПИРОВАНИЯ:**\n"
                        for ch in found_channels:
                            result_text += f"@{ch['username']}\n"
                        
                        await event.respond(result_text)
                    else:
                        await event.respond(
                            f"❌ Из {len(channels_to_check)} проверенных каналов не найдено ни одного подходящего.\n\n"
                            f"**Возможные причины:**\n"
                            f"• Менее 50,000 подписчиков\n"
                            f"• Комментарии отключены\n"
                            f"• Требуется вступление в канал\n"
                            f"• Канал приватный"
                        )
                
                finally:
                    await client.disconnect()
                    
            except Exception as e:
                logger.error(f"Find channels error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listchannels'))
        async def list_channels(event):
            if not await self.is_admin(event.sender_id): return
            if not self.channels:
                await event.respond("Нет каналов")
                return
            
            # Show all channels, split into multiple messages if needed
            total = len(self.channels)
            channels_per_msg = 50
            
            for batch_num in range(0, total, channels_per_msg):
                batch_channels = self.channels[batch_num:batch_num + channels_per_msg]
                text = f"КАНАЛЫ ({total}) - Часть {batch_num//channels_per_msg + 1}:\n\n"
                
                for i, ch in enumerate(batch_channels, batch_num + 1):
                    username = ch.get('username') if isinstance(ch, dict) else ch
                    # Display with @ (add if not present)
                    display_name = username if username.startswith('@') else '@' + username
                    text += f"{i}. `{display_name}`\n"
                
                await event.respond(text)
                # Small delay between messages to avoid flood
                if batch_num + channels_per_msg < total:
                    await asyncio.sleep(0.5)
        
        @self.bot_client.on(events.NewMessage(pattern='/delchannel'))
        async def del_channel(event):
            if not await self.is_admin(event.sender_id): return
            try:
                username = event.text.split(maxsplit=1)[1]
                # Ensure @ prefix for consistency
                if not username.startswith('@'):
                    username = '@' + username
                # Remove channel from list
                initial_count = len(self.channels)
                self.channels = [ch for ch in self.channels 
                               if (ch.get('username') if isinstance(ch, dict) else ch) != username]
                removed = initial_count - len(self.channels)
                self.save_data()
                if removed > 0:
                    await event.respond(f"Удален: `{username}`")
                else:
                    await event.respond(f"Канал `{username}` не найден")
            except:
                await event.respond("Формат: `/delchannel @username`")
        
        @self.bot_client.on(events.NewMessage(pattern='/listtemplates'))
        async def list_templates(event):
            if not await self.is_admin(event.sender_id): return
            text = f"Шаблоны ({len(self.templates)})\n\n"
            for i, template in enumerate(self.templates, 1):
                text += f"{i}. `{template}`\n"
            text += "\n**/addtemplate текст**\n**/edittemplate 1 текст**"
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/addtemplate'))
        async def add_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                new_template = event.text.replace('/addtemplate ', '').strip()
                if new_template and new_template not in self.templates:
                    self.templates.append(new_template)
                    self.save_data()
                    await event.respond(f"Добавлен: `{new_template}`")
                else:
                    await event.respond("Уже есть или пусто!")
            except:
                await event.respond("Формат: `/addtemplate Крутой пост!`")
        
        @self.bot_client.on(events.NewMessage(pattern='/edittemplate'))
        async def edit_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                parts = event.text.split(maxsplit=2)
                num = int(parts[1]) - 1
                new_text = parts[2]
                if 0 <= num < len(self.templates):
                    old = self.templates[num]
                    self.templates[num] = new_text
                    self.save_data()
                    await event.respond(f"#{num+1}: `{old}` → `{new_text}`")
                else:
                    await event.respond("Неверный номер!")
            except:
                await event.respond("Формат: `/edittemplate 1 Новый текст!`")
        
        @self.bot_client.on(events.NewMessage(pattern='/del-template'))
        async def del_template(event):
            if not await self.is_admin(event.sender_id): return
            try:
                num = int(event.text.split()[1]) - 1
                if 0 <= num < len(self.templates):
                    deleted = self.templates.pop(num)
                    self.save_data()
                    await event.respond(f"Удален: `{deleted}`")
                else:
                    await event.respond("Неверный номер!")
            except:
                await event.respond("Формат: `/del-template 1`")
        
        @self.bot_client.on(events.NewMessage(pattern='/cleartemplates'))
        async def clear_templates(event):
            if not await self.is_admin(event.sender_id): return
            self.templates.clear()
            self.save_data()
            await event.respond("Все шаблоны очищены!")
        
        @self.bot_client.on(events.NewMessage(pattern='/startmon'))
        async def start_monitor(event):
            if not await self.is_admin(event.sender_id): return
            if self.monitoring:
                await event.respond("Уже запущен!")
                return
            if not self.accounts_data:
                logger.info("⚠️ /startmon: нет аккаунтов в базе")
                await event.respond("ℹ️ В системе нет аккаунтов\n\n💡 Добавьте аккаунты через `/auth +номер`")
                return
            
            # Проверяем наличие активных аккаунтов
            active_accounts = {phone: data for phone, data in self.accounts_data.items()
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE}
            
            if not active_accounts:
                logger.warning("⚠️ /startmon: нет ACTIVE аккаунтов (все reserve/broken)")
                await event.respond(
                    "⚠️ Нет активных аккаунтов для запуска мониторинга\n\n"
                    f"📊 Всего аккаунтов: {len(self.accounts_data)}\n"
                    "❌ Активных: 0\n\n"
                    "💡 Используйте `/toggleaccount +номер` для активации аккаунтов\n"
                    "💡 Или `/verify_sessions` для проверки авторизации"
                )
                return
            self.monitoring = True
            self.monitoring_start_time = datetime.now()
            
            # ============= РЕАЛЬНЫЕ ДАННЫЕ =============
            # Подсчёт аккаунтов по статусам
            active_count = sum(1 for data in self.accounts_data.values() 
                             if data.get('status') == ACCOUNT_STATUS_ACTIVE)
            reserve_count = sum(1 for data in self.accounts_data.values() 
                              if data.get('status') == ACCOUNT_STATUS_RESERVE)
            broken_count = sum(1 for data in self.accounts_data.values() 
                             if data.get('status') == ACCOUNT_STATUS_BROKEN)
            
            # Количество параллельных аккаунтов
            parallel_limit = self.max_parallel_accounts
            
            # Количество каналов (с учётом тестового режима)
            if self.test_mode and self.test_channels:
                channels_count = len(self.test_channels)
                channels_note = f" (ТЕСТОВЫЙ РЕЖИМ: {', '.join(self.test_channels[:3])}{'...' if len(self.test_channels) > 3 else ''})"
            else:
                channels_count = len(self.channels)
                channels_note = ""
            
            # Количество шаблонов
            templates_count = len(self.templates)
            
            # Расчёт задержки между комментариями
            # Интервал = 3600 секунд / лимит_сообщений_в_час
            avg_interval_sec = 3600 // self.messages_per_hour if self.messages_per_hour > 0 else 0
            avg_interval_min = avg_interval_sec // 60
            
            # Расчёт ожидаемой скорости
            # Скорость = лимит_на_аккаунт × количество_активных_аккаунтов
            expected_speed = self.messages_per_hour * active_count
            
            # Определение режима безопасности
            is_safe_mode = (
                self.messages_per_hour <= 20 and  # Лимит консервативный
                active_count <= 3 and              # Немного активных аккаунтов
                parallel_limit <= 2                # Мало параллельных работников
            )
            
            if is_safe_mode:
                mode_text = "БЕЗОПАСНЫЙ РЕЖИМ"
                mode_emoji = "🛡️"
                risk_text = "🟢 **Риск бана: НИЗКИЙ**"
            elif self.messages_per_hour > 30 or active_count > 5:
                mode_text = "АГРЕССИВНЫЙ РЕЖИМ"
                mode_emoji = "⚡"
                risk_text = "🟡 **Риск бана: СРЕДНИЙ** (рекомендуется снизить лимиты)"
            else:
                mode_text = "СТАНДАРТНЫЙ РЕЖИМ"
                mode_emoji = "⚙️"
                risk_text = "🟢 **Риск бана: НИЗКИЙ**"
            
            # Расчёт интервала ротации в часах
            rotation_hours = self.rotation_interval // 3600
            
            # Формирование сообщения
            text = f"""🚀 **АВТОКОММЕНТАРИИ ЗАПУЩЕНЫ** {mode_emoji}

📊 **КОНФИГУРАЦИЯ:**
✅ Активных аккаунтов: `{active_count}`
🔵 Резервных: `{reserve_count}`
🔴 Заблокированных: `{broken_count}`

⚡ Параллельно работают: `{parallel_limit}` аккаунтов
📢 Каналов в работе: `{channels_count}`{channels_note}
💬 Шаблонов комментариев: `{templates_count}`

⏱️ **НАСТРОЙКИ СКОРОСТИ:**
📊 Лимит: `{self.messages_per_hour}` комм/час на аккаунт
⏳ Средний интервал: ~`{avg_interval_min}` мин между комментариями
🔄 Ротация аккаунтов: каждые `{rotation_hours}` часов

📈 **ОЖИДАЕМАЯ СКОРОСТЬ:**
Максимум: `{expected_speed}` комм/час
(= {self.messages_per_hour} × {active_count} аккаунтов)

{risk_text}
🔐 Режим: **{mode_text}**"""
            
            await event.respond(text)
            
            # Start ONE worker (safe mode) - it will handle parallel accounts internally
            asyncio.create_task(self.pro_auto_comment())
            
            # Schedule auto-stop after 4 hours
            asyncio.create_task(self.auto_stop_after_4_hours(event.chat_id))
        
        @self.bot_client.on(events.NewMessage(pattern='/stopmon'))
        async def stop_monitor(event):
            if not await self.is_admin(event.sender_id): return
            self.monitoring = False
            
            # Сохраняем прогресс перед остановкой
            processed_count = len(self.commenting_progress.get('processed_channels', []))
            total_channels = len(self.channels)
            remaining = total_channels - processed_count
            
            logger.info(f"💾 Сохранение прогресса перед остановкой...")
            logger.info(f"   Обработано: {processed_count}/{total_channels} каналов")
            self.save_data()
            
            # Закрываем все клиенты аккаунтов
            if self.account_clients:
                logger.info(f"🔌 Закрытие {len(self.account_clients)} клиентов аккаунтов...")
                for phone, client in list(self.account_clients.items()):
                    try:
                        await client.disconnect()
                        logger.info(f"✅ Клиент {phone} закрыт")
                    except Exception as e:
                        logger.error(f"❌ Ошибка закрытия клиента {phone}: {e}")
                self.account_clients.clear()
                logger.info("✅ Все клиенты закрыты")
            
            progress_text = ""
            if processed_count > 0:
                progress_text = f"\n\n📊 Прогресс сохранён: {processed_count}/{total_channels} каналов\n💡 При следующем `/startmon` продолжится с оставшихся {remaining} каналов"
            
            await event.respond(f"✅ Автокомментарии остановлены{progress_text}")
        
        @self.bot_client.on(events.NewMessage(pattern='/resetprogress'))
        async def reset_progress(event):
            """Сбросить прогресс комментирования (начать с начала)"""
            if not await self.is_admin(event.sender_id): return
            
            processed_count = len(self.commenting_progress.get('processed_channels', []))
            
            if processed_count == 0:
                await event.respond("ℹ️ Прогресс пуст, нечего сбрасывать")
                return
            
            self.commenting_progress = {'processed_channels': [], 'last_update': datetime.now().timestamp()}
            self.save_data()
            
            await event.respond(
                f"✅ **Прогресс сброшен**\n\n"
                f"Было обработано: {processed_count} каналов\n"
                f"Всего каналов: {len(self.channels)}\n\n"
                f"💡 При следующем `/startmon` комментирование начнётся с начала списка"
            )
        
        @self.bot_client.on(events.NewMessage(pattern='/showprogress'))
        async def show_progress(event):
            """Показать текущий прогресс комментирования"""
            if not await self.is_admin(event.sender_id): return
            
            processed = self.commenting_progress.get('processed_channels', [])
            processed_count = len(processed)
            total = len(self.channels)
            remaining = total - processed_count
            
            if processed_count == 0:
                await event.respond(
                    "📊 **ПРОГРЕСС КОММЕНТИРОВАНИЯ**\n\n"
                    f"Обработано: 0/{total} каналов\n"
                    f"Осталось: {total} каналов\n\n"
                    "💡 Прогресс начнёт сохраняться после `/startmon`"
                )
                return
            
            percentage = int((processed_count / total) * 100) if total > 0 else 0
            last_update = self.commenting_progress.get('last_update', 0)
            time_ago = int((datetime.now().timestamp() - last_update) / 60) if last_update > 0 else 0
            
            # Показываем последние 10 обработанных каналов
            recent = processed[-10:] if len(processed) > 10 else processed
            recent_text = "\n".join([f"  • @{ch}" for ch in recent])
            
            text = f"📊 **ПРОГРЕСС КОММЕНТИРОВАНИЯ**\n\n"
            text += f"Обработано: {processed_count}/{total} каналов ({percentage}%)\n"
            text += f"Осталось: {remaining} каналов\n"
            
            if time_ago < 60:
                text += f"Обновлён: {time_ago}м назад\n\n"
            else:
                hours = time_ago // 60
                text += f"Обновлён: {hours}ч назад\n\n"
            
            if recent_text:
                text += f"📝 Последние обработанные:\n{recent_text}\n\n"
            
            text += f"🔄 `/resetprogress` - начать с начала\n"
            text += f"🚀 `/startmon` - продолжить с оставшихся"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/addbio'))
        async def add_bio(event):
            if not await self.is_admin(event.sender_id): return
            try:
                link = event.text.split(maxsplit=1)[1]
                if 't.me' in link and link not in self.bio_links:
                    self.bio_links.append(link)
                    self.save_data()
                    await event.respond(f"BIO добавлен: `{link}`")
                else:
                    await event.respond("Новая ссылка t.me!")
            except:
                await event.respond("Формат: `/addbio https://t.me/channel`")
        
        @self.bot_client.on(events.NewMessage(pattern='/setbioall'))
        async def set_bio_all(event):
            if not await self.is_admin(event.sender_id): return
            if not self.bio_links:
                await event.respond("Сначала `/addbio`!")
                return
            
            # Determine admin_id for filtering
            admin_id = self.get_admin_id(event.sender_id)
            
            # Filter accounts by admin_id
            if admin_id is None:  # Super admin - show all
                filtered_accounts = self.accounts_data
            else:  # Regular admin - show only their accounts
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == admin_id}
            
            bio_text = " | ".join(self.bio_links[:4])
            updated = 0
            
            # Update only ACTIVE accounts with sessions
            for phone, data in filtered_accounts.items():
                if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session'):
                    if await self.set_account_bio(data, bio_text):
                        updated += 1
                        logger.info(f"Bio updated via /setbioall for {phone}")
            
            await event.respond(f"BIO обновлен: `{bio_text}`\n{updated} аккаунтов")
        
        @self.bot_client.on(events.NewMessage(pattern='/stats'))
        async def show_stats(event):
            if not await self.is_admin(event.sender_id): return
            
            # Determine admin_id for filtering
            admin_id = self.get_admin_id(event.sender_id)
            
            text = "📊 **УПРАВЛЕНЧЕСКИЙ ОТЧЁТ**\n\n"
            
            # ============= FIX: Define today_start once at the beginning =============
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            # ============= END FIX =============
            
            # 1. Общая сводка + скорость
            total_comments = self.stats.get('total_comments', 0)
            
            # ============= FIX: Calculate today's comments from DB with admin_id filter =============
            daily_comments = 0
            
            if self.conn:
                try:
                    cursor = self.conn.cursor()
                    if admin_id is None:  # Super admin - global view
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE timestamp >= ? AND event_type = 'comment_sent'",
                            (today_start,)
                        )
                    else:  # Regular admin - filtered view
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?",
                            (today_start, admin_id)
                        )
                    daily_comments = cursor.fetchone()[0]
                except Exception as e:
                    logger.error(f"Error counting today's comments: {e}")
            # ============= END FIX =============
            
            # Calculate hourly rate - filter by admin_id
            current_time = datetime.now().timestamp()
            hour_ago = current_time - 3600
            comments_last_hour = 0
            
            # Filter accounts by admin_id
            filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                               if admin_id is None or data.get('admin_id') == admin_id}
            
            
            for phone, activity in self.account_activity.items():
                # Skip if account doesn't belong to this admin
                if phone not in filtered_accounts:
                    continue
                messages = activity.get('messages', [])
                comments_last_hour += sum(1 for ts, _ in messages if ts >= hour_ago)
            
            active_accounts_count = sum(1 for d in filtered_accounts.values() 
                                       if d.get('status') == ACCOUNT_STATUS_ACTIVE)
            
            text += f"⚡ **Скорость:** `{comments_last_hour}` комм/час\n"
            text += f"👥 **Активных аккаунтов:** `{active_accounts_count}`\n"
            text += f"📋 **Лимит:** `{self.messages_per_hour}` комм/час на аккаунт\n"
            text += f"✅ **Всего комментариев:** `{total_comments}`\n"
            text += f"📈 **Сегодня комментариев:** `{daily_comments}`\n\n"
            
            # 2. Статистика по аккаунтам (filtered)
            if self.conn:
                try:
                    cursor = self.conn.cursor()
                    
                    text += "👤 **АККАУНТЫ:**\n"
                    
                    for phone, data in filtered_accounts.items():
                        status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                        if status_val == ACCOUNT_STATUS_ACTIVE:
                            status_emoji = "✅"
                        elif status_val == ACCOUNT_STATUS_BROKEN:
                            status_emoji = "🔴"
                        else:
                            status_emoji = "🔵"
                        
                        # Count today's comments (always filter by phone)
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE phone = ? AND timestamp >= ? AND event_type = 'comment_sent'",
                            (phone, today_start)
                        )
                        today_count = cursor.fetchone()[0]
                        
                        # Count total comments
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE phone = ? AND event_type = 'comment_sent'",
                            (phone,)
                        )
                        total_count = cursor.fetchone()[0]
                        
                        # Count errors
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE phone = ? AND success = 0",
                            (phone,)
                        )
                        error_count = cursor.fetchone()[0]
                        
                        short_phone = phone[-10:] if len(phone) > 10 else phone
                        text += f"{status_emoji} `{short_phone}` • сегодня: {today_count} • всего: {total_count} • ошибки: {error_count}\n"
                    
                    text += "\n"
                    
                    # 3. Топ аккаунтов (filtered by admin_id)
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            """SELECT phone, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' 
                            GROUP BY phone ORDER BY count DESC LIMIT 3""",
                            (today_start,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            """SELECT phone, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?
                            GROUP BY phone ORDER BY count DESC LIMIT 3""",
                            (today_start, admin_id)
                        )
                    top_accounts = cursor.fetchall()
                    
                    if top_accounts:
                        text += "🏆 **ТОП АККАУНТОВ СЕГОДНЯ:**\n"
                        for idx, (phone, count) in enumerate(top_accounts, 1):
                            short_phone = phone[-10:] if len(phone) > 10 else phone
                            text += f"{idx}. `{short_phone}` — {count} комм\n"
                        text += "\n"
                    
                    # 4. Статистика по каналам (filtered by admin_id)
                    cursor.execute("SELECT COUNT(*) FROM parsed_channels")
                    total_channels = cursor.fetchone()[0]
                    
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            """SELECT COUNT(DISTINCT channel) FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent'""",
                            (today_start,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            """SELECT COUNT(DISTINCT channel) FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?""",
                            (today_start, admin_id)
                        )
                    active_channels_today = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM blocked_channels")
                    blocked_channels_count = cursor.fetchone()[0]
                    
                    text += "📺 **КАНАЛЫ:**\n"
                    text += f"• Всего в работе: `{total_channels}`\n"
                    text += f"• Активных сегодня: `{active_channels_today}`\n"
                    text += f"• Без комментариев: `{blocked_channels_count}`\n\n"
                    
                    # Top channels (filtered by admin_id)
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            """SELECT channel, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND channel != '' 
                            GROUP BY channel ORDER BY count DESC LIMIT 3""",
                            (today_start,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            """SELECT channel, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND channel != '' AND admin_id = ?
                            GROUP BY channel ORDER BY count DESC LIMIT 3""",
                            (today_start, admin_id)
                        )
                    top_channels = cursor.fetchall()
                    
                    if top_channels:
                        text += "📊 **ТОП КАНАЛОВ СЕГОДНЯ:**\n"
                        for idx, (channel, count) in enumerate(top_channels, 1):
                            text += f"{idx}. `@{channel}` — {count} комм\n"
                        text += "\n"
                    
                    # 5. Последние блокировки
                    cursor.execute(
                        "SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC LIMIT 5"
                    )
                    blocks = cursor.fetchall()
                    
                    if blocks:
                        text += "🚫 **ПОСЛЕДНИЕ БЛОКИРОВКИ:**\n"
                        for phone, date, reason in blocks:
                            short_phone = phone[-10:] if len(phone) > 10 else phone
                            date_str = date[:10] if date else 'N/A'
                            text += f"• `{short_phone}` — {reason} ({date_str})\n"
                        text += "\n"
                    
                    # 6. Последние комментарии
                    cursor.execute(
                        "SELECT phone, channel, comment, date FROM comment_history ORDER BY id DESC LIMIT 5"
                    )
                    comments = cursor.fetchall()
                    
                    if comments:
                        text += "💬 **ПОСЛЕДНИЕ КОММЕНТАРИИ:**\n"
                        for phone, channel, comment, date in comments:
                            short_phone = phone[-10:] if len(phone) > 10 else phone
                            short_comment = comment[:25] if len(comment) > 25 else comment
                            date_str = date[:10] if date else 'N/A'
                            text += f"• `@{channel}` | {short_comment}... ({date_str})\n"
                        text += "\n"
                    
                    # 7. Предупреждения/риски (filtered by admin_id)
                    warnings = []
                    
                    # Check blocks in last 24h (filtered)
                    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
                    if admin_id is None:  # Super admin
                        cursor.execute(
                            "SELECT COUNT(*) FROM blocked_accounts WHERE block_date >= ?",
                            (yesterday,)
                        )
                    else:  # Regular admin
                        cursor.execute(
                            "SELECT COUNT(*) FROM blocked_accounts WHERE block_date >= ? AND admin_id = ?",
                            (yesterday, admin_id)
                        )
                    blocks_24h = cursor.fetchone()[0]
                    
                    if blocks_24h >= 2:
                        warnings.append(
                            "⚠️ **ВНИМАНИЕ:** Повышенное число блокировок за последние 24 часа. "
                            f"Рекомендуется снизить скорость и проверить прокси."
                        )
                    
                    # ============= FIX: Check % of blocked accounts by current status (filtered) =============
                    # Count accounts by status (only filtered accounts)
                    total_accounts = len(filtered_accounts)
                    broken_accounts = sum(1 for d in filtered_accounts.values() 
                                         if d.get('status') == ACCOUNT_STATUS_BROKEN)
                    
                    if total_accounts > 0 and broken_accounts > 0:
                        blocked_percent = (broken_accounts / total_accounts) * 100
                        if blocked_percent >= 30:
                            warnings.append(
                                f"⚠️ **ВЫСОКИЙ РИСК:** {blocked_percent:.1f}% аккаунтов заблокировано "
                                f"({broken_accounts} из {total_accounts}). Необходима ротация аккаунтов."
                            )
                    # ============= END FIX =============
                    
                    # Check if hourly rate is too high
                    if active_accounts_count > 0:
                        avg_rate_per_account = comments_last_hour / active_accounts_count
                        if avg_rate_per_account > self.messages_per_hour * 0.9:
                            warnings.append(
                                f"⚡ **ПРЕДУПРЕЖДЕНИЕ:** Приближение к лимиту скорости "
                                f"({avg_rate_per_account:.1f}/{self.messages_per_hour} комм/час)."
                            )
                    
                    if warnings:
                        text += "🔔 **РИСКИ И ПРЕДУПРЕЖДЕНИЯ:**\n"
                        for warning in warnings:
                            text += f"{warning}\n\n"
                    
                except Exception as e:
                    logger.error(f"Stats DB error: {e}")
                    text += f"\n⚠️ Ошибка получения статистики: {str(e)[:100]}\n"
            
            await event.respond(text)
        
        @self.bot_client.on(events.NewMessage(pattern='/listparsed'))
        async def list_parsed(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM parsed_channels")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("❌ Нет спарсенных каналов. Используйте /searchchannels")
                    return
                
                # Get all parsed channels
                cursor.execute("SELECT username, theme FROM parsed_channels ORDER BY added_date DESC")
                parsed = cursor.fetchall()
                
                # Show all channels, split into multiple messages if needed
                channels_per_msg = 50
                
                for batch_num in range(0, total, channels_per_msg):
                    batch_channels = parsed[batch_num:batch_num + channels_per_msg]
                    text = f"📋 **СПАРСЕННЫЕ КАНАЛЫ** ({total}) - Часть {batch_num//channels_per_msg + 1}:\n\n"
                    
                    for i, (username, theme) in enumerate(batch_channels, batch_num + 1):
                        # Display with @ (add if not present)
                        display_name = username if username.startswith('@') else '@' + username
                        text += f"{i}. {display_name} ({theme})\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + channels_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Listparsed error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        # Диагностика: код дошёл до этой точки
        logger.warning("=" * 80)
        logger.warning("🟢 CHECKPOINT: Код дошёл до регистрации /testmode")
        logger.warning("=" * 80)
        
        # === TESTMODE HANDLER ===
        logger.warning(f"🔥 РЕГИСТРАЦИЯ ОБРАБОТЧИКА /testmode НАЧИНАЕТСЯ...")
        logger.warning(f"🔥 bot_client type: {type(self.bot_client)}")
        logger.warning(f"🔥 test_mode={getattr(self, 'test_mode', None)}")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/testmode(?:@\w+)?'))
        async def testmode_command(event):
            logger.warning(f"🔥 /testmode HANDLER TRIGGERED from {event.sender_id}, text={event.raw_text!r}")
            """Управление тестовым режимом: /testmode <selector> или /testmode on <list>"""
            
            logger.info(f"🎯 /testmode handler called by {event.sender_id}, raw={event.raw_text}")
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            # Log command received
            logger.info(f"🧪 TESTMODE command received from {event.sender_id}")
            
            try:
                text = (event.raw_text or event.text or "").rstrip(';').strip()
                parts = text.split()
                
                if len(parts) == 1:
                    # Show current status
                    status = "🟢 ВКЛЮЧЕН" if self.test_mode else "🔴 ВЫКЛЮЧЕН"
                    text = f"""🧪 **ТЕСТОВЫЙ РЕЖИМ**

Статус: {status}
"""
                    if self.test_mode and self.test_channels:
                        text += f"\n📢 Тестовые каналы ({len(self.test_channels)}):\n"
                        for ch in self.test_channels:
                            text += f"  • `{ch}`\n"
                        text += f"\n⚡ Лимит: `{self.test_mode_speed_limit}` комм/час\n"
                    
                    text += "\n📝 **Использование:**\n"
                    text += "`/testmode <selector>` - включить на один канал (номер или username)\n"
                    text += "`/testmode on @channel1 @channel2` - массовый тест-режим\n"
                    text += "`/testmode on` + новой строкой список каналов\n"
                    text += "`/testmode off` - выключить\n"
                    text += "`/testmode speed 5` - установить скорость\n"
                    
                    await event.respond(text)
                    return
                
                action = parts[1].lower()
                
                if action == 'on':
                    split_after_on = text.split(None, 2)
                    logger.info(f"🧪 /testmode on: split_after_on = {split_after_on}")
                    
                    if len(split_after_on) < 3:
                        await event.respond(
                            "❌ Укажите список каналов.\n\n"
                            "Пример:\n"
                            "`/testmode on @chan1 @chan2`\n"
                            "или\n"
                            "`/testmode on`\n"
                            "`@chan1 @chan2`"
                        )
                        return

                    raw_channels_part = split_after_on[2]
                    logger.info(f"🧪 raw_channels_part BEFORE: {raw_channels_part}")
                    
                    # Убираем markdown ссылки: [@channel](url) -> @channel
                    import re
                    raw_channels_part = re.sub(r'\[(@\w+)\]\([^)]+\)', r'\1', raw_channels_part)
                    logger.info(f"🧪 raw_channels_part AFTER regex: {raw_channels_part}")
                    
                    raw_tokens = raw_channels_part.replace("\n", " ").split(" ")
                    logger.info(f"🧪 raw_tokens: {raw_tokens}")
                    
                    raw_usernames = []
                    for token in raw_tokens:
                        cleaned = token.strip().lstrip('@').strip()
                        if cleaned:
                            raw_usernames.append(cleaned)
                    
                    logger.info(f"🧪 raw_usernames: {raw_usernames}")
                    
                    normalized = []
                    seen = set()
                    for raw in raw_usernames:
                        norm = self._normalize_channel_username(raw)
                        if not norm:
                            continue
                        if norm not in seen:
                            seen.add(norm)
                            normalized.append(norm)

                    logger.info(f"🧪 normalized channels: {normalized}")

                    if not normalized:
                        await event.respond("❌ Не удалось распознать список каналов")
                        return

                    self.test_mode = True
                    self.test_channels = normalized
                    self.save_data()
                    
                    # Сохраняем в конфиг
                    self.save_config_value('test_mode', True)
                    self.save_config_value('test_channels', normalized)

                    # Сначала быстро отвечаем пользователю
                    await event.respond(
                        f"✅ Test mode ON.\nТест‑каналы: {', '.join(self.test_channels) or 'не заданы'}\n"
                        f"💾 Настройка сохранена в config.json\n\n"
                        f"🔍 Проверяю каналы..."
                    )
                    
                    # Потом делаем проверку (может занять время)
                    await self.test_mode_bulk_channels(event, normalized)
                    logger.info("TESTMODE UPDATED: %s", self.test_channels)

                    logger.info("="*80)
                    logger.info("🧪 TEST MODE: ENABLED (BULK)")
                    logger.info(f"🧪 Test channels: {self.test_channels}")
                    logger.info(f"🧪 Speed limit: {self.test_mode_speed_limit} msg/hour")
                    logger.info("="*80)
                    
                elif action == 'off':
                    # Disable test mode
                    was_enabled = self.test_mode
                    old_channels = self.test_channels.copy() if self.test_channels else []
                    
                    self.test_mode = False
                    self.test_channels = []
                    
                    # Сохраняем в конфиг
                    self.save_config_value('test_mode', False)
                    self.save_config_value('test_channels', [])
                    
                    if was_enabled:
                        text = """✅ **TEST MODE: OFF**

🎯 Возвращаемся к боевым каналам
"""
                        if old_channels:
                            text += "\n📢 Были в тесте:\n"
                            for ch in old_channels:
                                text += f"  • `{ch}`\n"
                        text += "\n💾 Настройка сохранена в config.json"
                    else:
                        text = "ℹ️ TEST MODE уже был выключен"
                    
                    await event.respond(text)
                    
                    logger.info("="*80)
                    logger.info("🔴 TEST MODE: DISABLED")
                    logger.info("✅ Switching to LIVE channels")
                    logger.info("="*80)
                    
                elif action == 'speed':
                    # Set test mode speed limit
                    if len(parts) < 3:
                        await event.respond(
                            f"❌ Укажите скорость:\n"
                            f"`/testmode speed 10`\n\n"
                            f"Текущая: `{self.test_mode_speed_limit}` комм/час"
                        )
                        return
                    
                    try:
                        speed = int(parts[2])
                        if speed < 1 or speed > 30:
                            await event.respond(
                                "❌ Скорость должна быть от 1 до 30 комм/час"
                            )
                            return
                        
                        old_speed = self.test_mode_speed_limit
                        self.test_mode_speed_limit = speed
                        
                        # Сохраняем в конфиг
                        self.save_config_value('test_mode_speed_limit', speed)
                        
                        await event.respond(
                            f"✅ Лимит тестового режима изменен:\n"
                            f"Было: `{old_speed}` комм/час\n"
                            f"Стало: `{self.test_mode_speed_limit}` комм/час\n"
                            f"💾 Настройка сохранена в config.json"
                        )
                        
                        logger.info(f"🧪 TEST MODE speed changed: {old_speed} -> {speed}")
                        
                    except ValueError:
                        await event.respond("❌ Неверное значение скорости")
                        return
                
                else:
                    selector = parts[1].strip()
                    raw_usernames = []

                    if selector.isdigit():
                        try:
                            idx = int(selector)
                            if idx < 1 or idx > len(self.channels):
                                await event.respond(
                                    f"❌ Неверный номер канала. Диапазон: 1-{len(self.channels)}"
                                )
                                return
                            selected = self.channels[idx - 1]
                            if isinstance(selected, dict):
                                selected_username = selected.get('username') or selected.get('channel') or selected.get('name')
                            else:
                                selected_username = selected
                            if not selected_username:
                                await event.respond("❌ Не удалось определить username канала по номеру")
                                return
                            raw_usernames = [selected_username]
                        except Exception as e:
                            logger.error(f"Testmode selector error: {e}")
                            await event.respond("❌ Ошибка при выборе канала по номеру")
                            return
                    else:
                        raw_usernames = [selector]

                    normalized = []
                    seen = set()
                    for raw in raw_usernames:
                        norm = self._normalize_channel_username(raw)
                        if not norm:
                            continue
                        if norm not in seen:
                            seen.add(norm)
                            normalized.append(norm)

                    if not normalized:
                        await event.respond("❌ Не удалось распознать канал")
                        return

                    self.test_mode = True
                    self.test_channels = normalized
                    self.save_data()
                    
                    # Сохраняем в конфиг
                    self.save_config_value('test_mode', True)
                    self.save_config_value('test_channels', normalized)

                    await self.test_mode_bulk_channels(event, normalized)

                    await event.respond(
                        f"✅ Test mode ON.\nТест‑каналы: {', '.join(self.test_channels) or 'не заданы'}\n"
                        f"💾 Настройка сохранена в config.json"
                    )
                    logger.info("TESTMODE UPDATED: %s", self.test_channels)
                    
            except Exception as e:
                logger.error(f"Testmode command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        logger.warning(f"✅ ОБРАБОТЧИК /testmode ЗАРЕГИСТРИРОВАН УСПЕШНО!")
        # === END TESTMODE HANDLER ===
        
        @self.bot_client.on(events.NewMessage(pattern='/listbans'))
        async def list_bans(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM blocked_accounts")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("✅ Нет заблокированных аккаунтов")
                    return
                
                # Get all blocked accounts
                cursor.execute("SELECT phone, block_date, reason FROM blocked_accounts ORDER BY block_date DESC")
                bans = cursor.fetchall()
                
                # Show all bans, split into multiple messages if needed
                bans_per_msg = 30
                
                for batch_num in range(0, total, bans_per_msg):
                    batch_bans = bans[batch_num:batch_num + bans_per_msg]
                    text = f"🚫 **ЗАБЛОКИРОВАННЫЕ АККАУНТЫ** ({total}) - Часть {batch_num//bans_per_msg + 1}:\n\n"
                    
                    for i, (phone, date, reason) in enumerate(batch_bans, batch_num + 1):
                        text += f"{i}. `{phone}` | {reason}\n     {date[:19]}\n\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + bans_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Listbans error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/history'))
        async def show_history(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM comment_history")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("❌ История пуста")
                    return
                
                # Get all history
                cursor.execute(
                    "SELECT phone, channel, comment, date FROM comment_history ORDER BY id DESC"
                )
                history = cursor.fetchall()
                
                # Show all history, split into multiple messages if needed
                history_per_msg = 30
                
                for batch_num in range(0, total, history_per_msg):
                    batch_history = history[batch_num:batch_num + history_per_msg]
                    text = f"📝 **ИСТОРИЯ КОММЕНТАРИЕВ** ({total}) - Часть {batch_num//history_per_msg + 1}:\n\n"
                    
                    for i, (phone, channel, comment, date) in enumerate(batch_history, batch_num + 1):
                        short_comment = comment[:40] if len(comment) > 40 else comment
                        # Display with @ (add if not present)
                        display_channel = channel if channel.startswith('@') else '@' + channel
                        text += f"{i}. `{phone[:12]}...` → {display_channel}\n     \"{short_comment}\"\n     {date[:19]}\n\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + history_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"History error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listblockedchannels'))
        async def list_blocked_channels(event):
            if not await self.is_admin(event.sender_id): return
            
            if not self.conn:
                await event.respond("❌ БД недоступна")
                return
            
            try:
                cursor = self.conn.cursor()
                
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM blocked_channels")
                total = cursor.fetchone()[0]
                
                if total == 0:
                    await event.respond("✅ Нет заблокированных каналов")
                    return
                
                # Get all blocked channels
                cursor.execute("SELECT username, block_date, reason FROM blocked_channels ORDER BY block_date DESC")
                blocked = cursor.fetchall()
                
                # Show all blocked channels, split into multiple messages if needed
                channels_per_msg = 40
                
                for batch_num in range(0, total, channels_per_msg):
                    batch_blocked = blocked[batch_num:batch_num + channels_per_msg]
                    text = f"🔇 **КАНАЛЫ БЕЗ КОММЕНТАРИЕВ** ({total}) - Часть {batch_num//channels_per_msg + 1}:\n\n"
                    
                    for i, (username, date, reason) in enumerate(batch_blocked, batch_num + 1):
                        # Display with @ (add if not present)
                        display_name = username if username.startswith('@') else '@' + username
                        text += f"{i}. {display_name}\n     {reason}\n     {date[:19]}\n\n"
                    
                    await event.respond(text)
                    # Small delay between messages to avoid flood
                    if batch_num + channels_per_msg < total:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"List blocked channels error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:50]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/safetyinfo'))
        async def safety_info(event):
            if not await self.is_admin(event.sender_id): return
            text = """🛡️ **НАСТРОЙКИ БЕЗОПАСНОСТИ**

**Текущая конфигурация:**
• Задержка между комментариями: `50-100 сек` (~1-2 мин)
• Перерыв между циклами: `3-7 мин`
• Параллельных аккаунтов: `2` (максимум)
• Прогрев перед стартом: `5-30 сек`
• Вариации комментариев: `ВКЛЮЧЕНЫ`

**Защита от бана:**
✅ Случайные задержки (имитация человека)
✅ Длинные паузы между циклами
✅ Ограничение параллельных аккаунтов
✅ Вариации текста комментариев
✅ Прогрев аккаунтов перед работой
✅ Отслеживание FloodWait ошибок

**Рекомендации:**
1️⃣ Не запускайте бота 24/7
2️⃣ Делайте перерывы по 2-3 часа
3️⃣ Добавьте больше шаблонов (>50)
4️⃣ Не комментируйте один канал часто
5️⃣ Меняйте био-ссылки раз в неделю

**Статистика рисков:**
• Текущий режим: `БЕЗОПАСНЫЙ`
• Скорость: `36-72 комм/час`
• Риск бана: `НИЗКИЙ` 🟢"""
            await event.respond(text)
        
        # ============= ACCOUNT WARMUP HANDLERS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/warmup'))
        async def warmup_command(event):
            """Управление прогревом аккаунтов"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            await event.respond(
                "🔥 **ПРОГРЕВ АККАУНТОВ (4 ДНЯ)**\n\n"
                "**Программа прогрева:**\n"
                "📅 День 1: Просмотр каналов, подписки (5-8 действий)\n"
                "📅 День 2: Реакции на посты (10-15 реакций)\n"
                "📅 День 3: Первые комментарии (3-5 шт)\n"
                "📅 День 4: Полная активность (8-10 комм)\n\n"
                "**Команды:**\n"
                "/warmup_start +номер - Начать прогрев\n"
                "/warmup_stop +номер - Остановить прогрев\n"
                "/warmup_status - Статус всех прогревов\n"
                "/warmup_run - Запустить цикл прогрева вручную\n\n"
                "⚠️ Аккаунты в прогреве не используются для комментирования!"
            )
        
        @self.bot_client.on(events.NewMessage(pattern=r'/warmup_start(?:\s+(.+))?'))
        async def warmup_start_command(event):
            """Начать прогрев аккаунта"""
            if not await self.is_admin(event.sender_id):
                return
            
            match = event.pattern_match
            phone = match.group(1).strip() if match.group(1) else None
            
            if not phone:
                await event.respond(
                    "❌ Укажите номер телефона\n"
                    "Пример: `/warmup_start +79991234567`"
                )
                return
            
            # Проверяем, есть ли такой аккаунт
            accounts = self.get_all_accounts_from_env()
            if phone not in accounts:
                await event.respond(f"❌ Аккаунт {phone} не найден в системе")
                return
            
            # Запускаем прогрев
            success = warmup_manager.start_warmup(phone)
            
            if success:
                await event.respond(
                    f"🔥 **ПРОГРЕВ НАЧАТ**\n\n"
                    f"Аккаунт: `{phone}`\n"
                    f"Программа: 4 дня\n"
                    f"Старт: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"✅ Аккаунт автоматически исключен из комментирования\n"
                    f"📊 Следите за прогрессом: /warmup_status"
                )
                
                # Запускаем фоновую задачу прогрева
                asyncio.create_task(self._run_warmup_background(phone))
            else:
                await event.respond(
                    f"⚠️ Аккаунт {phone} уже прогревается\n"
                    f"Проверьте статус: /warmup_status"
                )
        
        @self.bot_client.on(events.NewMessage(pattern=r'/warmup_stop(?:\s+(.+))?'))
        async def warmup_stop_command(event):
            """Остановить прогрев аккаунта"""
            if not await self.is_admin(event.sender_id):
                return
            
            match = event.pattern_match
            phone = match.group(1).strip() if match.group(1) else None
            
            if not phone:
                await event.respond(
                    "❌ Укажите номер телефона\n"
                    "Пример: `/warmup_stop +79991234567`"
                )
                return
            
            warmup_manager.stop_warmup(phone, 'manual_stop')
            await event.respond(
                f"⏸️ **ПРОГРЕВ ОСТАНОВЛЕН**\n\n"
                f"Аккаунт: `{phone}`\n"
                f"Причина: Остановлено вручную\n\n"
                f"Аккаунт можно использовать для комментирования"
            )
        
        @self.bot_client.on(events.NewMessage(pattern='/warmup_status'))
        async def warmup_status_command(event):
            """Статус прогрева всех аккаунтов"""
            if not await self.is_admin(event.sender_id):
                return
            
            report = warmup_manager.get_warmup_report()
            await event.respond(report)
        
        @self.bot_client.on(events.NewMessage(pattern=r'/warmup_run(?:\s+(.+))?'))
        async def warmup_run_command(event):
            """Запустить цикл прогрева вручную для аккаунта"""
            if not await self.is_admin(event.sender_id):
                return
            
            match = event.pattern_match
            phone = match.group(1).strip() if match.group(1) else None
            
            if not phone:
                # Запускаем для всех активных
                active = warmup_manager.get_all_active_warmups()
                if not active:
                    await event.respond("❌ Нет аккаунтов в активном прогреве")
                    return
                
                await event.respond(
                    f"🔄 Запуск прогрева для {len(active)} аккаунтов...\n"
                    f"Это может занять несколько минут"
                )
                
                for phone in active:
                    asyncio.create_task(self._run_warmup_background(phone))
                
                await event.respond("✅ Прогрев запущен")
            else:
                status = warmup_manager.get_warmup_status(phone)
                if not status or status['status'] != 'active':
                    await event.respond(f"❌ Аккаунт {phone} не находится в активном прогреве")
                    return
                
                await event.respond(f"🔄 Запуск прогрева для {phone}...")
                asyncio.create_task(self._run_warmup_background(phone))
                await event.respond("✅ Прогрев запущен")
        
        # ============= END ACCOUNT WARMUP HANDLERS =============
        
        # ============= ACCOUNTS PROFILE MANAGEMENT HANDLERS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/accounts'))
        async def accounts_command(event):
            """Показывает список всех аккаунтов из переменных окружения"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                accounts = self.get_all_accounts_from_env()
                
                if not accounts:
                    await event.respond(
                        "❌ **Аккаунты не найдены**\n\n"
                        "Убедитесь, что в переменных окружения есть:\n"
                        "`ACCOUNT_1_PHONE`\n"
                        "`ACCOUNT_1_SESSION`\n"
                        "`ACCOUNT_1_PROXY` (опционально)"
                    )
                    return
                
                text = f"🔐 **УПРАВЛЕНИЕ ПРОФИЛЯМИ АККАУНТОВ**\n\n"
                text += f"Найдено аккаунтов: **{len(accounts)}**\n\n"
                text += "Выберите аккаунт для управления профилем:"
                
                keyboard = self.create_accounts_keyboard(page=0)
                await event.respond(text, buttons=keyboard)
                
            except Exception as e:
                logger.error(f"Error in accounts command: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.CallbackQuery)
        async def handle_callback(event):
            """Обработчик всех callback кнопок для управления профилями"""
            if not await self.is_admin(event.sender_id):
                await event.answer("❌ Нет доступа")
                return
            
            data = event.data.decode('utf-8', errors='ignore')
            user_id = event.sender_id
            
            try:
                # Main menu
                if data == "main_menu":
                    await self.clear_user_state(user_id)
                    await event.edit(
                        "🏠 **Главное меню**\n\n"
                        "Используйте команды:\n"
                        "`/accounts` - управление профилями\n"
                        "`/help` - все команды",
                        buttons=None
                    )
                    return
                
                # Back to accounts list
                if data == "back_to_accounts":
                    await self.clear_user_state(user_id)
                    accounts = self.get_all_accounts_from_env()
                    text = f"🔐 **УПРАВЛЕНИЕ ПРОФИЛЯМИ АККАУНТОВ**\n\n"
                    text += f"Найдено аккаунтов: **{len(accounts)}**\n\n"
                    text += "Выберите аккаунт для управления профилем:"
                    keyboard = self.create_accounts_keyboard(page=0)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Page navigation
                if data.startswith("acc_page_"):
                    page = int(data.split("_")[-1])
                    accounts = self.get_all_accounts_from_env()
                    text = f"🔐 **УПРАВЛЕНИЕ ПРОФИЛЯМИ АККАУНТОВ**\n\n"
                    text += f"Найдено аккаунтов: **{len(accounts)}**\n\n"
                    text += "Выберите аккаунт для управления профилем:"
                    keyboard = self.create_accounts_keyboard(page=page)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Page info (do nothing)
                if data == "page_info":
                    await event.answer("ℹ️ Информация о странице")
                    return
                
                # No accounts found
                if data == "no_accounts":
                    await event.answer("❌ Аккаунты не настроены")
                    return
                
                # Account selected
                if data.startswith("acc_") and not "_" in data[4:]:
                    account_num = int(data[4:])
                    
                    # Get account info
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info:
                        await event.answer("❌ Аккаунт не найден")
                        return
                    
                    # Build info text
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"📱 Телефон: `{account_info['phone']}`\n"
                    
                    if account_info.get('authorized'):
                        text += f"✅ Статус: **Авторизован**\n\n"
                        text += f"👤 Имя: {account_info.get('first_name', 'Не указано')}\n"
                        text += f"👤 Фамилия: {account_info.get('last_name', 'Не указано')}\n"
                        if account_info.get('username'):
                            text += f"🔗 Username: @{account_info['username']}\n"
                        text += f"📝 Био: {account_info.get('bio', 'Не указано')[:100]}\n"
                    else:
                        text += f"❌ Статус: **Не авторизован**\n\n"
                        text += "⚠️ Этот аккаунт не может быть изменён.\n"
                    
                    text += f"\nВыберите действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Avatar button
                if data.endswith("_avatar"):
                    account_num = int(data.split("_")[1])
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info or not account_info.get('authorized'):
                        await event.answer("❌ Аккаунт не авторизован")
                        return
                    
                    # Set state
                    self.user_states[user_id] = {
                        'state': 'waiting_avatar',
                        'account_num': account_num,
                        'data': {}
                    }
                    
                    await event.edit(
                        f"📷 **ЗАГРУЗКА АВАТАРКИ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n\n"
                        f"Отправьте фото для аватарки (jpg, png)\n"
                        f"Или нажмите Отмена",
                        buttons=[
                            [Button.inline("❌ Отмена", f"cancel_acc_{account_num}".encode())]
                        ]
                    )
                    return
                
                # Name button
                if data.endswith("_name"):
                    account_num = int(data.split("_")[1])
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info or not account_info.get('authorized'):
                        await event.answer("❌ Аккаунт не авторизован")
                        return
                    
                    # Set state
                    self.user_states[user_id] = {
                        'state': 'waiting_name',
                        'account_num': account_num,
                        'data': {}
                    }
                    
                    current_name = f"{account_info.get('first_name', '')} {account_info.get('last_name', '')}".strip()
                    
                    await event.edit(
                        f"👤 **ИЗМЕНЕНИЕ ИМЕНИ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n"
                        f"Текущее: {current_name or 'Не указано'}\n\n"
                        f"Введите имя и фамилию через пробел:\n"
                        f"Пример: `Иван Петров`\n\n"
                        f"Или нажмите Отмена",
                        buttons=[
                            [Button.inline("❌ Отмена", f"cancel_acc_{account_num}".encode())]
                        ]
                    )
                    return
                
                # Bio button
                if data.endswith("_bio"):
                    account_num = int(data.split("_")[1])
                    account_info = await self.get_account_info(account_num)
                    
                    if not account_info or not account_info.get('authorized'):
                        await event.answer("❌ Аккаунт не авторизован")
                        return
                    
                    # Set state
                    self.user_states[user_id] = {
                        'state': 'waiting_bio',
                        'account_num': account_num,
                        'data': {}
                    }
                    
                    current_bio = account_info.get('bio', 'Не указано')
                    
                    await event.edit(
                        f"📝 **ИЗМЕНЕНИЕ ИНФОРМАЦИИ О СЕБЕ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n"
                        f"Текущее: {current_bio[:100]}\n\n"
                        f"Введите новую информацию о себе (до 500 символов):\n"
                        f"Можете добавить ссылку\n\n"
                        f"Пример: `Digital Marketing 🌐 https://example.com`\n\n"
                        f"Или нажмите Отмена",
                        buttons=[
                            [Button.inline("❌ Отмена", f"cancel_acc_{account_num}".encode())]
                        ]
                    )
                    return
                
                # Cancel button
                if data.startswith("cancel_acc_"):
                    account_num = int(data.split("_")[-1])
                    await self.clear_user_state(user_id)
                    
                    # Return to account menu
                    account_info = await self.get_account_info(account_num)
                    if account_info:
                        text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                        text += f"📱 Телефон: `{account_info['phone']}`\n"
                        text += f"✅ Операция отменена\n\n"
                        text += "Выберите действие:"
                        
                        keyboard = self.create_account_menu_keyboard(account_num)
                        await event.edit(text, buttons=keyboard)
                    return
                
                # Apply changes (avatar)
                if data.startswith("apply_avatar_"):
                    account_num = int(data.split("_")[-1])
                    
                    if user_id not in self.user_states:
                        await event.answer("❌ Сессия истекла")
                        return
                    
                    state = self.user_states[user_id]
                    avatar_file = state.get('data', {}).get('temp_avatar')
                    
                    if not avatar_file or not os.path.exists(avatar_file):
                        await event.answer("❌ Файл не найден")
                        return
                    
                    await event.edit("⏳ Загрузка аватарки...")
                    
                    # Apply changes
                    success, message = await self.apply_account_changes(
                        account_num, 
                        avatar_file=avatar_file
                    )
                    
                    await self.clear_user_state(user_id)
                    
                    # Show result and return to account menu
                    account_info = await self.get_account_info(account_num)
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"{message}\n\n"
                    text += "Выберите следующее действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Apply changes (name)
                if data.startswith("apply_name_"):
                    account_num = int(data.split("_")[-1])
                    
                    if user_id not in self.user_states:
                        await event.answer("❌ Сессия истекла")
                        return
                    
                    state = self.user_states[user_id]
                    first_name = state.get('data', {}).get('first_name', '')
                    last_name = state.get('data', {}).get('last_name', '')
                    
                    await event.edit("⏳ Обновление имени...")
                    
                    # Apply changes
                    success, message = await self.apply_account_changes(
                        account_num,
                        first_name=first_name,
                        last_name=last_name
                    )
                    
                    await self.clear_user_state(user_id)
                    
                    # Show result and return to account menu
                    account_info = await self.get_account_info(account_num)
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"{message}\n\n"
                    text += "Выберите следующее действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
                # Apply changes (bio)
                if data.startswith("apply_bio_"):
                    account_num = int(data.split("_")[-1])
                    
                    if user_id not in self.user_states:
                        await event.answer("❌ Сессия истекла")
                        return
                    
                    state = self.user_states[user_id]
                    bio = state.get('data', {}).get('bio', '')
                    
                    await event.edit("⏳ Обновление био...")
                    
                    # Apply changes
                    success, message = await self.apply_account_changes(
                        account_num,
                        bio=bio
                    )
                    
                    await self.clear_user_state(user_id)
                    
                    # Show result and return to account menu
                    account_info = await self.get_account_info(account_num)
                    text = f"🔐 **АККАУНТ #{account_num}**\n\n"
                    text += f"{message}\n\n"
                    text += "Выберите следующее действие:"
                    
                    keyboard = self.create_account_menu_keyboard(account_num)
                    await event.edit(text, buttons=keyboard)
                    return
                
            except Exception as e:
                logger.error(f"Callback error: {e}")
                await event.answer(f"❌ Ошибка: {str(e)[:50]}")
        
        # Handler for photo uploads (avatar)
        @self.bot_client.on(events.NewMessage(func=lambda e: e.photo))
        async def handle_photo(event):
            """Обработчик загрузки фотографий для аватарок"""
            if not await self.is_admin(event.sender_id):
                return
            
            user_id = event.sender_id
            
            # Check if user is in avatar upload state
            if user_id not in self.user_states:
                return
            
            state = self.user_states[user_id]
            # Поддержка старого формата ('state') и нового ('action')
            action = state.get('action') or state.get('state')
            
            # Обработка аватара аккаунта
            if action == 'waiting_avatar':
                account_num = state['account_num']
                
                try:
                    await event.respond("⏳ Загрузка изображения...")
                    
                    # Download photo
                    photo = await event.download_media()
                    
                    if not photo:
                        await event.respond("❌ Ошибка загрузки фото")
                        return
                    
                    # Save to temp
                    temp_file = await self.save_temp_avatar(user_id, photo)
                    
                    # Update state
                    self.user_states[user_id]['data']['temp_avatar'] = temp_file
                    
                    # Clean up original download
                    if os.path.exists(photo):
                        try:
                            os.remove(photo)
                        except:
                            pass
                    
                    # Show confirmation
                    await event.respond(
                        f"✅ **Фото выбрано!**\n\n"
                        f"Аккаунт: `{(await self.get_account_info(account_num))['phone']}`\n\n"
                        f"Применить это фото как аватарку?",
                        buttons=[
                            [
                                Button.inline("✅ Применить", f"apply_avatar_{account_num}".encode()),
                                Button.inline("❌ Отменить", f"cancel_acc_{account_num}".encode())
                            ]
                        ]
                    )
                    
                except Exception as e:
                    logger.error(f"Error handling photo upload: {e}")
                    await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                    await self.clear_user_state(user_id)
            
            # Обработка аватара канала-витрины
            elif action == 'waiting_profile_channel_avatar':
                phone = state['phone']
                
                try:
                    await event.respond("⏳ Загрузка изображения для канала...")
                    
                    # Download photo
                    photo = await event.download_media()
                    
                    if not photo:
                        await event.respond("❌ Ошибка загрузки фото")
                        return
                    
                    await event.respond("⏳ Устанавливаю аватар канала...")
                    
                    # Set channel avatar
                    success, message = await self.set_profile_channel_avatar(phone, photo)
                    
                    # Clean up downloaded photo
                    if os.path.exists(photo):
                        try:
                            os.remove(photo)
                        except:
                            pass
                    
                    await event.respond(message)
                    
                    if success:
                        logger.info(f"Profile channel avatar set by admin {user_id} for {phone}")
                    
                    # Clear state
                    await self.clear_user_state(user_id)
                    
                except Exception as e:
                    logger.error(f"Error setting profile channel avatar: {e}")
                    await event.respond(f"❌ Ошибка: {str(e)[:200]}")
                    await self.clear_user_state(user_id)
        
        # Handler for text messages (name and bio)
        @self.bot_client.on(events.NewMessage(func=lambda e: e.text and not e.text.startswith('/')))
        async def handle_text(event):
            """Обработчик текстовых сообщений для имени и био"""
            if not await self.is_admin(event.sender_id):
                return
            
            user_id = event.sender_id
            
            # Check if user is in text input state
            if user_id not in self.user_states:
                return
            
            state = self.user_states[user_id]
            account_num = state['account_num']
            
            try:
                # Handle name input
                if state.get('state') == 'waiting_name':
                    text = event.text.strip()
                    
                    # Split by first space
                    parts = text.split(' ', 1)
                    first_name = parts[0] if parts else ''
                    last_name = parts[1] if len(parts) > 1 else ''
                    
                    # Validate
                    if not first_name:
                        await event.respond("❌ Имя не может быть пустым. Попробуйте ещё раз:")
                        return
                    
                    if len(first_name) > 64 or len(last_name) > 64:
                        await event.respond("❌ Имя слишком длинное (макс 64 символа). Попробуйте ещё раз:")
                        return
                    
                    # Save to state
                    self.user_states[user_id]['data']['first_name'] = first_name
                    self.user_states[user_id]['data']['last_name'] = last_name
                    
                    # Show preview
                    account_info = await self.get_account_info(account_num)
                    preview_text = (
                        f"📋 **ПРЕВЬЮ ИЗМЕНЕНИЙ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n\n"
                        f"👤 Имя: {first_name}\n"
                        f"👤 Фамилия: {last_name or '(не указано)'}\n\n"
                        f"Применить эти изменения?"
                    )
                    
                    await event.respond(
                        preview_text,
                        buttons=[
                            [
                                Button.inline("✅ Применить", f"apply_name_{account_num}".encode()),
                                Button.inline("❌ Отменить", f"cancel_acc_{account_num}".encode())
                            ]
                        ]
                    )
                    return
                
                # Handle bio input
                if state.get('state') == 'waiting_bio':
                    text = event.text.strip()
                    
                    # Validate length
                    if len(text) > 500:
                        await event.respond(
                            f"❌ Текст слишком длинный ({len(text)}/500 символов)\n"
                            f"Сократите текст и попробуйте ещё раз:"
                        )
                        return
                    
                    # Save to state
                    self.user_states[user_id]['data']['bio'] = text
                    
                    # Show preview
                    account_info = await self.get_account_info(account_num)
                    preview_text = (
                        f"📋 **ПРЕВЬЮ ИЗМЕНЕНИЙ**\n\n"
                        f"Аккаунт: `{account_info['phone']}`\n\n"
                        f"📝 Новое био:\n{text}\n\n"
                        f"Применить эти изменения?"
                    )
                    
                    await event.respond(
                        preview_text,
                        buttons=[
                            [
                                Button.inline("✅ Применить", f"apply_bio_{account_num}".encode()),
                                Button.inline("❌ Отменить", f"cancel_acc_{account_num}".encode())
                            ]
                        ]
                    )
                    return
                
            except Exception as e:
                logger.error(f"Text handler error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        # ============= END ACCOUNTS PROFILE MANAGEMENT HANDLERS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/addadmin'))
        async def add_admin(event):
            # Only super admins can add new admins
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут добавлять новых админов")
                return
            
            try:
                admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Check if already a super admin
                if admin_id in SUPER_ADMINS:
                    await event.respond(f"ℹ️ `{admin_id}` уже является супер-админом")
                    return
                
                if admin_id not in self.admins:
                    self.admins.append(admin_id)
                    self.save_data()
                    
                    text = f"""✅ **Новый админ добавлен**

👤 ID: `{admin_id}`
🆔 Добавил: `{event.sender_id}`
📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}

🔹 Этот админ теперь имеет свой отдельный кабинет
🔹 Он видит только свои аккаунты и статистику
🔹 Не имеет доступа к глобальным данным"""
                    
                    await event.respond(text)
                    logger.info(f"New admin added: {admin_id} by super admin {event.sender_id}")
                else:
                    await event.respond("ℹ️ Этот админ уже добавлен")
            except Exception as e:
                await event.respond(f"❌ Ошибка: Формат: `/addadmin 123456789`")
                logger.error(f"Add admin error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listadmins'))
        async def list_admins_command(event):
            """List all admins (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут видеть список всех админов")
                return
            
            try:
                text = "👑 **СПИСОК АДМИНОВ**\n\n"
                
                # Super admins
                text += "🌟 **СУПЕР-АДМИНЫ:**\n"
                for admin_id in SUPER_ADMINS:
                    text += f"  • `{admin_id}` (глобальный доступ)\n"
                
                text += "\n👥 **ОБЫЧНЫЕ АДМИНЫ:**\n"
                if self.admins:
                    for idx, admin_id in enumerate(self.admins, 1):
                        # Count accounts for this admin
                        admin_accounts = sum(1 for d in self.accounts_data.values() 
                                            if d.get('admin_id') == admin_id)
                        text += f"{idx}. `{admin_id}` — аккаунтов: {admin_accounts}\n"
                else:
                    text += "  • Нет обычных админов\n"
                
                text += f"\n📊 Всего админов: {len(SUPER_ADMINS) + len(self.admins)}"
                
                await event.respond(text)
                
            except Exception as e:
                logger.error(f"List admins error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/removeadmin'))
        async def remove_admin_command(event):
            """Remove an admin (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут удалять админов")
                return
            
            try:
                admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Can't remove super admins
                if admin_id in SUPER_ADMINS:
                    await event.respond("❌ Нельзя удалить супер-админа")
                    return
                
                if admin_id in self.admins:
                    self.admins.remove(admin_id)
                    self.save_data()
                    
                    # Count their accounts
                    admin_accounts = sum(1 for d in self.accounts_data.values() 
                                        if d.get('admin_id') == admin_id)
                    
                    text = f"""✅ **Админ удалён**

👤 ID: `{admin_id}`
📊 У него было аккаунтов: {admin_accounts}

⚠️ Его аккаунты и данные остались в системе
💡 Для полной очистки используйте команды удаления аккаунтов"""
                    
                    await event.respond(text)
                    logger.info(f"Admin removed: {admin_id} by super admin {event.sender_id}")
                else:
                    await event.respond("❌ Этот ID не является админом")
                    
            except Exception as e:
                await event.respond(f"❌ Ошибка: Формат: `/removeadmin 123456789`")
                logger.error(f"Remove admin error: {e}")
        
        @self.bot_client.on(events.NewMessage(pattern='/stats_global'))
        async def stats_global_command(event):
            """Global stats for super admins - same as /stats but explicit"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут видеть глобальную статистику")
                return
            
            # Just call the regular stats command (it already shows global for super admins)
            await show_stats(event)
        
        @self.bot_client.on(events.NewMessage(pattern='/stats_admin'))
        async def stats_admin_command(event):
            """View stats for specific admin (super admins only)"""
        
        # ============= PROFILE CHANNEL COMMANDS =============
        
        # ============= SHOWCASE (UNIFIED PROFILE CHANNEL) COMMANDS =============
        # 
        # ВАЖНО: Разница между /showcase create и /createshowcase:
        # 
        # /showcase create — создаёт обычный канал через create_profile_channel()
        #   • НЕ добавляет автоматически в витрину профиля
        #   • Требует ручного добавления через настройки Telegram
        #   • Сохраняет в account_data['profile_channel']
        #   • Подходит для гибкой настройки
        # 
        # /createshowcase — создаёт showcase-канал через create_showcase_channel()
        #   • ✅ АВТОМАТИЧЕСКИ добавляет в витрину профиля через UpdatePersonalChannelRequest
        #   • Генерирует уникальный username (10 вариантов)
        #   • Сохраняет в account_data['showcase_channel']
        #   • Полностью автоматизирован
        # 
        # Обе команды нужны для разных сценариев использования.
        # ============================================================================
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/showcase(?:\s|$)'))
        async def showcase_command(event):
            """Единая команда для управления витринами-каналами"""
            if not await self.is_admin(event.sender_id):
                return
            
            logger.info(f"🎨 /showcase команда получена от admin {event.sender_id}: {event.text}")
            
            try:
                parts = event.text.split(maxsplit=1)
                
                if len(parts) < 2:
                    await event.respond(
                        "**🎨 УПРАВЛЕНИЕ ВИТРИНАМИ**\n\n"
                        "**Создание и связывание:**\n"
                        "`/showcase create <phone> <название>` - создать новую витрину\n"
                        "`/showcase link <phone> @channel` - привязать существующий канал\n"
                        "`/showcase unlink <phone>` - отвязать витрину\n\n"
                        "**Просмотр:**\n"
                        "`/showcase list` - список всех витрин\n"
                        "`/showcase info <phone>` - информация о витрине\n\n"
                        "**Настройка:**\n"
                        "`/showcase set avatar <phone>` - установить аватар\n"
                        "`/showcase set title <phone> \"Название\"` - изменить название\n"
                        "`/showcase set about <phone> \"Описание\"` - изменить описание\n"
                        "`/showcase set post <phone> \"Текст\"` - создать пост\n"
                        "`/showcase set post_pin <phone> \"Текст\"` - пост с закреплением"
                    )
                    return
                
                args = parts[1].split(maxsplit=1)
                action = args[0].lower()
                
                logger.info(f"🎨 /showcase подкоманда: {action}")
                
                if action == "create":
                    await self._showcase_create(event, args[1] if len(args) > 1 else "")
                elif action == "link":
                    await self._showcase_link(event, args[1] if len(args) > 1 else "")
                elif action == "unlink":
                    await self._showcase_unlink(event, args[1] if len(args) > 1 else "")
                elif action == "list":
                    await self._showcase_list(event)
                elif action == "info":
                    await self._showcase_info(event, args[1] if len(args) > 1 else "")
                elif action == "set":
                    await self._showcase_set(event, args[1] if len(args) > 1 else "")
                else:
                    await event.respond(f"❌ Неизвестная подкоманда: `{action}`\n\nИспользуйте `/showcase` для справки")
                    
            except Exception as e:
                logger.error(f"Showcase command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:200]}")
        
        # ============= END SHOWCASE COMMANDS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/createshowcase'))
        async def createshowcase_command(event):
            """
            Создать индивидуальную витрину-канал для аккаунта.
            Формат: /createshowcase <номер_аккаунта или телефон> [базовый_юзернейм]
            """
            if not await self.is_admin(event.sender_id):
                return
            
            try:
                parts = event.text.split(maxsplit=2)
                
                if len(parts) < 2:
                    await event.respond(
                        "**🎨 СОЗДАНИЕ ИНДИВИДУАЛЬНОЙ ВИТРИНЫ**\n\n"
                        "Формат: `/createshowcase <аккаунт> [базовый_username]`\n\n"
                        "**Примеры:**\n"
                        "`/createshowcase 1` - создать для аккаунта #1 с username 'showcase'\n"
                        "`/createshowcase +13434919340` - создать для конкретного номера\n"
                        "`/createshowcase 1 vitrine` - с кастомным базовым username\n\n"
                        "**Что происходит:**\n"
                        "• Создаётся публичный канал в выбранном аккаунте\n"
                        "• Автоматически генерируется уникальный username\n"
                        "• ⚡ Канал АВТОМАТИЧЕСКИ добавляется в витрину профиля!\n\n"
                        "✅ Никаких ручных действий не требуется - всё полностью автоматически!"
                    )
                    return
                
                account_identifier = parts[1]
                base_username = parts[2] if len(parts) > 2 else 'showcase'
                
                await event.respond(f"⏳ Создаю showcase-канал для аккаунта `{account_identifier}`...")
                
                # Вызываем функцию создания showcase-канала
                success, result = await self.create_showcase_channel(account_identifier, base_username)
                
                if success:
                    channel_info = result
                    
                    text = f"""✅ **ВИТРИНА СОЗДАНА И АВТОМАТИЧЕСКИ ДОБАВЛЕНА**

📱 Аккаунт: `{channel_info['phone']}`
📺 Канал: `{channel_info['title']}`
👤 Username: `@{channel_info['username']}`
🆔 ID: `{channel_info['channel_id']}`

🎉 **КАНАЛ АВТОМАТИЧЕСКИ ДОБАВЛЕН В ВИТРИНУ ПРОФИЛЯ!**

Витрина теперь видна в профиле аккаунта. Никаких ручных действий не требуется!

**📋 Что можно сделать дальше:**

1. **Настроить канал:**
   • Добавьте описание
   • Установите аватар
   • Создайте первый пост

2. **Проверить:**
   • Откройте профиль аккаунта в Telegram
   • Канал должен быть виден в разделе витрины

🔗 Ссылка на канал: https://t.me/{channel_info['username']}

💡 Информация сохранена в bot_data.json"""
                    
                    await event.respond(text)
                    logger.info(f"Showcase channel created by admin {event.sender_id}: @{channel_info['username']} for {channel_info['phone']}")
                else:
                    # Ошибка
                    await event.respond(result)
                    
            except Exception as e:
                logger.error(f"Createshowcase command error: {e}")
                import traceback
                traceback.print_exc()
                await event.respond(f"❌ Ошибка: {str(e)[:300]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/stats_admin'))
        async def stats_admin_command(event):
            """View stats for specific admin (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут просматривать статистику других админов")
                return
            
            try:
                target_admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Filter accounts for this admin
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == target_admin_id}
                
                if not filtered_accounts:
                    await event.respond(f"❌ У админа {target_admin_id} нет аккаунтов")
                    return
                
                text = f"📊 **СТАТИСТИКА АДМИНА {target_admin_id}**\n\n"
                
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                
                # Calculate stats
                if self.conn:
                    try:
                        cursor = self.conn.cursor()
                        
                        # Today's comments
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?",
                            (today_start, target_admin_id)
                        )
                        daily_comments = cursor.fetchone()[0]
                        
                        # Total comments
                        cursor.execute(
                            "SELECT COUNT(*) FROM account_stats WHERE event_type = 'comment_sent' AND admin_id = ?",
                            (target_admin_id,)
                        )
                        total_comments = cursor.fetchone()[0]
                        
                        active_accounts = sum(1 for d in filtered_accounts.values() 
                                            if d.get('status') == ACCOUNT_STATUS_ACTIVE)
                        reserve_accounts = sum(1 for d in filtered_accounts.values() 
                                             if d.get('status') == ACCOUNT_STATUS_RESERVE)
                        broken_accounts = sum(1 for d in filtered_accounts.values() 
                                            if d.get('status') == ACCOUNT_STATUS_BROKEN)
                        
                        text += f"👥 **Аккаунты:**\n"
                        text += f"  • ✅ Активных: {active_accounts}\n"
                        text += f"  • 🔵 Резервных: {reserve_accounts}\n"
                        text += f"  • 🔴 Заблокированных: {broken_accounts}\n\n"
                        
                        text += f"📈 **Комментарии:**\n"
                        text += f"  • Сегодня: {daily_comments}\n"
                        text += f"  • Всего: {total_comments}\n\n"
                        
                        # Top accounts
                        cursor.execute(
                            """SELECT phone, COUNT(*) as count FROM account_stats 
                            WHERE timestamp >= ? AND event_type = 'comment_sent' AND admin_id = ?
                            GROUP BY phone ORDER BY count DESC LIMIT 5""",
                            (today_start, target_admin_id)
                        )
                        top_accounts = cursor.fetchall()
                        
                        if top_accounts:
                            text += "🏆 **Топ аккаунтов сегодня:**\n"
                            for idx, (phone, count) in enumerate(top_accounts, 1):
                                short_phone = phone[-10:] if len(phone) > 10 else phone
                                text += f"  {idx}. `{short_phone}` — {count} комм\n"
                        
                        await event.respond(text)
                        
                    except Exception as e:
                        logger.error(f"Stats admin DB error: {e}")
                        await event.respond(f"❌ Ошибка БД: {str(e)[:100]}")
                else:
                    await event.respond("❌ БД недоступна")
                    
            except ValueError:
                await event.respond("❌ Формат: `/stats_admin 123456789`")
            except Exception as e:
                logger.error(f"Stats admin error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/listaccounts_admin'))
        async def listaccounts_admin_command(event):
            """List accounts for specific admin (super admins only)"""
            if not self.is_super_admin(event.sender_id):
                await event.respond("❌ Только супер-админы могут просматривать аккаунты других админов")
                return
            
            try:
                target_admin_id = int(event.text.split(maxsplit=1)[1])
                
                # Filter accounts for this admin
                filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                   if data.get('admin_id') == target_admin_id}
                
                if not filtered_accounts:
                    await event.respond(f"❌ У админа {target_admin_id} нет аккаунтов")
                    return
                
                text = f"👥 **АККАУНТЫ АДМИНА {target_admin_id}**\n\n"
                text += f"Всего: {len(filtered_accounts)}\n\n"
                
                for i, (phone, data) in enumerate(filtered_accounts.items(), 1):
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    name = data.get('name', 'Не авторизован')
                    username = data.get('username', 'нет')
                    text += f"{i}. {status} `{name}` (@{username})\n`   {phone}`\n"
                
                await event.respond(text)
                
            except ValueError:
                await event.respond("❌ Формат: `/listaccounts_admin 123456789`")
            except Exception as e:
                logger.error(f"Listaccounts admin error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/resetfails'))
        async def reset_fails(event):
            """Reset channel failure counters"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                old_count = len(self.channel_failed_attempts)
                self.channel_failed_attempts.clear()
                
                await event.respond(
                    f"✅ **Счетчики неудач сброшены!**\n\n"
                    f"Очищено записей: {old_count}\n\n"
                    f"💡 Теперь бот будет заново пробовать комментировать все каналы.\n"
                    f"⚠️ Каналы будут блокироваться только после 3+ неудачных попыток с каждого аккаунта."
                )
                logger.info(f"Channel failure counters reset by admin {event.sender_id}")
            except Exception as e:
                logger.error(f"Reset fails error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/showfails'))
        async def show_fails(event):
            """Show current channel failure attempts with detailed info"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                if not self.channel_failed_attempts:
                    await event.respond("✅ Нет записей о неудачных попытках")
                    return
                
                # Sort channels by number of failed accounts (descending)
                sorted_channels = sorted(
                    self.channel_failed_attempts.items(),
                    key=lambda x: len(x[1]),
                    reverse=True
                )
                
                text = f"⚠️ **НЕУДАЧНЫЕ ПОПЫТКИ КОММЕНТИРОВАНИЯ**\n\n"
                text += f"Всего каналов с проблемами: {len(sorted_channels)}\n\n"
                
                # Статистика hot channels
                hot_count = len(self.hot_channels)
                if hot_count > 0:
                    text += f"🔥 Горячих каналов (блокировка 2ч): {hot_count}\n\n"
                
                # Show top 15 problematic channels with details
                for i, (channel, failures) in enumerate(sorted_channels[:15], 1):
                    display_name = channel if channel.startswith('@') else '@' + channel
                    
                    # Count persistent failures (3+ times)
                    persistent = sum(1 for data in failures.values() if data['count'] >= 3)
                    total_accounts = len(failures)
                    
                    text += f"{i}. **{display_name}**\n"
                    text += f"   📊 Аккаунтов с проблемами: {total_accounts} | 🔴 Стабильных неудач: {persistent}\n"
                    
                    # Show most common reason
                    all_reasons = []
                    for data in failures.values():
                        all_reasons.extend(data['reasons'])
                    if all_reasons:
                        reason_counts = {}
                        for r in all_reasons:
                            reason_counts[r] = reason_counts.get(r, 0) + 1
                        sorted_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
                        
                        # Показываем топ-2 причины
                        for reason, count in sorted_reasons[:2]:
                            text += f"   ⚠️ {reason} ({count}x)\n"
                    
                    # Проверяем hot status
                    if channel in self.hot_channels:
                        hot_info = self.hot_channels[channel]
                        cooldown_minutes = int((hot_info['timestamp'] + 2*3600 - datetime.now().timestamp()) / 60)
                        if cooldown_minutes > 0:
                            text += f"   🔥 HOT (разблокировка через {cooldown_minutes}м)\n"
                    
                    # Показываем аккаунты с наибольшими проблемами
                    problematic_accounts = sorted(
                        failures.items(),
                        key=lambda x: x[1]['count'],
                        reverse=True
                    )[:3]
                    
                    if problematic_accounts:
                        text += f"   👥 Проблемные аккаунты: "
                        acc_names = []
                        for phone, data in problematic_accounts:
                            name = self.accounts_data.get(phone, {}).get('name', phone[-4:])
                            count = data['count']
                            acc_names.append(f"{name}({count})")
                        text += ", ".join(acc_names)
                        text += "\n"
                    
                    # Последняя попытка
                    last_timestamp = max(data['last_attempt'] for data in failures.values())
                    time_ago = int((datetime.now().timestamp() - last_timestamp) / 60)
                    if time_ago < 60:
                        text += f"   🕐 Последняя попытка: {time_ago}м назад\n"
                    else:
                        hours_ago = time_ago // 60
                        text += f"   🕐 Последняя попытка: {hours_ago}ч назад\n"
                    
                    text += "\n"
                
                if len(sorted_channels) > 15:
                    text += f"... и еще {len(sorted_channels) - 15} каналов\n\n"
                
                # Рекомендации
                text += f"💡 **Рекомендации:**\n"
                
                # Каналы для удаления
                channels_to_remove = [ch for ch, fails in sorted_channels 
                                     if len(fails) >= 3 and 
                                     sum(1 for d in fails.values() if d['count'] >= 3) >= 2]
                if channels_to_remove:
                    text += f"🗑️ Удалить безнадежные: {len(channels_to_remove)} каналов\n"
                
                # Hot channels
                if hot_count > 0:
                    text += f"⏳ Ждать разблокировки hot: {hot_count} каналов\n"
                
                text += f"🔄 `/resetfails` - очистить счетчики\n"
                text += f"📊 `/incidents all` - история всех инцидентов"
                
                await event.respond(text)
            except Exception as e:
                logger.error(f"Show fails error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/showblacklist'))
        async def show_blacklist(event):
            """Показать блэклист каналов для каждого аккаунта"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                if not self.account_channel_blacklist:
                    await event.respond(
                        "✅ **Блэклист пуст!**\n\n"
                        "Ни один канал не заблокирован для аккаунтов.\n"
                        "Каналы добавляются в блэклист после 3+ постоянных ошибок."
                    )
                    return
                
                text = "🚫 **БЛЭКЛИСТ КАНАЛОВ**\n\n"
                text += "Каналы, которые будут автоматически пропускаться:\n\n"
                
                total_blacklisted = 0
                
                for phone, channels in self.account_channel_blacklist.items():
                    if not channels:
                        continue
                    
                    # Получаем имя аккаунта
                    account_data = self.accounts_data.get(phone, {})
                    account_name = account_data.get('name', phone[-10:])
                    
                    text += f"📱 **{account_name}** ({phone[-10:]})\n"
                    
                    for channel, data in channels.items():
                        display_name = channel if channel.startswith('@') else '@' + channel
                        reason = data.get('reason', 'Unknown')
                        
                        # Форматируем время
                        timestamp = data.get('timestamp', 0)
                        if timestamp:
                            from datetime import datetime
                            time_str = datetime.fromtimestamp(timestamp).strftime('%d.%m %H:%M')
                            text += f"  • {display_name}\n"
                            text += f"    ⚠️ {reason}\n"
                            text += f"    🕐 {time_str}\n"
                        else:
                            text += f"  • {display_name} - {reason}\n"
                        
                        total_blacklisted += 1
                    
                    text += "\n"
                
                text += f"📊 **Итого:** {total_blacklisted} каналов в блэклисте\n\n"
                text += "💡 **Справка:**\n"
                text += "• Каналы добавляются после 3+ постоянных ошибок\n"
                text += "• Аккаунт больше не будет пробовать эти каналы\n"
                text += "• Используйте `/clearblacklist` для очистки\n"
                text += "• Используйте `/showfails` для просмотра текущих неудач"
                
                await event.respond(text)
                
            except Exception as e:
                logger.error(f"Show blacklist error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/clearblacklist'))
        async def clear_blacklist(event):
            """Очистить блэклист каналов"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                if not self.account_channel_blacklist:
                    await event.respond("ℹ️ Блэклист уже пуст")
                    return
                
                # Подсчитываем статистику до очистки
                total_accounts = len(self.account_channel_blacklist)
                total_channels = sum(len(channels) for channels in self.account_channel_blacklist.values())
                
                # Очищаем блэклист
                self.account_channel_blacklist = {}
                
                await event.respond(
                    f"✅ **Блэклист очищен!**\n\n"
                    f"📊 Статистика:\n"
                    f"• Аккаунтов: {total_accounts}\n"
                    f"• Каналов: {total_channels}\n\n"
                    f"💡 Аккаунты теперь будут пробовать все каналы заново.\n"
                    f"⚠️ Помните: каналы с постоянными ошибками снова попадут в блэклист после 3 неудач."
                )
                
                logger.info(f"Blacklist cleared by admin {event.sender_id}: {total_accounts} accounts, {total_channels} channels")
                
            except Exception as e:
                logger.error(f"Clear blacklist error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/clearblocked'))
        async def clear_blocked(event):
            """Clear blocked channels from database"""
            if not await self.is_admin(event.sender_id): return
            
            try:
                if not self.conn:
                    await event.respond("❌ БД недоступна")
                    return
                
                cursor = self.conn.cursor()
                
                # Get count before deletion
                cursor.execute("SELECT COUNT(*) FROM blocked_channels")
                count_before = cursor.fetchone()[0]
                
                # Clear blocked channels table
                cursor.execute("DELETE FROM blocked_channels")
                self.conn.commit()
                
                await event.respond(
                    f"✅ **Заблокированные каналы очищены!**\n\n"
                    f"Удалено записей: {count_before}\n\n"
                    f"💡 Бот теперь будет пробовать комментировать эти каналы снова.\n"
                    f"⚠️ Используйте `/resetfails` чтобы также очистить счетчики неудач."
                )
                logger.info(f"Blocked channels cleared by admin {event.sender_id}")
            except Exception as e:
                logger.error(f"Clear blocked error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        # ============= PROFILE MANAGEMENT COMMANDS =============
        
        @self.bot_client.on(events.NewMessage(pattern='/setname'))
        async def setname_command(event):
            """Шаг 1: Показывает список аккаунтов для выбора"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Determine admin_id for filtering (same as /listaccounts)
                admin_id = self.get_admin_id(event.sender_id)
                
                # Filter accounts by admin_id
                if admin_id is None:  # Super admin - show all
                    filtered_accounts = self.accounts_data
                else:  # Regular admin - show only their accounts
                    filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                       if data.get('admin_id') == admin_id}
                
                # Get accounts with sessions only, sorted for stable order
                all_accounts = [(phone, data) for phone, data in sorted(filtered_accounts.items()) 
                                if data.get('session')]
                
                if not all_accounts:
                    logger.warning(f"⚠️ /setname: у админа {admin_id or 'SUPER'} нет аккаунтов с сессией")
                    await event.respond(
                        "ℹ️ Нет аккаунтов с сохранённой сессией\n\n"
                        f"📊 Всего ваших аккаунтов: {len(filtered_accounts)}\n"
                        "❌ С сессиями: 0\n\n"
                        "💡 Используйте `/auth +номер` для авторизации аккаунта"
                    )
                    return
                
                logger.info(f"✅ /setname: найдено {len(all_accounts)} аккаунтов с сессией")
                # Build accounts list with status indicators
                text = "👤 **ИЗМЕНЕНИЕ ИМЕНИ**\n\n"
                text += "Выберите номер аккаунта:\n\n"
                
                for idx, (phone, data) in enumerate(all_accounts, 1):
                    # Get status indicator like in /listaccounts
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    text += f"{idx}. {status} `{phone}`\n"
                
                text += "\n📝 Ответьте (reply) на это сообщение с номером аккаунта"
                
                # Send message and save state
                msg = await event.respond(text)
                self.user_states[event.sender_id] = {
                    'state': 'waiting_account_selection_for_name',
                    'message_id': msg.id,
                    'accounts': all_accounts
                }
                
            except Exception as e:
                logger.error(f"Setname command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/setbio'))
        async def setbio_command(event):
            """Шаг 1: Показывает список аккаунтов для выбора"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Determine admin_id for filtering (same as /listaccounts)
                admin_id = self.get_admin_id(event.sender_id)
                
                # Filter accounts by admin_id
                if admin_id is None:  # Super admin - show all
                    filtered_accounts = self.accounts_data
                else:  # Regular admin - show only their accounts
                    filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                       if data.get('admin_id') == admin_id}
                
                # Get accounts with sessions only, sorted for stable order
                all_accounts = [(phone, data) for phone, data in sorted(filtered_accounts.items()) 
                                if data.get('session')]
                
                if not all_accounts:
                    logger.warning(f"⚠️ /setbio: у админа {admin_id or 'SUPER'} нет аккаунтов с сессией")
                    await event.respond(
                        "ℹ️ Нет аккаунтов с сохранённой сессией\n\n"
                        f"📊 Всего ваших аккаунтов: {len(filtered_accounts)}\n"
                        "❌ С сессиями: 0\n\n"
                        "💡 Используйте `/auth +номер` для авторизации аккаунта"
                    )
                    return
                
                logger.info(f"✅ /setbio: найдено {len(all_accounts)} аккаунтов с сессией")
                # Build accounts list with status indicators
                text = "📝 **ИЗМЕНЕНИЕ БИО**\n\n"
                text += "Выберите номер аккаунта:\n\n"
                
                for idx, (phone, data) in enumerate(all_accounts, 1):
                    # Get status indicator like in /listaccounts
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    text += f"{idx}. {status} `{phone}`\n"
                
                text += "\n📝 Ответьте (reply) на это сообщение с номером аккаунта"
                
                # Send message and save state
                msg = await event.respond(text)
                self.user_states[event.sender_id] = {
                    'state': 'waiting_account_selection_for_bio',
                    'message_id': msg.id,
                    'accounts': all_accounts
                }
                
            except Exception as e:
                logger.error(f"Setbio command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/setavatar'))
        async def setavatar_command(event):
            """Шаг 1: Показывает список аккаунтов для выбора"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Determine admin_id for filtering (same as /listaccounts)
                admin_id = self.get_admin_id(event.sender_id)
                
                # Filter accounts by admin_id
                if admin_id is None:  # Super admin - show all
                    filtered_accounts = self.accounts_data
                else:  # Regular admin - show only their accounts
                    filtered_accounts = {phone: data for phone, data in self.accounts_data.items()
                                       if data.get('admin_id') == admin_id}
                
                # Get accounts with sessions only, sorted for stable order
                all_accounts = [(phone, data) for phone, data in sorted(filtered_accounts.items()) 
                                if data.get('session')]
                
                if not all_accounts:
                    logger.warning(f"⚠️ /setavatar: у админа {admin_id or 'SUPER'} нет аккаунтов с сессией")
                    await event.respond(
                        "ℹ️ Нет аккаунтов с сохранённой сессией\n\n"
                        f"📊 Всего ваших аккаунтов: {len(filtered_accounts)}\n"
                        "❌ С сессиями: 0\n\n"
                        "💡 Используйте `/auth +номер` для авторизации аккаунта"
                    )
                    return
                
                logger.info(f"✅ /setavatar: найдено {len(all_accounts)} аккаунтов с сессией")
                # Build accounts list with status indicators
                text = "📷 **ЗАГРУЗКА АВАТАРКИ**\n\n"
                text += "Выберите номер аккаунта:\n\n"
                
                for idx, (phone, data) in enumerate(all_accounts, 1):
                    # Get status indicator like in /listaccounts
                    status_val = data.get('status', ACCOUNT_STATUS_RESERVE)
                    if status_val == ACCOUNT_STATUS_ACTIVE:
                        status = "✅"
                    elif status_val == ACCOUNT_STATUS_BROKEN:
                        status = "🔴"
                    else:
                        status = "🔵"
                    
                    text += f"{idx}. {status} `{phone}`\n"
                
                text += "\n📝 Ответьте (reply) на это сообщение с номером аккаунта"
                
                # Send message and save state
                msg = await event.respond(text)
                self.user_states[event.sender_id] = {
                    'state': 'waiting_account_selection_for_avatar',
                    'message_id': msg.id,
                    'accounts': all_accounts
                }
                
            except Exception as e:
                logger.error(f"Setavatar command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        @self.bot_client.on(events.NewMessage(pattern='/profile'))
        async def profile_command(event):
            """Показывает текущую информацию о профилях всех активных аккаунтов"""
            if not await self.is_admin(event.sender_id):
                await event.respond("❌ У вас нет доступа к этому боту.")
                return
            
            try:
                # Get all active accounts (NEW: use status)
                active_accounts = [(phone, data) for phone, data in self.accounts_data.items() 
                                 if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')]
                
                if not active_accounts:
                    await event.respond("❌ Нет активных авторизованных аккаунтов")
                    return
                
                text = f"👥 **ПРОФИЛИ АКТИВНЫХ АККАУНТОВ**\n\n"
                text += f"Всего аккаунтов: {len(active_accounts)}\n\n"
                
                profiles = []
                for phone, data in active_accounts[:10]:  # Limit to 10 for message size
                    try:
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        await client.connect()
                        
                        if await client.is_user_authorized():
                            me = await client.get_me()
                            
                            profile_text = f"📱 `{phone[-4:]}`\n"
                            profile_text += f"👤 {me.first_name or ''} {me.last_name or ''}\n"
                            
                            if me.username:
                                profile_text += f"🔗 @{me.username}\n"
                            
                            bio = me.about or "Не указано"
                            profile_text += f"📝 {bio[:50]}{'...' if len(bio) > 50 else ''}\n"
                            profile_text += f"✅ Статус: Активен\n"
                            
                            profiles.append(profile_text)
                        else:
                            profiles.append(f"📱 `{phone[-4:]}`\n❌ Не авторизован\n")
                        
                        await client.disconnect()
                        
                    except Exception as e:
                        profiles.append(f"📱 `{phone[-4:]}`\n❌ Ошибка: {str(e)[:30]}\n")
                        logger.error(f"Error getting profile for {phone}: {e}")
                
                text += "\n".join(profiles)
                
                if len(active_accounts) > 10:
                    text += f"\n\n... и еще {len(active_accounts) - 10} аккаунтов"
                
                text += f"\n\n💡 Используйте:\n"
                text += f"`/setname` - изменить имя\n"
                text += f"`/setbio` - изменить описание\n"
                text += f"`/setavatar` - загрузить аватар"
                
                await event.respond(text)
                
            except Exception as e:
                logger.error(f"Profile command error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
        
        # Handle text messages for account selection and data input
        @self.bot_client.on(events.NewMessage(func=lambda e: e.text and not e.text.startswith('/') and e.reply_to_msg_id))
        async def handle_profile_input(event):
            """Обрабатывает ввод номера аккаунта и данных профиля"""
            if not await self.is_admin(event.sender_id):
                return
            
            if event.sender_id not in self.user_states:
                return
            
            state_data = self.user_states[event.sender_id]
            state = state_data.get('state')
            
            try:
                # Step 2: Handle account selection (user replied with number)
                if state in ['waiting_account_selection_for_name', 'waiting_account_selection_for_bio', 'waiting_account_selection_for_avatar']:
                    # Check if reply is to our message
                    if event.reply_to_msg_id != state_data.get('message_id'):
                        return
                    
                    # Parse account number
                    try:
                        account_num = int(event.text.strip())
                    except ValueError:
                        await event.respond("❌ Введите число (номер аккаунта)")
                        return
                    
                    accounts = state_data.get('accounts', [])
                    if account_num < 1 or account_num > len(accounts):
                        await event.respond(f"❌ Неверный номер. Выберите от 1 до {len(accounts)}")
                        return
                    
                    # Get selected account
                    selected_phone, selected_data = accounts[account_num - 1]
                    
                    # Log selected account details
                    logger.info(f"PROFILE UPDATE: Account selected - index={account_num}, phone={selected_phone}, "
                               f"status={selected_data.get('status')}, admin_id={selected_data.get('admin_id')}, "
                               f"has_session={bool(selected_data.get('session'))}")
                    
                    # Update state based on command type
                    if state == 'waiting_account_selection_for_name':
                        self.user_states[event.sender_id] = {
                            'state': 'waiting_name_input',
                            'phone': selected_phone,
                            'data': selected_data
                        }
                        await event.respond(
                            f"👤 **Аккаунт {account_num}: `{selected_phone}`**\n\n"
                            f"Отправьте новое имя (и фамилию):\n"
                            f"Например: `Иван Петров`"
                        )
                    elif state == 'waiting_account_selection_for_bio':
                        self.user_states[event.sender_id] = {
                            'state': 'waiting_bio_input',
                            'phone': selected_phone,
                            'data': selected_data
                        }
                        await event.respond(
                            f"📝 **Аккаунт {account_num}: `{selected_phone}`**\n\n"
                            f"Отправьте новое описание (био):\n"
                            f"Например: `Инвестор | Трейдер | Крипто 🚀`"
                        )
                    elif state == 'waiting_account_selection_for_avatar':
                        self.user_states[event.sender_id] = {
                            'state': 'waiting_avatar_photo',
                            'phone': selected_phone,
                            'data': selected_data
                        }
                        await event.respond(
                            f"📷 **Аккаунт {account_num}: `{selected_phone}`**\n\n"
                            f"Отправьте фото для аватарки (jpg, png)"
                        )
                
                # Step 3: Handle data input for selected account
                elif state == 'waiting_name_input':
                    new_name = event.text.strip()
                    phone = state_data.get('phone')
                    data = state_data.get('data')
                    
                    if not new_name:
                        await event.respond("❌ Имя не может быть пустым")
                        return
                    
                    # Parse name
                    name_parts = new_name.split(maxsplit=1)
                    first_name = name_parts[0]
                    last_name = name_parts[1] if len(name_parts) > 1 else ""
                    
                    # ⏰ ПРОВЕРКА RATE LIMITING
                    can_do, wait_time, reason = await self.can_do_profile_operation(phone, 'name')
                    if not can_do:
                        if phone in FROZEN_ACCOUNTS:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` заблокирован Telegram**\n\n"
                                f"⚠️ Этот аккаунт имеет FROZEN блокировку.\n"
                                f"Изменение профиля невозможно.\n\n"
                                f"💡 Рабочие аккаунты: {', '.join(WORKING_ACCOUNTS)}"
                            )
                        elif wait_time:
                            wait_minutes = int(wait_time.total_seconds() / 60)
                            wait_hours = wait_minutes // 60
                            wait_mins_left = wait_minutes % 60
                            
                            if wait_hours > 0:
                                time_str = f"{wait_hours}ч {wait_mins_left}м"
                            else:
                                time_str = f"{wait_minutes} минут"
                            
                            await event.respond(
                                f"⏰ **Слишком частые операции!**\n\n"
                                f"Аккаунт `{phone}` использовался недавно.\n"
                                f"Подождите: **{time_str}**\n\n"
                                f"⚠️ Это защищает аккаунт от блокировки Telegram."
                            )
                        await self.clear_user_state(event.sender_id)
                        return
                    
                    await event.respond("⏳ Обновляю имя...")
                    
                    # Log profile update details
                    logger.info(f"PROFILE UPDATE: cmd=/setname, phone={phone}, "
                               f"status={data.get('status')}, admin_id={data.get('admin_id')}, "
                               f"has_session={bool(data.get('session'))}")
                    
                    # Update profile
                    client = None
                    try:
                        logger.info(f"PROFILE UPDATE: Creating client for phone={phone}")
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        
                        logger.info(f"PROFILE UPDATE: Connecting client for phone={phone}")
                        await client.connect()
                        
                        logger.info(f"PROFILE UPDATE: Checking authorization for phone={phone}")
                        if not await client.is_user_authorized():
                            logger.error(f"PROFILE UPDATE: FAILED - Account {phone} not authorized")
                            await event.respond(f"❌ Аккаунт `{phone}` не авторизован. Возможно, сессия устарела.")
                            await client.disconnect()
                            await self.clear_user_state(event.sender_id)
                            return
                        
                        # Get current name
                        logger.info(f"PROFILE UPDATE: Getting current profile for phone={phone}")
                        me = await client.get_me()
                        logger.info(f"PROFILE UPDATE: Got user object - id={me.id}, username={me.username}, phone={me.phone}")
                        old_name = f"{me.first_name or ''} {me.last_name or ''}".strip()
                        logger.info(f"PROFILE UPDATE: Current name for {phone}: '{old_name}' (first_name='{me.first_name}', last_name='{me.last_name}')")
                        
                        # Update name
                        logger.info(f"PROFILE UPDATE: Calling UpdateProfileRequest for phone={phone}, "
                                   f"first_name='{first_name}', last_name='{last_name}'")
                        logger.info(f"PROFILE UPDATE: About to call UpdateProfileRequest with params: {{first_name: '{first_name}', last_name: '{last_name}'}}")
                        
                        result = await client(UpdateProfileRequest(
                            first_name=first_name,
                            last_name=last_name
                        ))
                        
                        logger.info(f"PROFILE UPDATE: UpdateProfileRequest completed. Result type: {type(result).__name__}")
                        logger.info(f"PROFILE UPDATE: Result object: {result}")
                        
                        # ВЕРИФИКАЦИЯ: Проверяем что профиль реально изменился
                        logger.info(f"PROFILE UPDATE: Verifying name change...")
                        await asyncio.sleep(0.3)  # Пауза для синхронизации
                        me_after = await client.get_me()
                        logger.info(f"PROFILE UPDATE: After update - first_name='{me_after.first_name}', last_name='{me_after.last_name}'")
                        
                        if me_after.first_name == first_name and me_after.last_name == last_name:
                            logger.info(f"PROFILE UPDATE: ✅ VERIFIED - Name REALLY changed for phone={phone}")
                            logger.info(f"PROFILE UPDATE: Old name: '{old_name}'")
                            logger.info(f"PROFILE UPDATE: New name: '{first_name} {last_name}'")
                            
                            # Log to DB
                            await self.log_profile_change(phone, 'name', old_name, new_name, True)
                            
                            await event.respond(
                                f"✅ **Имя обновлено для `{phone}`**\n\n"
                                f"Было: {old_name or '(не задано)'}\n"
                                f"Стало: {first_name} {last_name}\n\n"
                                f"✅ Изменение подтверждено в Telegram"
                            )
                        else:
                            # API вернул success, но имя НЕ изменилось!
                            logger.warning(f"PROFILE UPDATE: ⚠️ FALSE SUCCESS - API OK but name NOT changed!")
                            logger.warning(f"PROFILE UPDATE: Expected: '{first_name} {last_name}'")
                            logger.warning(f"PROFILE UPDATE: Actual: '{me_after.first_name} {me_after.last_name}'")
                            
                            await self.log_profile_change(phone, 'name', old_name, new_name, False)
                            
                            await event.respond(
                                f"⚠️ **API вернул успех, но имя НЕ изменилось для `{phone}`**\n\n"
                                f"Telegram принял запрос, но профиль остался без изменений.\n\n"
                                f"Ожидали: {first_name} {last_name}\n"
                                f"Получили: {me_after.first_name or ''} {me_after.last_name or ''}\n\n"
                                f"💡 Возможно аккаунт имеет скрытые ограничения.\n"
                                f"Попробуйте другой аккаунт."
                            )
                        
                    except Exception as e:
                        await self.log_profile_change(phone, 'name', '', new_name, False)
                        error_msg = str(e)
                        logger.error(f"PROFILE UPDATE: ERROR - Failed to update name for phone={phone}")
                        logger.error(f"PROFILE UPDATE: ERROR Type: {type(e).__name__}")
                        logger.error(f"PROFILE UPDATE: ERROR Message: {error_msg}")
                        import traceback
                        logger.error(f"PROFILE UPDATE: ERROR Traceback:\n{traceback.format_exc()}")
                        
                        # Специальная обработка FROZEN ошибки
                        if "FROZEN" in error_msg or "420" in error_msg:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` не может изменять профиль**\n\n"
                                f"Telegram заблокировал эту функцию для данного аккаунта (FROZEN_METHOD).\n\n"
                                f"💡 Это означает что аккаунт имеет ограничения.\n"
                                f"Попробуйте другой аккаунт или обратитесь к администратору."
                            )
                        else:
                            await event.respond(
                                f"❌ **Ошибка при обновлении имени для `{phone}`**\n\n"
                            f"Тип: {type(e).__name__}\n"
                            f"Сообщение: {str(e)[:200]}"
                        )
                    finally:
                        if client and client.is_connected():
                            logger.info(f"PROFILE UPDATE: Disconnecting client for phone={phone}")
                            await client.disconnect()
                    
                    # Clear state
                    await self.clear_user_state(event.sender_id)
                
                elif state == 'waiting_bio_input':
                    new_bio = event.text.strip()
                    phone = state_data.get('phone')
                    data = state_data.get('data')
                    
                    if not new_bio:
                        await event.respond("❌ Описание не может быть пустым")
                        return
                    
                    # ⏰ ПРОВЕРКА RATE LIMITING
                    can_do, wait_time, reason = await self.can_do_profile_operation(phone, 'bio')
                    if not can_do:
                        if phone in FROZEN_ACCOUNTS:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` заблокирован Telegram**\n\n"
                                f"⚠️ Этот аккаунт имеет FROZEN блокировку.\n"
                                f"Изменение профиля невозможно.\n\n"
                                f"💡 Рабочие аккаунты: {', '.join(WORKING_ACCOUNTS)}"
                            )
                        elif wait_time:
                            wait_minutes = int(wait_time.total_seconds() / 60)
                            wait_hours = wait_minutes // 60
                            wait_mins_left = wait_minutes % 60
                            
                            if wait_hours > 0:
                                time_str = f"{wait_hours}ч {wait_mins_left}м"
                            else:
                                time_str = f"{wait_minutes} минут"
                            
                            await event.respond(
                                f"⏰ **Слишком частые операции!**\n\n"
                                f"Аккаунт `{phone}` использовался недавно.\n"
                                f"Подождите: **{time_str}**\n\n"
                                f"⚠️ Это защищает аккаунт от блокировки Telegram.\n\n"
                                f"Лимиты:\n"
                                f"• BIO: не чаще 1 раза в час\n"
                                f"• NAME: не чаще 1 раза в час\n"
                                f"• AVATAR: не чаще 1 раза в день"
                            )
                        await self.clear_user_state(event.sender_id)
                        return
                    
                    await event.respond("⏳ Обновляю био...")
                    
                    # Log profile update details
                    logger.info(f"PROFILE UPDATE: cmd=/setbio, phone={phone}, "
                               f"status={data.get('status')}, admin_id={data.get('admin_id')}, "
                               f"has_session={bool(data.get('session'))}, bio_length={len(new_bio)}")
                    
                    # Update profile
                    client = None
                    try:
                        logger.info(f"PROFILE UPDATE: Creating client for phone={phone}")
                        client = TelegramClient(
                            StringSession(data['session']), 
                            API_ID, 
                            API_HASH,
                            proxy=data.get('proxy')
                        )
                        
                        logger.info(f"PROFILE UPDATE: Connecting client for phone={phone}")
                        await client.connect()
                        
                        logger.info(f"PROFILE UPDATE: Checking authorization for phone={phone}")
                        if not await client.is_user_authorized():
                            logger.error(f"PROFILE UPDATE: FAILED - Account {phone} not authorized")
                            await event.respond(f"❌ Аккаунт `{phone}` не авторизован. Возможно, сессия устарела.")
                            await client.disconnect()
                            await self.clear_user_state(event.sender_id)
                            return
                        
                        # Get current bio (if possible)
                        logger.info(f"PROFILE UPDATE: Getting current profile for phone={phone}")
                        me = await client.get_me()
                        # Note: me.about might not be available, need to use GetFullUserRequest
                        full = await client(GetFullUserRequest(me))
                        old_bio = full.full_user.about or ''
                        logger.info(f"PROFILE UPDATE: Current bio for {phone}: '{old_bio[:50]}...'")
                        
                        # Update bio
                        logger.info(f"PROFILE UPDATE: Calling UpdateProfileRequest for phone={phone} with bio='{new_bio[:50]}...'")
                        
                        result = await client(UpdateProfileRequest(about=new_bio))
                        
                        logger.info(f"PROFILE UPDATE: UpdateProfileRequest result type: {type(result).__name__}")
                        
                        # ВЕРИФИКАЦИЯ: проверяем что профиль реально изменился
                        logger.info(f"PROFILE UPDATE: Verifying bio change...")
                        await asyncio.sleep(0.3)  # Пауза для синхронизации
                        full_after = await client(GetFullUserRequest(me))
                        actual_bio = full_after.full_user.about or ''
                        
                        if actual_bio == new_bio:
                            logger.info(f"PROFILE UPDATE: SUCCESS - Bio VERIFIED changed for phone={phone}")
                            logger.info(f"PROFILE UPDATE: Old bio: '{old_bio[:50]}...'")
                            logger.info(f"PROFILE UPDATE: New bio: '{actual_bio[:50]}...'")
                            
                            # Log to DB
                            await self.log_profile_change(phone, 'bio', old_bio, new_bio, True)
                            
                            await event.respond(
                                f"✅ **Био обновлено для `{phone}`**\n\n"
                                f"Было: {old_bio[:50]}...\n"
                                f"Стало: {new_bio[:150]}\n\n"
                                f"✅ Изменение подтверждено в Telegram"
                            )
                        else:
                            # API вернул success, но профиль НЕ изменился!
                            logger.warning(f"PROFILE UPDATE: FALSE SUCCESS - API OK but bio NOT changed!")
                            logger.warning(f"PROFILE UPDATE: Expected: '{new_bio}'")
                            logger.warning(f"PROFILE UPDATE: Actual: '{actual_bio}'")
                            
                            await self.log_profile_change(phone, 'bio', old_bio, new_bio, False)
                            
                            await event.respond(
                                f"⚠️ **API вернул успех, но био НЕ изменилось для `{phone}`**\n\n"
                                f"Telegram принял запрос, но профиль остался без изменений.\n\n"
                                f"Ожидали: {new_bio[:100]}\n"
                                f"Получили: {actual_bio[:100]}\n\n"
                                f"💡 Возможно аккаунт имеет скрытые ограничения.\n"
                                f"Попробуйте другой аккаунт."
                            )
                        
                    except Exception as e:
                        await self.log_profile_change(phone, 'bio', '', new_bio, False)
                        error_msg = str(e)
                        error_type = type(e).__name__
                        
                        logger.error(f"PROFILE UPDATE: ERROR - Failed to update bio for phone={phone}")
                        logger.error(f"PROFILE UPDATE: ERROR Type: {error_type}")
                        logger.error(f"PROFILE UPDATE: ERROR Message: {error_msg}")
                        import traceback
                        logger.error(f"PROFILE UPDATE: ERROR Traceback:\n{traceback.format_exc()}")
                        
                        # Детальная обработка конкретных ошибок
                        if "ABOUT_TOO_LONG" in error_msg:
                            await event.respond(
                                f"❌ **Био слишком длинное для `{phone}`**\n\n"
                                f"📏 Длина: {len(new_bio)} символов\n"
                                f"⚠️ Telegram: максимум 70 символов\n\n"
                                f"💡 Сократите текст и попробуйте снова"
                            )
                        elif "FROZEN" in error_msg or "USER_DEACTIVATED" in error_msg:
                            await event.respond(
                                f"❌ **Аккаунт `{phone}` заморожен/деактивирован**\n\n"
                                f"⚠️ Telegram полностью ограничил этот аккаунт\n"
                                f"🚫 Изменение профиля невозможно\n\n"
                                f"💡 Используйте другой активный аккаунт"
                            )
                        elif "FLOOD_WAIT" in error_msg:
                            # Извлекаем время ожидания из ошибки
                            import re
                            wait_match = re.search(r'(\d+)', error_msg)
                            wait_seconds = int(wait_match.group(1)) if wait_match else 60
                            wait_minutes = wait_seconds // 60
                            
                            await event.respond(
                                f"⏰ **Флуд-контроль Telegram для `{phone}`**\n\n"
                                f"⚠️ Слишком частые изменения профиля\n"
                                f"⏳ Подождите: {wait_minutes} минут ({wait_seconds} сек)\n\n"
                                f"💡 Это ограничение самого Telegram, не бота"
                            )
                        elif "AUTH_KEY_UNREGISTERED" in error_msg:
                            await event.respond(
                                f"❌ **Сессия `{phone}` недействительна**\n\n"
                                f"🔑 Аккаунт разлогинен в Telegram\n"
                                f"⚠️ Требуется повторная авторизация\n\n"
                                f"💡 Используйте /auth {phone} для входа заново"
                            )
                        elif "PHONE_NUMBER_BANNED" in error_msg:
                            await event.respond(
                                f"🚫 **Аккаунт `{phone}` забанен в Telegram**\n\n"
                                f"⛔ Номер заблокирован на уровне Telegram\n"
                                f"❌ Использование невозможно\n\n"
                                f"💡 Этот аккаунт нужно пометить как broken"
                            )
                        else:
                            await event.respond(
                                f"❌ **Ошибка при обновлении био для `{phone}`**\n\n"
                                f"Тип ошибки: `{error_type}`\n"
                                f"Сообщение: `{error_msg[:200]}`\n\n"
                                f"📋 Детали записаны в лог\n\n"
                                f"💡 Попробуйте:\n"
                                f"• Другой аккаунт\n"
                                f"• Более короткий текст\n"
                                f"• Подождать 1 час"
                            )
                    finally:
                        if client and client.is_connected():
                            logger.info(f"PROFILE UPDATE: Disconnecting client for phone={phone}")
                            await client.disconnect()
                    
                    # Clear state
                    await self.clear_user_state(event.sender_id)
                    
            except Exception as e:
                logger.error(f"Handle profile input error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                await self.clear_user_state(event.sender_id)
        
        # Handle photo upload for avatar
        @self.bot_client.on(events.NewMessage(func=lambda e: e.photo))
        async def handle_avatar_photo(event):
            """Обрабатывает загрузку фото для аватарки выбранного аккаунта"""
            if not await self.is_admin(event.sender_id):
                return
            
            if event.sender_id not in self.user_states:
                return
            
            state_data = self.user_states[event.sender_id]
            state = state_data.get('state')
            
            if state != 'waiting_avatar_photo':
                return
            
            try:
                phone = state_data.get('phone')
                data = state_data.get('data')
                
                # Log profile update details
                logger.info(f"PROFILE UPDATE: cmd=/setavatar, phone={phone}, "
                           f"status={data.get('status')}, admin_id={data.get('admin_id')}, "
                           f"has_session={bool(data.get('session'))}")
                
                # Download photo
                logger.info(f"PROFILE UPDATE: Downloading photo for phone={phone}")
                photo_path = await event.download_media(file=f"/tmp/avatar_{event.sender_id}.jpg")
                
                if not photo_path or not os.path.exists(photo_path):
                    logger.error(f"PROFILE UPDATE: FAILED - Photo download failed for phone={phone}")
                    await event.respond("❌ Ошибка загрузки фото")
                    await self.clear_user_state(event.sender_id)
                    return
                
                logger.info(f"PROFILE UPDATE: Photo downloaded to {photo_path} for phone={phone}")
                
                # ✅ ЗАЩИТА: Проверяем rate limiting перед загрузкой аватара
                can_do, wait_time, reason = await self.can_do_profile_operation(phone, 'avatar')
                if not can_do:
                    if phone in FROZEN_ACCOUNTS:
                        await event.respond(
                            f"❌ Аккаунт `{phone}` заблокирован Telegram для изменения аватара.\n\n"
                            f"**Причина:** {reason}\n\n"
                            f"🔧 **Что делать:**\n"
                            f"1. Используйте другой аккаунт из списка\n"
                            f"2. Или получите новый незаблокированный аккаунт"
                        )
                        # Clean up temp file
                        try:
                            os.remove(photo_path)
                        except:
                            pass
                        await self.clear_user_state(event.sender_id)
                        return
                    elif wait_time:
                        hours = int(wait_time.total_seconds() // 3600)
                        minutes = int((wait_time.total_seconds() % 3600) // 60)
                        wait_msg = f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"
                        await event.respond(
                            f"⏰ Аккаунт `{phone}` можно использовать для аватара через {wait_msg}\n\n"
                            f"**Причина:** {reason}\n\n"
                            f"Лимит: 1 раз в 24 часа (защита от блокировки)"
                        )
                        # Clean up temp file
                        try:
                            os.remove(photo_path)
                        except:
                            pass
                        await self.clear_user_state(event.sender_id)
                        return
                
                await event.respond("⏳ Загружаю аватарку...")
                
                # Upload to selected account
                client = None
                try:
                    logger.info(f"PROFILE UPDATE: Creating client for phone={phone}")
                    client = TelegramClient(
                        StringSession(data['session']), 
                        API_ID, 
                        API_HASH,
                        proxy=data.get('proxy')
                    )
                    
                    logger.info(f"PROFILE UPDATE: Connecting client for phone={phone}")
                    await client.connect()
                    
                    logger.info(f"PROFILE UPDATE: Checking authorization for phone={phone}")
                    if not await client.is_user_authorized():
                        logger.error(f"PROFILE UPDATE: FAILED - Account {phone} not authorized")
                        await event.respond(f"❌ Аккаунт `{phone}` не авторизован. Возможно, сессия устарела.")
                        await client.disconnect()
                        await self.clear_user_state(event.sender_id)
                        # Clean up temp file
                        try:
                            os.remove(photo_path)
                        except:
                            pass
                        return
                    
                    # Upload profile photo using upload_profile_photo method
                    logger.info(f"PROFILE UPDATE: Uploading photo file for phone={phone}")
                    
                    # Получаем количество фото ДО загрузки
                    photos_before = await client.get_profile_photos('me')
                    count_before = len(photos_before)
                    logger.info(f"PROFILE UPDATE: Photos count BEFORE: {count_before}")
                    
                    uploaded_file = await client.upload_file(photo_path)
                    logger.info(f"PROFILE UPDATE: File uploaded, type: {type(uploaded_file).__name__}")
                    
                    logger.info(f"PROFILE UPDATE: Calling UploadProfilePhotoRequest for phone={phone}")
                    result = await client(UploadProfilePhotoRequest(file=uploaded_file))
                    
                    logger.info(f"PROFILE UPDATE: UploadProfilePhotoRequest result type: {type(result).__name__}")
                    
                    # ВЕРИФИКАЦИЯ: Проверяем что фото реально добавилось
                    logger.info(f"PROFILE UPDATE: Verifying avatar upload...")
                    await asyncio.sleep(0.5)  # Пауза для синхронизации
                    photos_after = await client.get_profile_photos('me')
                    count_after = len(photos_after)
                    logger.info(f"PROFILE UPDATE: Photos count AFTER: {count_after}")
                    
                    if count_after > count_before:
                        logger.info(f"PROFILE UPDATE: ✅ VERIFIED - Avatar REALLY uploaded for phone={phone}")
                        logger.info(f"PROFILE UPDATE: Photos before: {count_before}, after: {count_after}")
                        
                        # Log to DB
                        await self.log_profile_change(phone, 'avatar', '', 'uploaded', True)
                        
                        await event.respond(
                            f"✅ **Аватарка загружена для `{phone}`**\n\n"
                            f"Было фото: {count_before}\n"
                            f"Стало фото: {count_after}\n\n"
                            f"✅ Загрузка подтверждена в Telegram"
                        )
                    else:
                        # API вернул success, но фото НЕ добавилось!
                        logger.warning(f"PROFILE UPDATE: ⚠️ FALSE SUCCESS - API OK but avatar NOT uploaded!")
                        logger.warning(f"PROFILE UPDATE: Photos before: {count_before}, after: {count_after}")
                        
                        await self.log_profile_change(phone, 'avatar', '', '', False)
                        
                        await event.respond(
                            f"⚠️ **API вернул успех, но аватарка НЕ загружена для `{phone}`**\n\n"
                            f"Telegram принял запрос, но фото не появилось в профиле.\n\n"
                            f"Количество фото: до={count_before}, после={count_after}\n\n"
                            f"💡 Возможно аккаунт имеет скрытые ограничения.\n"
                            f"Попробуйте другой аккаунт."
                        )
                    
                except Exception as e:
                    await self.log_profile_change(phone, 'avatar', '', '', False)
                    error_msg = str(e)
                    logger.error(f"PROFILE UPDATE: ERROR - Failed to upload avatar for phone={phone}")
                    logger.error(f"PROFILE UPDATE: ERROR Type: {type(e).__name__}")
                    logger.error(f"PROFILE UPDATE: ERROR Message: {error_msg}")
                    import traceback
                    logger.error(f"PROFILE UPDATE: ERROR Traceback:\n{traceback.format_exc()}")
                    
                    # Специальная обработка FROZEN ошибки
                    if "FROZEN" in error_msg or "420" in error_msg:
                        await event.respond(
                            f"❌ **Загрузка АВАТАРА заблокирована для `{phone}`**\n\n"
                            f"⚠️ Telegram ограничил UploadProfilePhotoRequest для этого аккаунта.\n\n"
                            f"💡 Возможно работают другие операции:\n"
                            f"• Попробуйте /setname или /setbio\n"
                            f"• Или выберите другой аккаунт для /setavatar"
                        )
                    else:
                        await event.respond(
                            f"❌ **Ошибка при загрузке аватарки для `{phone}`**\n\n"
                            f"Тип: {type(e).__name__}\n"
                            f"Сообщение: {error_msg[:200]}"
                        )
                finally:
                    if client and client.is_connected():
                        logger.info(f"PROFILE UPDATE: Disconnecting client for phone={phone}")
                        await client.disconnect()
                    
                    # Clean up temp file
                    try:
                        if photo_path and os.path.exists(photo_path):
                            os.remove(photo_path)
                            logger.info(f"PROFILE UPDATE: Temp file removed: {photo_path}")
                    except Exception as cleanup_error:
                        logger.warning(f"PROFILE UPDATE: Failed to remove temp file: {cleanup_error}")
                
                # Clear state
                await self.clear_user_state(event.sender_id)
                
            except Exception as e:
                logger.error(f"Handle avatar photo error: {e}")
                await event.respond(f"❌ Ошибка: {str(e)[:100]}")
                await self.clear_user_state(event.sender_id)
        
        # ============= END PROFILE MANAGEMENT COMMANDS =============
        
        # Log successful handler registration
        logger.info("=" * 80)
        logger.info("✅ ALL COMMAND HANDLERS REGISTERED SUCCESSFULLY")
        logger.info("Total handlers: 71 (via Telethon @self.bot_client.on() decorators)")
        logger.info("Key handlers: /auth, /start, /testmode, /addcomment, /setname, etc.")
        logger.info("=" * 80)
    
    async def auto_stop_after_4_hours(self, chat_id):
        """Automatically stop monitoring after 4 hours"""
        try:
            # Disabled for maximum runtime - bot runs indefinitely
            return  # Skip auto-stop
            
            if self.monitoring:  # Check if still running
                self.monitoring = False
                elapsed_time = datetime.now() - self.monitoring_start_time if self.monitoring_start_time else None
                
                msg = f"""⏱ АВТОКОММЕНТАРИИ ОСТАНОВЛЕНЫ\n\n✅ Работа завершена автоматически после 4 часов\n\n📊 Статистика сессии:\n• Комментариев сегодня: `{self.stats.get('daily_comments', 0)}`\n• Всего комментариев: `{self.stats.get('total_comments', 0)}`"""
                
                await self.bot_client.send_message(chat_id, msg)
                logger.info("Monitoring auto-stopped after 4 hours")
        except Exception as e:
            logger.error(f"Auto-stop error: {e}")
    
    def generate_comment_variation(self, template):
        """Generate natural variations of comments to avoid detection"""
        # Add random spaces, emojis, or punctuation variations
        variations = [
            template,  # Original
            template + " 😊",
            template + "!",
            template.replace("!", " !"),
            template + " ❤️",
        ]
        
        # Add trailing spaces or line breaks sometimes (natural typing)
        if random.random() < 0.3:
            variations.append(template + " ")
        
        # Randomly capitalize first letter differently
        if random.random() < 0.2 and len(template) > 0:
            variations.append(template[0].lower() + template[1:] if template[0].isupper() else template[0].upper() + template[1:])
        
        return random.choice(variations)
    
    async def account_worker(self, phone, account_data, all_channels, worker_index, total_workers, mode='distributed'):
        """Worker function: processes channels based on mode (cyclic or distributed)"""
        import traceback
        
        account_name = account_data.get('name', phone[-10:])
        worker_task_name = f"worker_{worker_index}_{phone[-10:]}"
        
        logger.info("="*80)
        logger.info(f"🚀 WORKER PROCESS STARTING")
        logger.info(f"   Worker ID: {worker_task_name}")
        logger.info(f"   Account: {account_name} ({phone})")
        logger.info(f"   Status: {account_data.get('status', 'UNKNOWN')}")
        logger.info(f"   Task ID: {id(asyncio.current_task())}")
        logger.info(f"   Index: {worker_index + 1}/{total_workers}")
        logger.info(f"   Mode: {mode.upper()}")
        logger.info("="*80)
        
        # Create Telethon client once
        worker_client = None
        
        try:
            # В distributed режиме делим каналы между воркерами
            if mode == 'distributed':
                channels_per_worker = len(all_channels) // total_workers
                remainder = len(all_channels) % total_workers
                
                start_idx = worker_index * channels_per_worker + min(worker_index, remainder)
                end_idx = start_idx + channels_per_worker + (1 if worker_index < remainder else 0)
                my_channels = all_channels[start_idx:end_idx]
                
                logger.info("="*60)
                logger.info(f"WORKER STARTED: account={phone}, parallel_idx={worker_index+1}/{total_workers}")
                logger.info(f"   Name: {account_name}")
                logger.info(f"   Mode: DISTRIBUTED (dedicated channels)")
                logger.info(f"   My channels: {start_idx+1}-{end_idx} ({len(my_channels)} total)")
                logger.info(f"   Status: {account_data.get('status', 'unknown')}")
                logger.info("="*60)
            else:  # cyclic mode
                my_channels = all_channels
                logger.info("="*60)
                logger.info(f"WORKER STARTED: account={phone}, parallel_idx={worker_index+1}/{total_workers}")
                logger.info(f"   Name: {account_name}")
                logger.info(f"   Mode: CYCLIC (all channels with offset)")
                logger.info(f"   Total channels: {len(all_channels)}")
                logger.info(f"   Offset: starts from channel #{(worker_index % len(all_channels)) + 1}")
                logger.info(f"   Status: {account_data.get('status', 'unknown')}")
                logger.info("="*60)
            
            # Offset delay to spread workers
            initial_offset = worker_index * 10
            if initial_offset > 0:
                logger.info(f"[{account_name}] Offset delay: {initial_offset}s")
                await asyncio.sleep(initial_offset)
            
            # Получаем или создаем клиент (один на аккаунт, переиспользуется всеми воркерами)
            if phone not in self.account_clients:
                logger.info(f"🔌 [{account_name}] Создание НОВОГО клиента для {phone}...")
                try:
                    worker_client = TelegramClient(
                        StringSession(account_data['session']), 
                        API_ID, 
                        API_HASH,
                        proxy=account_data.get('proxy'),
                        connection_retries=5,
                        retry_delay=3
                    )
                    
                    await worker_client.connect()
                    
                    if not await worker_client.is_user_authorized():
                        logger.error(f"❌ [{account_name}] Account not authorized! Marking as BROKEN")
                        # Автоматически помечаем аккаунт как сломанный
                        account_data['status'] = ACCOUNT_STATUS_BROKEN
                        self.save_data()
                        
                        # Уведомляем админа
                        try:
                            await self.bot_client.send_message(
                                BOT_OWNER_ID,
                                f"⚠️ **АККАУНТ ПОТЕРЯЛ АВТОРИЗАЦИЮ**\n\n"
                                f"Аккаунт: `{account_name}`\n"
                                f"Телефон: `{phone}`\n\n"
                                f"❌ Статус изменён на: **BROKEN**\n"
                                f"💡 Используйте `/auth {phone}` для реавторизации\n"
                                f"💡 Или `/toggleaccount {phone}` для активации после входа"
                            )
                        except:
                            pass
                        
                        return
                    
                    self.account_clients[phone] = worker_client
                    logger.info(f"✅ [{account_name}] Клиент создан и сохранён для переиспользования")
                    
                except Exception as conn_error:
                    if 'AuthKeyDuplicated' in str(conn_error):
                        logger.error(f"❌ [{account_name}] AuthKeyDuplicatedError - аккаунт используется в другом месте")
                        logger.error(f"   Пропускаю этот аккаунт...")
                    else:
                        logger.error(f"❌ [{account_name}] Ошибка подключения: {conn_error}")
                        import traceback
                        logger.error(traceback.format_exc())
                    return
            else:
                worker_client = self.account_clients[phone]
                logger.info(f"♻️ [{account_name}] Переиспользую существующий клиент")
                
                # КРИТИЧНО: Проверяем подключён ли клиент
                if not worker_client.is_connected():
                    logger.warning(f"⚠️ [{account_name}] Клиент отключён, переподключаюсь...")
                    try:
                        await worker_client.connect()
                        logger.info(f"✅ [{account_name}] Клиент успешно переподключён")
                    except Exception as reconnect_err:
                        logger.error(f"❌ [{account_name}] Ошибка переподключения: {reconnect_err}")
                        # Удаляем из кэша и пытаемся создать заново
                        del self.account_clients[phone]
                        logger.info(f"🔄 [{account_name}] Создаю новый клиент...")
                        try:
                            worker_client = TelegramClient(
                                StringSession(account_data['session']),
                                API_ID,
                                API_HASH,
                                proxy=account_data.get('proxy'),
                                connection_retries=5,
                                retry_delay=3
                            )
                            await worker_client.connect()
                            self.account_clients[phone] = worker_client
                            logger.info(f"✅ [{account_name}] Новый клиент создан и подключён")
                        except Exception as new_client_err:
                            logger.error(f"❌ [{account_name}] Не удалось создать новый клиент: {new_client_err}")
                            return
            
            logger.info(f"[{account_name}] Client ready")
            
            # Main cycle loop
            cycle_number = 0
            max_cycles = self.max_cycles_per_worker
            
            while self.monitoring:
                # Проверка лимита циклов (если установлен)
                if max_cycles > 0 and cycle_number >= max_cycles:
                    logger.info("="*60)
                    logger.info(f"[{account_name}] ROTATION: completed {max_cycles} cycles")
                    logger.info(f"[{account_name}] Moving to reserve, next account will take over")
                    logger.info(f"[{account_name}] Worker index: {worker_index}, Mode: {mode}")
                    logger.info("="*60)
                    
                    # Помечаем что этот воркер завершает циклы (для health_check)
                    self.workers_completing_cycles.add(phone)
                    
                    # Переводим себя в резерв (только если не BROKEN!)
                    current_status = self.accounts_data.get(phone, {}).get('status', ACCOUNT_STATUS_RESERVE)
                    if current_status == ACCOUNT_STATUS_BROKEN:
                        logger.warning(f"⚠️ [{account_name}] Account is BROKEN, not moving to RESERVE")
                        logger.warning(f"   Worker will exit without rotation")
                        # Не пытаемся активировать замену - просто выходим
                        logger.info(f"🛑 [{account_name}] Worker completing, exiting cycle loop")
                        break
                    else:
                        self.set_account_status(phone, ACCOUNT_STATUS_RESERVE, "Completed max cycles")
                        logger.info(f"✅ [{account_name}] Status changed: ACTIVE → RESERVE")
                    
                    # Проверяем, не превышен ли лимит активных аккаунтов
                    active_count = len([p for p, d in self.accounts_data.items() 
                                      if d.get('status') == ACCOUNT_STATUS_ACTIVE and d.get('session')])
                    
                    if active_count >= self.max_parallel_accounts:
                        logger.warning(f"⚠️ [{account_name}] Active accounts limit reached ({active_count}/{self.max_parallel_accounts})")
                        logger.warning(f"   Not activating replacement, redistributing channels instead")
                        await self.redistribute_channels_to_active_workers(worker_index, my_channels)
                    else:
                        # Активируем следующий резервный аккаунт и запускаем замену
                        logger.info(f"🔄 [{account_name}] Attempting to activate replacement account...")
                        try:
                            # ВАЖНО: Исключаем текущий аккаунт из выбора (он только что стал резервным)
                            new_phone = await self.activate_next_reserve_account(exclude_phone=phone)
                            if new_phone:
                                logger.info(f"✅ [{account_name}] New account activated: {new_phone}")
                                logger.info(f"🚀 [{account_name}] Launching replacement worker...")
                                # Запускаем нового worker'а на замену в том же слоте
                                success = await self.launch_replacement_worker(worker_index, my_channels, mode, total_workers)
                                if success:
                                    logger.info(f"✅ [{account_name}] Replacement worker launched successfully")
                                else:
                                    logger.warning(f"⚠️ [{account_name}] Replacement worker launch failed, channels redistributed")
                            else:
                                logger.warning(f"⚠️ [{account_name}] No reserve accounts available!")
                                logger.warning(f"   Redistributing {len(my_channels)} channels to active workers...")
                                await self.redistribute_channels_to_active_workers(worker_index, my_channels)
                        except Exception as activate_err:
                            logger.error(f"❌ [{account_name}] Failed to activate and launch replacement: {activate_err}")
                            import traceback
                            logger.error(traceback.format_exc())
                            # В случае ошибки - перераспределяем каналы
                            try:
                                await self.redistribute_channels_to_active_workers(worker_index, my_channels)
                            except Exception as redist_err:
                                logger.error(f"Failed to redistribute channels: {redist_err}")
                    
                    logger.info(f"🛑 [{account_name}] Worker completing, exiting cycle loop")
                    break
                
                cycle_number += 1
                commented_channels = []
                
                # Сохраняем информацию о текущем worker'е для возможной замены
                self.worker_slots[worker_index] = {
                    'phone': phone,
                    'channels': my_channels,
                    'mode': mode,
                    'total_workers': total_workers,
                    'cycle_number': cycle_number,
                    'current_channel_index': 0  # Будет обновляться в процессе
                }
                
                logger.info("="*60)
                logger.info(f"[{account_name}] CYCLE #{cycle_number} STARTED")
                logger.info(f"[{account_name}] Channels: {len(my_channels)}")
                if max_cycles > 0:
                    logger.info(f"[{account_name}] Progress: {cycle_number}/{max_cycles} cycles")
                else:
                    logger.info(f"[{account_name}] Mode: Infinite (no auto-rotation)")
                logger.info("="*60)
                
                # Check account status
                current_status = self.get_account_status(phone)
                if current_status != ACCOUNT_STATUS_ACTIVE:
                    logger.warning(f"[{account_name}] Status: {current_status}, pausing...")
                    await asyncio.sleep(30)
                    continue
                
                # Process channels based on mode
                if mode == 'cyclic':
                    # В cyclic режиме используем offset для распределения
                    start_offset = worker_index % len(my_channels)
                else:
                    # В distributed режиме обрабатываем последовательно
                    start_offset = 0
                
                for step, idx in enumerate(range(len(my_channels)), 1):
                    if not self.monitoring:
                        break
                    
                    # Check status before each comment
                    current_status = self.get_account_status(phone)
                    if current_status != ACCOUNT_STATUS_ACTIVE:
                        logger.info(f"[{account_name}] Status changed, stopping cycle")
                        break
                    
                    # Check rate limit
                    can_send, wait_time = self.can_account_send_message(phone)
                    if not can_send:
                        logger.warning(f"[{account_name}] Rate limit. Wait: {wait_time}s")
                        await asyncio.sleep(min(wait_time + 10, 300))
                        can_send, wait_time = self.can_account_send_message(phone)
                        if not can_send:
                            logger.info(f"[{account_name}] Still limited, skipping")
                            continue
                    
                    # Get channel with offset
                    channel_idx = (start_offset + idx) % len(my_channels)
                    channel = my_channels[channel_idx]
                    
                    # Обновляем текущую позицию в слоте (для продолжения с этого места при замене)
                    if worker_index in self.worker_slots:
                        self.worker_slots[worker_index]['current_channel_index'] = channel_idx
                    
                    # Normalize channel
                    if isinstance(channel, dict):
                        username = channel.get('username') or channel.get('name')
                    else:
                        username = str(channel)
                    username = str(username).strip().lstrip('@')
                    
                    # ============= NEW: ПРОВЕРКА ГОРЯЧИХ КАНАЛОВ =============
                    # Проверяем, не является ли канал "горячим" (недавний FloodWait)
                    is_hot, cooldown_minutes = self.is_channel_hot(username)
                    if is_hot:
                        logger.info(
                            f"[{account_name}] 🔥 @{username} is HOT (cooldown: {cooldown_minutes} min), skipping"
                        )
                        continue
                    # ============= END ПРОВЕРКА ГОРЯЧИХ КАНАЛОВ =============
                    
                    # ============= NEW: ПРОВЕРКИ ПЕРЕД ОТПРАВКОЙ =============
                    # 1. Проверка блэклиста для этого аккаунта
                    is_blacklisted, blacklist_reason = self.is_channel_blacklisted_for_account(phone, username)
                    if is_blacklisted:
                        logger.info(
                            f"[{account_name}] @{username} в блэклисте (причина: {blacklist_reason}), пропускаю"
                        )
                        continue
                    
                    # 2. Проверка недавних FloodWait на этом канале
                    if self.has_recent_floodwait(phone, username, within_minutes=30):
                        logger.info(
                            f"[{account_name}] @{username} недавний FloodWait, пропускаю"
                        )
                        continue
                    # ============= END NEW =============
                    
                    # Anti-spam protection
                    can_comment, wait_for_channel = self.can_account_comment_in_channel(phone, username)
                    if not can_comment:
                        logger.info(f"[{account_name}] @{username} recently commented, skipping")
                        continue
                    
                    # Initialize tracking
                    if username not in self.commented_posts:
                        self.commented_posts[username] = set()
                    
                    client = worker_client
                    
                    try:
                        # Get/join channel
                        channel_entity = None
                        try:
                            try:
                                channel_entity = await client.get_entity(username)
                            except:
                                channel_entity = await client.get_entity('https://t.me/' + username)
                        except Exception as e_get:
                            logger.info(f"[{account_name}] Joining @{username}...")
                            try:
                                result = await client(functions.channels.JoinChannelRequest('https://t.me/' + username))
                                await asyncio.sleep(1)
                                try:
                                    channel_entity = await client.get_entity(username)
                                except:
                                    channel_entity = await client.get_entity('https://t.me/' + username)
                            except Exception as e_join:
                                logger.error(f"[{account_name}] Cannot access @{username}: {e_join}")
                                await self.mark_channel_failed_for_account(username, phone, f"Access error")
                                await asyncio.sleep(1)
                                continue
                        
                        if not channel_entity:
                            logger.error(f"[{account_name}] Failed to get @{username}")
                            await asyncio.sleep(1)
                            continue
                        
                        # Find discussion group
                        linked_chat_id = None
                        discussion_entity = None
                        
                        try:
                            full = await client(functions.channels.GetFullChannelRequest(channel=channel_entity))
                            
                            if hasattr(full, 'full_chat'):
                                if hasattr(full.full_chat, 'linked_chat_id'):
                                    linked_chat_id = full.full_chat.linked_chat_id
                            
                            if not linked_chat_id and hasattr(full, 'chats'):
                                for ch in full.chats:
                                    if hasattr(ch, 'megagroup') and ch.megagroup:
                                        try:
                                            discussion_entity = ch
                                            linked_chat_id = ch.id
                                            break
                                        except Exception:
                                            continue
                        except Exception as e_full:
                            logger.error(f"[{account_name}] GetFullChannel error for @{username}: {e_full}")
                            await asyncio.sleep(2)
                            continue
                        
                        # Resolve discussion entity
                        if linked_chat_id and not discussion_entity:
                            for attempt in range(3):
                                try:
                                    if attempt == 0:
                                        discussion_entity = await client.get_entity(int(linked_chat_id))
                                    elif attempt == 1:
                                        from telethon.tl.types import PeerChannel
                                        discussion_entity = await client.get_entity(PeerChannel(int(linked_chat_id)))
                                    else:
                                        discussion_entity = await client.get_entity(-100 + int(linked_chat_id) if linked_chat_id > 0 else linked_chat_id)
                                    
                                    if discussion_entity:
                                        break
                                except Exception as e_get:
                                    if attempt == 2:
                                        logger.error(f"[{account_name}] Cannot resolve discussion for @{username}")
                                    await asyncio.sleep(0.5)
                        
                        if not discussion_entity and not linked_chat_id:
                            await self.mark_channel_failed_for_account(username, phone, "No discussion group")
                            logger.warning(f"[{account_name}] @{username} has no discussion")
                            await asyncio.sleep(1)
                            continue
                        elif not discussion_entity:
                            logger.warning(f"[{account_name}] Could not resolve discussion for @{username}")
                            await asyncio.sleep(2)
                            continue
                        
                        # Get messages
                        try:
                            logger.info(f"🧪 Check comment eligibility for chat={discussion_entity.id}")
                            msgs = await client.get_messages(discussion_entity, limit=10)
                            
                            reply_id = None
                            post_text = ""
                            for msg in msgs:
                                logger.info(
                                    f"🧵 New post event: chat={discussion_entity.id}, "
                                    f"sender={msg.sender_id}, message_id={msg.id}"
                                )
                                if msg.id not in self.commented_posts[username]:
                                    reply_id = msg.id
                                    post_text = msg.text or msg.message or ""
                                    break
                            
                            if not reply_id and msgs:
                                reply_id = msgs[0].id
                                post_text = msgs[0].text or msgs[0].message or ""
                                if len(self.commented_posts[username]) > 30:
                                    oldest_ids = sorted(list(self.commented_posts[username]))[:15]
                                    for old_id in oldest_ids:
                                        self.commented_posts[username].discard(old_id)
                            
                            if not post_text:
                                try:
                                    channel_msgs = await client.get_messages(channel_entity, limit=5)
                                    if channel_msgs:
                                        post_text = channel_msgs[0].text or channel_msgs[0].message or "Интересный пост!"
                                except Exception:
                                    post_text = "Интересный пост!"
                            
                            # ============= NEW: ANTI-SPAM CHECKS =============
                            # 1. Получаем недавних авторов в треде для проверки самокомментирования
                            recent_authors = await self.get_recent_thread_authors(client, discussion_entity, limit=5)
                            
                            # 2. Проверяем, можно ли комментировать (защита от петель)
                            can_comment_check, reason = self.can_account_comment_on_post(
                                phone, discussion_entity.id, recent_authors
                            )
                            
                            if not can_comment_check:
                                logger.warning(
                                    f"[{account_name}] ⛔ Пропускаю @{username}: {reason}"
                                )
                                await asyncio.sleep(2)
                                continue
                            # ============= END ANTI-SPAM CHECKS =============
                            
                            # Generate comment (выбираем случайный тип реакции)
                            channel_theme_str = channel.get('theme', 'общая') if isinstance(channel, dict) else 'общая'
                            
                            # Генерируем до 3 попыток для получения уникального комментария
                            comment = None
                            for attempt in range(3):
                                # Выбираем провайдера на основе переменной окружения
                                if COMMENT_PROVIDER == 'rockapi':
                                    temp_comment = generate_comment_rockapi(
                                        post_text=post_text,
                                        channel_theme=channel_theme_str
                                    )
                                else:
                                    temp_comment = generate_neuro_comment(
                                        post_text=post_text,
                                        channel_theme=channel_theme_str
                                    )
                                
                                # Проверка на дублирование
                                is_dup, dup_reason = self.is_comment_duplicate(username, temp_comment, min_word_count=5)
                                
                                if not is_dup:
                                    comment = temp_comment
                                    logger.info(f"✅ [{account_name}] Комментарий уникален (попытка {attempt+1}/3)")
                                    break
                                else:
                                    logger.warning(
                                        f"⚠️ [{account_name}] Дубликат комментария: {dup_reason} "
                                        f"(попытка {attempt+1}/3)"
                                    )
                            
                            # Если после 3 попыток не получили уникальный комментарий - пропускаем пост
                            if not comment:
                                logger.error(
                                    f"❌ [{account_name}] Не удалось сгенерировать уникальный комментарий "
                                    f"для @{username} за 3 попытки, пропускаю"
                                )
                                await asyncio.sleep(2)
                                continue
                            
                            # Test mode duplicate check (старая проверка, оставляем для совместимости)
                            if self.test_mode:
                                if not hasattr(self, '_last_test_comments'):
                                    self._last_test_comments = []
                                
                                if comment in self._last_test_comments:
                                    logger.warning(f"[{account_name}] Duplicate comment detected, regenerating...")
                                    # Выбираем провайдера на основе переменной окружения
                                    if COMMENT_PROVIDER == 'rockapi':
                                        comment = generate_comment_rockapi(
                                            post_text=post_text,
                                            channel_theme=channel_theme_str
                                        )
                                    else:
                                        comment = generate_neuro_comment(
                                            post_text=post_text,
                                            channel_theme=channel_theme_str
                                        )
                                    if comment in self._last_test_comments:
                                        base_comment = random.choice(self.templates)
                                        comment = self.generate_comment_variation(base_comment)
                                
                                self._last_test_comments.append(comment)
                                if len(self._last_test_comments) > 10:
                                    self._last_test_comments.pop(0)
                            
                        except Exception as e_msgs:
                            logger.error(f"[{account_name}] Error getting messages: {e_msgs}")
                            reply_id = None
                            base_comment = random.choice(self.templates)
                            comment = self.generate_comment_variation(base_comment)
                        
                        # Join discussion
                        try:
                            await client(functions.channels.JoinChannelRequest(discussion_entity))
                            await asyncio.sleep(1)
                        except Exception:
                            pass
                        
                        # Send comment
                        comment_success = False
                        try:
                            logger.info(
                                f"💬 Sending comment to chat={discussion_entity.id}, "
                                f"message_id={reply_id or 'new'}, account={account_name} ({phone})"
                            )
                            if reply_id:
                                await client.send_message(discussion_entity, comment, reply_to=reply_id)
                                self.commented_posts[username].add(reply_id)
                            else:
                                await client.send_message(discussion_entity, comment)
                            
                            comment_success = True
                            self.register_message_sent(phone, username)
                            
                            # ============= NEW: Сохраняем комментарий в историю для дедупликации =============
                            self.add_comment_to_history(username, comment, phone)
                            # ============= END NEW =============
                            
                            # Logging with MODE indicator
                            short_comment = comment[:50] if len(comment) > 50 else comment
                            current_time = datetime.now().strftime('%H:%M:%S')
                            commented_channels.append(f"@{username}")
                            
                            # КРИТИЧНО: Явный индикатор режима в логах
                            mode_indicator = "🧪 mode=TEST" if self.test_mode else "🚀 mode=LIVE"
                            
                            logger.info("="*80)
                            logger.info(f"{mode_indicator} | COMMENT SENT")
                            logger.info(f"   Channel: @{username}")
                            logger.info(f"   Account: {account_name} ({phone[-10:]})")
                            logger.info(f"   Time: {current_time}")
                            logger.info(f"   Comment: {short_comment}...")
                            if reply_id:
                                logger.info(f"   Reply to: post #{reply_id}")
                            logger.info("="*80)
                            
                            await self.add_comment_stat(phone, True, channel=username)
                            
                            # ============= НОВОЕ: Обновление прогресса =============
                            # Нормализуем username для сохранения прогресса (приводим к нижнему регистру)
                            username_normalized = username.lower() if username else username
                            if username_normalized not in self.commenting_progress.get('processed_channels', []):
                                if 'processed_channels' not in self.commenting_progress:
                                    self.commenting_progress['processed_channels'] = []
                                self.commenting_progress['processed_channels'].append(username_normalized)
                                self.commenting_progress['last_update'] = datetime.now().timestamp()
                                
                                # Сохраняем прогресс каждые 10 каналов или раз в 5 минут
                                last_save = self.commenting_progress.get('last_save', 0)
                                if (len(self.commenting_progress['processed_channels']) % 10 == 0 or 
                                    datetime.now().timestamp() - last_save > 300):
                                    self.commenting_progress['last_save'] = datetime.now().timestamp()
                                    self.save_data()
                                    logger.debug(f"💾 Progress saved: {len(self.commenting_progress['processed_channels'])} channels processed")
                            # ============= КОНЕЦ ОБНОВЛЕНИЯ ПРОГРЕССА =============
                            
                            if self.conn:
                                try:
                                    cursor = self.conn.cursor()
                                    cursor.execute(
                                        "INSERT INTO comment_history (phone, channel, comment, date) VALUES (?, ?, ?, ?)",
                                        (phone, username, comment, datetime.now().isoformat()),
                                    )
                                    self.conn.commit()
                                except Exception as db_err:
                                    logger.error(f"DB log error: {db_err}")
                        
                        except Exception as send_exc:
                            logger.error(f"❌ Comment error: {send_exc}", exc_info=True)
                            err_text = str(send_exc)
                            
                            if self.test_mode:
                                logger.error(f"TEST MODE ERROR:")
                                logger.error(f"   Channel: @{username}")
                                logger.error(f"   Account: {account_name} ({phone})")
                                logger.error(f"   Error: {err_text[:100]}")
                            
                            logger.error(f"[{account_name}] Send error for @{username}: {err_text}")
                            
                            # ============= ПРОВЕРКА НА БАН АККАУНТА =============
                            # Если аккаунт забанен в каналах - это серьёзно!
                            if "UserBannedInChannelError" in err_text or "You're banned from sending messages" in err_text:
                                logger.error(f"⚠️ [{account_name}] ACCOUNT IS BANNED IN CHANNELS!")
                                logger.error(f"   This account cannot comment anywhere")
                                logger.error(f"   Marking account as BROKEN...")
                                
                                # Помечаем аккаунт как сломанный
                                await self.handle_account_ban(phone, "Banned from channels")
                                
                                # Прерываем цикл - нет смысла пробовать другие каналы
                                break
                            # ============= END ПРОВЕРКА НА БАН =============
                            
                            # Error handling...
                            permanent_errors = [
                                "You can't write in this chat",
                                "CHAT_WRITE_FORBIDDEN",
                                "CHAT_SEND_PLAIN_FORBIDDEN",
                                "CHANNEL_PRIVATE",
                            ]
                            
                            is_permanent = any(err in err_text for err in permanent_errors)
                            
                            if is_permanent:
                                await self.mark_channel_failed_for_account(username, phone, "Comments forbidden")
                                # Пропускаем этот канал и переходим к следующему СРАЗУ
                                continue
                            elif "FloodWait" in err_text:
                                try:
                                    import re
                                    wait_match = re.search(r'(\d+)', err_text)
                                    wait_seconds = int(wait_match.group(1)) if wait_match else 60
                                    
                                    # ============= NEW: УЛУЧШЕННАЯ ОБРАБОТКА FLOODWAIT =============
                                    logger.warning(
                                        f"🚨 [{account_name}] FloodWait {wait_seconds}s на @{username}"
                                    )
                                    
                                    # 1. Записываем FloodWait в историю
                                    self.record_floodwait(phone, username, wait_seconds)
                                    
                                    # 2. ЗАПИСЫВАЕМ ИНЦИДЕНТ ДЛЯ АККАУНТА (статистика)
                                    self.record_account_incident(
                                        phone=phone,
                                        channel=username,
                                        reason=f"FloodWait {wait_seconds}s",
                                        wait_seconds=wait_seconds,
                                        action_taken="marked_hot" if wait_seconds <= 60 else "worker_stopped"
                                    )
                                    
                                    # 3. ПОМЕЧАЕМ КАНАЛ КАК ГОРЯЧИЙ (избегаем 2 часа)
                                    self.mark_channel_as_hot(username, phone, f"FloodWait {wait_seconds}s")
                                    
                                    # 3. Если FloodWait > 60 секунд - прерываем работу этого воркера
                                    # Система автоматически переключится на другой аккаунт
                                    if wait_seconds > 60:
                                        logger.error(
                                            f"⚠️ [{account_name}] FloodWait слишком долгий ({wait_seconds}s), "
                                            f"прерываю worker для переключения на другой аккаунт"
                                        )
                                        # FloodWait > 60s - это нормально, уведомление не требуется
                                        # Инциденты сохраняются в account_incidents для /incidents
                                        
                                        # Прерываем цикл - система запустит другой аккаунт
                                        break
                                    else:
                                        # Если FloodWait короткий - ждем и пропускаем канал
                                        logger.info(f"[{account_name}] Короткий FloodWait, жду {wait_seconds}s")
                                        await asyncio.sleep(min(wait_seconds + 5, 120))
                                        # Пропускаем этот канал
                                        continue
                                    # ============= END NEW =============
                                    
                                except Exception as fw_err:
                                    logger.error(f"Error processing FloodWait: {fw_err}")
                                    await asyncio.sleep(60)
                                    continue
                            elif "USER_DEACTIVATED" in err_text or "AUTH_KEY_UNREGISTERED" in err_text:
                                logger.error(f"[{account_name}] ACCOUNT BANNED!")
                                await self.handle_account_ban(phone, "Account Deactivated")
                                break
                            else:
                                await asyncio.sleep(3)
                                # Для других ошибок тоже переходим к следующему каналу
                                continue
                    
                    except Exception as e:
                        logger.error(f"[{account_name}] Error on @{username}: {str(e)[:100]}")
                        await asyncio.sleep(3)
                    
                    # Delay between comments
                    if self.test_mode:
                        target_rate = self.test_mode_speed_limit
                    else:
                        target_rate = self.messages_per_hour
                    
                    base_delay = (3600 // target_rate) if target_rate > 0 else 60
                    
                    # ============= NEW: ПРИМЕНЯЕМ ГЛОБАЛЬНЫЙ МНОЖИТЕЛЬ ЗАДЕРЖКИ =============
                    # Если были частые FloodWait - увеличиваем задержку
                    base_delay = int(base_delay * self.global_delay_multiplier)
                    # ============= END NEW =============
                    
                    delay = random.randint(int(base_delay * 0.8), int(base_delay * 1.2))
                    
                    # Логируем с указанием множителя, если он != 1.0
                    if self.global_delay_multiplier > 1.0:
                        logger.info(
                            f"[{account_name}] Waiting {delay}s (target: {target_rate} msg/hour, "
                            f"multiplier: {self.global_delay_multiplier:.2f}x)"
                        )
                    else:
                        logger.info(f"[{account_name}] Waiting {delay}s (target: {target_rate} msg/hour)")
                    
                    await asyncio.sleep(delay)
                
                # Cycle completed
                logger.info("="*60)
                logger.info(f"WORKER FINISHED CYCLE: account={phone}, cycle={cycle_number}")
                logger.info(f"   Commented channels: {commented_channels}")
                logger.info(f"   Total: {len(commented_channels)}")
                logger.info("="*60)
                
                # Break between cycles
                cycle_break = random.randint(30, 60)
                logger.info(f"[{account_name}] Break: {cycle_break}s")
                await asyncio.sleep(cycle_break)
        
        except Exception as outer_e:
            logger.error("="*80)
            logger.error(f"💥 WORKER FATAL ERROR: {worker_task_name}")
            logger.error(f"   Account: {account_name} ({phone})")
            logger.error(f"   Error: {outer_e}")
            logger.error(f"   Traceback:")
            logger.error(traceback.format_exc())
            logger.error("="*80)
            
            # Попытка уведомить владельца об ошибке
            try:
                await self.bot_client.send_message(
                    BOT_OWNER_ID,
                    f"💥 **ВОРКЕР УПАЛ**\n\n"
                    f"Аккаунт: `{account_name}`\n"
                    f"Телефон: `{phone}`\n"
                    f"Ошибка: `{str(outer_e)[:200]}`\n\n"
                    f"🔄 Система попытается восстановить через health check"
                )
            except:
                pass
        finally:
            # Cleanup
            logger.info("="*80)
            logger.info(f"🛑 WORKER STOPPING: {worker_task_name}")
            logger.info(f"   Account: {account_name} ({phone})")
            logger.info(f"   Reason: {'Normal exit' if self.monitoring else 'Monitoring stopped'}")
            logger.info("="*80)
            
            if worker_client:
                try:
                    if worker_client.is_connected():
                        logger.info(f"🔌 [{account_name}] Отключение worker-клиента...")
                        await worker_client.disconnect()
                        logger.info(f"✅ [{account_name}] Worker-клиент отключён")
                    else:
                        logger.info(f"ℹ️ [{account_name}] Worker-клиент уже отключён")
                except Exception as e:
                    logger.error(f"❌ [{account_name}] Ошибка отключения worker-клиента: {e}")

    async def start_commenting(self):
        """Wrapper to start auto-commenting loop from run()."""
        try:
            await self.pro_auto_comment()
        except Exception as e:
            logger.error(f"Start commenting error: {e}")

    async def pro_auto_comment(self):
        """Main commenting loop - runs accounts in parallel with rate limiting, rotation, and auto-replacement!"""
        logger.info("="*80)
        logger.info("🚀 PRO_AUTO_COMMENT STARTED")
        logger.info("="*80)
        
        # ============= NEW: Работаем только с активными аккаунтами (статус 'active') =============
        logger.info(f"📊 Total accounts in system: {len(self.accounts_data)}")
        
        # Debug: show all accounts with statuses
        for phone, data in self.accounts_data.items():
            status = data.get('status', 'UNKNOWN')
            has_session = 'session' in data and data.get('session')
            logger.info(f"   Account {phone[-10:]}: status={status}, has_session={has_session}")
        
        active_accounts = {phone: data for phone, data in self.accounts_data.items()
                         if data.get('status') == ACCOUNT_STATUS_ACTIVE and data.get('session')}
        # ============= END NEW =============
        
        # ============= ЗАЩИТА: Исключаем аккаунты в прогреве =============
        warmup_accounts = warmup_manager.get_all_active_warmups()
        if warmup_accounts:
            logger.info(f"🔥 Аккаунтов в прогреве: {len(warmup_accounts)}")
            for phone in warmup_accounts:
                if phone in active_accounts:
                    del active_accounts[phone]
                    logger.info(f"   🔥 {phone[-10:]} исключен (в прогреве)")
        # ============= END ЗАЩИТА =============
        
        logger.info(f"✅ Active accounts with sessions: {len(active_accounts)}")
        if active_accounts:
            for phone in active_accounts:
                logger.info(f"   ✅ {phone[-10:]}")
        
        if not active_accounts:
            logger.error("❌ No active accounts found!")
            logger.error("💡 Use /listaccounts to check account statuses")
            logger.error("💡 Use /toggleaccount to activate accounts")
            return
        
        logger.info(f"📢 Total channels in system: {len(self.channels)}")
        if not self.channels:
            logger.error("❌ No channels found!")
            logger.error("💡 Use /addchannel to add channels")
            return
        
        # ============= TEST MODE: Filter channels =============
        if self.test_mode and self.test_channels:
            # ТЕСТОВЫЙ РЕЖИМ АКТИВЕН
            logger.info("="*80)
            logger.info("🧪 MODE: TEST")
            logger.info("="*80)
            # Нормализуем test_channels
            normalized_test_channels = []
            for tc in self.test_channels:
                norm = self._normalize_channel_username(tc)
                if norm:
                    normalized_test_channels.append(norm)
            normalized_test_channels_set = set(normalized_test_channels)
            logger.info(f"🎯 Test channels: {normalized_test_channels}")
            logger.info(f"📊 Total channels in system: {len(self.channels)}")
            logger.info("🔍 Filtering channels...")
            
            # В тестовом режиме используем ТОЛЬКО тестовые каналы
            channels_to_use = []
            for ch in self.channels:
                ch_username = ch.get('username') if isinstance(ch, dict) else ch
                ch_username_norm = self._normalize_channel_username(ch_username)
                if not ch_username_norm:
                    continue
                
                if ch_username_norm in normalized_test_channels_set:
                    channels_to_use.append(ch)
                    logger.info(f"   ✅ TEST channel: {ch_username_norm}")
            
            if not channels_to_use:
                logger.error("="*80)
                logger.error("🧪 ❌ ERROR: NO TEST CHANNELS FOUND!")
                logger.error(f"🔍 Looking for: {normalized_test_channels}")
                logger.error(
                    f"📋 Available: {[self._normalize_channel_username(ch.get('username') if isinstance(ch, dict) else ch) for ch in self.channels[:10]]}"
                )
                logger.error("💡 Use /addchannel to add test channels")
                logger.error("="*80)
                return
            
            logger.info(f"✅ Will use {len(channels_to_use)} TEST channels")
            logger.info("⚠️  ALL other channels are IGNORED in TEST MODE")
            logger.info("="*80)
        else:
            # БОЕВОЙ РЕЖИМ
            logger.info("="*80)
            logger.info("🚀 MODE: LIVE")
            logger.info("="*80)
            logger.info(f"📊 Using all {len(self.channels)} channels")
            logger.info("="*80)
            channels_to_use = self.channels
        # ============= END TEST MODE =============
        
        # Use configured max parallel accounts
        MAX_PARALLEL_ACCOUNTS = self.max_parallel_accounts
        
        logger.info("="*80)
        logger.info("⚙️  PARALLEL PROCESSING CONFIGURATION")
        logger.info("="*80)
        logger.info(f"📊 Total active accounts available: {len(active_accounts)}")
        logger.info(f"⚡ MAX_PARALLEL_ACCOUNTS setting: {MAX_PARALLEL_ACCOUNTS}")
        logger.info(f"🎯 Will create workers for: {min(len(active_accounts), MAX_PARALLEL_ACCOUNTS)} accounts")
        
        if len(active_accounts) == 1:
            logger.warning("⚠️⚠️⚠️ ONLY 1 ACTIVE ACCOUNT! ⚠️⚠️⚠️")
            logger.warning("⚠️ This means NO PARALLEL PROCESSING!")
            logger.warning("⚠️ To enable parallel work:")
            logger.warning("⚠️   1. Use /listaccounts to see all accounts")
            logger.warning("⚠️   2. Use /toggleaccount to activate more accounts")
            logger.warning("⚠️   3. Or add new accounts with /auth")
        elif MAX_PARALLEL_ACCOUNTS == 1:
            logger.warning("⚠️⚠️⚠️ MAX_PARALLEL_ACCOUNTS = 1 ⚠️⚠️⚠️")
            logger.warning("⚠️ Even though you have multiple active accounts,")
            logger.warning("⚠️ only 1 will work due to parallel limit!")
            logger.warning("⚠️ Use /setparallel <number> to increase (e.g., /setparallel 3)")
        
        logger.info("="*80)
        
        # ============= NEW: Initialize rotation timer =============
        if self.last_rotation_time is None:
            self.last_rotation_time = datetime.now().timestamp()
        # ============= END NEW =============
        
        # Divide channels among accounts for parallel processing
        accounts_list = list(active_accounts.items())
        num_accounts = min(len(accounts_list), MAX_PARALLEL_ACCOUNTS)
        
        if len(accounts_list) > MAX_PARALLEL_ACCOUNTS:
            logger.warning(f"⚠️ You have {len(accounts_list)} active accounts, but only {MAX_PARALLEL_ACCOUNTS} will work in parallel")
            logger.warning(f"⚠️ Use /setparallel to change this limit")
        
        accounts_list = accounts_list[:MAX_PARALLEL_ACCOUNTS]  # Use first N accounts
        
        # ============= TEST MODE: Use filtered channels =============
        if self.test_mode and self.test_channels:
            channels_copy = channels_to_use.copy()
        else:
            channels_copy = self.channels.copy()
        # ============= END TEST MODE =============
        
        # ============= НОВОЕ: Восстановление прогресса или создание нового =============
        processed_channels = self.commenting_progress.get('processed_channels', [])
        
        if processed_channels:
            # Есть сохраненный прогресс - продолжаем с него
            logger.info("="*80)
            logger.info("♻️  ВОССТАНОВЛЕНИЕ ПРОГРЕССА")
            logger.info("="*80)
            logger.info(f"📊 Обработано ранее: {len(processed_channels)} каналов")
            
            # Убираем уже обработанные каналы (ИСПРАВЛЕНО: правильное сравнение)
            processed_channels_normalized = set(processed_channels)  # Для быстрого поиска
            remaining_channels = [
                ch for ch in channels_copy 
                if self._get_channel_username_normalized(ch) not in processed_channels_normalized
            ]
            
            if remaining_channels:
                # Продолжаем с оставшихся
                channels_copy = remaining_channels
                logger.info(f"✅ Продолжаем с {len(channels_copy)} необработанных каналов")
                logger.info(f"📊 Пропущено обработанных: {len(processed_channels)} каналов")
            else:
                # Все каналы обработаны - начинаем новый цикл
                logger.info(f"✅ Все каналы обработаны! Начинаем новый цикл")
                self.commenting_progress = {'processed_channels': [], 'last_update': datetime.now().timestamp()}
                self.save_data()
                random.shuffle(channels_copy)
        else:
            # Первый запуск или прогресс сброшен - перемешиваем
            logger.info("🔀 Первый запуск: перемешиваем каналы")
            random.shuffle(channels_copy)
            self.commenting_progress = {'processed_channels': [], 'last_update': datetime.now().timestamp()}
        # ============= КОНЕЦ ВОССТАНОВЛЕНИЯ ПРОГРЕССА =============
        
        # Calculate channels per account
        
        # ============= TEST MODE: Log info =============
        if self.test_mode:
            logger.info(f"🧪 TEST MODE: {num_accounts} accounts × {len(channels_copy)} TEST channels")
            logger.info(f"🧪 Test channels: {self.test_channels}")
            logger.info(f"🧪 Speed limit: {self.test_mode_speed_limit} msg/hour per account")
        else:
            logger.info(f"🚀 SMART MODE: {num_accounts} active accounts (max {MAX_PARALLEL_ACCOUNTS}) × {len(channels_copy)} channels")
        # ============= END TEST MODE =============
        
        # Логирование режима работы
        if self.worker_mode == 'distributed':
            channels_per_worker = len(channels_copy) // num_accounts
            logger.info(f"📊 Mode: DISTRIBUTED - each account gets ~{channels_per_worker} dedicated channels")
            logger.info(f"📊 Total: {num_accounts} accounts × ~{channels_per_worker} channels = {len(channels_copy)} total")
        else:
            logger.info(f"📊 Mode: CYCLIC - each account processes ALL {len(channels_copy)} channels with offset")
        
        logger.info(f"⚡ Rate limit: {self.messages_per_hour} msg/hour per account")
        logger.info(f"🔄 Max cycles per worker: {self.max_cycles_per_worker} (0=infinite)")
        logger.info(f"🛡️ Anti-spam: {MIN_INTERVAL_BETWEEN_OWN_ACCOUNTS}s between own accounts in same chat")
        
        # ============= NEW: Start health check task =============
        # ПРИМЕЧАНИЕ: rotation_worker ОТКЛЮЧЕН - ротация происходит автоматически
        # когда воркеры завершают max_cycles_per_worker циклов
        # rotation_task = asyncio.create_task(self.rotation_worker())  # ОТКЛЮЧЕНО
        health_task = asyncio.create_task(self.health_check_worker())
        logger.info("✅ Health check worker started")
        if self.max_cycles_per_worker > 0:
            logger.info(f"🔄 Rotation mode: BY CYCLES (every {self.max_cycles_per_worker} cycles)")
        else:
            logger.info(f"🔄 Rotation mode: MANUAL (max_cycles=0, no automatic rotation)")
        # ============= END NEW =============
        
        # Create worker tasks for each account
        tasks = []
        self.active_worker_tasks.clear()  # Очищаем старый список
        self.worker_slots.clear()  # Очищаем информацию о слотах
        
        logger.info("="*80)
        logger.info(f"🚀 CREATING {len(accounts_list)} PARALLEL WORKERS")
        logger.info("="*80)
        
        if len(accounts_list) == 1:
            logger.warning("⚠️ WARNING: Only 1 worker will be created!")
            logger.warning("⚠️ Reason: Only 1 active account found or MAX_PARALLEL_ACCOUNTS=1")
            logger.warning("⚠️ Solution: Add more accounts with /auth and set to 'active' status")
            logger.warning("⚠️ Or increase limit with /setparallel")
        
        for i, (phone, data) in enumerate(accounts_list):
            # Give extra channels to first accounts if there's a remainder
            
            logger.info(f"🔧 Creating worker #{i+1}/{len(accounts_list)} for [{data.get('name', phone)}]")
            logger.info(f"   Phone: {phone}")
            logger.info(f"   Status: {data.get('status', 'unknown')}")
            logger.info(f"   Session: {'✅ EXISTS' if data.get('session') else '❌ MISSING'}")
            logger.info(f"   Will process: ALL {len(channels_copy)} channels")
            logger.info(f"   Offset: starts from channel #{(i % len(channels_copy)) + 1}")
            
            # Задержка между созданием воркеров для избежания конфликтов
            if i > 0:
                delay = 3
                logger.info(f"⏳ Задержка {delay}s перед созданием воркера #{i+1}...")
                await asyncio.sleep(delay)
            
            # Create worker task for this account
            # Create worker task - каждый воркер получает ВСЕ каналы
            task = asyncio.create_task(
                self.account_worker(phone, data, channels_copy, i, len(accounts_list), mode=self.worker_mode)
            )
            task.set_name(f"worker_{i}_{phone[-10:]}")
            tasks.append(task)
            self.active_worker_tasks.append(task)  # Отслеживаем для health check
            
            logger.info(f"   ✅ Task created: {task.get_name()} (id={id(task)})")  
            
        
        logger.info("="*80)
        logger.info(f"✅ ALL {len(tasks)} WORKERS CREATED AND LAUNCHED")
        logger.info("="*80)
        
        # Wait for all workers (they run until self.monitoring becomes False)
        try:
            # ============= ИСПРАВЛЕНО: rotation_task отключен, ждём только воркеров =============
            # all_tasks = tasks + [rotation_task]  # СТАРЫЙ КОД
            await asyncio.gather(*tasks, return_exceptions=True)
            # ============= END ИСПРАВЛЕНО =============
        except Exception as e:
            logger.error(f"Error in parallel workers: {e}")
    
    async def _run_warmup_background(self, phone: str):
        """Фоновая задача для прогрева аккаунта"""
        try:
            # Получаем или создаем клиент для аккаунта
            client = await self.get_account_client(phone)
            if not client:
                logger.error(f"❌ Не удалось создать клиент для {phone}")
                warmup_manager.stop_warmup(phone, 'client_error')
                return
            
            # Запускаем цикл прогрева
            await warmup_manager.run_warmup_cycle(client, phone)
            
        except Exception as e:
            logger.error(f"❌ Ошибка прогрева {phone}: {e}")
            warmup_manager.stop_warmup(phone, f'error: {str(e)[:50]}')
    
    def is_account_in_warmup(self, phone: str) -> bool:
        """Проверить, находится ли аккаунт в процессе прогрева"""
        status = warmup_manager.get_warmup_status(phone)
        return status and status['status'] == 'active'
    
    async def rotation_worker(self):
        """Background worker that performs periodic account rotation"""
        logger.info(f"🔄 Rotation worker started (interval: {self.rotation_interval}s)")
        
        while self.monitoring:
            try:
                # Wait and check rotation periodically (every 5 minutes)
                await asyncio.sleep(300)  # Check every 5 minutes
                
                if not self.monitoring:
                    break
                
                # Check if rotation is needed
                await self.check_and_rotate_if_needed()
                
            except Exception as e:
                logger.error(f"Error in rotation worker: {e}")
                await asyncio.sleep(60)  # Wait a bit before retry
        
        logger.info("🔄 Rotation worker stopped")
    
    async def periodic_backup_worker(self):
        """
        Воркер для создания периодических timestamped бэкапов.
        Создаёт бэкапы каждые BACKUP_INTERVAL_MINUTES минут.
        """
        BACKUP_INTERVAL_MINUTES = 30  # Интервал между бэкапами
        BACKUP_DIR = 'backups'  # Папка для бэкапов
        MAX_BACKUPS = 48  # Хранить последние 48 бэкапов (24 часа при интервале 30 мин)
        
        # Создаём папку для бэкапов
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)
            logger.info(f"📁 Created backup directory: {BACKUP_DIR}")
        
        logger.info(f"💾 Periodic backup worker started (every {BACKUP_INTERVAL_MINUTES} min)")
        
        while True:
            try:
                await asyncio.sleep(BACKUP_INTERVAL_MINUTES * 60)  # Ждём интервал
                
                # Проверяем, что файл данных существует
                if not os.path.exists(DB_NAME):
                    logger.warning(f"⚠️ {DB_NAME} not found, skipping backup")
                    continue
                
                # Создаём timestamped бэкап
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_name = os.path.join(BACKUP_DIR, f'bot_data_{timestamp}.json')
                
                import shutil
                shutil.copy2(DB_NAME, backup_name)
                
                file_size = os.path.getsize(backup_name)
                logger.info(f"💾 Auto-backup created: {backup_name} ({file_size} bytes)")
                
                # Очистка старых бэкапов (оставляем только последние MAX_BACKUPS)
                backups = sorted([
                    os.path.join(BACKUP_DIR, f) 
                    for f in os.listdir(BACKUP_DIR) 
                    if f.startswith('bot_data_') and f.endswith('.json')
                ])
                
                if len(backups) > MAX_BACKUPS:
                    to_delete = backups[:-MAX_BACKUPS]
                    for old_backup in to_delete:
                        try:
                            os.remove(old_backup)
                            logger.debug(f"🗑️  Removed old backup: {old_backup}")
                        except Exception as e:
                            logger.warning(f"Failed to remove old backup {old_backup}: {e}")
                    
                    logger.info(f"🗑️  Cleaned up {len(to_delete)} old backups, keeping {MAX_BACKUPS} most recent")
                
            except Exception as e:
                logger.error(f"Error in periodic backup worker: {e}")
                await asyncio.sleep(60)  # Пауза перед повтором при ошибке
    
    async def run(self):
        await self.start()
        
        # Запускаем воркер периодических бэкапов
        asyncio.create_task(self.periodic_backup_worker())
        # Запускаем воркер ротации аккаунтов
        asyncio.create_task(self.rotation_worker())
        # Запускаем автокомментирование
        asyncio.create_task(self.start_commenting())
        
        try:
            await self.bot_client.run_until_disconnected()
        finally:
            # Закрываем все клиенты при выходе
            logger.info("🔌 Закрытие всех клиентов аккаунтов...")
            for phone, client in list(self.account_clients.items()):
                try:
                    await client.disconnect()
                    logger.info(f"✅ Клиент {phone} закрыт")
                except Exception as e:
                    logger.error(f"❌ Ошибка закрытия {phone}: {e}")
            self.account_clients.clear()
            logger.info("✅ Все клиенты закрыты")

if __name__ == '__main__':
    try:
        bot = UltimateCommentBot()
        asyncio.run(bot.run())
    except Exception as e:
        print(f"❌ FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
