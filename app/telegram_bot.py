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
from app.email_client import send_email_smtp, get_email_from_cache, test_imap_connection
from app.ai_client import polish_reply
from app.oauth_client import get_authorization_url, exchange_code_for_tokens, refresh_access_token

# Глобальные переменные для бота
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None

def get_owner_id():
    """Получает ID владельца из переменных окружения."""
    owner_id = os.getenv("OWNER_TELEGRAM_ID")
    if not owner_id:
        return 0
    try:
        return int(owner_id)
    except ValueError:
        return 0

OWNER_TELEGRAM_ID = get_owner_id()


# FSM состояния для настройки аккаунтов
class SetupStates(StatesGroup):
    gmail_user = State()
    gmail_oauth_code = State()  # Для OAuth2 кода
    gmail_pass = State()  # Fallback для пароля
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
    async def wrapper(event, *args, **kwargs):
        # Поддерживаем как Message, так и CallbackQuery
        if isinstance(event, types.Message):
            user_id = event.from_user.id
            answer_func = event.answer
        elif isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
            answer_func = event.message.answer if event.message else None
        else:
            user_id = getattr(event, 'from_user', None)
            if user_id:
                user_id = user_id.id
            answer_func = None
        
        if user_id != OWNER_TELEGRAM_ID:
            if answer_func:
                await answer_func("❌ У вас нет доступа к этому боту.")
            return
        return await func(event, *args, **kwargs)
    return wrapper


@check_owner
async def handle_start(message: types.Message, **kwargs):
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


@check_owner
async def handle_callback(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Обработчик callback-кнопок."""
    
    data = callback.data
    
    if data.startswith("setup:"):
        parts = data.split(":")
        account_id = int(parts[1])
        provider = parts[2]
        
        await callback.answer()
        
        if provider == "gmail":
            await state.update_data(account_id=account_id, provider="gmail")
            await state.set_state(SetupStates.gmail_user)
            
            # Проверяем, настроен ли OAuth2
            from app.oauth_client import CLIENT_ID, CLIENT_SECRET
            if CLIENT_ID and CLIENT_SECRET:
                await callback.message.answer(
                    f"📧 Настройка аккаунта {account_id} (Gmail)\n\n"
                    "Введите ваш email адрес для OAuth2 авторизации:"
                )
            else:
                await callback.message.answer(
                    f"📧 Настройка аккаунта {account_id} (Gmail)\n\n"
                    "⚠️ OAuth2 не настроен. Используется авторизация по паролю.\n"
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


async def handle_text_message(message: types.Message, state: FSMContext, **kwargs):
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
        
        # Проверяем, настроен ли OAuth2
        from app.oauth_client import CLIENT_ID, CLIENT_SECRET, get_authorization_url
        data = await state.get_data()
        account_id = data["account_id"]
        
        if CLIENT_ID and CLIENT_SECRET:
            # Используем OAuth2
            try:
                auth_url = get_authorization_url(account_id, email)
                await state.set_state(SetupStates.gmail_oauth_code)
                await message.answer(
                    f"🔐 Авторизация через Google OAuth2\n\n"
                    f"📋 Инструкция:\n\n"
                    f"1️⃣ Откройте эту ссылку в браузере:\n"
                    f"🔗 {auth_url}\n\n"
                    f"2️⃣ Войдите в Google и разрешите доступ\n"
                    f"3️⃣ После авторизации вы будете перенаправлены на страницу с ошибкой - это нормально!\n"
                    f"4️⃣ Посмотрите на адресную строку браузера\n"
                    f"5️⃣ Найдите параметр `code=` в URL\n"
                    f"6️⃣ Скопируйте весь код после `code=` (до следующего `&` или до конца)\n"
                    f"7️⃣ Отправьте скопированный код боту\n\n"
                    f"💡 Пример кода: `4/0AeanS2AbCdEf...` (длинная строка)\n\n"
                    f"❓ Если не получается, отправьте 'skip' для использования пароля"
                )
            except Exception as e:
                await message.answer(
                    f"❌ Ошибка при создании OAuth2 ссылки: {e}\n\n"
                    "Попробуем использовать пароль вместо этого."
                )
                await state.set_state(SetupStates.gmail_pass)
                await message.answer(
                    "Введите пароль для Gmail:\n\n"
                    "💡 Сначала попробуем обычный пароль. Если не подойдет, попросим App Password."
                )
        else:
            # Fallback на пароль
            await state.set_state(SetupStates.gmail_pass)
            await message.answer(
                "Введите пароль для Gmail:\n\n"
                "💡 Сначала попробуем обычный пароль. Если не подойдет, попросим App Password."
            )
    
    elif current_state == SetupStates.gmail_oauth_code.state:
        # Обработка OAuth2 кода
        code = message.text.strip()
        
        # Позволяем пропустить OAuth2 и использовать пароль
        if code.lower() == 'skip':
            await state.set_state(SetupStates.gmail_pass)
            await message.answer(
                "⏭️ Пропускаем OAuth2. Используем авторизацию по паролю.\n\n"
                "Введите пароль для Gmail:\n\n"
                "💡 Сначала попробуем обычный пароль. Если не подойдет, попросим App Password."
            )
            return
        
        data = await state.get_data()
        account_id = data["account_id"]
        email = data["imap_user"]
        
        await message.answer("🔄 Обрабатываю код авторизации...")
        
        try:
            tokens = exchange_code_for_tokens(account_id, email, code)
            
            if not tokens:
                await message.answer(
                    "❌ Не удалось получить токены.\n\n"
                    "Возможные причины:\n"
                    "• Код истек (коды действительны несколько минут)\n"
                    "• Код уже был использован\n"
                    "• Неправильно скопирован код\n\n"
                    "Попробуйте:\n"
                    "1. Получить новую ссылку (начните настройку заново)\n"
                    "2. Или отправьте 'skip' для использования пароля"
                )
                return
        except Exception as e:
            await message.answer(
                f"❌ Ошибка при обработке кода: {str(e)}\n\n"
                "Попробуйте получить новый код или отправьте 'skip' для использования пароля."
            )
            return
        
        # Сохраняем аккаунт с OAuth2 токенами
        account_data = {
            "imap_host": "imap.gmail.com",
            "imap_user": email,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "auth_type": "oauth2",
            "oauth_tokens": tokens
        }
        
        save_account(account_id, account_data)
        await state.clear()
        await message.answer(
            f"✅ Аккаунт {account_id} (Gmail) успешно настроен через OAuth2!\n\n"
            "Бот будет проверять почту каждую минуту."
        )
    
    elif current_state == SetupStates.gmail_pass.state:
        password = message.text.strip()
        data = await state.get_data()
        account_id = data["account_id"]
        email = data["imap_user"]
        
        # Проверяем, не просили ли уже App Password
        needs_app_password = data.get("needs_app_password", False)
        
        if not needs_app_password:
            # Пробуем подключиться с обычным паролем
            await message.answer("🔄 Проверяю подключение...")
            
            success, error = await test_imap_connection(
                "imap.gmail.com",
                email,
                password
            )
            
            if not success and error == "authentication_error":
                # Не получилось с обычным паролем - просим App Password
                await state.update_data(needs_app_password=True)
                await message.answer(
                    "⚠️ Обычный пароль не подошел.\n\n"
                    "Похоже, у вас включена двухфакторная аутентификация.\n"
                    "Введите App Password для Gmail:\n\n"
                    "📖 Инструкция: https://support.google.com/accounts/answer/185833"
                )
                return
            elif not success:
                # Другая ошибка
                await message.answer(
                    f"❌ Ошибка подключения: {error}\n\n"
                    "Попробуйте еще раз или введите другой пароль:"
                )
                return
        
        # Пароль подошел или это уже App Password - сохраняем
        account_data = {
            "imap_host": "imap.gmail.com",
            "imap_user": email,
            "imap_pass": password,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587
        }
        
        # Финальная проверка перед сохранением
        await message.answer("🔄 Финальная проверка подключения...")
        success, error = await test_imap_connection(
            "imap.gmail.com",
            email,
            password
        )
        
        if not success:
            if error == "authentication_error":
                await message.answer(
                    "❌ Пароль не подошел.\n\n"
                    "Попробуйте еще раз или используйте App Password:\n"
                    "https://support.google.com/accounts/answer/185833"
                )
                return
            else:
                await message.answer(
                    f"❌ Ошибка подключения: {error}\n\n"
                    "Попробуйте еще раз:"
                )
                return
        
        save_account(account_id, account_data)
        await state.clear()
        await message.answer(
            f"✅ Аккаунт {account_id} (Gmail) успешно настроен!\n\n"
            "Бот будет проверять почту каждую минуту."
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
        data = await state.get_data()
        imap_host = data["imap_host"]
        imap_user = data["imap_user"]
        
        await state.update_data(imap_pass=imap_pass)
        
        # Проверяем подключение
        await message.answer("🔄 Проверяю подключение к IMAP...")
        success, error = await test_imap_connection(imap_host, imap_user, imap_pass)
        
        if not success:
            await message.answer(
                f"❌ Ошибка подключения к IMAP: {error}\n\n"
                "Проверьте правильность данных и попробуйте еще раз.\n"
                "Введите IMAP пароль:"
            )
            return
        
        await state.set_state(SetupStates.custom_smtp_host)
        await message.answer("✅ IMAP подключение успешно!\n\nВведите SMTP хост (например, smtp.example.com):")
    
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
async def handle_reply(message: types.Message, **kwargs):
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

