"""
Vercel serverless entry point для веб-приложения.
"""
import sys
import os
from pathlib import Path

# Определяем корневую директорию проекта
base_dir = Path(__file__).parent.parent
base_dir_str = str(base_dir.absolute())

# Добавляем путь к приложению
if base_dir_str not in sys.path:
    sys.path.insert(0, base_dir_str)

# Устанавливаем PYTHONPATH
os.environ['PYTHONPATH'] = base_dir_str

# Для отладки (будет видно в логах Vercel)
print(f"Python version: {sys.version}")
print(f"Base directory: {base_dir_str}")
print(f"Current working directory: {os.getcwd()}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH')}")
print(f"sys.path: {sys.path[:3]}...")  # Первые 3 элемента

try:
    # Импортируем FastAPI приложение
    from app.web_app import app
    
    # Vercel для Python ожидает ASGI приложение
    handler = app
    print("✅ FastAPI app успешно импортирован")
except ImportError as e:
    # Детальная информация об ошибке импорта
    import traceback
    print("❌ Ошибка импорта:")
    print(f"   Тип ошибки: {type(e).__name__}")
    print(f"   Сообщение: {str(e)}")
    print(f"   Модуль: {getattr(e, 'name', 'неизвестно')}")
    print("\n📋 Traceback:")
    traceback.print_exc()
    print("\n📁 Проверка файлов:")
    print(f"   app/web_app.py существует: {Path(base_dir / 'app' / 'web_app.py').exists()}")
    print(f"   app/__init__.py существует: {Path(base_dir / 'app' / '__init__.py').exists()}")
    raise
except Exception as e:
    # Другие ошибки
    import traceback
    print("❌ Неожиданная ошибка:")
    print(f"   Тип: {type(e).__name__}")
    print(f"   Сообщение: {str(e)}")
    print("\n📋 Traceback:")
    traceback.print_exc()
    raise
