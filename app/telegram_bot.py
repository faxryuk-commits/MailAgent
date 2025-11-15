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
from aiogram.exceptions import TelegramBadRequest

from app.storage import save_account, get_account, load_accounts
from app.email_client import send_email_smtp, get_email_from_cache, test_imap_connection
from app.ai_client import (
    polish_reply, understand_user_intent, generate_friendly_response, suggest_reply_options,
    understand_user_intent_with_email_access, analyze_emails_by_topic
)
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
    dp.message.register(handle_help, Command("help"))
    print("   ✅ /help зарегистрирован")
    dp.message.register(handle_reply, Command("reply"))
    print("   ✅ /reply зарегистрирован")
    dp.message.register(handle_emails, Command("emails"))
    print("   ✅ /emails зарегистрирован")
    dp.message.register(handle_thread, Command("thread"))
    print("   ✅ /thread зарегистрирован")
    dp.message.register(handle_search, Command("search"))
    print("   ✅ /search зарегистрирован")
    dp.message.register(handle_stats, Command("stats"))
    print("   ✅ /stats зарегистрирован")
    dp.message.register(handle_status, Command("status"))
    print("   ✅ /status зарегистрирован")
    dp.callback_query.register(handle_callback)
    print("   ✅ callback_query зарегистрирован")
    # Обработчик голосовых сообщений (регистрируем перед текстовыми, чтобы перехватить голосовые)
    dp.message.register(handle_voice_message)
    print("   ✅ voice messages зарегистрирован")
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


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает главное меню с основными разделами."""
    keyboard = InlineKeyboardBuilder()
    
    keyboard.add(InlineKeyboardButton(
        text="📧 Письма",
        callback_data="menu:emails"
    ))
    keyboard.add(InlineKeyboardButton(
        text="🔍 Поиск",
        callback_data="menu:search"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📊 Статистика",
        callback_data="menu:stats"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📬 Цепочки",
        callback_data="menu:threads"
    ))
    keyboard.add(InlineKeyboardButton(
        text="⚙️ Настройки",
        callback_data="menu:settings"
    ))
    keyboard.add(InlineKeyboardButton(
        text="❓ Помощь",
        callback_data="show_help"
    ))
    
    keyboard.adjust(2)  # 2 кнопки в ряд
    
    return keyboard.as_markup()


def get_emails_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает меню фильтров писем."""
    keyboard = InlineKeyboardBuilder()
    
    keyboard.add(InlineKeyboardButton(
        text="📧 Все письма",
        callback_data="emails:all"
    ))
    keyboard.add(InlineKeyboardButton(
        text="💼 Рабочие",
        callback_data="emails:work"
    ))
    keyboard.add(InlineKeyboardButton(
        text="⭐ Важные",
        callback_data="emails:important"
    ))
    keyboard.add(InlineKeyboardButton(
        text="🔴 Высокий приоритет",
        callback_data="emails:high"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📰 Рассылки",
        callback_data="emails:newsletter"
    ))
    keyboard.add(InlineKeyboardButton(
        text="🗑️ Спам",
        callback_data="emails:spam"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📅 Сегодня",
        callback_data="emails:today"
    ))
    keyboard.add(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="menu:main"
    ))
    
    keyboard.adjust(2)  # 2 кнопки в ряд
    
    return keyboard.as_markup()


def get_settings_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает меню настроек."""
    keyboard = InlineKeyboardBuilder()
    
    keyboard.add(InlineKeyboardButton(
        text="📧 Аккаунт 1 — Gmail",
        callback_data="setup:1:gmail"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📧 Аккаунт 1 — Другая почта",
        callback_data="setup:1:custom"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📧 Аккаунт 2 — Gmail",
        callback_data="setup:2:gmail"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📧 Аккаунт 2 — Другая почта",
        callback_data="setup:2:custom"
    ))
    keyboard.add(InlineKeyboardButton(
        text="📊 Статус аккаунтов",
        callback_data="show_status"
    ))
    keyboard.add(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="menu:main"
    ))
    
    keyboard.adjust(2)  # 2 кнопки в ряд
    
    return keyboard.as_markup()


async def safe_edit_text(message, text: str, reply_markup=None, parse_mode=None):
    """
    Безопасно редактирует текст сообщения, обрабатывая ошибку "message is not modified".
    
    Args:
        message: Объект сообщения для редактирования
        text: Новый текст
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (опционально)
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        # Игнорируем ошибку "message is not modified" - это нормально
        if "message is not modified" in str(e).lower():
            # Просто отвечаем на callback, чтобы убрать индикатор загрузки
            try:
                if hasattr(message, 'answer'):
                    await message.answer()
            except:
                pass
        else:
            # Другие ошибки логируем
            print(f"⚠️  Ошибка при редактировании сообщения: {e}")
            raise
    except Exception as e:
        print(f"⚠️  Неожиданная ошибка при редактировании сообщения: {e}")
        raise


@check_owner
async def handle_start(message: types.Message, **kwargs):
    """Обработчик команды /start."""
    try:
        from app.email_client import check_account_status
        from app.storage import load_accounts
        
        # Проверяем, что аккаунты не потерялись
        accounts_before = load_accounts()
        print(f"📋 Аккаунты до /start: {list(accounts_before.keys())}")
        
        # Генерируем дружелюбное приветствие через AI (с обработкой ошибок)
        try:
            greeting = generate_friendly_response(
                "Пользователь запустил бота. Нужно поприветствовать и предложить настроить почтовый аккаунт."
            )
        except Exception as e:
            print(f"⚠️  Ошибка генерации приветствия через AI: {e}")
            greeting = "👋 Привет! Я Mail Agent AI - твой помощник для управления почтой."
        
        # Проверяем статус аккаунтов (только чтение, не изменяет данные)
        try:
            status1 = await check_account_status(1)
            status2 = await check_account_status(2)
        except Exception as e:
            print(f"⚠️  Ошибка при проверке статуса: {e}")
            # Если ошибка, используем данные из загруженных аккаунтов
            status1 = {"configured": "1" in accounts_before, "connected": False, "email": accounts_before.get("1", {}).get("imap_user") if "1" in accounts_before else None}
            status2 = {"configured": "2" in accounts_before, "connected": False, "email": accounts_before.get("2", {}).get("imap_user") if "2" in accounts_before else None}
        
        # Проверяем, что аккаунты не потерялись после проверки статуса
        accounts_after = load_accounts()
        print(f"📋 Аккаунты после проверки статуса: {list(accounts_after.keys())}")
        
        if len(accounts_before) > len(accounts_after):
            print(f"⚠️  ВНИМАНИЕ! Потеряны аккаунты! Было: {list(accounts_before.keys())}, Стало: {list(accounts_after.keys())}")
        
        # Добавляем информацию о статусе
        status_info = "\n\n📊 **Статус аккаунтов:**\n"
        if status1["configured"]:
            status_emoji = "✅" if status1["connected"] else "❌"
            status_info += f"{status_emoji} Аккаунт 1: {status1['email'] or 'Не настроен'}\n"
        else:
            status_info += "⚪ Аккаунт 1: Не настроен\n"
        
        if status2["configured"]:
            status_emoji = "✅" if status2["connected"] else "❌"
            status_info += f"{status_emoji} Аккаунт 2: {status2['email'] or 'Не настроен'}\n"
        else:
            status_info += "⚪ Аккаунт 2: Не настроен\n"
        
        greeting += status_info
        
        # Используем главное меню
        await message.answer(
            f"{greeting}\n\n"
            "📱 **Главное меню**\n\n"
            "Выберите раздел:",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
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
async def handle_help(message: types.Message, **kwargs):
    """Обработчик команды /help - показывает список всех команд."""
    help_text = """
📱 **Mail Agent AI - Список команд**

**Основные команды:**

`/start` - Запустить бота и настроить почтовые аккаунты
`/help` - Показать этот список команд
`/emails [фильтр]` - Показать список писем
`/search <запрос>` - Поиск по письмам
`/thread <ID>` - Показать всю цепочку писем
`/stats` - Статистика по письмам
`/status` - Статус почтовых аккаунтов

**Фильтры для /emails:**
• `/emails` - все письма
• `/emails work` - только рабочие
• `/emails important` - только важные
• `/emails high` - высокий приоритет
• `/emails newsletter` - рассылки
• `/emails spam` - спам
• `/emails today` - письма за сегодня

**Работа с письмами:**
`/reply <ID> <текст>` - Ответить на письмо
`/thread <ID>` - Показать всю цепочку писем

**Примеры:**
`/reply 1-1234567890 Спасибо за письмо!`
`/thread 1-1234567890` - показать всю переписку

**Автоматические функции:**
✅ Проверка почты каждые 60 секунд
✅ Умная приоритизация писем (🔴 высокий, 🟡 средний, 🟢 низкий)
✅ Умная категоризация (💼 работа, 👤 личное, 📰 рассылка, 🗑️ спам, ⭐ важное)
✅ История переписки (группировка писем по темам)
✅ Поиск по письмам (по теме, отправителю, содержимому)
✅ Статистика и аналитика (категории, приоритеты, отправители)
✅ Резюме писем через AI
✅ Варианты ответов через AI (с учетом контекста переписки)

**Интерактивные кнопки:**
• 💬 Ответить - получить варианты ответов от AI
• Выбор варианта - автоматическая отправка выбранного ответа
• ✏️ Написать свой ответ - написать и отправить свой текст

💡 Все ответы автоматически улучшаются через AI и переводятся в деловой английский.
"""
    await message.answer(help_text, parse_mode="Markdown")


@check_owner
async def handle_callback(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Обработчик callback-кнопок."""
    
    data = callback.data
    
    # Обработка меню
    if data == "menu:main":
        try:
            await callback.answer()
        except:
            pass
        
        from app.email_client import check_account_status
        
        # Проверяем статус аккаунтов
        status1 = await check_account_status(1)
        status2 = await check_account_status(2)
        
        status_info = "📊 **Статус аккаунтов:**\n"
        if status1["configured"]:
            status_emoji = "✅" if status1["connected"] else "❌"
            status_info += f"{status_emoji} Аккаунт 1: {status1['email'] or 'Не настроен'}\n"
        else:
            status_info += "⚪ Аккаунт 1: Не настроен\n"
        
        if status2["configured"]:
            status_emoji = "✅" if status2["connected"] else "❌"
            status_info += f"{status_emoji} Аккаунт 2: {status2['email'] or 'Не настроен'}\n"
        else:
            status_info += "⚪ Аккаунт 2: Не настроен\n"
        
        await safe_edit_text(
            callback.message,
            f"📱 **Mail Agent AI**\n\n{status_info}\n\nВыберите раздел:",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif data == "menu:emails":
        try:
            await callback.answer()
        except:
            pass
        
        await safe_edit_text(
            callback.message,
            "📧 **Письма**\n\nВыберите фильтр:",
            reply_markup=get_emails_menu_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif data == "menu:search":
        try:
            await callback.answer()
        except:
            pass
        
        await safe_edit_text(
            callback.message,
            "🔍 **Поиск по письмам**\n\n"
            "Введите поисковый запрос:\n\n"
            "Примеры:\n"
            "• `проект` - найти все письма со словом 'проект'\n"
            "• `client@company.com` - найти письма от этого отправителя\n"
            "• `встреча` - найти письма с упоминанием 'встреча'\n\n"
            "Или используйте команду: `/search <запрос>`",
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")
            ).as_markup(),
            parse_mode="Markdown"
        )
        return
    
    elif data == "menu:stats":
        try:
            await callback.answer("🔄 Загружаю статистику...")
        except:
            pass
        
        # Вызываем handle_stats логику
        from app.email_client import get_email_statistics
        
        stats = get_email_statistics()
        
        if stats["total"] == 0:
            await safe_edit_text(
                callback.message,
                "📊 **Статистика**\n\n❌ Писем в кэше нет.\n\n"
                "💡 Дождитесь получения новых писем.",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")
                ).as_markup(),
                parse_mode="Markdown"
            )
            return
        
        result_text = "📊 **Статистика по письмам**\n\n"
        result_text += f"📧 **Всего писем:** {stats['total']}\n"
        result_text += f"📬 **Цепочек переписки:** {stats['threads_count']}\n\n"
        
        # По категориям
        category_emoji = {
            "work": "💼", "personal": "👤", "newsletter": "📰", 
            "spam": "🗑️", "important": "⭐"
        }
        category_name = {
            "work": "Работа", "personal": "Личное", "newsletter": "Рассылка",
            "spam": "Спам", "important": "Важное"
        }
        
        result_text += "**По категориям:**\n"
        for category, count in sorted(stats["by_category"].items(), key=lambda x: x[1], reverse=True):
            emoji = category_emoji.get(category, "📧")
            name = category_name.get(category, category)
            percentage = (count / stats["total"]) * 100
            result_text += f"{emoji} {name}: {count} ({percentage:.1f}%)\n"
        
        result_text += "\n"
        
        # По приоритетам
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        priority_name = {
            "high": "Высокий", "medium": "Средний", "low": "Низкий"
        }
        
        result_text += "**По приоритетам:**\n"
        for priority, count in sorted(stats["by_priority"].items(), key=lambda x: x[1], reverse=True):
            emoji = priority_emoji.get(priority, "🟡")
            name = priority_name.get(priority, priority)
            percentage = (count / stats["total"]) * 100
            result_text += f"{emoji} {name}: {count} ({percentage:.1f}%)\n"
        
        result_text += "\n"
        
        # По времени
        result_text += "**По времени:**\n"
        result_text += f"📅 Сегодня: {stats['by_time']['today']}\n"
        result_text += f"📅 Вчера: {stats['by_time']['yesterday']}\n"
        result_text += f"📅 За неделю: {stats['by_time']['week']}\n"
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"))
        
        await safe_edit_text(
            callback.message,
            result_text,
            reply_markup=keyboard.as_markup(),
            parse_mode="Markdown"
        )
        return
    
    elif data == "menu:threads":
        try:
            await callback.answer()
        except:
            pass
        
        await safe_edit_text(
            callback.message,
            "📬 **Цепочки переписки**\n\n"
            "Для просмотра цепочки писем используйте команду:\n"
            "`/thread <ID>`\n\n"
            "Пример: `/thread 1-1234567890`\n\n"
            "ID письма можно найти в списке писем.",
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")
            ).as_markup(),
            parse_mode="Markdown"
        )
        return
    
    elif data == "menu:settings":
        try:
            await callback.answer()
        except:
            pass
        
        await safe_edit_text(
            callback.message,
            "⚙️ **Настройки**\n\nВыберите действие:",
            reply_markup=get_settings_menu_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Обработка фильтров писем
    elif data.startswith("emails:"):
        filter_type = data.split(":")[1]
        try:
            await callback.answer("🔄 Загружаю письма...")
        except:
            pass
        
        # Вызываем handle_emails логику
        from app.email_client import EMAIL_CACHE
        
        all_emails = list(EMAIL_CACHE.values())
        all_emails.sort(key=lambda x: x.get('date_raw', ''), reverse=True)
        
        if filter_type != "all":
            if filter_type in ["work", "personal", "newsletter", "spam", "important"]:
                all_emails = [e for e in all_emails if e.get('category') == filter_type]
            elif filter_type in ["high", "medium", "low"]:
                all_emails = [e for e in all_emails if e.get('priority') == filter_type]
            elif filter_type == "today":
                filtered_emails = []
                for e in all_emails:
                    date_str = e.get('date', '')
                    if any(word in date_str.lower() for word in ['сегодня', 'только что', 'мин', 'час', 'сек']):
                        filtered_emails.append(e)
                all_emails = filtered_emails
        
        if not all_emails:
            await safe_edit_text(
                callback.message,
                f"📭 Писем не найдено" + 
                (f" (фильтр: {filter_type})" if filter_type != "all" else ""),
                reply_markup=get_emails_menu_keyboard(),
                parse_mode="Markdown"
            )
            return
        
        emails_to_show = all_emails[:20]
        
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        category_emoji = {
            "work": "💼", "personal": "👤", "newsletter": "📰", 
            "spam": "🗑️", "important": "⭐"
        }
        
        result_text = f"📧 Найдено писем: {len(all_emails)}\n"
        if filter_type != "all":
            result_text += f"🔍 Фильтр: {filter_type}\n"
        result_text += f"\n"
        
        for i, email_data in enumerate(emails_to_show, 1):
            priority = email_data.get('priority', 'medium')
            category = email_data.get('category', 'work')
            
            result_text += (
                f"{i}. {priority_emoji.get(priority, '🟡')} {category_emoji.get(category, '💼')} "
                f"{email_data.get('from', 'Неизвестно')[:30]}\n"
                f"   📝 {email_data.get('subject', 'Без темы')[:40]}\n"
                f"   📅 {email_data.get('date', '')}\n"
                f"   ID: `{email_data.get('local_id', '')}`\n\n"
            )
        
        if len(all_emails) > 20:
            result_text += f"\n... и еще {len(all_emails) - 20} писем"
        
        await safe_edit_text(
            callback.message,
            result_text,
            reply_markup=get_emails_menu_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    if data == "show_status":
        # Показываем статус через callback
        try:
            await callback.answer("🔄 Проверяю статус...")
        except:
            pass
        
        from app.email_client import check_account_status
        from app.storage import load_accounts
        
        accounts = load_accounts()
        
        result_text = "📊 **Статус почтовых аккаунтов**\n\n"
        
        # Проверяем аккаунт 1
        status1 = await check_account_status(1)
        if status1["configured"]:
            if status1["connected"]:
                result_text += f"✅ **Аккаунт 1** - Активен\n"
                result_text += f"📧 {status1['email']}\n\n"
            else:
                result_text += f"❌ **Аккаунт 1** - Ошибка подключения\n"
                result_text += f"📧 {status1['email']}\n"
                result_text += f"⚠️ {status1['error']}\n\n"
        else:
            result_text += f"⚪ **Аккаунт 1** - Не настроен\n\n"
        
        # Проверяем аккаунт 2
        status2 = await check_account_status(2)
        if status2["configured"]:
            if status2["connected"]:
                result_text += f"✅ **Аккаунт 2** - Активен\n"
                result_text += f"📧 {status2['email']}\n\n"
            else:
                result_text += f"❌ **Аккаунт 2** - Ошибка подключения\n"
                result_text += f"📧 {status2['email']}\n"
                result_text += f"⚠️ {status2['error']}\n\n"
        else:
            result_text += f"⚪ **Аккаунт 2** - Не настроен\n\n"
        
        # Общая статистика
        from app.email_client import EMAIL_CACHE
        total_emails = len(EMAIL_CACHE)
        result_text += f"📬 **Писем в кэше:** {total_emails}\n\n"
        
        # Подсказки
        if not status1["connected"] and not status2["connected"]:
            result_text += (
                "💡 **Что делать:**\n"
                "• Используйте кнопки выше для настройки аккаунтов\n"
                "• Проверьте правильность паролей\n"
                "• Для Gmail может потребоваться App Password"
            )
        elif status1["connected"] or status2["connected"]:
            result_text += (
                "✅ Аккаунты работают! Бот проверяет почту каждые 60 секунд.\n\n"
                "💡 Используйте `/emails` для просмотра писем"
            )
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
        await safe_edit_text(callback.message, result_text, reply_markup=keyboard.as_markup(), parse_mode="Markdown")
        return
    
    if data == "show_help":
        # Показываем справку через callback
        try:
            await callback.answer()
        except:
            pass
        
        help_text = """
📱 **Mail Agent AI - Список команд**

**Основные команды:**

`/start` - Запустить бота и настроить почтовые аккаунты
`/help` - Показать этот список команд
`/emails [фильтр]` - Показать список писем
`/search <запрос>` - Поиск по письмам
`/thread <ID>` - Показать всю цепочку писем
`/stats` - Статистика по письмам
`/status` - Статус почтовых аккаунтов

**Фильтры для /emails:**
• `/emails` - все письма
• `/emails work` - только рабочие
• `/emails important` - только важные
• `/emails high` - высокий приоритет
• `/emails newsletter` - рассылки
• `/emails spam` - спам
• `/emails today` - письма за сегодня

**Работа с письмами:**
`/reply <ID> <текст>` - Ответить на письмо
`/thread <ID>` - Показать всю цепочку писем

**Примеры:**
`/reply 1-1234567890 Спасибо за письмо!`
`/thread 1-1234567890` - показать всю переписку

**Автоматические функции:**
✅ Проверка почты каждые 60 секунд
✅ Умная приоритизация писем (🔴 высокий, 🟡 средний, 🟢 низкий)
✅ Умная категоризация (💼 работа, 👤 личное, 📰 рассылка, 🗑️ спам, ⭐ важное)
✅ История переписки (группировка писем по темам)
✅ Поиск по письмам (по теме, отправителю, содержимому)
✅ Статистика и аналитика (категории, приоритеты, отправители)
✅ Резюме писем через AI
✅ Варианты ответов через AI (с учетом контекста переписки)

**Интерактивные кнопки:**
• 💬 Ответить - получить варианты ответов от AI
• Выбор варианта - автоматическая отправка выбранного ответа
• ✏️ Написать свой ответ - написать и отправить свой текст

💡 Все ответы автоматически улучшаются через AI и переводятся в деловой английский.
"""
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
        await safe_edit_text(callback.message, help_text, reply_markup=keyboard.as_markup(), parse_mode="Markdown")
        return
    
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
            print(f"🔧 Настройка Gmail для аккаунта {account_id}")
            await state.update_data(account_id=account_id, provider="gmail")
            print(f"✅ account_id={account_id} сохранен в state")
            
            await state.set_state(SetupStates.gmail_user)
            print(f"✅ Состояние установлено: gmail_user")
            
            # Проверяем, настроен ли OAuth2
            try:
                from app.oauth_client import CLIENT_ID, CLIENT_SECRET
                oauth_available = bool(CLIENT_ID and CLIENT_SECRET)
                print(f"🔍 OAuth2 доступен: {oauth_available}")
            except ImportError as e:
                print(f"⚠️  Ошибка импорта oauth_client: {e}")
                oauth_available = False
            
            if oauth_available:
                await callback.message.answer(
                    f"📧 Настройка аккаунта {account_id} (Gmail)\n\n"
                    "Введите ваш email адрес для OAuth2 авторизации:"
                )
                print(f"✅ Запрос email для OAuth2 отправлен")
            else:
                await callback.message.answer(
                    f"📧 Настройка аккаунта {account_id} (Gmail)\n\n"
                    "⚠️ OAuth2 не настроен. Используется авторизация по паролю.\n"
                    "Введите ваш email адрес:"
                )
                print(f"✅ Запрос email для пароля отправлен")
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
        
        # Получаем контекст переписки для более умных ответов
        from app.email_client import get_email_thread
        thread_emails = get_email_thread(email_data)
        
        # Генерируем варианты ответов через AI с учетом контекста переписки
        try:
            reply_options = suggest_reply_options(email_data, thread_emails)
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
        thread_info = ""
        if len(thread_emails) > 1:
            thread_info = f"\n📬 В цепочке: {len(thread_emails)} писем (используйте `/thread {local_id}` для просмотра)\n"
        
        message_text = (
            f"💬 Ответ на письмо{thread_info}\n"
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


@check_owner
async def handle_voice_message(message: types.Message, state: FSMContext, **kwargs):
    """Обработчик голосовых сообщений - транскрибирует и обрабатывает через ИИ."""
    # Проверяем, что это голосовое сообщение
    if not message.voice:
        # Если это не голосовое сообщение, пропускаем обработку
        # (это позволит другим обработчикам обработать сообщение)
        return
    
    await message.answer("🎤 Обрабатываю голосовое сообщение...")
    
    try:
        # Скачиваем голосовое сообщение
        file_info = await bot.get_file(message.voice.file_id)
        file_path = file_info.file_path
        
        # Скачиваем файл
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
            await bot.download_file(file_path, tmp_file.name)
            tmp_path = tmp_file.name
        
        # Транскрибируем через OpenAI Whisper
        from app.ai_client import init_openai
        init_openai()
        from app.ai_client import client
        
        # Whisper API требует файл, открываем его напрямую
        with open(tmp_path, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )
        
        # Удаляем временный файл
        os.unlink(tmp_path)
        
        transcribed_text = transcript.text
        await message.answer(f"📝 Распознано: {transcribed_text}")
        
        # Обрабатываем транскрибированный текст как обычное сообщение
        # Создаем временное сообщение с текстом
        message.text = transcribed_text
        await handle_text_message(message, state, **kwargs)
        
    except Exception as e:
        print(f"Ошибка при обработке голосового сообщения: {e}")
        import traceback
        traceback.print_exc()
        await message.answer("❌ Не удалось обработать голосовое сообщение. Попробуйте написать текстом.")


async def handle_text_message(message: types.Message, state: FSMContext, **kwargs):
    """Обработчик текстовых сообщений (для FSM и ИИ-обработки)."""
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
    print(f"🔍 Текущее состояние FSM: {current_state}")
    print(f"🔍 Ожидаемое состояние gmail_user: {SetupStates.gmail_user.state}")
    
    if current_state == SetupStates.gmail_user.state:
        try:
            email = message.text.strip()
            print(f"📧 Получен email для настройки: {email}")
            
            if not email or "@" not in email:
                await message.answer("❌ Пожалуйста, введите корректный email адрес.")
                return
            
            await state.update_data(imap_user=email)
            print(f"✅ Email сохранен в state: {email}")
            
            # Получаем account_id из state
            data = await state.get_data()
            account_id = data.get("account_id")
            print(f"📋 Account ID из state: {account_id}")
            
            if not account_id:
                await message.answer("❌ Ошибка: не найден ID аккаунта. Попробуйте начать настройку заново через /start.")
                await state.clear()
                return
            
            # Проверяем, настроен ли OAuth2
            try:
                from app.oauth_client import CLIENT_ID, CLIENT_SECRET, get_authorization_url
                print(f"🔍 OAuth2 проверка: CLIENT_ID={'установлен' if CLIENT_ID else 'не установлен'}, CLIENT_SECRET={'установлен' if CLIENT_SECRET else 'не установлен'}")
            except ImportError as e:
                print(f"⚠️  Ошибка импорта oauth_client: {e}")
                CLIENT_ID = None
                CLIENT_SECRET = None
                get_authorization_url = None
            
            if CLIENT_ID and CLIENT_SECRET and get_authorization_url:
                # Используем OAuth2
                try:
                    print(f"🔐 Создание OAuth2 ссылки для аккаунта {account_id}, email {email}...")
                    auth_url = get_authorization_url(account_id, email)
                    print(f"✅ OAuth2 ссылка создана: {auth_url[:50]}...")
                    
                    await state.set_state(SetupStates.gmail_oauth_code)
                    print(f"✅ Состояние изменено на gmail_oauth_code")
                    
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
                    print(f"✅ Сообщение с OAuth2 инструкцией отправлено")
                except Exception as e:
                    print(f"❌ Ошибка при создании OAuth2 ссылки: {e}")
                    import traceback
                    traceback.print_exc()
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
                print(f"💡 OAuth2 не настроен, используем пароль")
                await state.set_state(SetupStates.gmail_pass)
                await message.answer(
                    "Введите пароль для Gmail:\n\n"
                    "💡 Сначала попробуем обычный пароль. Если не подойдет, попросим App Password."
                )
                print(f"✅ Запрос пароля отправлен")
        except Exception as e:
            print(f"❌ Критическая ошибка в обработке gmail_user: {e}")
            import traceback
            traceback.print_exc()
            try:
                await message.answer(f"❌ Произошла ошибка: {e}\n\nПопробуйте начать настройку заново через /start.")
            except:
                pass
    
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
            "Бот будет проверять почту каждую минуту.",
            reply_markup=get_main_menu_keyboard()
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
            f"✅ {success_msg}",
            reply_markup=get_main_menu_keyboard()
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
            f"✅ Аккаунт {account_id} (Custom) успешно настроен!",
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    # Если не в процессе настройки - обрабатываем через ИИ
    # Это позволяет боту понимать естественный язык и выполнять действия
    current_state = await state.get_state()
    if not current_state or current_state not in [
        SetupStates.gmail_user.state,
        SetupStates.gmail_oauth_code.state,
        SetupStates.gmail_pass.state,
        SetupStates.custom_imap_host.state,
        SetupStates.custom_imap_user.state,
        SetupStates.custom_imap_pass.state,
        SetupStates.custom_smtp_host.state,
        SetupStates.custom_smtp_port.state
    ]:
        # Обрабатываем запрос через ИИ
        user_text = message.text.strip() if message.text else ""
        if not user_text:
            return
        
        await message.answer("🤔 Анализирую ваш запрос...")
        
        try:
            # Понимаем намерение через ИИ
            intent_result = understand_user_intent_with_email_access(user_text, current_state)
            intent = intent_result.get("intent", "unknown")
            action = intent_result.get("action", "answer_question")
            parameters = intent_result.get("parameters", {})
            ai_response = intent_result.get("response", "")
            
            # Выполняем действие в зависимости от намерения
            if intent == "check_email":
                # Проверяем почту прямо сейчас
                await message.answer("📧 Проверяю почту...")
                from app.email_client import check_account_emails
                from app.storage import load_accounts
                
                accounts = load_accounts()
                account_id = parameters.get("account_id")
                
                if account_id:
                    # Проверяем конкретный аккаунт
                    if str(account_id) in accounts:
                        emails = await check_account_emails(account_id, telegram_notify_func=send_notification)
                        if emails:
                            await message.answer(f"✅ Найдено новых писем: {len(emails)}")
                        else:
                            await message.answer("📭 Новых писем нет.")
                    else:
                        await message.answer(f"❌ Аккаунт {account_id} не настроен.")
                else:
                    # Проверяем все аккаунты
                    found_any = False
                    for acc_id in ["1", "2"]:
                        if acc_id in accounts:
                            emails = await check_account_emails(int(acc_id), telegram_notify_func=send_notification)
                            if emails:
                                found_any = True
                    
                    if not found_any:
                        await message.answer("📭 Новых писем нет во всех аккаунтах.")
            
            elif intent == "search":
                # Поиск писем
                query = parameters.get("query") or user_text
                await message.answer(f"🔍 Ищу письма по запросу: {query}")
                
                from app.email_client import search_emails
                results = search_emails(query, limit=20)
                
                if results:
                    result_text = f"📧 Найдено писем: {len(results)}\n\n"
                    for i, email_data in enumerate(results[:10], 1):
                        result_text += (
                            f"{i}. {email_data.get('from', 'Неизвестно')[:30]}\n"
                            f"   📝 {email_data.get('subject', 'Без темы')[:40]}\n"
                            f"   📅 {email_data.get('date', '')}\n"
                            f"   ID: `{email_data.get('local_id', '')}`\n\n"
                        )
                    if len(results) > 10:
                        result_text += f"... и еще {len(results) - 10} писем"
                    
                    await message.answer(result_text, parse_mode="Markdown")
                else:
                    await message.answer(f"📭 Писем по запросу '{query}' не найдено.")
            
            elif intent == "analyze":
                # Анализ писем по теме
                topic = parameters.get("topic") or parameters.get("query") or user_text
                await message.answer(f"📊 Анализирую письма по теме: {topic}")
                
                from app.email_client import search_emails
                emails = search_emails(topic, limit=20)
                
                if emails:
                    analysis = analyze_emails_by_topic(emails, topic)
                    await message.answer(analysis)
                else:
                    await message.answer(f"📭 Писем по теме '{topic}' не найдено для анализа.")
            
            elif intent == "stats":
                # Показываем статистику
                await message.answer("📊 Собираю статистику...")
                
                from app.email_client import get_email_statistics
                stats = get_email_statistics()
                
                result_text = "📊 **Статистика по письмам**\n\n"
                result_text += f"📧 **Всего писем:** {stats['total']}\n"
                result_text += f"📬 **Цепочек переписки:** {stats['threads_count']}\n\n"
                
                if stats['total'] > 0:
                    # По категориям
                    result_text += "**По категориям:**\n"
                    category_emoji = {
                        "work": "💼", "personal": "👤", "newsletter": "📰", 
                        "spam": "🗑️", "important": "⭐"
                    }
                    category_name = {
                        "work": "Работа", "personal": "Личное", "newsletter": "Рассылка",
                        "spam": "Спам", "important": "Важное"
                    }
                    for category, count in sorted(stats["by_category"].items(), key=lambda x: x[1], reverse=True):
                        emoji = category_emoji.get(category, "📧")
                        name = category_name.get(category, category)
                        result_text += f"{emoji} {name}: {count}\n"
                    
                    result_text += "\n**По приоритетам:**\n"
                    priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                    priority_name = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}
                    for priority, count in sorted(stats["by_priority"].items(), key=lambda x: x[1], reverse=True):
                        emoji = priority_emoji.get(priority, "🟡")
                        name = priority_name.get(priority, priority)
                        result_text += f"{emoji} {name}: {count}\n"
                    
                    result_text += "\n**По времени:**\n"
                    result_text += f"📅 Сегодня: {stats['by_time']['today']}\n"
                    result_text += f"📅 Вчера: {stats['by_time']['yesterday']}\n"
                    result_text += f"📅 За неделю: {stats['by_time']['week']}\n"
                
                await message.answer(result_text, parse_mode="Markdown")
            
            elif intent == "question":
                # Отвечаем на вопрос
                if ai_response:
                    await message.answer(ai_response)
                else:
                    # Генерируем ответ через ИИ
                    from app.ai_client import generate_friendly_response
                    response = generate_friendly_response(
                        f"Пользователь задал вопрос: {user_text}. "
                        "Нужно ответить дружелюбно и рассказать о возможностях бота."
                    )
                    await message.answer(response)
            
            else:
                # Не поняли запрос
                if ai_response:
                    await message.answer(ai_response)
                else:
                    await message.answer(
                        "🤔 Не совсем понял ваш запрос. Попробуйте:\n"
                        "• 'Проверь почту' - проверить почту сейчас\n"
                        "• 'Найди письма про инвестиции' - найти письма\n"
                        "• 'Расскажи про проект' - проанализировать письма\n"
                        "• 'Сколько писем?' - показать статистику\n"
                        "• 'Что ты умеешь?' - узнать возможности"
                    )
        
        except Exception as e:
            print(f"Ошибка при обработке запроса через ИИ: {e}")
            import traceback
            traceback.print_exc()
            await message.answer("❌ Произошла ошибка при обработке запроса. Попробуйте позже.")


@check_owner
async def handle_emails(message: types.Message, **kwargs):
    """Обработчик команды /emails [фильтр]."""
    from app.email_client import EMAIL_CACHE
    
    text = message.text.strip()
    parts = text.split()
    
    # Определяем фильтр
    filter_type = None
    filter_value = None
    
    if len(parts) > 1:
        filter_value = parts[1].lower()
    
    # Получаем все письма из кэша
    all_emails = list(EMAIL_CACHE.values())
    
    # Сортируем по дате (новые первыми)
    all_emails.sort(key=lambda x: x.get('date_raw', ''), reverse=True)
    
    # Применяем фильтры
    if filter_value:
        if filter_value in ["work", "personal", "newsletter", "spam", "important"]:
            all_emails = [e for e in all_emails if e.get('category') == filter_value]
            filter_type = "category"
        elif filter_value in ["high", "medium", "low"]:
            all_emails = [e for e in all_emails if e.get('priority') == filter_value]
            filter_type = "priority"
        elif filter_value == "today":
            from datetime import datetime, timedelta
            today = datetime.now().date()
            filtered_emails = []
            for e in all_emails:
                date_str = e.get('date', '')
                # Простая проверка: если в дате есть "сегодня" или "только что" или "X мин/час назад"
                if any(word in date_str.lower() for word in ['сегодня', 'только что', 'мин', 'час', 'сек']):
                    filtered_emails.append(e)
            all_emails = filtered_emails
            filter_type = "date"
    
    if not all_emails:
        await message.answer(
            f"📭 Писем не найдено" + 
            (f" (фильтр: {filter_value})" if filter_value else "")
        )
        return
    
    # Ограничиваем до 20 писем для отображения
    emails_to_show = all_emails[:20]
    
    # Формируем сообщение
    priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    category_emoji = {
        "work": "💼", "personal": "👤", "newsletter": "📰", 
        "spam": "🗑️", "important": "⭐"
    }
    category_name = {
        "work": "Работа", "personal": "Личное", "newsletter": "Рассылка",
        "spam": "Спам", "important": "Важное"
    }
    
    result_text = f"📧 Найдено писем: {len(all_emails)}\n"
    if filter_value:
        result_text += f"🔍 Фильтр: {filter_value}\n"
    result_text += f"\n"
    
    for i, email_data in enumerate(emails_to_show, 1):
        priority = email_data.get('priority', 'medium')
        category = email_data.get('category', 'work')
        
        result_text += (
            f"{i}. {priority_emoji.get(priority, '🟡')} {category_emoji.get(category, '💼')} "
            f"{email_data.get('from', 'Неизвестно')[:30]}\n"
            f"   📝 {email_data.get('subject', 'Без темы')[:40]}\n"
            f"   📅 {email_data.get('date', '')}\n"
            f"   ID: `{email_data.get('local_id', '')}`\n\n"
        )
    
    if len(all_emails) > 20:
        result_text += f"\n... и еще {len(all_emails) - 20} писем"
    
    result_text += (
        f"\n\n💡 Используйте фильтры:\n"
        f"`/emails work` - только рабочие\n"
        f"`/emails important` - только важные\n"
        f"`/emails high` - высокий приоритет\n"
        f"`/emails newsletter` - рассылки\n"
        f"`/emails today` - за сегодня"
    )
    
    await message.answer(result_text, parse_mode="Markdown")


@check_owner
async def handle_thread(message: types.Message, **kwargs):
    """Обработчик команды /thread <ID> - показывает всю цепочку писем."""
    from app.email_client import get_email_from_cache, get_email_thread
    
    text = message.text.strip()
    parts = text.split()
    
    if len(parts) < 2:
        await message.answer(
            "📝 Правильный формат: `/thread <ID>`\n\n"
            "Пример: `/thread 1-1234567890`\n\n"
            "Покажет всю цепочку писем с этим письмом.",
            parse_mode="Markdown"
        )
        return
    
    local_id = parts[1]
    email_data = get_email_from_cache(local_id)
    
    if not email_data:
        await message.answer(f"❌ Письмо с ID `{local_id}` не найдено в кэше.", parse_mode="Markdown")
        return
    
    # Получаем всю цепочку писем
    thread_emails = get_email_thread(email_data)
    
    if len(thread_emails) == 1:
        await message.answer(
            f"📧 Это письмо не является частью цепочки.\n\n"
            f"От: {email_data.get('from', 'Неизвестно')}\n"
            f"Тема: {email_data.get('subject', 'Без темы')}\n"
            f"📅 {email_data.get('date', '')}\n\n"
            f"📝 {email_data.get('summary', 'Нет резюме')}"
        )
        return
    
    # Формируем сообщение с цепочкой
    result_text = f"📬 **Цепочка писем** ({len(thread_emails)} писем)\n\n"
    result_text += f"📝 Тема: {email_data.get('subject', 'Без темы')}\n\n"
    result_text += "---\n\n"
    
    for i, thread_email in enumerate(thread_emails, 1):
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
            thread_email.get('priority', 'medium'), '🟡'
        )
        
        result_text += (
            f"**{i}. {priority_emoji}** {thread_email.get('from', 'Неизвестно')}\n"
            f"📅 {thread_email.get('date', '')}\n"
            f"📝 {thread_email.get('summary', 'Нет резюме')[:100]}...\n"
            f"ID: `{thread_email.get('local_id', '')}`\n\n"
        )
    
    result_text += "💡 Используйте `/reply <ID> <текст>` для ответа на любое письмо из цепочки."
    
    await message.answer(result_text, parse_mode="Markdown")


@check_owner
async def handle_search(message: types.Message, **kwargs):
    """Обработчик команды /search <запрос> - поиск по письмам."""
    from app.email_client import search_emails
    
    text = message.text.strip()
    parts = text.split(maxsplit=1)  # Разделяем на команду и запрос
    
    if len(parts) < 2:
        await message.answer(
            "🔍 **Поиск по письмам**\n\n"
            "**Формат:** `/search <запрос>`\n\n"
            "**Примеры:**\n"
            "• `/search проект` - найти все письма со словом 'проект'\n"
            "• `/search client@company.com` - найти письма от этого отправителя\n"
            "• `/search встреча` - найти письма с упоминанием 'встреча'\n\n"
            "Поиск выполняется по:\n"
            "• Тема письма\n"
            "• Отправитель\n"
            "• Резюме письма\n"
            "• Содержимое письма",
            parse_mode="Markdown"
        )
        return
    
    query = parts[1]
    
    # Выполняем поиск
    results = search_emails(query, limit=20)
    
    if not results:
        await message.answer(
            f"❌ По запросу `{query}` ничего не найдено.\n\n"
            "💡 Попробуйте:\n"
            "• Использовать другое ключевое слово\n"
            "• Проверить правильность написания\n"
            "• Использовать часть слова или email адреса",
            parse_mode="Markdown"
        )
        return
    
    # Формируем сообщение с результатами
    result_text = f"🔍 **Найдено писем: {len(results)}**\n\n"
    result_text += f"📝 Запрос: `{query}`\n\n"
    result_text += "---\n\n"
    
    priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    category_emoji = {
        "work": "💼", "personal": "👤", "newsletter": "📰", 
        "spam": "🗑️", "important": "⭐"
    }
    
    for i, email_data in enumerate(results, 1):
        priority = email_data.get('priority', 'medium')
        category = email_data.get('category', 'work')
        
        result_text += (
            f"**{i}. {priority_emoji.get(priority, '🟡')} {category_emoji.get(category, '💼')}**\n"
            f"📧 От: {email_data.get('from', 'Неизвестно')}\n"
            f"📝 Тема: {email_data.get('subject', 'Без темы')}\n"
            f"📅 {email_data.get('date', '')}\n"
            f"💡 {email_data.get('summary', 'Нет резюме')[:80]}...\n"
            f"ID: `{email_data.get('local_id', '')}`\n\n"
        )
    
    if len(results) == 20:
        result_text += "\n💡 Показаны первые 20 результатов. Уточните запрос для более точного поиска."
    
    result_text += (
        f"\n\n💡 **Действия:**\n"
        f"• Используйте `/reply <ID> <текст>` для ответа\n"
        f"• Используйте `/thread <ID>` для просмотра цепочки"
    )
    
    await message.answer(result_text, parse_mode="Markdown")


@check_owner
async def handle_stats(message: types.Message, **kwargs):
    """Обработчик команды /stats - показывает статистику по письмам."""
    from app.email_client import get_email_statistics
    
    stats = get_email_statistics()
    
    if stats["total"] == 0:
        await message.answer(
            "📊 **Статистика**\n\n"
            "❌ Писем в кэше нет.\n\n"
            "💡 Дождитесь получения новых писем или проверьте настройки аккаунтов.",
            parse_mode="Markdown"
        )
        return
    
    # Формируем сообщение со статистикой
    result_text = "📊 **Статистика по письмам**\n\n"
    
    # Общая информация
    result_text += f"📧 **Всего писем:** {stats['total']}\n"
    result_text += f"📬 **Цепочек переписки:** {stats['threads_count']}\n\n"
    
    # По категориям
    category_emoji = {
        "work": "💼", "personal": "👤", "newsletter": "📰", 
        "spam": "🗑️", "important": "⭐"
    }
    category_name = {
        "work": "Работа", "personal": "Личное", "newsletter": "Рассылка",
        "spam": "Спам", "important": "Важное"
    }
    
    result_text += "**По категориям:**\n"
    for category, count in sorted(stats["by_category"].items(), key=lambda x: x[1], reverse=True):
        emoji = category_emoji.get(category, "📧")
        name = category_name.get(category, category)
        percentage = (count / stats["total"]) * 100
        result_text += f"{emoji} {name}: {count} ({percentage:.1f}%)\n"
    
    result_text += "\n"
    
    # По приоритетам
    priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    priority_name = {
        "high": "Высокий", "medium": "Средний", "low": "Низкий"
    }
    
    result_text += "**По приоритетам:**\n"
    for priority, count in sorted(stats["by_priority"].items(), key=lambda x: x[1], reverse=True):
        emoji = priority_emoji.get(priority, "🟡")
        name = priority_name.get(priority, priority)
        percentage = (count / stats["total"]) * 100
        result_text += f"{emoji} {name}: {count} ({percentage:.1f}%)\n"
    
    result_text += "\n"
    
    # По времени
    result_text += "**По времени:**\n"
    result_text += f"📅 Сегодня: {stats['by_time']['today']}\n"
    result_text += f"📅 Вчера: {stats['by_time']['yesterday']}\n"
    result_text += f"📅 За неделю: {stats['by_time']['week']}\n\n"
    
    # Топ отправителей
    if stats["top_senders"]:
        result_text += "**Топ отправителей:**\n"
        for i, sender_info in enumerate(stats["top_senders"][:5], 1):  # Топ-5
            from_addr = sender_info["from"]
            count = sender_info["count"]
            # Обрезаем длинные email адреса
            if len(from_addr) > 35:
                from_addr = from_addr[:32] + "..."
            result_text += f"{i}. {from_addr}: {count} писем\n"
    
    result_text += "\n💡 Используйте `/emails`, `/search` или `/thread` для работы с письмами."
    
    await message.answer(result_text, parse_mode="Markdown")


@check_owner
async def handle_status(message: types.Message, **kwargs):
    """Обработчик команды /status - показывает статус почтовых аккаунтов."""
    from app.email_client import check_account_status
    from app.storage import load_accounts
    
    accounts = load_accounts()
    
    result_text = "📊 **Статус почтовых аккаунтов**\n\n"
    
    # Проверяем аккаунт 1
    status1 = await check_account_status(1)
    if status1["configured"]:
        if status1["connected"]:
            result_text += f"✅ **Аккаунт 1** - Активен\n"
            result_text += f"📧 {status1['email']}\n\n"
        else:
            result_text += f"❌ **Аккаунт 1** - Ошибка подключения\n"
            result_text += f"📧 {status1['email']}\n"
            result_text += f"⚠️ {status1['error']}\n\n"
    else:
        result_text += f"⚪ **Аккаунт 1** - Не настроен\n\n"
    
    # Проверяем аккаунт 2
    status2 = await check_account_status(2)
    if status2["configured"]:
        if status2["connected"]:
            result_text += f"✅ **Аккаунт 2** - Активен\n"
            result_text += f"📧 {status2['email']}\n\n"
        else:
            result_text += f"❌ **Аккаунт 2** - Ошибка подключения\n"
            result_text += f"📧 {status2['email']}\n"
            result_text += f"⚠️ {status2['error']}\n\n"
    else:
        result_text += f"⚪ **Аккаунт 2** - Не настроен\n\n"
    
    # Общая статистика
    from app.email_client import EMAIL_CACHE
    total_emails = len(EMAIL_CACHE)
    result_text += f"📬 **Писем в кэше:** {total_emails}\n\n"
    
    # Подсказки
    if not status1["connected"] and not status2["connected"]:
        result_text += (
            "💡 **Что делать:**\n"
            "• Используйте `/start` для настройки аккаунтов\n"
            "• Проверьте правильность паролей\n"
            "• Для Gmail может потребоваться App Password"
        )
    elif status1["connected"] or status2["connected"]:
        result_text += (
            "✅ Аккаунты работают! Бот проверяет почту каждые 60 секунд.\n\n"
            "💡 Используйте `/emails` для просмотра писем"
        )
    
    await message.answer(result_text, parse_mode="Markdown")


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


async def send_notification(text: str, local_id: str = None, category: str = None):
    """Отправляет уведомление владельцу в Telegram."""
    if not bot:
        return
    
    try:
        # Не показываем кнопку "Ответить" для спама и рассылок
        if local_id and category not in ["spam", "newsletter"]:
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
            await bot.send_message(OWNER_TELEGRAM_ID, text, parse_mode="Markdown")
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

