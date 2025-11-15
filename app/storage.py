"""
Модуль для работы с хранением почтовых аккаунтов.
"""
import json
import os
from typing import Dict, Optional
from pathlib import Path

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


def load_accounts() -> Dict[str, dict]:
    """Загружает аккаунты из email_accounts.json."""
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
    """Сохраняет аккаунты в email_accounts.json."""
    # Защита от случайной перезаписи пустым словарем
    if not accounts:
        print("⚠️  Попытка сохранить пустой словарь аккаунтов! Пропускаем сохранение.")
        return
    
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
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Файл не был создан после записи: {STORAGE_FILE}")
            raise IOError(f"Файл не был создан: {STORAGE_FILE}")
    except Exception as e:
        print(f"❌ Ошибка при сохранении аккаунтов в {STORAGE_FILE}: {e}")
        import traceback
        traceback.print_exc()
        raise


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

