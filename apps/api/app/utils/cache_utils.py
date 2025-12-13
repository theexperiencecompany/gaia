"""
Cache utilities for key generation and hashing.
"""

import hashlib


def create_cache_key_hash(func_name: str, *args, **kwargs) -> str:
    """
    Simple hash of all function data - no complexity, just works.
    Uses full hash for collision safety.
    """
    try:
        # Just stringify everything and hash it
        data_str = f"{func_name}:{str(args)}:{str(sorted(kwargs.items()))}"
        # Use full hash for better uniqueness, Redis can handle it
        hash_key = hashlib.sha256(data_str.encode()).hexdigest()
        return f"{func_name}:{hash_key}"
    except Exception:
        # Super simple fallback
        return f"{func_name}:{hash(str(args) + str(kwargs))}"
