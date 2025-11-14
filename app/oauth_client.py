"""
Модуль для OAuth2 авторизации через Google.
"""
import os
import base64
import json
from typing import Optional, Dict
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.exceptions import RefreshError

# OAuth2 настройки для Gmail
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://mail.google.com/'  # Полный доступ к Gmail
]

# Эти данные нужно получить в Google Cloud Console
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8080/callback")

# Временное хранилище для OAuth flow (в production лучше использовать Redis или БД)
OAUTH_FLOWS: Dict[str, Dict] = {}


def get_oauth_flow(account_id: int, email: str) -> Flow:
    """Создает OAuth2 flow для авторизации."""
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI]
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    # Сохраняем flow для последующего использования
    flow_key = f"{account_id}:{email}"
    OAUTH_FLOWS[flow_key] = {
        "flow": flow,
        "account_id": account_id,
        "email": email
    }
    
    return flow


def get_authorization_url(account_id: int, email: str) -> str:
    """
    Генерирует URL для авторизации через Google.
    
    Returns:
        URL для авторизации
    """
    flow = get_oauth_flow(account_id, email)
    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'  # Всегда запрашиваем согласие для получения refresh_token
    )
    return authorization_url


def exchange_code_for_tokens(account_id: int, email: str, authorization_code: str) -> Optional[Dict]:
    """
    Обменивает код авторизации на токены.
    
    Returns:
        Словарь с токенами или None при ошибке
    """
    flow_key = f"{account_id}:{email}"
    if flow_key not in OAUTH_FLOWS:
        return None
    
    flow = OAUTH_FLOWS[flow_key]["flow"]
    
    try:
        flow.fetch_token(code=authorization_code)
        credentials = flow.credentials
        
        # Сохраняем токены
        tokens = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
            "expiry": credentials.expiry.isoformat() if credentials.expiry else None
        }
        
        # Удаляем временный flow
        del OAUTH_FLOWS[flow_key]
        
        return tokens
    except Exception as e:
        print(f"Ошибка при обмене кода на токены: {e}")
        return None


def refresh_access_token(tokens: Dict) -> Optional[str]:
    """
    Обновляет access token используя refresh token.
    
    Returns:
        Новый access token или None при ошибке
    """
    try:
        creds = Credentials(
            token=tokens.get("token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri=tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=tokens.get("client_id", CLIENT_ID),
            client_secret=tokens.get("client_secret", CLIENT_SECRET),
            scopes=tokens.get("scopes", SCOPES)
        )
        
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            return creds.token
        
        return creds.token
    except RefreshError as e:
        print(f"Ошибка обновления токена: {e}")
        return None
    except Exception as e:
        print(f"Ошибка при обновлении токена: {e}")
        return None


def get_xoauth2_string(email: str, access_token: str) -> str:
    """
    Генерирует строку для XOAUTH2 авторизации в IMAP/SMTP.
    
    Формат: user=email\1auth=Bearer access_token\1\1
    """
    auth_string = f"user={email}\1auth=Bearer {access_token}\1\1"
    return base64.b64encode(auth_string.encode()).decode()

