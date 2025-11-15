"""
Модуль для работы с PostgreSQL базой данных.
Используется как альтернатива файловому хранилищу для постоянного сохранения данных.
"""
import os
import json
from typing import Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

# Глобальный пул соединений
connection_pool = None


def init_db_pool():
    """Инициализирует пул соединений с PostgreSQL."""
    global connection_pool
    
    # Railway автоматически создает DATABASE_URL для всех сервисов в проекте
    # Но если его нет, пробуем собрать из отдельных переменных
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        # Пробуем собрать из отдельных переменных (Railway может создавать их отдельно)
        pghost = os.getenv("PGHOST")
        pgport = os.getenv("PGPORT", "5432")
        pguser = os.getenv("PGUSER")
        pgpassword = os.getenv("PGPASSWORD")
        pgdatabase = os.getenv("PGDATABASE")
        
        if all([pghost, pguser, pgpassword, pgdatabase]):
            database_url = f"postgresql://{pguser}:{pgpassword}@{pghost}:{pgport}/{pgdatabase}"
            print(f"💡 DATABASE_URL собран из отдельных переменных")
        else:
            print("⚠️  DATABASE_URL не найден, PostgreSQL недоступен")
            print(f"   Проверьте, что PostgreSQL добавлен в проект и переменные доступны")
            return None
    
    try:
        # Создаем пул соединений (минимум 1, максимум 5)
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            1, 5,
            database_url,
            cursor_factory=RealDictCursor
        )
        print(f"✅ Пул соединений с PostgreSQL создан")
        # Показываем только хост для безопасности (не весь URL с паролем)
        if "://" in database_url:
            host_part = database_url.split("@")[-1].split("/")[0] if "@" in database_url else "unknown"
            print(f"   Подключение к: {host_part}")
        return connection_pool
    except Exception as e:
        print(f"❌ Ошибка при создании пула соединений PostgreSQL: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_connection():
    """Получает соединение из пула."""
    global connection_pool
    
    if not connection_pool:
        connection_pool = init_db_pool()
    
    if not connection_pool:
        return None
    
    try:
        return connection_pool.getconn()
    except Exception as e:
        print(f"⚠️  Ошибка при получении соединения: {e}")
        return None


def return_connection(conn):
    """Возвращает соединение в пул."""
    global connection_pool
    if connection_pool and conn:
        try:
            connection_pool.putconn(conn)
        except Exception as e:
            print(f"⚠️  Ошибка при возврате соединения: {e}")


def create_tables():
    """Создает таблицы в базе данных, если их нет."""
    conn = get_connection()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            # Создаем таблицу для почтовых аккаунтов
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_accounts (
                    account_id VARCHAR(10) PRIMARY KEY,
                    account_data JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Создаем индекс для быстрого поиска
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_email_accounts_account_id 
                ON email_accounts(account_id)
            """)
            
            conn.commit()
            print("✅ Таблицы в PostgreSQL созданы/проверены")
            return True
    except Exception as e:
        print(f"❌ Ошибка при создании таблиц: {e}")
        conn.rollback()
        return False
    finally:
        return_connection(conn)


def load_accounts_from_db() -> Dict[str, dict]:
    """Загружает аккаунты из PostgreSQL."""
    conn = get_connection()
    if not conn:
        return {}
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT account_id, account_data FROM email_accounts")
            rows = cur.fetchall()
            
            accounts = {}
            for row in rows:
                account_id = row['account_id']
                account_data = row['account_data']
                # Преобразуем JSONB в обычный dict
                if isinstance(account_data, dict):
                    accounts[account_id] = account_data
                else:
                    accounts[account_id] = json.loads(account_data) if isinstance(account_data, str) else account_data
            
            if accounts:
                print(f"✅ Загружено аккаунтов из PostgreSQL: {len(accounts)} ({list(accounts.keys())})")
            else:
                print("📭 В PostgreSQL нет аккаунтов")
            
            return accounts
    except Exception as e:
        print(f"⚠️  Ошибка при загрузке аккаунтов из PostgreSQL: {e}")
        return {}
    finally:
        return_connection(conn)


def save_accounts_to_db(accounts: Dict[str, dict]) -> bool:
    """Сохраняет аккаунты в PostgreSQL."""
    if not accounts:
        print("⚠️  Попытка сохранить пустой словарь аккаунтов в PostgreSQL! Пропускаем.")
        return False
    
    conn = get_connection()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            # Удаляем все существующие аккаунты
            cur.execute("DELETE FROM email_accounts")
            
            # Вставляем новые аккаунты
            for account_id, account_data in accounts.items():
                cur.execute("""
                    INSERT INTO email_accounts (account_id, account_data, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (account_id) 
                    DO UPDATE SET 
                        account_data = EXCLUDED.account_data,
                        updated_at = CURRENT_TIMESTAMP
                """, (account_id, json.dumps(account_data, ensure_ascii=False)))
            
            conn.commit()
            print(f"✅ Аккаунты сохранены в PostgreSQL: {list(accounts.keys())}")
            return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении аккаунтов в PostgreSQL: {e}")
        conn.rollback()
        return False
    finally:
        return_connection(conn)


def is_postgresql_available() -> bool:
    """Проверяет, доступен ли PostgreSQL."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return False
    
    # Пробуем подключиться
    conn = get_connection()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except:
        return False
    finally:
        return_connection(conn)

