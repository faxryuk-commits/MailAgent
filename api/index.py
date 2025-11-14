"""
Vercel serverless entry point для веб-приложения.
"""
import sys
import os

# Добавляем путь к приложению
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

try:
    from app.web_app import app
    
    # Vercel для Python ожидает ASGI приложение
    handler = app
except Exception as e:
    # Для отладки
    import traceback
    print(f"Ошибка импорта: {e}")
    traceback.print_exc()
    raise
