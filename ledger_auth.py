"""
بوابة كلمة المرور لدفتر المحفظة.

- الباسورد بيتقرا من Streamlit Secrets (LEDGER_PASSWORD) أو متغير بيئة بنفس الاسم.
- لو الباسورد مش مضبوط: الدفتر يتقفل بالكامل (مفيش قراءة ولا كتابة).
- مفيش باسورد افتراضي لأن المستودع عام.
"""

import hmac
import os
import threading
import time

import streamlit as st

import constants as C

_AUTH_KEY = "ledger_auth_expiry"
_ATTEMPTS_KEY = "ledger_auth_attempts"
_LOCK_KEY = "ledger_auth_locked_until"

# عدّاد عام لكل الجلسات: لو حد بيفتح جلسات جديدة عشان يهرب من قفل الجلسة الواحدة.
_GLOBAL_FAILS: list = []
_GLOBAL_LOCK = threading.Lock()
_GLOBAL_WINDOW = 600
_GLOBAL_LOCK_SECONDS = 300
_global_locked_until = 0.0


def _globally_locked() -> bool:
    return time.time() < _global_locked_until


def _record_global_fail() -> None:
    global _global_locked_until
    now = time.time()
    with _GLOBAL_LOCK:
        _GLOBAL_FAILS[:] = [t for t in _GLOBAL_FAILS if now - t < _GLOBAL_WINDOW]
        _GLOBAL_FAILS.append(now)
        if len(_GLOBAL_FAILS) >= C.LEDGER_GLOBAL_MAX_FAILS:
            _global_locked_until = now + _GLOBAL_LOCK_SECONDS
            _GLOBAL_FAILS.clear()


def _configured_password() -> str:
    try:
        value = st.secrets.get("LEDGER_PASSWORD", "")
    except Exception:  # noqa: BLE001 (لا يوجد ملف secrets)
        value = ""
    return str(value or os.environ.get("LEDGER_PASSWORD", "") or "")


def is_configured() -> bool:
    return bool(_configured_password())


def is_authenticated() -> bool:
    if not is_configured():
        return False
    return time.time() < float(st.session_state.get(_AUTH_KEY, 0))


def check_password(candidate: str) -> bool:
    expected = _configured_password()
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def logout() -> None:
    st.session_state.pop(_AUTH_KEY, None)
    st.session_state.pop(_ATTEMPTS_KEY, None)


def require_auth(key: str) -> bool:
    """
    بيرجع True لو المستخدم داخل. غير كده بيرسم نموذج الدخول ويرجع False.
    بيجدد مهلة الجلسة مع كل نشاط.
    """
    if not is_configured():
        st.error(
            "🔒 دفتر المحفظة مقفول: كلمة المرور (LEDGER_PASSWORD) غير مضبوطة في Secrets."
        )
        return False

    if is_authenticated():
        st.session_state[_AUTH_KEY] = time.time() + C.LEDGER_SESSION_TIMEOUT_SECONDS
        return True

    locked_until = float(st.session_state.get(_LOCK_KEY, 0))
    if _globally_locked() or time.time() < locked_until:
        st.error("🔒 محاولات كتير غلط. استنى شوية وجرب تاني.")
        return False

    with st.form(f"ledger_login_{key}"):
        pwd = st.text_input(
            "🔑 كلمة مرور الدفتر", type="password", key=f"ledger_pwd_{key}"
        )
        submitted = st.form_submit_button("دخول")
    if submitted:
        if check_password(pwd):
            st.session_state[_AUTH_KEY] = time.time() + C.LEDGER_SESSION_TIMEOUT_SECONDS
            st.session_state[_ATTEMPTS_KEY] = 0
            st.rerun()
        else:
            _record_global_fail()
            attempts = int(st.session_state.get(_ATTEMPTS_KEY, 0)) + 1
            st.session_state[_ATTEMPTS_KEY] = attempts
            if attempts >= C.LEDGER_MAX_LOGIN_ATTEMPTS:
                st.session_state[_LOCK_KEY] = time.time() + 300
                st.session_state[_ATTEMPTS_KEY] = 0
            time.sleep(min(2**attempts, 10))
            st.error("كلمة المرور غلط.")
    return False
