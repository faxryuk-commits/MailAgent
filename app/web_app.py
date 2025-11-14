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

from app.storage import load_accounts, get_account, save_account
from app.email_client import get_email_from_cache, EMAIL_CACHE, send_email_smtp
from app.ai_client import summarize_email, polish_reply, suggest_reply_options

app = FastAPI(title="Mail Agent AI")

# Настройка шаблонов
# Для Vercel используем абсолютный путь
import pathlib
template_dir = pathlib.Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(template_dir))

# URL бэкенда (Railway или другой сервер)
# На Vercel это должен быть URL вашего Railway сервиса
BACKEND_URL = os.getenv("BACKEND_URL", "")

# Секретный ключ для доступа (опционально, для защиты API)
# Если не задан, защита отключена (подходит для личного использования)
WEB_ACCESS_KEY = os.getenv("WEB_ACCESS_KEY", "")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница."""
    # Пытаемся получить данные из локального кэша или бэкенда
    try:
        accounts = load_accounts()
        recent_emails = list(EMAIL_CACHE.values())[-20:]  # Последние 20 писем
    except:
        # Если локально нет данных, пытаемся получить с бэкенда
        accounts = {}
        recent_emails = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/emails", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    recent_emails = data.get("emails", [])[:20]
        except:
            pass
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "accounts": accounts,
        "recent_emails": recent_emails
    })


@app.get("/api/emails", response_class=JSONResponse)
async def get_emails():
    """API для получения списка писем."""
    try:
        emails = list(EMAIL_CACHE.values())
        # Сортируем по дате (новые первыми)
        emails.sort(key=lambda x: x.get('date_raw', ''), reverse=True)
        return {"emails": emails[:50]}  # Последние 50 писем
    except:
        # Если локально нет данных, пробуем получить с бэкенда
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/emails", timeout=5.0)
                if response.status_code == 200:
                    return response.json()
        except:
            pass
        return {"emails": []}


@app.get("/api/email/{local_id}", response_class=JSONResponse)
async def get_email(local_id: str):
    """API для получения конкретного письма."""
    email_data = get_email_from_cache(local_id)
    
    # Если локально нет, пробуем получить с бэкенда
    if not email_data:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/email/{local_id}", timeout=5.0)
                if response.status_code == 200:
                    return response.json()
        except:
            pass
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    
    # Генерируем варианты ответов через AI
    reply_options = suggest_reply_options(email_data)
    
    return {
        "email": email_data,
        "reply_options": reply_options
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
    
    email_data = get_email_from_cache(local_id)
    
    # Если локально нет, пробуем получить с бэкенда
    if not email_data:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BACKEND_URL}/api/email/{local_id}", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    email_data = data.get("email")
        except:
            pass
    
    if not email_data:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    
    # Если есть бэкенд, отправляем через него
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
    
    # Локальная отправка (если нет бэкенда)
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


@app.get("/email/{local_id}", response_class=HTMLResponse)
async def view_email(request: Request, local_id: str):
    """Страница просмотра письма."""
    email_data = get_email_from_cache(local_id)
    if not email_data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Письмо не найдено"
        })
    
    # Генерируем варианты ответов
    reply_options = suggest_reply_options(email_data)
    
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

