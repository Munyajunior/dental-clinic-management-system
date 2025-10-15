# src/core/email_config.py
from pydantic import BaseSettings, EmailStr
from dotenv import load_dotenv

load_dotenv()


class EmailSettings(BaseSettings):
    """Email configuration settings"""

    RESEND_API_KEY: str
    FROM_EMAIL: EmailStr = "noreply@your-dental-clinic.com"
    FROM_NAME: str = "Dental Clinic Management System"

    # Template settings
    TEMPLATE_DIR: str = "src/templates/email"

    # Feature flags
    SEND_EMAILS: bool = True
    LOG_EMAILS: bool = True

    class Config:
        env_file_encoding = "utf-8"
        case_sensitive = True
        env_file = ".env"


email_settings = EmailSettings()
