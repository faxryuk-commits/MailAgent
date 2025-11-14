"""
Модуль для работы с Telegram ботом.
"""
import os
import asyncio
from typing import Optional
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.storage import save_account, get_account, load_accounts
from app.email_client import send_email_smtp, get_email_from_cache
from app.ai_client import polish_reply

# Глобальные переменные для бота
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None

OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))


# FSM состояния для настройки аккаунтов
class SetupStates(StatesGroup):
    gmail_user = State()
    gmail_pass = State()
    custom_imap_host = State()
    custom_imap_user = State()
    custom_imap_pass = State()
    custom_smtp_host = State()
    custom_smtp_port = State()


# Глобальная переменная для функции уведомлений
notify_function = None


def init_bot():
    """Инициализирует бота и диспетчер."""
    global bot, dp
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
    
    bot = Bot(token=token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрация обработчиков (важен порядок - более специфичные первыми)
    dp.message.register(handle_start, Command("start"))
    dp.message.register(handle_reply, Command("reply"))
    dp.callback_query.register(handle_callback)
    # Обработчик текстовых сообщений для FSM (должен быть последним)
    dp.message.register(handle_text_message)
    
    return bot, dp


def check_owner(func):
    """Декоратор для проверки, что пользователь - владелец."""
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.from_user.id != OWNER_TELEGRAM_ID:
            await message.answer("❌ У вас нет доступа к этому боту.")
            return
        return await func(message, *args, **kwargs)
    return wrapper


@check_owner
async def handle_start(message: types.Message):
    """Обработчик команды /start."""
    keyboard = InlineKeyboardBuilder()
    
    keyboard.add(InlineKeyboardButton(
        text="Аккаунт 1 — Gmail",
        callback_data="setup:1:gmail"
    ))
    keyboard.add(InlineKeyboardButton(
        text="Аккаунт 1 — Другая почта",
        callback_data="setup:1:custom"
    ))
    keyboard.add(InlineKeyboardButton(
        text="Аккаунт 2 — Gmail",
        callback_data="setup:2:gmail"
    ))
    keyboard.add(InlineKeyboardButton(
        text="Аккаунт 2 — Другая почта",
        callback_data="setup:2:custom"
    ))
    
    await message.answer(
        "👋 Добро пожаловать в Mail Agent AI!\n\n"
        "Выберите аккаунт для настройки:",
        reply_markup=keyboard.as_markup()
    )


async def handle_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback-кнопок."""
    if callback.from_user.id != OWNER_TELEGRAM_ID:
        await callback.answer("❌ У вас нет доступа.", show_alert=True)
        return
    
    data = callback.data
    
    if data.startswith("setup:"):
        parts = data.split(":")
        account_id = int(parts[1])
        provider = parts[2]
        
        await callback.answer()
        
        if provider == "gmail":
            await state.update_data(account_id=account_id, provider="gmail")
            await state.set_state(SetupStates.gmail_user)
            await callback.message.answer(
                f"📧 Настройка аккаунта {account_id} (Gmail)\n\n"
                "Введите ваш email адрес:"
            )
        elif provider == "custom":
            await state.update_data(account_id=account_id, provider="custom")
            await state.set_state(SetupStates.custom_imap_host)
            await callback.message.answer(
                f"📧 Настройка аккаунта {account_id} (Custom)\n\n"
                "Введите IMAP хост (например, imap.example.com):"
            )
    elif data.startswith("quick_reply:"):
        local_id = data.split(":", 1)[1]
        await callback.answer()
        await callback.message.answer(
            f"💬 Для ответа на это письмо используйте команду:\n\n"
            f"`/reply {local_id} ваш текст ответа`\n\n"
            f"Пример:\n"
            f"`/reply {local_id} давайте созвонимся завтра`",
            parse_mode="Markdown"
        )


async def handle_text_message(message: types.Message, state: FSMContext):
    """Обработчик текстовых сообщений (для FSM)."""
    if message.from_user.id != OWNER_TELEGRAM_ID:
        return
    
    # Пропускаем, если это команда (она уже обработана другими обработчиками)
    if message.text and message.text.startswith('/'):
        return
    
    current_state = await state.get_state()
    
    if current_state == SetupStates.gmail_user.state:
        email = message.text.strip()
        await state.update_data(imap_user=email)
        await state.set_state(SetupStates.gmail_pass)
        await message.answer(
            "Введите App Password для Gmail:\n\n"
            "⚠️ Необходимо использовать App Password, а не обычный пароль.\n"
            "Инструкция: https://support.google.com/accounts/answer/185833"
        )
    
    elif current_state == SetupStates.gmail_pass.state:
        password = message.text.strip()
        data = await state.get_data()
        account_id = data["account_id"]
        
        account_data = {
            "imap_host": "imap.gmail.com",
            "imap_user": data["imap_user"],
            "imap_pass": password,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587
        }
        
        save_account(account_id, account_data)
        await state.clear()
        await message.answer(
            f"✅ Аккаунт {account_id} (Gmail) успешно настроен!"
        )
    
    elif current_state == SetupStates.custom_imap_host.state:
        imap_host = message.text.strip()
        await state.update_data(imap_host=imap_host)
        await state.set_state(SetupStates.custom_imap_user)
        await message.answer("Введите IMAP логин (email):")
    
    elif current_state == SetupStates.custom_imap_user.state:
        imap_user = message.text.strip()
        await state.update_data(imap_user=imap_user)
        await state.set_state(SetupStates.custom_imap_pass)
        await message.answer("Введите IMAP пароль:")
    
    elif current_state == SetupStates.custom_imap_pass.state:
        imap_pass = message.text.strip()
        await state.update_data(imap_pass=imap_pass)
        await state.set_state(SetupStates.custom_smtp_host)
        await message.answer("Введите SMTP хост (например, smtp.example.com):")
    
    elif current_state == SetupStates.custom_smtp_host.state:
        smtp_host = message.text.strip()
        await state.update_data(smtp_host=smtp_host)
        await state.set_state(SetupStates.custom_smtp_port)
        await message.answer("Введите SMTP порт (обычно 587 или 465):")
    
    elif current_state == SetupStates.custom_smtp_port.state:
        try:
            smtp_port = int(message.text.strip())
            if smtp_port < 1 or smtp_port > 65535:
                raise ValueError()
        except ValueError:
            await message.answer(
                "❌ Некорректный порт. Введите число от 1 до 65535:"
            )
            return
        
        data = await state.get_data()
        account_id = data["account_id"]
        
        account_data = {
            "imap_host": data["imap_host"],
            "imap_user": data["imap_user"],
            "imap_pass": data["imap_pass"],
            "smtp_host": data["smtp_host"],
            "smtp_port": smtp_port
        }
        
        save_account(account_id, account_data)
        await state.clear()
        await message.answer(
            f"✅ Аккаунт {account_id} (Custom) успешно настроен!"
        )


@check_owner
async def handle_reply(message: types.Message):
    """Обработчик команды /reply <ID> <текст>."""
    text = message.text.strip()
    parts = text.split(None, 2)  # /reply ID текст
    
    if len(parts) < 3:
        await message.answer(
            "❌ Неверный формат команды.\n\n"
            "Использование: /reply <ID> <текст ответа>\n\n"
            "Пример: /reply 1-1234567890 давайте созвонимся завтра"
        )
        return
    
    local_id = parts[1]
    draft_text = parts[2]
    
    # Получаем письмо из кэша
    email_data = get_email_from_cache(local_id)
    if not email_data:
        await message.answer(f"❌ Письмо с ID {local_id} не найдено в кэше.")
        return
    
    # Улучшаем ответ через AI
    context = f"От: {email_data['from']}\nТема: {email_data['subject']}\n\n{email_data['body'][:500]}"
    polished_reply = polish_reply(draft_text, context)
    
    # Отправляем письмо
    account_id = email_data["account_id"]
    # Извлекаем email адрес из поля "From"
    from_field = email_data["from"]
    if "<" in from_field and ">" in from_field:
        to_email = from_field.split("<")[-1].split(">")[0].strip()
    else:
        to_email = from_field.strip()
    subject = f"Re: {email_data['subject']}"
    
    success, msg = await send_email_smtp(
        account_id,
        to_email,
        subject,
        polished_reply,
        telegram_notify_func=send_notification
    )
    
    if success:
        await message.answer(
            f"✅ Ответ отправлен!\n\n"
            f"Получатель: {to_email}\n"
            f"Текст ответа:\n{polished_reply}"
        )
    else:
        await message.answer(f"❌ Ошибка при отправке: {msg}")


async def send_notification(text: str, local_id: str = None):
    """Отправляет уведомление владельцу в Telegram."""
    if not bot:
        return
    
    try:
        if local_id:
            # Добавляем кнопку для быстрого ответа
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(
                text="💬 Ответить",
                callback_data=f"quick_reply:{local_id}"
            ))
            await bot.send_message(
                OWNER_TELEGRAM_ID,
                text,
                reply_markup=keyboard.as_markup(),
                parse_mode="Markdown"
            )
        else:
            await bot.send_message(OWNER_TELEGRAM_ID, text)
    except Exception as e:
        print(f"Ошибка при отправке уведомления в Telegram: {e}")


async def start_polling():
    """Запускает polling бота."""
    global bot, dp
    
    if not bot or not dp:
        bot, dp = init_bot()
    
    print("🔄 Запуск polling...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка при запуске polling: {e}")
        raise

