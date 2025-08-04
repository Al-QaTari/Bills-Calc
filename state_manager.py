"""
State management utilities for the Treasury Bills Calculator application.
أدوات إدارة الحالة لتطبيق حاسبة أذون الخزانة.
"""

import streamlit as st
from typing import Any, Optional, TypeVar, Generic

T = TypeVar("T")


class StateManager:
    """
    Central state manager for the application.
    مدير حالة مركزي للتطبيق.
    """

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """
        Retrieve a value from the state.

        Args:
            key: The key to retrieve
            default: Default value if key doesn't exist

        Returns:
            The value associated with the key
        """
        return st.session_state.get(key, default)

    @staticmethod
    def set(key: str, value: Any) -> None:
        """
        Set a value in the state.

        Args:
            key: The key to set
            value: The value to store
        """
        st.session_state[key] = value

    @staticmethod
    def has(key: str) -> bool:
        """
        Check if a key exists in the state.

        Args:
            key: The key to check

        Returns:
            True if key exists, False otherwise
        """
        return key in st.session_state

    @staticmethod
    def remove(key: str) -> None:
        """
        Remove a key from the state.

        Args:
            key: The key to remove
        """
        if key in st.session_state:
            del st.session_state[key]

    @staticmethod
    def clear() -> None:
        """Clear all state."""
        for key in list(st.session_state.keys()):
            del st.session_state[key]


class Repository(Generic[T]):
    """
    Generic data repository using the state manager.
    خزان بيانات نموذجي باستخدام مدير الحالة.
    """

    def __init__(self, key_prefix: str):
        """
        Initialize repository with a key prefix.

        Args:
            key_prefix: Prefix for all keys in this repository
        """
        self.key_prefix = key_prefix

    def _get_full_key(self, key: str) -> str:
        """
        Get the full key with prefix.

        Args:
            key: The base key

        Returns:
            Full key with prefix
        """
        return f"{self.key_prefix}_{key}"

    def save(self, key: str, item: T) -> None:
        """
        Save an item to the repository.

        Args:
            key: The key to save under
            item: The item to save
        """
        StateManager.set(self._get_full_key(key), item)

    def get(self, key: str) -> Optional[T]:
        """
        Retrieve an item from the repository.

        Args:
            key: The key to retrieve

        Returns:
            The item or None if not found
        """
        return StateManager.get(self._get_full_key(key))

    def exists(self, key: str) -> bool:
        """
        Check if an item exists in the repository.

        Args:
            key: The key to check

        Returns:
            True if item exists, False otherwise
        """
        return StateManager.has(self._get_full_key(key))

    def remove(self, key: str) -> None:
        """
        Remove an item from the repository.

        Args:
            key: The key to remove
        """
        StateManager.remove(self._get_full_key(key))
