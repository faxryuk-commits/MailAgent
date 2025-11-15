"""
Vercel serverless entry point для веб-приложения.
"""
import sys
import os
from pathlib import Path

# Определяем корневую директорию проекта
# На Vercel __file__ будет указывать на /var/task/api/index.py
current_file = Path(__file__).resolve()
base_dir = current_file.parent.parent
base_dir_str = str(base_dir)

# Добавляем путь к приложению
if base_dir_str not in sys.path:
    sys.path.insert(0, base_dir_str)

# Также добавляем текущую директорию
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.insert(0, cwd)

# Устанавливаем PYTHONPATH
os.environ['PYTHONPATH'] = f"{base_dir_str}:{cwd}"

# Для отладки
print("=" * 50)
print("🚀 Инициализация Vercel serverless function")
print("=" * 50)
print(f"Python version: {sys.version.split()[0]}")
print(f"Current file: {current_file}")
print(f"Base directory: {base_dir_str}")
print(f"Working directory: {cwd}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH')}")
print(f"sys.path (first 3): {sys.path[:3]}")

# Проверка файлов
app_web_app = base_dir / "app" / "web_app.py"
app_init = base_dir / "app" / "__init__.py"
print(f"\n📁 Проверка файлов:")
print(f"   app/web_app.py: {app_web_app.exists()} ({app_web_app})")
print(f"   app/__init__.py: {app_init.exists()} ({app_init})")

# Подавляем предупреждения
import warnings
warnings.filterwarnings("ignore")

try:
    print("\n🔄 Импорт app.web_app...")
    from app.web_app import app
    
    # Vercel для Python ожидает ASGI приложение
    handler = app
    print("✅ FastAPI app успешно импортирован")
    print(f"✅ BACKEND_URL: {os.getenv('BACKEND_URL', 'НЕ УСТАНОВЛЕН')}")
    print("=" * 50)
except Exception as e:
    # Детальная информация об ошибке
    import traceback
    print("\n" + "=" * 50)
    print("❌ КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА")
    print("=" * 50)
    print(f"Тип ошибки: {type(e).__name__}")
    print(f"Сообщение: {str(e)}")
    if hasattr(e, 'name'):
        print(f"Модуль: {e.name}")
    print("\n📋 Полный traceback:")
    traceback.print_exc()
    print("\n📁 Дополнительная информация:")
    print(f"   sys.path: {sys.path}")
    print(f"   PYTHONPATH: {os.environ.get('PYTHONPATH')}")
    print("=" * 50)
    raise
