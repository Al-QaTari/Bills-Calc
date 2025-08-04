"""
Error Handler for Treasury Bills Calculator
معالج الأخطاء لحاسبة أذون الخزانة

This module provides error handling utilities to improve application stability.
"""

import logging
import functools
import streamlit as st
from typing import Callable, Any


def handle_streamlit_errors(func: Callable) -> Callable:
    """
    Decorator to handle Streamlit-specific errors gracefully.
    معالج للأخطاء الخاصة بـ Streamlit.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error in {func.__name__}: {str(e)}")
            # Don't show error to user for non-critical functions
            return None

    return wrapper


def suppress_websocket_errors():
    """
    Suppress common WebSocket and asyncio errors that don't affect functionality.
    كتم أخطاء WebSocket الشائعة التي لا تؤثر على الوظائف.
    """
    import warnings

    # Suppress WebSocket closed errors
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="streamlit")
    warnings.filterwarnings("ignore", category=UserWarning, module="tornado")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="asyncio")

    # Suppress specific WebSocket errors
    warnings.filterwarnings("ignore", message=".*WebSocketClosedError.*")
    warnings.filterwarnings("ignore", message=".*no running event loop.*")
    warnings.filterwarnings("ignore", message=".*Stream is closed.*")


def safe_streamlit_call(func: Callable, *args, **kwargs) -> Any:
    """
    Safely call Streamlit functions with error handling.
    استدعاء دوال Streamlit بأمان مع معالجة الأخطاء.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.warning(f"Streamlit call failed: {func.__name__} - {str(e)}")
        return None


def log_application_state():
    """
    Log current application state for debugging.
    تسجيل حالة التطبيق الحالية للتشخيص.
    """
    try:
        state_info = {
            "session_state_keys": (
                list(st.session_state.keys()) if hasattr(st, "session_state") else []
            ),
            "page_config": getattr(st, "_config", {}),
        }
        logging.info(f"Application state: {state_info}")
    except Exception as e:
        logging.warning(f"Could not log application state: {str(e)}")


# Initialize error suppression on import
suppress_websocket_errors()
