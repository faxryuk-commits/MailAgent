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
from app.ai_client import polish_reply, understand_user_intent, generate_friendly_response, suggest_reply_options
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
    
    print("🔄 Инициализация Telegram бота...")
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
    
    print(f"✅ TELEGRAM_BOT_TOKEN получен (длина: {len(token)})")
    
    bot = Bot(token=token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    print("✅ Bot и Dispatcher созданы")
    
    # Регистрация обработчиков (важен порядок - более специфичные первыми)
    print("🔄 Регистрация обработчиков...")
    dp.message.register(handle_start, Command("start"))
    print("   ✅ /start зарегистрирован")
    dp.message.register(handle_reply, Command("reply"))
    print("   ✅ /reply зарегистрирован")
    dp.callback_query.register(handle_callback)
    print("   ✅ callback_query зарегистрирован")
    # Обработчик текстовых сообщений для FSM (должен быть последним)
    dp.message.register(handle_text_message)
    print("   ✅ text messages зарегистрирован")
    
    print(f"✅ OWNER_TELEGRAM_ID: {OWNER_TELEGRAM_ID}")
    
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
        
        if OWNER_TELEGRAM_ID == 0:
            print("⚠️  OWNER_TELEGRAM_ID не установлен! Пропускаем проверку.")
            return await func(event, *args, **kwargs)
        
        if user_id != OWNER_TELEGRAM_ID:
            print(f"⚠️  Доступ запрещен: user_id={user_id}, OWNER_TELEGRAM_ID={OWNER_TELEGRAM_ID}")
            if answer_func:
                try:
                    await answer_func("❌ У вас нет доступа к этому боту.")
                except Exception as e:
                    print(f"⚠️  Ошибка при отправке сообщения об отказе: {e}")
            return
        
        print(f"✅ Доступ разрешен: user_id={user_id}")
        return await func(event, *args, **kwargs)
    return wrapper


@check_owner
async def handle_start(message: types.Message, **kwargs):
    """Обработчик команды /start."""
    try:
        # Генерируем дружелюбное приветствие через AI (с обработкой ошибок)
        try:
            greeting = generate_friendly_response(
                "Пользователь запустил бота. Нужно поприветствовать и предложить настроить почтовый аккаунт."
            )
        except Exception as e:
            print(f"⚠️  Ошибка генерации приветствия через AI: {e}")
            greeting = "👋 Привет! Я Mail Agent AI - твой помощник для управления почтой."
        
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
            f"{greeting}\n\n"
            "Выберите аккаунт для настройки:",
            reply_markup=keyboard.as_markup()
        )
        print(f"✅ Команда /start обработана для пользователя {message.from_user.id}")
    except Exception as e:
        print(f"❌ Ошибка в handle_start: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.answer("❌ Произошла ошибка при обработке команды. Попробуйте позже.")
        except:
            pass


@check_owner
async def handle_callback(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Обработчик callback-кнопок."""
    
    data = callback.data
    
    if data.startswith("setup:"):
        parts = data.split(":")
        account_id = int(parts[1])
        provider = parts[2]
        
        # Отвечаем на callback быстро
        try:
            await callback.answer()
        except Exception as e:
            print(f"⚠️  Ошибка при ответе на callback (query expired?): {e}")
            # Продолжаем обработку
        
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
        
        # Отвечаем на callback быстро, до долгих операций
        try:
            await callback.answer("🔄 Анализирую письмо...")
        except Exception as e:
            print(f"⚠️  Ошибка при ответе на callback (query expired?): {e}")
            # Продолжаем обработку даже если callback истек
        
        # Получаем данные письма
        email_data = get_email_from_cache(local_id)
        if not email_data:
            try:
                await callback.message.answer(
                    "❌ Письмо не найдено в кэше. Возможно, оно уже удалено."
                )
            except Exception as e:
                print(f"⚠️  Ошибка при отправке сообщения: {e}")
            return
        
        # Генерируем варианты ответов через AI
        try:
            reply_options = suggest_reply_options(email_data)
        except Exception as e:
            print(f"⚠️  Ошибка при генерации вариантов ответов: {e}")
            reply_options = {"suggestions": [], "context": "Не удалось сгенерировать варианты ответов"}
        
        # Создаем клавиатуру с вариантами ответов
        keyboard = InlineKeyboardBuilder()
        
        for i, suggestion in enumerate(reply_options.get("suggestions", [])[:3], 1):
            # Ограничиваем длину текста для callback_data (64 символа максимум)
            short_suggestion = suggestion[:50] if len(suggestion) > 50 else suggestion
            keyboard.add(InlineKeyboardButton(
                text=f"💡 Вариант {i}: {short_suggestion[:30]}...",
                callback_data=f"use_reply:{local_id}:{i}"
            ))
        
        keyboard.add(InlineKeyboardButton(
            text="✏️ Написать свой ответ",
            callback_data=f"custom_reply:{local_id}"
        ))
        
        # Формируем сообщение
        message_text = (
            f"💬 Ответ на письмо\n\n"
            f"📧 От: {email_data.get('from', 'Неизвестно')}\n"
            f"📝 Тема: {email_data.get('subject', 'Без темы')}\n\n"
            f"💡 {reply_options.get('context', 'Выберите вариант ответа или напишите свой')}\n\n"
            f"Выберите вариант ответа или напишите свой:"
        )
        
        await callback.message.answer(
            message_text,
            reply_markup=keyboard.as_markup()
        )
        
        # Сохраняем варианты ответов в state для последующего использования
        await state.update_data(
            reply_options=reply_options,
            reply_local_id=local_id
        )
    
    elif data.startswith("use_reply:"):
        # Пользователь выбрал один из предложенных вариантов
        parts = data.split(":")
        local_id = parts[1]
        option_num = int(parts[2])
        
        email_data = get_email_from_cache(local_id)
        if not email_data:
            try:
                await callback.answer("❌ Письмо не найдено", show_alert=True)
            except Exception as e:
                print(f"⚠️  Ошибка при ответе на callback: {e}")
            return
        
        data_state = await state.get_data()
        reply_options = data_state.get("reply_options", {})
        suggestions = reply_options.get("suggestions", [])
        
        if option_num <= len(suggestions):
            selected_reply = suggestions[option_num - 1]
            try:
                await callback.answer("✅ Отправляю ответ...")
            except Exception as e:
                print(f"⚠️  Ошибка при ответе на callback: {e}")
            
            # Автоматически отправляем выбранный ответ
            account_id = email_data["account_id"]
            from_field = email_data["from"]
            if "<" in from_field and ">" in from_field:
                to_email = from_field.split("<")[-1].split(">")[0].strip()
            else:
                to_email = from_field.strip()
            
            subject = f"Re: {email_data['subject']}"
            context = f"От: {email_data['from']}\nТема: {email_data['subject']}\n\n{email_data['body'][:500]}"
            polished_reply = polish_reply(selected_reply, context)
            
            success, msg = await send_email_smtp(
                account_id,
                to_email,
                subject,
                polished_reply,
                telegram_notify_func=send_notification
            )
            
            if success:
                success_msg = generate_friendly_response(
                    f"Ответ успешно отправлен получателю {to_email}."
                )
                await callback.message.answer(
                    f"✅ {success_msg}\n\n"
                    f"📧 Получатель: {to_email}\n"
                    f"📝 Отправленный текст:\n{polished_reply}"
                )
            else:
                await callback.message.answer(f"❌ Ошибка при отправке: {msg}")
        else:
            try:
                await callback.answer("❌ Вариант не найден", show_alert=True)
            except Exception as e:
                print(f"⚠️  Ошибка при ответе на callback: {e}")
    
    elif data.startswith("custom_reply:"):
        # Пользователь хочет написать свой ответ
        local_id = data.split(":", 1)[1]
        try:
            await callback.answer()
        except Exception as e:
            print(f"⚠️  Ошибка при ответе на callback: {e}")
        
        email_data = get_email_from_cache(local_id)
        if not email_data:
            await callback.message.answer("❌ Письмо не найдено в кэше.")
            return
        
        # Сохраняем local_id для ответа
        await state.update_data(custom_reply_id=local_id)
        
        help_text = generate_friendly_response(
            f"Пользователь хочет написать свой ответ на письмо от {email_data.get('from', 'неизвестного отправителя')}. "
            f"Нужно попросить его написать текст ответа и объяснить, что можно писать на русском, бот переведет в деловой английский."
        )
        
        await callback.message.answer(
            f"✏️ {help_text}\n\n"
            f"📧 Письмо от: {email_data.get('from', 'Неизвестно')}\n"
            f"📝 Тема: {email_data.get('subject', 'Без темы')}\n\n"
            f"💡 Напишите ваш ответ (можно на русском, бот переведет в деловой английский):\n\n"
            f"Или используйте команду:\n"
            f"`/reply {local_id} ваш текст ответа`",
            parse_mode="Markdown"
        )


async def handle_text_message(message: types.Message, state: FSMContext, **kwargs):
    """Обработчик текстовых сообщений (для FSM)."""
    if message.from_user.id != OWNER_TELEGRAM_ID:
        return
    
    # Пропускаем, если это команда (она уже обработана другими обработчиками)
    if message.text and message.text.startswith('/'):
        return
    
    # Проверяем, не пишет ли пользователь свой ответ на письмо
    data_state = await state.get_data()
    custom_reply_id = data_state.get("custom_reply_id")
    
    if custom_reply_id:
        # Пользователь пишет свой ответ на письмо
        email_data = get_email_from_cache(custom_reply_id)
        if not email_data:
            await message.answer("❌ Письмо не найдено в кэше.")
            await state.update_data(custom_reply_id=None)
            return
        
        # Обрабатываем ответ как команду /reply
        draft_text = message.text.strip()
        account_id = email_data["account_id"]
        from_field = email_data["from"]
        if "<" in from_field and ">" in from_field:
            to_email = from_field.split("<")[-1].split(">")[0].strip()
        else:
            to_email = from_field.strip()
        
        subject = f"Re: {email_data['subject']}"
        context = f"От: {email_data['from']}\nТема: {email_data['subject']}\n\n{email_data['body'][:500]}"
        
        await message.answer("🔄 Обрабатываю ваш ответ...")
        polished_reply = polish_reply(draft_text, context)
        
        success, msg = await send_email_smtp(
            account_id,
            to_email,
            subject,
            polished_reply,
            telegram_notify_func=send_notification
        )
        
        await state.update_data(custom_reply_id=None)
        
        if success:
            success_msg = generate_friendly_response(
                f"Ответ успешно отправлен получателю {to_email}."
            )
            await message.answer(
                f"✅ {success_msg}\n\n"
                f"📧 Получатель: {to_email}\n"
                f"📝 Отправленный текст:\n{polished_reply}"
            )
        else:
            await message.answer(f"❌ Ошибка при отправке: {msg}")
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
        # Убираем все пробелы из пароля (App Password может быть введен с пробелами)
        password = message.text.strip().replace(" ", "").replace("-", "")
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
            
            if not success and error == "app_password_required":
                # Gmail требует App Password
                await state.update_data(needs_app_password=True)
                await message.answer(
                    "⚠️ Gmail требует App Password!\n\n"
                    "Обычный пароль не подходит, потому что:\n"
                    "• Включена двухфакторная аутентификация, или\n"
                    "• Google требует использовать App Password для безопасности\n\n"
                    "📋 Как получить App Password:\n"
                    "1. Перейдите: https://myaccount.google.com/apppasswords\n"
                    "2. Выберите приложение: 'Почта'\n"
                    "3. Выберите устройство: 'Другое' → введите 'Mail Agent'\n"
                    "4. Нажмите 'Создать'\n"
                    "5. Скопируйте 16-символьный пароль (можно с пробелами, я их уберу)\n\n"
                    "Введите App Password:"
                )
                return
            elif not success and error == "authentication_error":
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
        
        # Если уже просили App Password, значит это App Password - проверяем его
        if needs_app_password:
            await message.answer("🔄 Проверяю App Password...")
            success, error = await test_imap_connection(
                "imap.gmail.com",
                email,
                password
            )
            
            if not success:
                if error == "app_password_required" or error == "authentication_error":
                    await message.answer(
                        "❌ App Password не подошел.\n\n"
                        "Возможные причины:\n"
                        "• Пароль скопирован неправильно\n"
                        "• Пароль уже использован или удален\n"
                        "• Не тот аккаунт\n\n"
                        "Попробуйте:\n"
                        "1. Создать новый App Password\n"
                        "2. Скопировать его полностью (можно с пробелами)\n"
                        "3. Ввести снова\n\n"
                        "Введите App Password:"
                    )
                    return
                else:
                    await message.answer(
                        f"❌ Ошибка подключения: {error}\n\n"
                        "Попробуйте еще раз:"
                    )
                    return
        
        # Пароль подошел - сохраняем
        account_data = {
            "imap_host": "imap.gmail.com",
            "imap_user": email,
            "imap_pass": password,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587
        }
        
        save_account(account_id, account_data)
        await state.clear()
        
        success_msg = generate_friendly_response(
            f"Аккаунт {account_id} (Gmail) успешно настроен! Бот будет проверять почту автоматически."
        )
        await message.answer(
            f"✅ {success_msg}"
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
    
    # Пытаемся понять намерение через AI, если формат нестандартный
    if not text.startswith('/reply'):
        intent_data = understand_user_intent(
            text,
            current_state=None,
            available_commands=["/reply <ID> <текст> - ответить на письмо"]
        )
        
        if intent_data.get("intent") == "command" and intent_data.get("command") == "/reply":
            # AI понял, что это команда reply
            params = intent_data.get("parameters", {})
            reply_id = params.get("id")
            reply_text = params.get("text")
            
            if reply_id and reply_text:
                # Используем параметры от AI
                text = f"/reply {reply_id} {reply_text}"
            else:
                # Не удалось извлечь параметры
                await message.answer(
                    generate_friendly_response(
                        "Пользователь хочет ответить на письмо, но не указал ID письма или текст ответа. Нужно вежливо попросить указать эти данные."
                    )
                )
                return
    
    parts = text.split(None, 2)  # /reply ID текст
    
    if len(parts) < 3:
        friendly_error = generate_friendly_response(
            "Пользователь использовал команду /reply неправильно. Нужно вежливо объяснить правильный формат."
        )
        await message.answer(
            f"{friendly_error}\n\n"
            "📝 Правильный формат: `/reply <ID> <текст ответа>`\n\n"
            "Пример: `/reply 1-1234567890 давайте созвонимся завтра`"
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
        print("🔄 Инициализация бота перед запуском polling...")
        bot, dp = init_bot()
        print("✅ Бот инициализирован")
    
    print("🔄 Запуск polling...")
    print(f"✅ OWNER_TELEGRAM_ID: {OWNER_TELEGRAM_ID}")
    print(f"✅ Обработчики зарегистрированы:")
    print(f"   - /start")
    print(f"   - /reply")
    print(f"   - callback_query")
    print(f"   - text messages")
    
    try:
        # В aiogram 3.x правильный способ запуска polling
        await dp.start_polling(bot, skip_updates=True, allowed_updates=["message", "callback_query"])
        print("✅ Polling запущен успешно")
    except Exception as e:
        print(f"❌ Ошибка при запуске polling: {e}")
        import traceback
        traceback.print_exc()
        raise

