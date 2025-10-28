# src/core/email_config.py
from pydantic_settings import BaseSettings
from pydantic import EmailStr
from dotenv import load_dotenv

load_dotenv()


class EmailSettings(BaseSettings):
    """Email configuration settings"""

    RESEND_API_KEY: str = "re_6bb4txSc_9XSA5K74U3W2Ktry8BnA7yJC"
    FROM_EMAIL: EmailStr = "noreply@kwantabit.com"
    FROM_NAME: str = "Dental Clinic Management System"
    SUPPORT_EMAIL: EmailStr = "support@kwantabit.com"
    SETUP_GUIDE_URL: str = (
        "https://docs.kwantabit.com/dental-clinic-management-system/getting-started"
    )
    WHATSAPP_SUPPORT: str = "+237 690908721"
    DOWNLOAD_URL: str = "https://kwantabit.com/download"

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
