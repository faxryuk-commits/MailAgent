"""
Vercel serverless entry point для веб-приложения.
"""
import sys
import os

# Добавляем путь к приложению
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

# Устанавливаем PYTHONPATH если не установлен
if 'PYTHONPATH' not in os.environ:
    os.environ['PYTHONPATH'] = base_dir

try:
    from app.web_app import app
    
    # Vercel для Python ожидает ASGI приложение
    handler = app
except Exception as e:
    # Для отладки
    import traceback
    error_msg = f"Ошибка импорта: {e}\n"
    error_msg += f"base_dir: {base_dir}\n"
    error_msg += f"sys.path: {sys.path}\n"
    error_msg += f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'не установлен')}\n"
    print(error_msg)
    traceback.print_exc()
    raise
