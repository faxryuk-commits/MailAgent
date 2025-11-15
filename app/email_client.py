"""
Модуль для работы с почтой через IMAP и SMTP.
"""
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime
from typing import Optional, List, Dict
import asyncio

from app.storage import get_account
from app.ai_client import summarize_email, analyze_email_priority_and_category

# Кэш писем в памяти: {local_id: email_data}
EMAIL_CACHE: Dict[str, dict] = {}


def decode_mime_words(s):
    """Декодирует MIME-заголовки."""
    if s is None:
        return ""
    decoded_parts = decode_header(s)
    decoded_str = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            decoded_str += part.decode(encoding or 'utf-8', errors='ignore')
        else:
            decoded_str += part
    return decoded_str


def parse_email_date(date_str: str) -> str:
    """
    Парсит дату из email заголовка и форматирует в читаемый вид.
    
    Args:
        date_str: Строка с датой из заголовка email
        
    Returns:
        Отформатированная дата и время
    """
    if not date_str:
        return "Дата не указана"
    
    try:
        # Парсим дату из email формата
        email_date = parsedate_to_datetime(date_str)
        
        # Форматируем в читаемый вид (русская локаль)
        # Приводим к одному timezone для сравнения
        if email_date.tzinfo:
            now = datetime.now(email_date.tzinfo)
            email_date_naive = email_date
        else:
            now = datetime.now()
            email_date_naive = email_date
        
        diff = now - email_date_naive
        
        # Если письмо сегодня
        if diff.days == 0:
            if diff.seconds < 3600:  # Меньше часа
                minutes = diff.seconds // 60
                if minutes == 0:
                    return "только что"
                return f"{minutes} мин. назад"
            else:  # Больше часа, но сегодня
                hours = diff.seconds // 3600
                return f"{hours} ч. назад"
        # Если письмо вчера
        elif diff.days == 1:
            return f"вчера в {email_date.strftime('%H:%M')}"
        # Если письмо на этой неделе
        elif diff.days < 7:
            days_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
            day_name = days_ru[email_date.weekday()]
            return f"{day_name} в {email_date.strftime('%H:%M')}"
        # Если письмо старше недели
        else:
            # Форматируем дату на русском
            months_ru = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
                        "июля", "августа", "сентября", "октября", "ноября", "декабря"]
            return f"{email_date.day} {months_ru[email_date.month]} {email_date.year} в {email_date.strftime('%H:%M')}"
    
    except Exception as e:
        # Если не удалось распарсить, возвращаем как есть
        print(f"Ошибка при парсинге даты: {e}, исходная строка: {date_str}")
        return date_str


def parse_email_body(msg) -> str:
    """Извлекает текст письма из email.message."""
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body += payload.decode(charset, errors='ignore')
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='ignore')
        except Exception:
            pass
    
    return body.strip()


async def check_account_emails(account_id: int, telegram_notify_func=None) -> List[dict]:
    """
    Проверяет новые письма для указанного аккаунта.
    
    Args:
        account_id: ID аккаунта (1 или 2)
        telegram_notify_func: Асинхронная функция для отправки уведомлений в Telegram
        
    Returns:
        Список новых писем
    """
    account = get_account(account_id)
    if not account:
        return []
    
    imap_host = account.get("imap_host")
    imap_user = account.get("imap_user")
    imap_pass = account.get("imap_pass")
    
    if not all([imap_host, imap_user, imap_pass]):
        return []
    
    new_emails = []
    
    try:
        # Подключение к IMAP (синхронная операция в executor)
        loop = asyncio.get_event_loop()
        
        def imap_connect():
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")
            return mail
        
        mail = await loop.run_in_executor(None, imap_connect)
        
        # Поиск непрочитанных писем (только новые, не старше 7 дней)
        from datetime import datetime, timedelta
        date_limit = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        
        def imap_search():
            # Ищем только непрочитанные письма за последние 7 дней
            search_criteria = f'(UNSEEN SINCE {date_limit})'
            status, messages = mail.search(None, search_criteria)
            return status, messages
        
        status, messages = await loop.run_in_executor(None, imap_search)
        
        if status != "OK":
            def imap_close():
                mail.close()
                mail.logout()
            await loop.run_in_executor(None, imap_close)
            return []
        
        email_ids = messages[0].split()
        
        # Ограничиваем количество писем за раз (максимум 10)
        email_ids = email_ids[:10]
        
        print(f"Найдено новых писем: {len(email_ids)}")
        
        for email_id_bytes in email_ids:
            try:
                # Получение письма (сохраняем email_id_bytes для использования в замыкании)
                email_id = email_id_bytes
                def imap_fetch():
                    status, msg_data = mail.fetch(email_id, "(RFC822)")
                    return status, msg_data
                
                status, msg_data = await loop.run_in_executor(None, imap_fetch)
                
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Извлечение данных
                from_addr = decode_mime_words(msg.get("From", ""))
                subject = decode_mime_words(msg.get("Subject", ""))
                date_raw = msg.get("Date", "")
                date_formatted = parse_email_date(date_raw)
                body = parse_email_body(msg)
                
                # Создание резюме через OpenAI (синхронная операция)
                summary = await loop.run_in_executor(None, summarize_email, body[:2000])
                
                # Генерация local_id
                timestamp_ms = int(datetime.now().timestamp() * 1000)
                local_id = f"{account_id}-{timestamp_ms}"
                
                # Временный email_data для анализа приоритета/категории
                temp_email_data = {
                    "from": from_addr,
                    "subject": subject,
                    "body": body,
                    "summary": summary
                }
                
                # Анализ приоритета и категории через AI
                priority_data = await loop.run_in_executor(
                    None, 
                    analyze_email_priority_and_category, 
                    temp_email_data
                )
                
                # Сохранение в кэш с приоритетом и категорией
                email_data = {
                    "local_id": local_id,
                    "account_id": account_id,
                    "from": from_addr,
                    "subject": subject,
                    "date": date_formatted,
                    "date_raw": date_raw,  # Сохраняем и исходную дату
                    "body": body,
                    "summary": summary,
                    "priority": priority_data.get("priority", "medium"),
                    "category": priority_data.get("category", "work"),
                    "priority_reason": priority_data.get("reason", ""),
                    "original_msg": msg
                }
                
                EMAIL_CACHE[local_id] = email_data
                new_emails.append(email_data)
                
                # Помечаем письмо как прочитанное, чтобы не обрабатывать его снова
                def mark_as_read():
                    mail.store(email_id, '+FLAGS', '\\Seen')
                
                await loop.run_in_executor(None, mark_as_read)
                
                # Формирование эмодзи для приоритета
                priority_emoji = {
                    "high": "🔴",
                    "medium": "🟡",
                    "low": "🟢"
                }.get(priority_data.get("priority", "medium"), "🟡")
                
                # Формирование эмодзи для категории
                category_emoji = {
                    "work": "💼",
                    "personal": "👤",
                    "newsletter": "📰",
                    "spam": "🗑️",
                    "important": "⭐"
                }.get(priority_data.get("category", "work"), "💼")
                
                category_name = {
                    "work": "Работа",
                    "personal": "Личное",
                    "newsletter": "Рассылка",
                    "spam": "Спам",
                    "important": "Важное"
                }.get(priority_data.get("category", "work"), "Работа")
                
                priority_name = {
                    "high": "Высокий",
                    "medium": "Средний",
                    "low": "Низкий"
                }.get(priority_data.get("priority", "medium"), "Средний")
                
                # Отправка уведомления в Telegram с приоритетом и категорией
                if telegram_notify_func:
                    # Для спама и рассылок - более короткое уведомление
                    if priority_data.get("category") in ["spam", "newsletter"]:
                        message = (
                            f"{category_emoji} {category_name} ({priority_emoji} {priority_name})\n\n"
                            f"📧 От: {from_addr}\n"
                            f"📝 Тема: {subject}\n"
                            f"📅 {date_formatted}\n\n"
                            f"💡 {summary}"
                        )
                    else:
                        message = (
                            f"{priority_emoji} {priority_name} приоритет | {category_emoji} {category_name}\n\n"
                            f"📧 Новое письмо (Аккаунт {account_id})\n\n"
                            f"От: {from_addr}\n"
                            f"Тема: {subject}\n"
                            f"📅 Дата: {date_formatted}\n\n"
                            f"📝 Резюме:\n{summary}\n\n"
                            f"💡 {priority_data.get('reason', '')}\n\n"
                            f"ID для ответа: `{local_id}`"
                        )
                    await telegram_notify_func(message, local_id)
                
            except Exception as e:
                print(f"Ошибка при обработке письма {email_id}: {e}")
                continue
        
        def imap_close():
            mail.close()
            mail.logout()
        await loop.run_in_executor(None, imap_close)
        
    except imaplib.IMAP4.error as e:
        error_msg = str(e).lower()
        if "authentication" in error_msg or "login" in error_msg:
            if telegram_notify_func:
                notify_msg = (
                    f"⚠️ Ошибка авторизации для аккаунта {account_id}.\n\n"
                    f"Возможно, включена двухфакторная аутентификация. "
                    f"Для Gmail необходимо использовать App Password вместо обычного пароля.\n\n"
                    f"Инструкция: https://support.google.com/accounts/answer/185833"
                )
                await telegram_notify_func(notify_msg)
        else:
            if telegram_notify_func:
                await telegram_notify_func(f"Ошибка IMAP для аккаунта {account_id}: {str(e)}")
    except Exception as e:
        if telegram_notify_func:
            await telegram_notify_func(f"Ошибка при проверке почты (аккаунт {account_id}): {str(e)}")
    
    return new_emails


async def send_email_smtp(account_id: int, to: str, subject: str, body: str, telegram_notify_func=None) -> tuple[bool, str]:
    """
    Отправляет письмо через SMTP.
    
    Args:
        account_id: ID аккаунта
        to: Адрес получателя
        subject: Тема письма
        body: Текст письма
        telegram_notify_func: Асинхронная функция для отправки уведомлений
        
    Returns:
        (успех, сообщение)
    """
    account = get_account(account_id)
    if not account:
        return False, "Аккаунт не настроен"
    
    smtp_host = account.get("smtp_host")
    smtp_port = account.get("smtp_port", 587)
    imap_user = account.get("imap_user")
    imap_pass = account.get("imap_pass")
    
    if not all([smtp_host, imap_user, imap_pass]):
        return False, "Не все настройки SMTP заполнены"
    
    try:
        # Создание письма
        msg = MIMEMultipart()
        msg["From"] = imap_user
        msg["To"] = to
        msg["Subject"] = subject
        
        msg.attach(MIMEText(body, "plain", "utf-8"))
        
        # Отправка через SMTP (синхронная операция в executor)
        loop = asyncio.get_event_loop()
        
        def smtp_send():
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
            server.login(imap_user, imap_pass)
            server.send_message(msg)
            server.quit()
        
        await loop.run_in_executor(None, smtp_send)
        
        return True, "Письмо успешно отправлено"
        
    except smtplib.SMTPAuthenticationError:
        error_msg = (
            f"⚠️ Ошибка авторизации SMTP для аккаунта {account_id}.\n\n"
            f"Вероятно, включена двухфакторная аутентификация. "
            f"Для Gmail необходимо использовать App Password.\n\n"
            f"Инструкция: https://support.google.com/accounts/answer/185833"
        )
        if telegram_notify_func:
            await telegram_notify_func(error_msg)
        return False, "Ошибка авторизации SMTP"
    except Exception as e:
        error_msg = f"Ошибка при отправке письма: {str(e)}"
        if telegram_notify_func:
            await telegram_notify_func(error_msg)
        return False, error_msg


def get_email_from_cache(local_id: str) -> Optional[dict]:
    """Получает письмо из кэша по local_id."""
    return EMAIL_CACHE.get(local_id)


async def test_imap_connection(imap_host: str, imap_user: str, imap_pass: str) -> tuple[bool, str]:
    """
    Тестирует подключение к IMAP серверу.
    
    Returns:
        (успех, сообщение_об_ошибке)
        Сообщение может быть: "authentication_error", "app_password_required", или текст ошибки
    """
    try:
        loop = asyncio.get_event_loop()
        
        def imap_test():
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")
            mail.close()
            mail.logout()
            return True, ""
        
        await loop.run_in_executor(None, imap_test)
        return True, ""
        
    except imaplib.IMAP4.error as e:
        error_msg = str(e).lower()
        error_bytes = str(e)
        
        # Проверяем на требование App Password
        if "application-specific password" in error_msg or "app password" in error_msg:
            return False, "app_password_required"
        
        # Проверяем на общую ошибку авторизации
        if "authentication" in error_msg or "login" in error_msg or "failure" in error_msg:
            # Для Gmail, если это не App Password, то скорее всего нужен App Password
            if "gmail.com" in imap_host.lower():
                return False, "app_password_required"
            return False, "authentication_error"
        
        return False, str(e)
    except Exception as e:
        return False, str(e)

