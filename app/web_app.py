"""
Веб-приложение для Mail Agent AI.
Простой и удобный веб-интерфейс для управления почтовым агентом.
"""
import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import uvicorn
import httpx

# Импорты с обработкой ошибок для Vercel
try:
    from app.storage import load_accounts, get_account, save_account
    from app.email_client import get_email_from_cache, EMAIL_CACHE, send_email_smtp
    from app.ai_client import summarize_email, polish_reply, suggest_reply_options
    LOCAL_MODE = True
except ImportError as e:
    # На Vercel эти модули недоступны, работаем только через BACKEND_URL
    LOCAL_MODE = False
    print(f"Локальные модули недоступны, работаем через BACKEND_URL: {e}")

app = FastAPI(title="Mail Agent AI")

# Настройка шаблонов
# Для Vercel используем абсолютный путь
import pathlib
template_dir = pathlib.Path(__file__).parent / "templates"
template_dir_str = str(template_dir.absolute())

# Проверяем существование директории шаблонов
if not template_dir.exists():
    print(f"⚠️  Директория шаблонов не найдена: {template_dir_str}")
    print(f"   Текущая директория: {os.getcwd()}")
    print(f"   __file__: {__file__}")
    # Пробуем альтернативный путь
    alt_template_dir = pathlib.Path("app/templates")
    if alt_template_dir.exists():
        template_dir_str = str(alt_template_dir.absolute())
        print(f"   Используем альтернативный путь: {template_dir_str}")
    else:
        print(f"   ⚠️  Альтернативный путь тоже не найден: {alt_template_dir.absolute()}")

templates = Jinja2Templates(directory=template_dir_str)
print(f"✅ Шаблоны загружены из: {template_dir_str}")

# URL бэкенда (Railway или другой сервер)
# На Vercel это должен быть URL вашего Railway сервиса
BACKEND_URL = os.getenv("BACKEND_URL", "")

# Секретный ключ для доступа (опционально, для защиты API)
# Если не задан, защита отключена (подходит для личного использования)
WEB_ACCESS_KEY = os.getenv("WEB_ACCESS_KEY", "")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница."""
    accounts = {}
    recent_emails = []
    
    # Пытаемся получить данные из локального кэша (только если доступно)
    if LOCAL_MODE:
        try:
            accounts = load_accounts()
            recent_emails = list(EMAIL_CACHE.values())[-20:]  # Последние 20 писем
        except:
            pass
    
    # Если локально нет данных или на Vercel, пытаемся получить с бэкенда
    if not recent_emails and BACKEND_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/emails", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    recent_emails = data.get("emails", [])[:20]
        except Exception as e:
            print(f"Ошибка получения данных с бэкенда: {e}")
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "accounts": accounts,
        "recent_emails": recent_emails
    })


@app.get("/api/emails", response_class=JSONResponse)
async def get_emails():
    """API для получения списка писем."""
    # Пытаемся получить локально (только если доступно)
    if LOCAL_MODE:
        try:
            emails = list(EMAIL_CACHE.values())
            # Сортируем по дате (новые первыми)
            emails.sort(key=lambda x: x.get('date_raw', ''), reverse=True)
            return {"emails": emails[:50]}  # Последние 50 писем
        except:
            pass
    
    # Если локально нет данных или на Vercel, пробуем получить с бэкенда
    if BACKEND_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/emails", timeout=5.0)
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"Ошибка получения данных с бэкенда: {e}")
    
    return {"emails": []}


@app.get("/api/email/{local_id}", response_class=JSONResponse)
async def get_email(local_id: str):
    """API для получения конкретного письма."""
    email_data = None
    
    # Пытаемся получить локально (только если доступно)
    if LOCAL_MODE:
        try:
            email_data = get_email_from_cache(local_id)
        except:
            pass
    
    # Если локально нет или на Vercel, пробуем получить с бэкенда
    if not email_data and BACKEND_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/email/{local_id}", timeout=5.0)
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"Ошибка получения письма с бэкенда: {e}")
    
    if not email_data:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    
    # Генерируем варианты ответов через AI (только если доступно)
    if LOCAL_MODE:
        try:
            reply_options = suggest_reply_options(email_data)
            return {
                "email": email_data,
                "reply_options": reply_options
            }
        except:
            pass
    
    return {
        "email": email_data,
        "reply_options": {"suggestions": []}
    }


@app.post("/api/reply", response_class=JSONResponse)
async def send_reply(
    local_id: str = Form(...),
    reply_text: str = Form(...),
    access_key: Optional[str] = Form(None)
):
    """API для отправки ответа на письмо."""
    # Простая проверка доступа (только если WEB_ACCESS_KEY задан)
    if WEB_ACCESS_KEY and access_key and access_key != WEB_ACCESS_KEY:
        raise HTTPException(status_code=403, detail="Неверный ключ доступа")
    
    email_data = None
    
    # Пытаемся получить локально (только если доступно)
    if LOCAL_MODE:
        try:
            email_data = get_email_from_cache(local_id)
        except:
            pass
    
    # Если локально нет или на Vercel, пробуем получить с бэкенда
    if not email_data and BACKEND_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/email/{local_id}", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    email_data = data.get("email")
        except Exception as e:
            print(f"Ошибка получения письма с бэкенда: {e}")
    
    if not email_data:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    
    # Всегда отправляем через бэкенд (на Vercel это обязательно)
    if BACKEND_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{BACKEND_URL}/api/reply",
                    data={
                        "local_id": local_id,
                        "reply_text": reply_text,
                        "access_key": access_key or WEB_ACCESS_KEY
                    },
                    timeout=30.0
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"Ошибка при отправке через бэкенд: {e}")
    
    # Локальная отправка (только если нет бэкенда и доступны локальные модули)
    if not BACKEND_URL and LOCAL_MODE:
        try:
            account_id = email_data["account_id"]
            from_field = email_data["from"]
            
            # Извлекаем email адрес
            if "<" in from_field and ">" in from_field:
                to_email = from_field.split("<")[-1].split(">")[0].strip()
            else:
                to_email = from_field.strip()
            
            subject = f"Re: {email_data['subject']}"
            context = f"От: {email_data['from']}\nТема: {email_data['subject']}\n\n{email_data['body'][:500]}"
            
            # Улучшаем ответ через AI
            polished_reply = polish_reply(reply_text, context)
            
            # Отправляем письмо
            success, msg = await send_email_smtp(
                account_id,
                to_email,
                subject,
                polished_reply
            )
            
            if success:
                return {"success": True, "message": "Ответ отправлен", "polished_reply": polished_reply}
            else:
                raise HTTPException(status_code=500, detail=msg)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка локальной отправки: {str(e)}")
    
    # Если нет бэкенда и локальная отправка недоступна
    raise HTTPException(status_code=500, detail="BACKEND_URL не настроен. Настройте BACKEND_URL в переменных окружения.")


@app.get("/email/{local_id}", response_class=HTMLResponse)
async def view_email(request: Request, local_id: str):
    """Страница просмотра письма."""
    email_data = None
    reply_options = {"suggestions": []}
    
    # Пытаемся получить локально (только если доступно)
    if LOCAL_MODE:
        try:
            email_data = get_email_from_cache(local_id)
            if email_data:
                reply_options = suggest_reply_options(email_data)
        except:
            pass
    
    # Если локально нет или на Vercel, пробуем получить с бэкенда
    if not email_data and BACKEND_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/email/{local_id}", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    email_data = data.get("email")
                    reply_options = data.get("reply_options", {"suggestions": []})
        except Exception as e:
            print(f"Ошибка получения письма с бэкенда: {e}")
    
    if not email_data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Письмо не найдено"
        })
    
    return templates.TemplateResponse("email.html", {
        "request": request,
        "email": email_data,
        "reply_options": reply_options,
        "access_key": WEB_ACCESS_KEY
    })


def run_web_app(host: str = "0.0.0.0", port: int = 8000):
    """Запускает веб-приложение."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)

