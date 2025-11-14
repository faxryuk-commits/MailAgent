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

