"""
Главный модуль приложения.
Точка входа для запуска почтового агента.
"""
import os
import asyncio
import signal
from dotenv import load_dotenv

from app.telegram_bot import init_bot, start_polling, send_notification
from app.email_client import check_account_emails
from app.storage import load_accounts
from app.ai_client import init_openai
# Импорт веб-приложения с обработкой ошибок
# Важно: даже если веб-приложение не загрузится, бот должен работать
web_app = None
try:
    print("🔄 Попытка импорта веб-приложения...")
    from app.web_app import app as web_app
    print("✅ Веб-приложение успешно импортировано")
except ImportError as e:
    print(f"⚠️  Ошибка импорта веб-приложения (ImportError): {e}")
    print("   Веб-интерфейс будет отключен, но бот продолжит работать")
    web_app = None
except Exception as e:
    print(f"⚠️  Ошибка импорта веб-приложения (другая ошибка): {e}")
    import traceback
    traceback.print_exc()
    print("   Веб-интерфейс будет отключен, но бот продолжит работать")
    web_app = None

# Интервал проверки почты (в секундах)
CHECK_INTERVAL = 60  # 1 минута

# Флаг для корректного завершения
running = True


def signal_handler(sig, frame):
    """Обработчик сигналов для корректного завершения."""
    global running
    print("\nПолучен сигнал завершения. Останавливаю сервис...")
    running = False


async def email_checker_loop():
    """Основной цикл проверки почты."""
    global running
    
    print("Запуск цикла проверки почты...")
    
    while running:
        try:
            accounts = load_accounts()
            print(f"📋 Загружено аккаунтов для проверки: {len(accounts)} ({list(accounts.keys())})")
            
            # Проверяем оба аккаунта
            if "1" in accounts:
                print(f"📧 Проверка аккаунта 1...")
                try:
                    emails = await check_account_emails(1, telegram_notify_func=send_notification)
                    if emails:
                        print(f"  ✅ Найдено новых писем: {len(emails)}")
                    else:
                        print(f"  ℹ️  Новых писем нет")
                except Exception as e:
                    print(f"  ❌ Ошибка при проверке аккаунта 1: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"  ⚪ Аккаунт 1 не настроен")
            
            if "2" in accounts:
                print(f"📧 Проверка аккаунта 2...")
                try:
                    emails = await check_account_emails(2, telegram_notify_func=send_notification)
                    if emails:
                        print(f"  ✅ Найдено новых писем: {len(emails)}")
                    else:
                        print(f"  ℹ️  Новых писем нет")
                except Exception as e:
                    print(f"  ❌ Ошибка при проверке аккаунта 2: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"  ⚪ Аккаунт 2 не настроен")
            
            print(f"⏳ Ожидание {CHECK_INTERVAL} секунд до следующей проверки...")
            # Ждём перед следующей проверкой
            await asyncio.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            print(f"❌ Ошибка в цикле проверки почты: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(CHECK_INTERVAL)


async def main():
    """Главная функция приложения."""
    global running
    
    # Загрузка переменных окружения
    load_dotenv()
    
    # Проверка обязательных переменных
    required_vars = ["TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID", "OPENAI_API_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise ValueError(
            f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}"
        )
    
    print("Инициализация сервисов...")
    
    # Проверка PostgreSQL подключения
    print("\n🔍 Проверка подключения к PostgreSQL...")
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        print(f"✅ DATABASE_URL найден (длина: {len(database_url)} символов)")
        # Показываем только хост для безопасности
        if "@" in database_url:
            host_part = database_url.split("@")[-1].split("/")[0]
            print(f"   Хост: {host_part}")
    else:
        print("⚠️  DATABASE_URL не найден")
        # Проверяем отдельные переменные
        pghost = os.getenv("PGHOST")
        pguser = os.getenv("PGUSER")
        if pghost and pguser:
            print(f"💡 Найдены отдельные переменные: PGHOST={pghost}, PGUSER={pguser}")
        else:
            print("   PostgreSQL переменные не найдены")
            print("   💡 Убедитесь, что PostgreSQL добавлен в проект Railway")
            print("   💡 Railway должен автоматически создать DATABASE_URL для всех сервисов")
    
    # Проверка хранилища (импорт storage.py уже вывел путь к файлу)
    from app.storage import STORAGE_FILE, STORAGE_DIR
    try:
        from app.db_storage import is_postgresql_available
        if is_postgresql_available():
            print("💾 Хранилище: PostgreSQL (данные сохраняются между деплоями)")
        else:
            print(f"💾 Хранилище: {STORAGE_DIR}")
            if STORAGE_DIR == "/data":
                print("✅ Используется Railway Volume (данные сохраняются между деплоями)")
            else:
                print(f"⚠️  Используется локальное хранилище: {STORAGE_DIR}")
                print("   Для постоянного хранения на Railway настройте PostgreSQL или Volume")
    except ImportError as e:
        print(f"⚠️  Не удалось импортировать db_storage: {e}")
        print(f"💾 Хранилище: {STORAGE_DIR}")
        if STORAGE_DIR == "/data":
            print("✅ Используется Railway Volume (данные сохраняются между деплоями)")
        else:
            print(f"⚠️  Используется локальное хранилище: {STORAGE_DIR}")
            print("   Для постоянного хранения на Railway настройте PostgreSQL или Volume")
    except Exception as e:
        print(f"⚠️  Ошибка при проверке PostgreSQL: {e}")
        import traceback
        traceback.print_exc()
    
    # Инициализация OpenAI
    try:
        init_openai()
        print("✅ OpenAI инициализирован")
    except Exception as e:
        print(f"❌ Ошибка инициализации OpenAI: {e}")
        return
    
    # Инициализация Telegram бота
    try:
        bot, dp = init_bot()
        print("✅ Telegram бот инициализирован")
        print(f"✅ OWNER_TELEGRAM_ID: {os.getenv('OWNER_TELEGRAM_ID')}")
    except Exception as e:
        print(f"❌ Ошибка инициализации Telegram бота: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Загрузка аккаунтов
    accounts = load_accounts()
    print(f"✅ Загружено аккаунтов: {len(accounts)}")
    if accounts:
        print(f"   Аккаунты: {list(accounts.keys())}")
    
    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("\n🚀 Запуск сервиса...")
    print(f"📧 Проверка почты каждые {CHECK_INTERVAL} секунд")
    print("💬 Telegram бот готов к работе")
    
    # Проверяем, нужно ли запускать веб-приложение
    web_enabled = os.getenv("WEB_ENABLED", "false").lower() == "true"
    
    # Обработка порта: если WEB_PORT=$PORT, используем переменную PORT от Railway
    web_port_str = os.getenv("WEB_PORT", "8000")
    if web_port_str == "$PORT":
        # Railway автоматически устанавливает переменную PORT
        web_port_str = os.getenv("PORT", "8000")
    
    try:
        web_port = int(web_port_str)
    except ValueError:
        print(f"⚠️  Неверное значение WEB_PORT: '{web_port_str}', используем 8000")
        web_port = 8000
    
    if web_enabled and web_app is not None:
        print(f"🌐 Веб-интерфейс доступен на http://0.0.0.0:{web_port}")
        # Запускаем веб-приложение в отдельном процессе
        import threading
        import uvicorn
        
        def run_web():
            try:
                uvicorn.run(web_app, host="0.0.0.0", port=web_port, log_level="info")
            except Exception as e:
                print(f"❌ Ошибка запуска веб-сервера: {e}")
                import traceback
                traceback.print_exc()
        
        web_thread = threading.Thread(target=run_web, daemon=True)
        web_thread.start()
    elif web_enabled and web_app is None:
        print("⚠️  WEB_ENABLED=true, но веб-приложение не загружено")
    else:
        print("💡 Для включения веб-интерфейса установите WEB_ENABLED=true")
    
    print("\nНажмите Ctrl+C для остановки\n")
    
    # Запуск задач
    bot_task = asyncio.create_task(start_polling())
    email_task = asyncio.create_task(email_checker_loop())
    
    try:
        # Ожидание завершения задач
        await asyncio.gather(bot_task, email_task)
    except asyncio.CancelledError:
        pass
    finally:
        # Корректное завершение
        print("Остановка сервиса...")
        bot_task.cancel()
        email_task.cancel()
        
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        
        try:
            await email_task
        except asyncio.CancelledError:
            pass
        
        if bot:
            await bot.session.close()
        
        print("✅ Сервис остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nЗавершение работы...")
    except Exception as e:
        print(f"Критическая ошибка: {e}")

