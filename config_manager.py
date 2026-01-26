"""
Модуль управления конфигурацией бота
Сохраняет все настройки в config.json для полного восстановления состояния после перезапуска
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

CONFIG_FILE = 'config.json'
CONFIG_BACKUP_FILE = 'config.json.bak'

# Значения по умолчанию
DEFAULT_CONFIG = {
    # Основные настройки
    'speed': 20,  # сообщений в час на аккаунт
    'max_parallel_accounts': 2,  # количество одновременно активных аккаунтов
    'rotation_interval': 14400,  # интервал ротации в секундах (4 часа)
    
    # Режим работы воркеров
    'worker_mode': 'distributed',  # cyclic или distributed
    'max_cycles_per_worker': 3,  # количество циклов перед ротацией (0 = бесконечно)
    'worker_recovery_enabled': True,  # автоматическое восстановление воркеров
    
    # Тестовый режим
    'test_mode': False,
    'test_channels': [],  # список тестовых каналов
    'test_mode_speed_limit': 10,  # лимит в тестовом режиме
    
    # Активные аккаунты (список номеров телефонов в формате +1234567890)
    'active_accounts': [],
    
    # Дополнительные настройки
    'min_interval_between_own_accounts': 300,  # 5 минут
    'enable_comment_logging': False,  # логирование комментариев для отладки
    
    # Параметры генерации комментариев
    'comment_temperature': 0.8,
    'comment_max_tokens': 120,
    
    # Время последнего обновления
    'last_updated': None,
    'version': '1.0'
}


def load_config():
    """
    Загружает конфигурацию из config.json
    При отсутствии файла создаёт новый с дефолтными значениями
    
    Returns:
        dict: Конфигурация бота
    """
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"✅ Конфигурация загружена из {CONFIG_FILE}")
                
                # Дополняем недостающие ключи значениями по умолчанию
                updated = False
                for key, default_value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = default_value
                        updated = True
                        logger.info(f"  Добавлен отсутствующий параметр: {key} = {default_value}")
                
                # Если были обновления, сохраняем
                if updated:
                    save_config(config)
                    logger.info("  Конфигурация обновлена с новыми параметрами")
                
                return config
        else:
            logger.warning(f"⚠️ {CONFIG_FILE} не найден, создаю с дефолтными значениями")
            config = DEFAULT_CONFIG.copy()
            config['last_updated'] = datetime.now().isoformat()
            save_config(config)
            return config
            
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга {CONFIG_FILE}: {e}")
        logger.warning(f"  Восстановление из бэкапа: {CONFIG_BACKUP_FILE}")
        
        # Пробуем загрузить бэкап
        if os.path.exists(CONFIG_BACKUP_FILE):
            try:
                with open(CONFIG_BACKUP_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    logger.info(f"✅ Конфигурация восстановлена из бэкапа")
                    return config
            except Exception as backup_err:
                logger.error(f"❌ Не удалось загрузить бэкап: {backup_err}")
        
        # Если и бэкап не помог, используем дефолт
        logger.warning("⚠️ Использую дефолтную конфигурацию")
        return DEFAULT_CONFIG.copy()
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки конфигурации: {e}")
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """
    Сохраняет конфигурацию в config.json с атомарной записью и бэкапом
    
    Args:
        config (dict): Конфигурация для сохранения
    """
    try:
        # Обновляем время последнего изменения
        config['last_updated'] = datetime.now().isoformat()
        
        # Создаём бэкап текущего файла (если существует)
        if os.path.exists(CONFIG_FILE):
            try:
                import shutil
                shutil.copy2(CONFIG_FILE, CONFIG_BACKUP_FILE)
                logger.debug(f"Создан бэкап: {CONFIG_BACKUP_FILE}")
            except Exception as e:
                logger.warning(f"Не удалось создать бэкап: {e}")
        
        # Атомарная запись через временный файл
        temp_file = f'{CONFIG_FILE}.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # Перемещаем временный файл на место основного
        import shutil
        shutil.move(temp_file, CONFIG_FILE)
        
        logger.debug(f"✅ Конфигурация сохранена в {CONFIG_FILE}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения конфигурации: {e}")
        # Удаляем временный файл при ошибке
        temp_file = f'{CONFIG_FILE}.tmp'
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        raise


def get_config_value(config, key, default=None):
    """
    Безопасное получение значения из конфига
    
    Args:
        config (dict): Конфигурация
        key (str): Ключ параметра
        default: Значение по умолчанию
        
    Returns:
        Значение параметра или default
    """
    return config.get(key, default if default is not None else DEFAULT_CONFIG.get(key))


def update_config_value(config, key, value):
    """
    Обновляет значение в конфиге и сразу сохраняет
    
    Args:
        config (dict): Конфигурация
        key (str): Ключ параметра
        value: Новое значение
        
    Returns:
        dict: Обновлённая конфигурация
    """
    config[key] = value
    save_config(config)
    logger.info(f"  Обновлён параметр конфигурации: {key} = {value}")
    return config


def reset_config():
    """
    Сбрасывает конфигурацию к дефолтным значениям
    Создаёт бэкап текущей конфигурации
    
    Returns:
        dict: Новая конфигурация
    """
    # Создаём бэкап с датой
    if os.path.exists(CONFIG_FILE):
        backup_name = f'{CONFIG_FILE}.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        try:
            import shutil
            shutil.copy2(CONFIG_FILE, backup_name)
            logger.info(f"Создан бэкап старой конфигурации: {backup_name}")
        except Exception as e:
            logger.warning(f"Не удалось создать бэкап: {e}")
    
    # Создаём новую конфигурацию
    config = DEFAULT_CONFIG.copy()
    config['last_updated'] = datetime.now().isoformat()
    save_config(config)
    logger.info("✅ Конфигурация сброшена к дефолтным значениям")
    
    return config


def print_config(config):
    """
    Красиво выводит конфигурацию для отладки
    
    Args:
        config (dict): Конфигурация
        
    Returns:
        str: Форматированная строка с конфигурацией
    """
    lines = ["=" * 50, "ТЕКУЩАЯ КОНФИГУРАЦИЯ:", "=" * 50]
    
    for key, value in sorted(config.items()):
        if key == 'active_accounts' and isinstance(value, list) and len(value) > 3:
            # Сокращаем длинные списки
            lines.append(f"  {key}: [{', '.join(value[:3])}, ... ({len(value)} всего)]")
        elif key == 'test_channels' and isinstance(value, list) and len(value) > 3:
            lines.append(f"  {key}: [{', '.join(value[:3])}, ... ({len(value)} всего)]")
        else:
            lines.append(f"  {key}: {value}")
    
    lines.append("=" * 50)
    return "\n".join(lines)


# Экспорт основных функций
__all__ = [
    'load_config',
    'save_config',
    'get_config_value',
    'update_config_value',
    'reset_config',
    'print_config',
    'DEFAULT_CONFIG'
]
