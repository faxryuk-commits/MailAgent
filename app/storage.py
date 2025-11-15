"""
Модуль для работы с хранением почтовых аккаунтов.
Поддерживает несколько способов хранения:
1. PostgreSQL (приоритет, если доступен)
2. Переменная окружения EMAIL_ACCOUNTS_JSON
3. Файл email_accounts.json
"""
import json
import os
from typing import Dict, Optional
from pathlib import Path

# Пробуем импортировать модуль для работы с PostgreSQL
try:
    from app.db_storage import (
        init_db_pool, create_tables, load_accounts_from_db, 
        save_accounts_to_db, is_postgresql_available
    )
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False
    print("⚠️  Модуль db_storage недоступен, PostgreSQL не будет использоваться")

# Определяем путь к файлу хранилища
# На Railway используем Volume для постоянного хранения
# Если переменная STORAGE_PATH не задана, используем /data (стандартный путь для Railway Volume)
# Если /data недоступен, используем текущую директорию (для локальной разработки)
STORAGE_DIR = os.getenv("STORAGE_PATH", "/data")
if not os.path.exists(STORAGE_DIR):
    # Если /data не существует (локальная разработка), используем текущую директорию
    STORAGE_DIR = os.getcwd()
    print(f"⚠️  /data не найден, используем текущую директорию: {STORAGE_DIR}")

# Создаем директорию, если её нет
Path(STORAGE_DIR).mkdir(parents=True, exist_ok=True)

STORAGE_FILE = os.path.join(STORAGE_DIR, "email_accounts.json")
print(f"📁 Файл хранилища: {STORAGE_FILE}")

# Альтернативное хранилище через переменные окружения (если Volume недоступен)
# Если EMAIL_ACCOUNTS_JSON задана, используем её вместо файла
ENV_STORAGE_KEY = "EMAIL_ACCOUNTS_JSON"


def migrate_old_accounts() -> None:
    """
    Мигрирует аккаунты из старого места (текущая директория) в новое (/data).
    Вызывается только если /data доступен и там нет файла, но есть в старом месте.
    """
    if STORAGE_DIR != "/data":
        # Миграция нужна только если мы используем /data
        return
    
    old_storage_file = os.path.join(os.getcwd(), "email_accounts.json")
    
    # Если новый файл уже существует, миграция не нужна
    if os.path.exists(STORAGE_FILE):
        return
    
    # Если старый файл существует, мигрируем его
    if os.path.exists(old_storage_file):
        try:
            print(f"🔄 Обнаружен старый файл аккаунтов: {old_storage_file}")
            print(f"   Мигрирую в новое хранилище: {STORAGE_FILE}")
            
            with open(old_storage_file, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
            
            if accounts:
                # Сохраняем в новое место
                with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(accounts, f, indent=2, ensure_ascii=False)
                
                print(f"✅ Миграция завершена: {len(accounts)} аккаунтов перенесены")
                print(f"   Старый файл сохранен как резервная копия")
                
                # Переименовываем старый файл как резервную копию
                backup_file = old_storage_file + ".backup"
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                os.rename(old_storage_file, backup_file)
                print(f"   Резервная копия: {backup_file}")
            else:
                print("   Старый файл пуст, миграция не требуется")
        except Exception as e:
            print(f"⚠️  Ошибка при миграции аккаунтов: {e}")
            print(f"   Продолжаем работу, данные останутся в старом месте")


# Выполняем миграцию при импорте модуля
migrate_old_accounts()

# Инициализируем PostgreSQL при импорте (если доступен)
print("🔄 Попытка инициализации PostgreSQL...")
if POSTGRESQL_AVAILABLE:
    try:
        pool = init_db_pool()
        if pool:
            # Создаем таблицы при первом запуске
            create_tables()
            print("✅ PostgreSQL инициализирован и готов к работе")
        else:
            print("⚠️  Не удалось создать пул соединений PostgreSQL")
    except Exception as e:
        print(f"⚠️  Ошибка при инициализации PostgreSQL: {e}")
        import traceback
        traceback.print_exc()
else:
    print("⚠️  PostgreSQL модуль недоступен (psycopg2 не установлен?)")


def load_accounts() -> Dict[str, dict]:
    """
    Загружает аккаунты из хранилища.
    Приоритет: PostgreSQL > Переменная окружения > Файл
    """
    # 1. Пробуем загрузить из PostgreSQL (наивысший приоритет)
    if POSTGRESQL_AVAILABLE and is_postgresql_available():
        accounts = load_accounts_from_db()
        if accounts:
            return accounts
        # Если PostgreSQL доступен, но пуст, не загружаем из других источников
        # (чтобы не перезаписать данные при следующем сохранении)
        return {}
    
    # 2. Проверяем переменную окружения
    env_data = os.getenv(ENV_STORAGE_KEY)
    if env_data:
        try:
            accounts = json.loads(env_data)
            if accounts:
                print(f"✅ Загружено аккаунтов из переменной окружения {ENV_STORAGE_KEY}: {len(accounts)} ({list(accounts.keys())})")
            else:
                print(f"📭 Переменная окружения {ENV_STORAGE_KEY} пуста")
            return accounts
        except json.JSONDecodeError as e:
            print(f"⚠️  Ошибка при парсинге {ENV_STORAGE_KEY}: {e}")
            # Продолжаем загрузку из файла
    
    # 3. Загружаем из файла (последний вариант)
    if not os.path.exists(STORAGE_FILE):
        print(f"📭 Файл аккаунтов не найден: {STORAGE_FILE}")
        return {}
    
    try:
        with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
            if accounts:
                print(f"✅ Загружено аккаунтов из {STORAGE_FILE}: {len(accounts)} ({list(accounts.keys())})")
            else:
                print(f"📭 Файл аккаунтов пуст: {STORAGE_FILE}")
            return accounts
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️  Ошибка при загрузке аккаунтов из {STORAGE_FILE}: {e}")
        return {}


def save_accounts(accounts: Dict[str, dict]) -> None:
    """
    Сохраняет аккаунты в хранилище.
    Приоритет: PostgreSQL > Файл > Переменная окружения (только для информации)
    """
    # Защита от случайной перезаписи пустым словарем
    if not accounts:
        print("⚠️  Попытка сохранить пустой словарь аккаунтов! Пропускаем сохранение.")
        return
    
    # 1. Пробуем сохранить в PostgreSQL (наивысший приоритет)
    if POSTGRESQL_AVAILABLE and is_postgresql_available():
        if save_accounts_to_db(accounts):
            # Если успешно сохранили в PostgreSQL, всё готово
            return
        # Если не удалось, продолжаем сохранение в файл
    
    # 2. Сохраняем в файл (резервный вариант)
    try:
        # Создаем директорию, если её нет (на случай, если она была удалена)
        Path(STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
        
        # Проверяем, что файл действительно записался
        if os.path.exists(STORAGE_FILE):
            file_size = os.path.getsize(STORAGE_FILE)
            print(f"✅ Аккаунты сохранены в {STORAGE_FILE}: {list(accounts.keys())} (размер: {file_size} байт)")
        else:
            print(f"⚠️  Файл не был создан: {STORAGE_FILE} (возможно, нет доступа к файловой системе)")
    except Exception as e:
        print(f"⚠️  Не удалось сохранить в файл {STORAGE_FILE}: {e}")
    
    # 3. Информация о переменной окружения (только если PostgreSQL недоступен)
    if not (POSTGRESQL_AVAILABLE and is_postgresql_available()):
        accounts_json = json.dumps(accounts, ensure_ascii=False)
        print(f"💡 Для постоянного хранения без PostgreSQL:")
        print(f"   1. Скопируйте следующий JSON:")
        print(f"   {accounts_json[:200]}..." if len(accounts_json) > 200 else f"   {accounts_json}")
        print(f"   2. Добавьте переменную окружения EMAIL_ACCOUNTS_JSON в Railway")
        print(f"   3. Вставьте скопированный JSON как значение")


def get_account(account_id: int) -> Optional[dict]:
    """Получает настройки аккаунта по ID."""
    accounts = load_accounts()
    return accounts.get(str(account_id))


def save_account(account_id: int, account_data: dict) -> None:
    """Сохраняет настройки одного аккаунта."""
    # Защита от сохранения пустых данных
    if not account_data or not any(account_data.values()):
        print(f"⚠️  Попытка сохранить пустой аккаунт {account_id}! Пропускаем сохранение.")
        return
    
    accounts = load_accounts()
    # Сохраняем существующие данные других аккаунтов
    accounts[str(account_id)] = account_data
    save_accounts(accounts)
    print(f"✅ Аккаунт {account_id} сохранен. Всего аккаунтов: {len(accounts)}")

