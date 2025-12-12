# src/core/email_config.py
from pydantic_settings import BaseSettings
from pydantic import EmailStr
from dotenv import load_dotenv

load_dotenv()


class EmailSettings(BaseSettings):
    """Email configuration settings"""

    RESEND_API_KEY: str
    FROM_EMAIL: EmailStr = "example@gmail.com"
    FROM_NAME: str
    SUPPORT_EMAIL: EmailStr = "support@gmail.com"
    SETUP_GUIDE_URL: str
    WHATSAPP_SUPPORT: str
    DOWNLOAD_URL: str
    APP_NAME: str = "KwantaDent Suite"
    APP_VERSION: str = "1.0.0"
    SCHEME: str = "kwantabit-kwantadent"

    # Template settings
    TEMPLATE_DIR: str

    # Feature flags
    SEND_EMAILS: bool = True
    LOG_EMAILS: bool = True

    class Config:
        env_file_encoding = "utf-8"
        case_sensitive = True
        env_file = ".env"


email_settings = EmailSettings()
