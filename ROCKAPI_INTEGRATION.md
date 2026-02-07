# Интеграция RockAPI для генерации комментариев

## Что изменилось

Добавлена поддержка RockAPI (DeepSeek) в качестве альтернативы YandexGPT для генерации комментариев через нейросеть.

### Ключевые особенности

✅ **Сохранены все промпты и параметры** — используется тот же промпт, temperature и max_tokens, что и в YandexGPT  
✅ **Простое переключение** — через переменную окружения `COMMENT_PROVIDER`  
✅ **Обработка ошибок** — при сбое API используются fallback комментарии  
✅ **OpenAI-совместимый формат** — RockAPI использует стандартный Chat Completions API  
✅ **Та же постобработка** — функция `humanize_comment` применяется к результату

## Настройка

### 1. Переменные окружения

Добавьте в `.env` или systemd unit:

```bash
# RockAPI конфигурация (обязательно)
ROCKAPI_KEY=ваш_api_ключ_rockapi
ROCKAPI_MODEL=deepseek-chat
ROCKAPI_BASE_URL=https://api.rockapi.ru/deepseek

# Выбор провайдера (rockapi или yandex)
COMMENT_PROVIDER=rockapi
```

### 2. Проверка настроек

Запустите тестовый скрипт:

```bash
python test_rockapi.py
```

Скрипт проверит:
- Наличие и корректность API ключа
- Генерацию комментариев через RockAPI
- Качество сгенерированных комментариев (длина, женский род, отсутствие шаблонов)

## Использование

### Автоматическое переключение

Бот автоматически использует провайдера, указанного в `COMMENT_PROVIDER`:

```python
# В коде бота автоматически выбирается провайдер
if COMMENT_PROVIDER == 'rockapi':
    comment = generate_comment_rockapi(post_text, channel_theme)
else:
    comment = generate_neuro_comment(post_text, channel_theme)
```

### Переключение провайдера

**Использовать RockAPI (по умолчанию):**
```bash
export COMMENT_PROVIDER=rockapi
```

**Вернуться к YandexGPT:**
```bash
export COMMENT_PROVIDER=yandex
```

**Применить изменения:**
```bash
sudo systemctl restart comapc-bot
```

## API провайдеры

### RockAPI (DeepSeek)
- **Модель**: `deepseek-chat`
- **URL**: `https://api.rockapi.ru/deepseek/v1/chat/completions`
- **Формат**: OpenAI Chat Completions API
- **Timeout**: 30 секунд

### YandexGPT (прежний)
- **Модель**: `yandexgpt/latest`
- **URL**: `https://llm.api.cloud.yandex.net/foundationModels/v1/completion`
- **Формат**: Yandex Foundation Models API
- **Timeout**: 30 секунд

## Структура запроса

### RockAPI (OpenAI-совместимый)

```json
{
  "model": "deepseek-chat",
  "messages": [
    {
      "role": "user",
      "content": "промпт..."
    }
  ],
  "temperature": 0.88,
  "max_tokens": 100
}
```

### YandexGPT (оригинальный)

```json
{
  "modelUri": "gpt://folder_id/yandexgpt/latest",
  "completionOptions": {
    "temperature": 0.88,
    "maxTokens": 100
  },
  "messages": [
    {
      "role": "user",
      "text": "промпт..."
    }
  ]
}
```

## Обработка ошибок

При любой ошибке API (timeout, non-200 статус, некорректный JSON) бот:

1. Логирует подробную информацию об ошибке
2. Возвращает один из fallback комментариев:
   - "Мне понравилось"
   - "Полезная информация"
   - "Рада, что прочитала"
   - "Хорошо написано"
   - и др. (женский род, естественные фразы)

Это гарантирует, что бот не упадёт даже при полном отказе API.

## Логирование

Для отладки промптов включите логирование комментариев:

```bash
export LOG_COMMENTS=true
```

В логах будут видны:
- Сырой комментарий от API
- Финальный комментарий после постобработки
- Параметры запроса (temperature, max_tokens, длина промпта)
- Статус HTTP и время ответа

## Преимущества RockAPI

✅ **Стабильность** — меньше ограничений rate limit  
✅ **Скорость** — быстрые ответы через OpenAI-формат  
✅ **Совместимость** — стандартный API для замены других LLM  
✅ **Качество** — DeepSeek показывает хорошие результаты на русском языке

## Откат к YandexGPT

Если нужно вернуться к YandexGPT:

1. Установите переменную окружения:
   ```bash
   export COMMENT_PROVIDER=yandex
   ```

2. Убедитесь, что YandexGPT настроен:
   ```bash
   export YC_API_KEY=ваш_yandex_api_key
   export YC_FOLDER_ID=ваш_folder_id
   ```

3. Перезапустите бота:
   ```bash
   sudo systemctl restart comapc-bot
   ```

## Тестирование

### Быстрый тест
```bash
python test_rockapi.py
```

### Проверка в боте
1. Запустите бота
2. Активируйте автокомментирование
3. Проверьте логи: должны быть записи `🤖 ROCKAPI: начинаем генерацию комментария`
4. Убедитесь, что комментарии публикуются успешно

## Поддержка

При проблемах проверьте:

1. **API ключ**: `echo $ROCKAPI_KEY | wc -c` (должно быть > 10)
2. **Доступность API**: `curl -I https://api.rockapi.ru/deepseek/v1/chat/completions`
3. **Логи бота**: `journalctl -u comapc-bot -f`
4. **Тест напрямую**: `python test_rockapi.py`

## Файлы

- `main.py` — основной код бота с функцией `generate_comment_rockapi`
- `test_rockapi.py` — тестовый скрипт для проверки интеграции
- `ROCKAPI_INTEGRATION.md` — эта документация

---

**Дата создания**: 2026-02-07  
**Версия**: 1.0  
**Статус**: ✅ Готово к использованию
