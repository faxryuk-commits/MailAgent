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

from app.storage import load_accounts, get_account, save_account
from app.email_client import get_email_from_cache, EMAIL_CACHE, send_email_smtp
from app.ai_client import summarize_email, polish_reply, suggest_reply_options

app = FastAPI(title="Mail Agent AI")

# Настройка шаблонов
templates = Jinja2Templates(directory="app/templates")

# Секретный ключ для доступа (можно вынести в env)
WEB_ACCESS_KEY = os.getenv("WEB_ACCESS_KEY", "change-me-in-production")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница."""
    accounts = load_accounts()
    recent_emails = list(EMAIL_CACHE.values())[-20:]  # Последние 20 писем
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "accounts": accounts,
        "recent_emails": recent_emails
    })


@app.get("/api/emails", response_class=JSONResponse)
async def get_emails():
    """API для получения списка писем."""
    emails = list(EMAIL_CACHE.values())
    # Сортируем по дате (новые первыми)
    emails.sort(key=lambda x: x.get('date_raw', ''), reverse=True)
    return {"emails": emails[:50]}  # Последние 50 писем


@app.get("/api/email/{local_id}", response_class=JSONResponse)
async def get_email(local_id: str):
    """API для получения конкретного письма."""
    email_data = get_email_from_cache(local_id)
    if not email_data:
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
    # Простая проверка доступа (в production использовать нормальную аутентификацию)
    if access_key and access_key != WEB_ACCESS_KEY:
        raise HTTPException(status_code=403, detail="Неверный ключ доступа")
    
    email_data = get_email_from_cache(local_id)
    if not email_data:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    
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
    uvicorn.run(app, host=host, port=port)

