"""
Модуль для работы с хранением почтовых аккаунтов.
"""
import json
import os
from typing import Dict, Optional

STORAGE_FILE = "email_accounts.json"


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
    with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


def get_account(account_id: int) -> Optional[dict]:
    """Получает настройки аккаунта по ID."""
    accounts = load_accounts()
    return accounts.get(str(account_id))


def save_account(account_id: int, account_data: dict) -> None:
    """Сохраняет настройки одного аккаунта."""
    accounts = load_accounts()
    accounts[str(account_id)] = account_data
    save_accounts(accounts)

