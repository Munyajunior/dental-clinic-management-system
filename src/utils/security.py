from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from typing import Optional
from uuid import UUID
from utils.logger import setup_logger
from dotenv import load_dotenv
import random
import string
from core.config import settings

logger = setup_logger("SECURITY")

# Load environment variables
load_dotenv()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Secret key for JWT
SECRET_KEY: str = settings.SECRET_KEY
ALGORITHM: str = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE: int = settings.ACCESS_TOKEN_EXPIRE  # Recommended expiry time


# Hash password
def hash_password(password: str) -> str:
    """Hash a password with proper error handling."""
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Error hashing password: {str(e)}")
        raise ValueError("Failed to hash password")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash with proper error handling."""
    try:
        if not plain_password or not hashed_password:
            return False

        # Check if the hashed password looks like a bcrypt hash
        if not hashed_password.startswith("$2b$") and not hashed_password.startswith(
            "$2a$"
        ):
            logger.warning(
                f"Password hash doesn't look like bcrypt: {hashed_password[:10]}..."
            )

        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Error verifying password: {str(e)}")
        return False


def generate_password(length=8):
    """Generate a random password for the patient."""
    characters = string.ascii_letters + string.digits
    return "".join(random.choice(characters) for _ in range(length))


# Generate JWT token
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now() + expires_delta
    else:
        expire = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE)
    to_encode.update({"exp": expire})

    # Ensure the subject is always a string
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# Decode JWT token
def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def create_reset_token(user_id: UUID, expires_delta: timedelta = timedelta(hours=1)):
    expire = datetime.now() + expires_delta
    to_encode = {"sub": str(user_id), "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_reset_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return str(payload.get("sub"))
    except:
        return None
