# scripts/fake_telegram_server_test.py
"""
اختبار تنبيهات تليجرام من البداية للنهاية بدون إرسال حقيقي:
- يشغّل "سيرفر تليجرام" وهمي محلي (127.0.0.1) يستقبل طلبات sendMessage.
- يبني قاعدة بيانات مؤقتة فيها عطاءان: 357 تغيّر بنسبة أكبر من الحد.
- يمرر كل الطلبات عبر HTTP حقيقي للسيرفر المحلي ويتحقق من محتوى الرسالة.

التشغيل: python scripts/fake_telegram_server_test.py
"""

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

os.environ["TELEGRAM_BOT_TOKEN"] = "FAKE_TOKEN_LOCAL_TEST"
os.environ["TELEGRAM_CHAT_ID"] = "123456789"
os.environ["ALERTS_ENABLED"] = "true"

import constants as C  # noqa: E402
import update_data  # noqa: E402
from db_manager import SQLiteDBManager  # noqa: E402

received = []


class FakeTelegramHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        received.append({"path": self.path, "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):
        pass


class LocalTelegramSession:
    """يلف طلبات api.telegram.org إلى السيرفر المحلي - كل الباقي HTTP حقيقي."""

    def __init__(self, port):
        import requests

        self._session = requests.Session()
        self._port = port

    def post(self, url, json=None, timeout=None):
        local_url = url.replace(
            "https://api.telegram.org", f"http://127.0.0.1:{self._port}"
        )
        return self._session.post(local_url, json=json, timeout=timeout)


def main():
    server = HTTPServer(("127.0.0.1", 0), FakeTelegramHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"🧪 سيرفر تليجرام الوهمي يعمل على 127.0.0.1:{port}")

    with tempfile.TemporaryDirectory() as tmp:
        db = SQLiteDBManager(db_filename=Path(tmp) / "test.db")
        rows = []
        for tenor, y in [(357, 25.70), (182, 25.0)]:
            rows.append(
                {
                    C.TENOR_COLUMN_NAME: tenor,
                    C.YIELD_COLUMN_NAME: y,
                    C.SESSION_DATE_COLUMN_NAME: "12/11/2026",
                    C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-12"),
                }
            )
        for tenor, y in [(357, 26.165), (182, 25.03)]:
            rows.append(
                {
                    C.TENOR_COLUMN_NAME: tenor,
                    C.YIELD_COLUMN_NAME: y,
                    C.SESSION_DATE_COLUMN_NAME: "19/11/2026",
                    C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-19"),
                }
            )
        db.save_data(pd.DataFrame(rows))
        print("🧪 قاعدة مؤقتة: 357 ارتفع من 25.70 إلى 26.165 (+1.81%)، 182 شبه ثابت")

        update_data.HTTP_SESSION = LocalTelegramSession(port)
        update_data.ALERT_CACHE_FILE = Path(tmp) / "alerts.json"

        update_data._check_and_send_telegram_alerts_blocking(db)

    server.shutdown()

    ok = True
    if len(received) != 1:
        print(f"❌ وصل {len(received)} رسالة بدل رسالة واحدة")
        ok = False
    else:
        msg = received[0]
        if "/botFAKE_TOKEN_LOCAL_TEST/sendMessage" not in msg["path"]:
            print(f"❌ مسار غير متوقع: {msg['path']}")
            ok = False
        if msg["body"].get("chat_id") != "123456789":
            print("❌ chat_id غلط")
            ok = False
        text = msg["body"].get("text", "")
        for needle in ("357", "26.165", "25.700", "📈", "زيادة"):
            if needle not in text:
                print(f"❌ الرسالة ناقصة: {needle!r}")
                ok = False
        print("📨 الرسالة التي استلمها السيرفر الوهمي:")
        print(text)

    print("✅ نجح اختبار تليجرام من البداية للنهاية" if ok else "❌ فشل الاختبار")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
