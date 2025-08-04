"""
Enhanced caching mechanism for the Treasury Bills Calculator application.
آلية تخزين مؤقت محسنة لتطبيق حاسبة أذون الخزانة.
"""

import json
import redis
import logging
import pandas as pd
from typing import Optional, TypeVar, Generic
from io import StringIO
import constants as C

T = TypeVar("T")

logger = logging.getLogger(__name__)


class EnhancedCache(Generic[T]):
    """
    Enhanced caching mechanism with variable TTL support and tiering.
    آلية تخزين مؤقت محسنة مع دعم TTL متغير والتدرج.
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis],
        key_prefix: str,
        base_ttl_seconds: int = 3600,
        max_ttl_seconds: int = 86400,  # One day
    ):
        """
        Initialize the enhanced cache.

        Args:
            redis_client: Redis client instance
            key_prefix: Prefix for all cache keys
            base_ttl_seconds: Base TTL in seconds
            max_ttl_seconds: Maximum TTL in seconds
        """
        self.redis_client = redis_client
        self.key_prefix = key_prefix
        self.base_ttl_seconds = base_ttl_seconds
        self.max_ttl_seconds = max_ttl_seconds

        # Set TTL values based on data type
        self._ttl_mapping = {
            "df_latest": base_ttl_seconds * 2,  # Latest data stays longer
            "df_historical": base_ttl_seconds * 6,  # Historical data stays even longer
            "default": base_ttl_seconds,
        }

    def _get_full_key(self, key: str) -> str:
        """
        Get the full cache key with prefix.

        Args:
            key: Base key

        Returns:
            Full key with prefix
        """
        return f"{self.key_prefix}:{key}"

    def _get_ttl_for_key(self, key: str) -> int:
        """
        Determine appropriate TTL for the key.

        Args:
            key: Cache key

        Returns:
            TTL in seconds
        """
        for pattern, ttl in self._ttl_mapping.items():
            if pattern in key:
                return ttl
        return self._ttl_mapping["default"]

    def get(self, key: str) -> Optional[T]:
        """
        Retrieve a value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if not self.redis_client:
            return None

        try:
            full_key = self._get_full_key(key)
            cached_data = self.redis_client.get(full_key)

            if cached_data is None:
                return None

            # Handle different data types
            if "df_" in key:
                # Retrieve DataFrame
                df = pd.read_json(StringIO(cached_data.decode("utf-8")), lines=True)

                # Handle date column
                if C.DATE_COLUMN_NAME in df.columns:
                    df[C.DATE_COLUMN_NAME] = pd.to_datetime(
                        df[C.DATE_COLUMN_NAME], errors="coerce", utc=True
                    )

                return df  # type: ignore
            else:
                # For general objects, use JSON
                return json.loads(cached_data.decode("utf-8"))  # type: ignore

        except redis.exceptions.RedisError as e:
            logger.error(f"خطأ في قراءة التخزين المؤقت: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(
                f"خطأ عام في استرجاع البيانات من التخزين المؤقت: {e}", exc_info=True
            )
            return None

    def set(self, key: str, value: T, ttl_seconds: Optional[int] = None) -> bool:
        """
        Store a value in cache.

        Args:
            key: Cache key
            value: Value to store
            ttl_seconds: TTL in seconds (optional)

        Returns:
            True if successful, False otherwise
        """
        if not self.redis_client:
            return False

        try:
            full_key = self._get_full_key(key)

            # Determine appropriate TTL
            if ttl_seconds is None:
                ttl_seconds = self._get_ttl_for_key(key)

            # Handle different data types
            if isinstance(value, pd.DataFrame):
                # Store DataFrame
                self.redis_client.setex(
                    full_key,
                    ttl_seconds,
                    value.to_json(orient="records", lines=True),
                )
            else:
                # Store general objects as JSON
                self.redis_client.setex(
                    full_key, ttl_seconds, json.dumps(value, ensure_ascii=False)
                )

            return True

        except redis.exceptions.RedisError as e:
            logger.error(f"خطأ في كتابة التخزين المؤقت: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(
                f"خطأ عام في تخزين البيانات في التخزين المؤقت: {e}", exc_info=True
            )
            return False

    def invalidate(self, key: str) -> bool:
        """
        Invalidate a specific cache key.

        Args:
            key: Cache key to invalidate

        Returns:
            True if successful, False otherwise
        """
        if not self.redis_client:
            return False

        try:
            full_key = self._get_full_key(key)
            return bool(self.redis_client.delete(full_key))
        except redis.exceptions.RedisError as e:
            logger.error(f"خطأ في حذف مفتاح التخزين المؤقت: {e}", exc_info=True)
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern.

        Args:
            pattern: Pattern to match keys

        Returns:
            Number of keys invalidated
        """
        if not self.redis_client:
            return 0

        try:
            full_pattern = self._get_full_key(pattern)
            keys = self.redis_client.keys(full_pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except redis.exceptions.RedisError as e:
            logger.error(f"خطأ في حذف مفاتيح التخزين المؤقت: {e}", exc_info=True)
            return 0

    def exists(self, key: str) -> bool:
        """
        Check if a key exists in cache.

        Args:
            key: Cache key to check

        Returns:
            True if key exists, False otherwise
        """
        if not self.redis_client:
            return False

        try:
            full_key = self._get_full_key(key)
            return bool(self.redis_client.exists(full_key))
        except redis.exceptions.RedisError as e:
            logger.error(
                f"خطأ في التحقق من وجود مفتاح التخزين المؤقت: {e}", exc_info=True
            )
            return False
