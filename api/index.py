"""
Vercel serverless entry point для веб-приложения.
"""
from app.web_app import app

# Vercel ожидает переменную handler или app
handler = app

