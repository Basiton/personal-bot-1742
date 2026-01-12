# 🗺️ Карта проекта: Управление профилями аккаунтов

```
personal-bot-1742/
│
├── 📱 ОСНОВНОЙ КОД
│   ├── main.py (2776 строк) ⭐ — основной бот с новым функционалом
│   ├── demo_profiles.py (12 КБ) — демонстрация работы системы
│   └── check_system.sh (8 КБ) — автоматическая проверка компонентов
│
├── 📚 ДОКУМЕНТАЦИЯ (начальный уровень)
│   ├── 🏠 INSTALLATION_COMPLETE.md (12 КБ) ⭐ НАЧНИТЕ ЗДЕСЬ!
│   │   └─> Главная точка входа, быстрый обзор
│   │
│   ├── ⚡ QUICK_PROFILES.md (4 КБ)
│   │   └─> Быстрый старт за 3 шага
│   │
│   └── 📖 README.md (обновлён)
│       └─> Добавлен новый раздел о профилях
│
├── 📚 ДОКУМЕНТАЦИЯ (продвинутый уровень)
│   ├── 📗 ACCOUNTS_PROFILES_GUIDE.md (16 КБ)
│   │   └─> Подробное руководство со всеми деталями
│   │
│   ├── 📘 ACCOUNTS_PROFILES_README.md (12 КБ)
│   │   └─> Техническое описание и примеры
│   │
│   └── 📙 PROJECT_SUMMARY.md (16 КБ)
│       └─> Итоговое резюме проекта
│
├── 📚 ДОКУМЕНТАЦИЯ (технический уровень)
│   ├── 🏗️ ARCHITECTURE_DIAGRAM.md (28 КБ) ⭐
│   │   └─> Схемы, диаграммы, потоки данных
│   │
│   └── ✅ CHECKLIST.md (12 КБ)
│       └─> Чеклист проверки и типичные проблемы
│
└── 📁 ВРЕМЕННЫЕ ФАЙЛЫ (создаются автоматически)
    └── /tmp/bot_avatars/ — загруженные изображения

```

---

## 🎯 Как ориентироваться в проекте

### Если вы новичок:
```
1. INSTALLATION_COMPLETE.md — прочитайте первым
2. QUICK_PROFILES.md — быстрый старт
3. python3 demo_profiles.py — посмотрите демо
4. /accounts — попробуйте в боте
```

### Если нужны детали:
```
1. ACCOUNTS_PROFILES_GUIDE.md — полное руководство
2. ARCHITECTURE_DIAGRAM.md — как работает
3. main.py (строки 406-900) — изучите код
```

### Если возникли проблемы:
```
1. ./check_system.sh — проверьте систему
2. CHECKLIST.md — типичные проблемы
3. ACCOUNTS_PROFILES_GUIDE.md (раздел FAQ)
```

---

## 📊 Структура кода в main.py

```
main.py (2776 строк)
│
├── Строки 1-100: Импорты и конфигурация
│   ├── Button (новый импорт)
│   └── Path (новый импорт)
│
├── Строки 100-406: Класс UltimateCommentBot (основа)
│   ├── __init__ — добавлены user_states и account_cache
│   └── Существующие методы...
│
├── Строки 406-650: 🆕 НОВЫЙ ФУНКЦИОНАЛ (управление профилями)
│   ├── get_all_accounts_from_env() — чтение из env
│   ├── create_accounts_keyboard() — создание клавиатуры
│   ├── create_account_menu_keyboard() — меню аккаунта
│   ├── get_account_info() — информация об аккаунте
│   ├── apply_account_changes() — применение изменений
│   ├── clear_user_state() — очистка состояния
│   └── save_temp_avatar() — сохранение аватарки
│
├── Строки 650-1700: Обработчики команд бота (setup_handlers)
│   ├── /start, /help, /auth... (существующие)
│   │
│   ├── 🆕 /accounts (строка ~700)
│   │   └─> Точка входа в систему профилей
│   │
│   ├── 🆕 CallbackQuery handler (строка ~730)
│   │   ├─> Обработка inline кнопок
│   │   ├─> Пагинация
│   │   ├─> Меню аккаунта
│   │   └─> Применение изменений
│   │
│   ├── 🆕 Photo handler (строка ~1500)
│   │   └─> Загрузка аватарок
│   │
│   └── 🆕 Text handler (строка ~1580)
│       └─> Ввод имени и био
│
└── Строки 1700-2776: Мониторинг и автокомментирование
    └── Существующий функционал...
```

---

## 🔄 Потоки данных

### 1. Команда /accounts:
```
Пользователь → Telegram → Bot
                            ↓
                    get_all_accounts_from_env()
                            ↓
                    create_accounts_keyboard()
                            ↓
                        Telegram
                            ↓
                        Пользователь
```

### 2. Выбор аккаунта:
```
Пользователь (кнопка) → CallbackQuery
                              ↓
                      get_account_info()
                              ↓
                  create_account_menu_keyboard()
                              ↓
                          Telegram
                              ↓
                          Пользователь
```

### 3. Изменение аватарки:
```
Пользователь (кнопка) → CallbackQuery → user_states[id]
                                              ↓
Пользователь (фото) → Photo Handler → download_media()
                                              ↓
                                      save_temp_avatar()
                                              ↓
Пользователь (применить) → CallbackQuery → apply_account_changes()
                                                    ↓
                                            Telethon API
                                                    ↓
                                            clear_user_state()
                                                    ↓
                                                Telegram
                                                    ↓
                                                Пользователь
```

---

## 📁 Зависимости между файлами

```
INSTALLATION_COMPLETE.md ──┐
                            ├──> QUICK_PROFILES.md
                            ├──> ACCOUNTS_PROFILES_GUIDE.md
                            ├──> ARCHITECTURE_DIAGRAM.md
                            └──> CHECKLIST.md

PROJECT_SUMMARY.md ─────────┐
                            ├──> Все документы
                            └──> demo_profiles.py

check_system.sh ────────────┐
                            ├──> main.py
                            └──> demo_profiles.py

demo_profiles.py ───────────┐
                            └──> Имитация get_all_accounts_from_env()
```

---

## 🔑 Ключевые концепции

### State Management:
```python
user_states = {
    user_id: {
        'state': 'waiting_avatar' | 'waiting_name' | 'waiting_bio',
        'account_num': int,
        'data': dict
    }
}
```

### Account Cache:
```python
account_cache = {
    'accounts': [
        (num, phone, session, proxy),
        ...
    ]
}
```

### Inline Keyboard:
```python
buttons = [
    [Button.inline("Text", callback_data)],
    ...
]
```

---

## 🎓 Учебные материалы по сложности

### Уровень 1: Начинающий (10 мин)
1. `INSTALLATION_COMPLETE.md` — обзор
2. `QUICK_PROFILES.md` — быстрый старт
3. `python3 demo_profiles.py` — демо

### Уровень 2: Практика (30 мин)
1. Настройте env переменные
2. Запустите бота: `python3 main.py`
3. Используйте `/accounts` в боте
4. Попробуйте изменить профиль

### Уровень 3: Продвинутый (1 час)
1. `ACCOUNTS_PROFILES_GUIDE.md` — все детали
2. `ARCHITECTURE_DIAGRAM.md` — архитектура
3. Изучите код в `main.py`

### Уровень 4: Эксперт (2+ часа)
1. Изучите все схемы в `ARCHITECTURE_DIAGRAM.md`
2. Прочитайте весь код функций профилей
3. Модифицируйте под свои нужды

---

## 🚀 Запуск проекта (схема)

```
┌─────────────────────────────────────────────┐
│  1. Настройка переменных окружения          │
│     export ACCOUNT_N_PHONE="+..."           │
│     export ACCOUNT_N_SESSION="..."          │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  2. Проверка системы (опционально)          │
│     ./check_system.sh                       │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  3. Запуск бота                             │
│     python3 main.py                         │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  4. Использование команды                   │
│     /accounts в Telegram                    │
└─────────────────────────────────────────────┘
```

---

## 🎯 Что и где находится

### Хотите быстро начать?
→ [INSTALLATION_COMPLETE.md](INSTALLATION_COMPLETE.md)

### Нужна инструкция за 3 шага?
→ [QUICK_PROFILES.md](QUICK_PROFILES.md)

### Хотите все детали?
→ [ACCOUNTS_PROFILES_GUIDE.md](ACCOUNTS_PROFILES_GUIDE.md)

### Интересуют схемы и диаграммы?
→ [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md)

### Ищете решение проблемы?
→ [CHECKLIST.md](CHECKLIST.md)

### Нужна техническая информация?
→ [ACCOUNTS_PROFILES_README.md](ACCOUNTS_PROFILES_README.md)

### Хотите общий обзор?
→ [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)

### Посмотреть демо?
→ `python3 demo_profiles.py`

### Проверить систему?
→ `./check_system.sh`

---

## 📞 Помощь

**Не знаете с чего начать?**
1. Откройте [INSTALLATION_COMPLETE.md](INSTALLATION_COMPLETE.md)
2. Следуйте инструкциям
3. Запустите `/accounts` в боте

**Что-то не работает?**
1. Запустите `./check_system.sh`
2. Изучите [CHECKLIST.md](CHECKLIST.md)
3. Проверьте логи бота

**Хотите понять как это работает?**
1. Прочитайте [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md)
2. Изучите код в `main.py` (строки 406-900)
3. Запустите `python3 demo_profiles.py`

---

**Эта карта поможет вам ориентироваться в проекте! 🗺️**
