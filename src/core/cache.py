# src/core/cache.py
import hashlib
import inspect
import json
from functools import wraps
from typing import Optional, Callable, Any, Union, List, Tuple
from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.coder import JsonCoder, PickleCoder
from pydantic import BaseModel
from redis import asyncio as aioredis
from asyncio import sleep
from utils.logger import setup_logger
from uuid import UUID
from datetime import datetime
from core.config import settings

logger = setup_logger("REDIS CACHE")


class HybridCoder:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def encode(cls, value: Any) -> bytes:
        try:
            return JsonCoder.encode(value)
        except (TypeError, ValueError):
            return PickleCoder.encode(value)

    @classmethod
    def decode(cls, value: bytes) -> Any:
        try:
            return JsonCoder.decode(value)
        except (TypeError, ValueError):
            return PickleCoder.decode(value)


async def init_redis(app: FastAPI):
    """Initialize Redis connection with proper configuration"""
    redis_password = settings.REDIS_PASSWORD
    try:
        redis = aioredis.from_url(
            settings.REDIS_CACHE_URL,
            password=redis_password or None,
            encoding="utf8",
            decode_responses=False,
            socket_timeout=5,
            socket_keepalive=True,
            retry_on_timeout=True,
            max_connections=20,
        )

        # Test connection with retry
        for _ in range(3):
            try:
                if await redis.ping():
                    break
            except Exception as e:
                logger.warning(f"Redis ping attempt failed: {str(e)}")
                await sleep(0.5)
        else:
            raise ConnectionError("Redis ping failed after 3 attempts")

        # Initialize with correct parameters
        FastAPICache.init(
            EnhancedRedisBackend(redis),
            prefix="dental_clinic_saas",
            coder=HybridCoder,
            enable=True,
        )
        logger.info("Redis cache initialized successfully")

    except Exception as e:
        logger.error(f"Redis connection failed: {str(e)}", exc_info=True)
        raise RuntimeError(f"Redis connection failed: {str(e)}")


class EnhancedRedisBackend(RedisBackend):
    """Enhanced Redis backend with proper prefix handling and error handling"""

    def __init__(self, redis):
        self.redis = redis  # Store the redis connection
        self._default_ttl = 300  # Default 5 minutes

    async def _get_full_key(self, key: str) -> str:
        """Get the full key with prefix"""
        prefix = FastAPICache.get_prefix()
        return f"{prefix}:{key}" if prefix else key

    async def get_with_ttl(self, key: str) -> Tuple[int, Optional[bytes]]:
        """Get value with TTL with proper prefix handling"""
        full_key = await self._get_full_key(key)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.ttl(full_key)
                pipe.get(full_key)
                ttl, value = await pipe.execute()
                return ttl, value
        except Exception as e:
            logger.error(f"Error getting value with TTL: {str(e)}")
            return 0, None

    async def get(self, key: str) -> Optional[bytes]:
        """Get value with proper prefix handling"""
        full_key = await self._get_full_key(key)
        try:
            result = await self.redis.get(full_key)
            if result is None:
                logger.debug(f"Cache miss for key: {full_key}")
            else:
                logger.debug(f"Cache hit for key: {full_key}")
            return result
        except Exception as e:
            logger.error(f"Error getting cache value: {str(e)}")
            return None

    async def set(self, key: str, value: bytes, expire: Optional[int] = None) -> None:
        """Set value with proper prefix handling"""
        full_key = await self._get_full_key(key)
        try:
            await self.redis.set(full_key, value, ex=expire or self._default_ttl)
            logger.debug(f"Cache set for key: {full_key}")
        except Exception as e:
            logger.error(f"Error setting cache value: {str(e)}")

    async def delete(self, key: str) -> None:
        """Delete key with proper prefix handling"""
        full_key = await self._get_full_key(key)
        try:
            await self.redis.delete(full_key)
            logger.debug(f"Cache deleted for key: {full_key}")
        except Exception as e:
            logger.error(f"Error deleting cache key: {str(e)}")

    async def clear(
        self, namespace: Optional[str] = None, key: Optional[str] = None
    ) -> int:
        """Clear cache with proper prefix handling"""
        try:
            if namespace:
                prefixed_namespace = (
                    f"{FastAPICache.get_prefix()}:{namespace}"
                    if FastAPICache.get_prefix()
                    else namespace
                )
                keys = await self.redis.keys(f"{prefixed_namespace}:*")
                if keys:
                    await self.redis.delete(*keys)
                    return len(keys)
                return 0
            elif key:
                await self.redis.delete(key)
                return 1
            return 0
        except Exception as e:
            logger.error(f"Error clearing cache: {str(e)}")
            return 0

    async def delete_by_pattern(self, pattern: str) -> int:
        """Delete keys matching a pattern with proper prefix handling"""
        prefix = FastAPICache.get_prefix()
        full_pattern = f"{prefix}:{pattern}" if prefix else pattern

        deleted_count = 0
        try:
            cursor = "0"
            while cursor != 0:
                cursor, keys = await self.redis.scan(
                    cursor=cursor, match=full_pattern, count=1000
                )
                if keys:
                    await self.redis.delete(*keys)
                    deleted_count += len(keys)
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting by pattern: {str(e)}")
            return 0

    async def invalidate_related(
        self, namespace: str, identifier: Union[str, UUID] = None
    ) -> None:
        """
        Invalidate all cache entries related to a specific entity or namespace
        with proper prefix handling and detailed logging
        """
        try:
            logger.info(
                f"Starting cache invalidation for {namespace}:{identifier or 'all'}"
            )

            # Invalidate the collection cache
            collection_pattern = f"{namespace}:collection*"
            col_deleted = await self.delete_by_pattern(collection_pattern)
            logger.debug(
                f"Deleted {col_deleted} collection cache entries for {collection_pattern}"
            )

            # Invalidate specific item cache if ID provided
            if identifier:
                item_pattern = f"{namespace}:item:{identifier}*"
                item_deleted = await self.delete_by_pattern(item_pattern)
                logger.debug(
                    f"Deleted {item_deleted} item cache entries for {item_pattern}"
                )

            # Invalidate any queries related to this namespace
            query_pattern = f"{namespace}:query*"
            query_deleted = await self.delete_by_pattern(query_pattern)
            logger.debug(
                f"Deleted {query_deleted} query cache entries for {query_pattern}"
            )

            logger.info(
                f"Cache invalidation complete for {namespace}:{identifier or 'all'}"
            )

        except Exception as e:
            logger.error(f"Cache invalidation failed: {str(e)}", exc_info=True)
            raise


def _build_collection_cache_key(namespace: str) -> str:
    """Standardized key builder for collections that works with prefix"""
    return f"{namespace}:collection:v2"


def _build_item_cache_key(namespace: str, item_id: Union[str, UUID]) -> str:
    """Standardized key builder for individual items that works with prefix"""
    return f"{namespace}:item:{item_id}"


def _build_query_cache_key(namespace: str, query_params: dict) -> str:
    """Standardized key builder for query results"""
    query_hash = hashlib.md5(
        json.dumps(query_params, sort_keys=True).encode()
    ).hexdigest()
    return f"{namespace}:query:{query_hash}"


def advanced_cache(
    expire: int = 300,
    namespace: Optional[str] = None,
    key_builder: Optional[Callable[..., str]] = None,
    coder: type = HybridCoder,
    ignore_args: Optional[list] = None,
    condition: Optional[Callable[[Any], bool]] = None,
    invalidate_on_update: bool = False,
    tags: Optional[List[str]] = None,
):
    """Cache decorator that properly handles ignored arguments"""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            backend = FastAPICache.get_backend()
            if not backend:
                return await func(*args, **kwargs)

            # Filter out ignored arguments
            filtered_kwargs = {
                k: v
                for k, v in kwargs.items()
                if not ignore_args or k not in ignore_args
            }

            # Build cache key
            cache_key = (
                key_builder(*args, **filtered_kwargs)
                if key_builder
                else _build_cache_key(func, namespace, ignore_args, *args, **kwargs)
            )

            # Try cache lookup if no condition specified
            if condition is None:
                try:
                    cached = await backend.get(cache_key)
                    if cached is not None:
                        logger.debug(f"Cache hit for {cache_key}")
                        return coder.decode(cached)
                except Exception as e:
                    logger.warning(f"Cache read error for {cache_key}: {str(e)}")

            # Execute the function
            result = await func(*args, **kwargs)

            # Store result if condition passes
            if condition is None or condition(result):
                try:
                    await backend.set(cache_key, coder.encode(result), expire=expire)
                    logger.debug(f"Cache set for {cache_key}")
                except Exception as e:
                    logger.error(f"Cache write error for {cache_key}: {str(e)}")

            return result

        return wrapper

    return decorator


def _build_cache_key(
    func: Callable,
    namespace: Optional[str],
    ignore_args: Optional[list],
    *args,
    **kwargs,
) -> str:
    """Build consistent cache key with WSL-specific considerations"""
    sig = inspect.signature(func)
    bound_args = sig.bind(*args, **kwargs)
    bound_args.apply_defaults()

    # Filter ignored arguments
    filtered_args = {
        k: v
        for k, v in bound_args.arguments.items()
        if not ignore_args or k not in ignore_args
    }

    # Create serializable dictionary
    serializable_args = {}
    for k, v in filtered_args.items():
        try:
            if hasattr(v, "dict"):
                serializable_args[k] = v.dict()
            elif hasattr(v, "__module__") and "sqlalchemy" in v.__module__:
                if hasattr(v, "id"):
                    serializable_args[k] = str(v.id)
            else:
                json.dumps(v)  # Test serialization
                serializable_args[k] = v
        except (TypeError, ValueError):
            serializable_args[k] = str(v)

    # Create hash
    args_hash = hashlib.md5(
        json.dumps(serializable_args, sort_keys=True).encode()
    ).hexdigest()

    # Build final key
    namespace_prefix = f"{namespace}:" if namespace else ""
    return f"{namespace_prefix}{func.__module__}:{func.__name__}:{args_hash}"


class CacheKeyInput(BaseModel):
    """Model for cache key input data"""

    email: str
    password: str

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            # Add any custom type encoders if needed
        }


def login_cache_key_builder(
    login_cred: "LoginRequest",
    db: "AsyncSession" = None,
    **kwargs,  # Catches any unexpected arguments (like request)
) -> str:
    """
    Cache key builder that:
    1. Uses only email and password from login credentials
    2. Explicitly ignores the db session
    3. Silently ignores any other arguments (like request)
    """
    try:
        if not login_cred or not login_cred.email:
            raise ValueError("Invalid login credentials")

        # Create cache key based only on credentials
        cache_input = {"email": login_cred.email, "password": login_cred.password}

        args_hash = hashlib.md5(
            json.dumps(cache_input, sort_keys=True).encode()
        ).hexdigest()

        return f"auth:login:{args_hash}"

    except Exception as e:
        logger.error(f"Cache key build failed: {str(e)}")
        return (
            f"auth:login:error_{hashlib.md5(str(datetime.now()).encode()).hexdigest()}"
        )


def cache_only_successful_logins(*args, **kwargs) -> bool:
    """
    Universal cache condition that works with both:
    - Being called with only the result (new style)
    - Being called with all endpoint args (old style)
    """
    # First argument is always the result in FastAPI cache decorator
    result = args[0] if args else kwargs.get("result")

    if not result:
        return False
    if isinstance(result, dict):
        return "access_token" in result and "error" not in result
    if hasattr(result, "dict"):  # For Pydantic models
        result_dict = result.dict()
        return "access_token" in result_dict and "error" not in result_dict
    return False
