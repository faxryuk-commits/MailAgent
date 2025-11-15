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


def load_accounts() -> Dict[str, dict]:
    """Загружает аккаунты из email_accounts.json."""
    if not os.path.exists(STORAGE_FILE):
        return {}
    
    try:
        with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_accounts(accounts: Dict[str, dict]) -> None:
    """Сохраняет аккаунты в email_accounts.json."""
    # Защита от случайной перезаписи пустым словарем
    if not accounts:
        print("⚠️  Попытка сохранить пустой словарь аккаунтов! Пропускаем сохранение.")
        return
    
    try:
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
        print(f"✅ Аккаунты сохранены: {list(accounts.keys())}")
    except Exception as e:
        print(f"❌ Ошибка при сохранении аккаунтов: {e}")
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

