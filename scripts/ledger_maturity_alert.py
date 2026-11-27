"""تنبيه تليجرام قبل استحقاق أذون المحفظة.

بيشتغل dry-run افتراضيًا (بيطبع بس). الإرسال الفعلي بيحتاج:
  LEDGER_ALERTS_ENABLED=1 + TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID + POSTGRES_URI
بيتشغّل كخطوة داخل scheduled_scrape.yml (continue-on-error)، وبيفضل dry-run لحد ما المتغير LEDGER_ALERTS_ENABLED=1 يتضبط في الريبو.
"""

import os
import sys
from datetime import date

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ledger  # noqa: E402
from timeutil import cairo_now  # noqa: E402


def send(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    return r.ok


def run(today: date, rows, enabled: bool, sender=send, store=None) -> int:
    """
    بيرجع عدد التنبيهات المستحقة، أو سالب عدد اللي فشل.
    مفيش علامة "اتبعت" غير بعد نجاح الإرسال، وفي dry-run مفيش علامة خالص.
    """
    alerts = ledger.due_alerts(rows, today)
    failed = 0
    for a in alerts:
        text = ledger.alert_text(a)
        if not enabled:
            print("[dry-run]", text)
            continue
        if sender(text):
            if store is not None:
                try:
                    store.mark_alerted(a["id"], today)
                except Exception as e:  # noqa: BLE001
                    print(f"sent #{a['no']} but could not mark it: {type(e).__name__}")
        else:
            failed += 1
    if failed:
        print(f"{failed} alert(s) failed to send; will retry next run")
        return -failed
    return len(alerts)


def main() -> int:
    enabled = os.environ.get("LEDGER_ALERTS_ENABLED") == "1"
    try:
        store = ledger.LedgerStore()
        rows = store.list_all()
    except Exception as e:  # noqa: BLE001  (من غير تفاصيل اتصال في اللوج)
        print(f"ledger unavailable: {type(e).__name__}. nothing sent.")
        return 1
    n = run(cairo_now().date(), rows, enabled, store=store)
    if n < 0:
        return 1
    print(f"alerts due: {n}, mode: {'SEND' if enabled else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
