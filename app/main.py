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
            
            # Проверяем оба аккаунта
            if "1" in accounts:
                print(f"Проверка аккаунта 1...")
                await check_account_emails(1, telegram_notify_func=send_notification)
            
            if "2" in accounts:
                print(f"Проверка аккаунта 2...")
                await check_account_emails(2, telegram_notify_func=send_notification)
            
            # Ждём перед следующей проверкой
            await asyncio.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            print(f"Ошибка в цикле проверки почты: {e}")
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
    except Exception as e:
        print(f"❌ Ошибка инициализации Telegram бота: {e}")
        return
    
    # Загрузка аккаунтов
    accounts = load_accounts()
    print(f"✅ Загружено аккаунтов: {len(accounts)}")
    
    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("\n🚀 Запуск сервиса...")
    print(f"📧 Проверка почты каждые {CHECK_INTERVAL} секунд")
    print("💬 Telegram бот готов к работе")
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

