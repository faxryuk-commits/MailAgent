"""
Модуль для работы с OpenAI API.
"""
import os
from openai import OpenAI

client = None


def init_openai():
    """Инициализирует OpenAI клиент."""
    global client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY не установлен в переменных окружения")
    client = OpenAI(api_key=api_key)


def summarize_email(text: str) -> str:
    """
    Создаёт краткое резюме письма (1-3 предложения).
    
    Args:
        text: Текст письма
        
    Returns:
        Краткое резюме письма
    """
    if not client:
        init_openai()
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Сделай краткое резюме письма на 1-3 предложения. Сохрани важную информацию: от кого, о чём, что требуется."
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            temperature=0.3,
            max_tokens=200
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка при создании резюме: {str(e)}"


def polish_reply(draft: str, context: str) -> str:
    """
    Улучшает черновик ответа, переводя его в деловой английский стиль.
    
    Args:
        draft: Черновик ответа (может быть на русском или английском)
        context: Контекст исходного письма
        
    Returns:
        Улучшенный ответ на деловом английском
    """
    if not client:
        init_openai()
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Ты профессиональный помощник для написания деловых писем. Преобразуй черновик ответа в вежливое деловое письмо на английском языке. Сохрани смысл и намерение автора."
                },
                {
                    "role": "user",
                    "content": f"Контекст исходного письма:\n{context}\n\nЧерновик ответа:\n{draft}\n\nНапиши профессиональный ответ на английском языке."
                }
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка при обработке ответа: {str(e)}"


def understand_user_intent(user_message: str, current_state: str = None, available_commands: list = None) -> dict:
    """
    Понимает намерение пользователя через OpenAI.
    
    Args:
        user_message: Сообщение пользователя
        current_state: Текущее состояние FSM (если есть)
        available_commands: Доступные команды
        
    Returns:
        Словарь с намерением и параметрами:
        {
            "intent": "command" | "question" | "setup" | "unknown",
            "command": "/start" | "/reply" | None,
            "parameters": {...},
            "response": "естественный ответ бота"
        }
    """
    if not client:
        init_openai()
    
    commands_info = "\n".join(available_commands or ["/start - начать настройку", "/reply <ID> <текст> - ответить на письмо"])
    state_info = f"Текущее состояние: {current_state}" if current_state else "Состояние: не в процессе настройки"
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Ты умный помощник для почтового бота Mail Agent AI. 
Твоя задача - понять намерение пользователя и ответить естественно и дружелюбно.

Доступные команды:
- /start - начать настройку почтового аккаунта
- /reply <ID> <текст> - ответить на письмо с указанным ID

Если пользователь хочет:
- Начать настройку → intent: "command", command: "/start"
- Ответить на письмо → intent: "command", command: "/reply", parameters: {"id": "...", "text": "..."}
- Задать вопрос → intent: "question", response: "естественный ответ"
- Продолжить настройку → intent: "setup", response: "подтверждение"

Отвечай на русском языке, дружелюбно и естественно. Если это команда, укажи её в формате JSON."""
                },
                {
                    "role": "user",
                    "content": f"""Сообщение пользователя: "{user_message}"

{state_info}
Доступные команды:
{commands_info}

Понял намерение и ответь в формате JSON:
{{
    "intent": "command" | "question" | "setup" | "unknown",
    "command": "/start" | "/reply" | null,
    "parameters": {{"id": "...", "text": "..."}} или {{}},
    "response": "естественный дружелюбный ответ на русском"
}}"""
                }
            ],
            temperature=0.7,
            max_tokens=300,
            response_format={"type": "json_object"}
        )
        
        import json
        result = json.loads(response.choices[0].message.content.strip())
        return result
    except Exception as e:
        print(f"Ошибка при понимании намерения: {e}")
        return {
            "intent": "unknown",
            "command": None,
            "parameters": {},
            "response": "Извините, не совсем понял. Попробуйте использовать команды /start или /reply."
        }


def generate_friendly_response(context: str, user_message: str = None) -> str:
    """
    Генерирует дружелюбный ответ на основе контекста.
    
    Args:
        context: Контекст ситуации
        user_message: Сообщение пользователя (опционально)
        
    Returns:
        Естественный ответ
    """
    if not client:
        init_openai()
    
    try:
        messages = [
            {
                "role": "system",
                "content": "Ты дружелюбный помощник почтового бота Mail Agent AI. Отвечай на русском языке естественно, вежливо и по делу. Используй эмодзи для выразительности."
            },
            {
                "role": "user",
                "content": f"Контекст: {context}\n\n{'Сообщение пользователя: ' + user_message if user_message else ''}\n\nСгенерируй естественный дружелюбный ответ:"
            }
        ]
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.8,
            max_tokens=200
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        return "Понял! Продолжаем."

