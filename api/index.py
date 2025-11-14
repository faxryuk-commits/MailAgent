"""
Vercel serverless entry point для веб-приложения.
"""
import sys
import os

# Добавляем путь к приложению
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)

from app.web_app import app

# Vercel ожидает переменную handler
handler = app
