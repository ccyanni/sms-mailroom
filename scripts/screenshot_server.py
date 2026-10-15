"""Serve SMS Mailroom with invented Modems and Messages, for the README screenshots.

Usage: uv run python scripts/screenshot_server.py zh|en [port]

The language picks the sample Messages and the Telegram texts. Nothing touches
real Modems, Telegram or the real database. scripts/screenshots.sh drives it.
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from support import FakeModem, FakeTransport, build_pdu  # noqa: E402

from mailroom.telegram import TelegramSettings  # noqa: E402
from mailroom.web import create_app  # noqa: E402

LANG = sys.argv[1]
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8799


class Allowed:  # stands in for a configured Cloudflare Access
    def allows(self, token):
        return True


home = FakeModem(iccid="89886000000000000001", number="+886900000001", imei="860000000000001")
roaming = FakeModem(iccid="89860000000000000002", number="+8613800000000", imei="860000000000002")
third = FakeModem(iccid="89886010000000000003", number="+886900000003", imei="860000000000003")
home.operator, home.signal = "TW Mobile", 28
roaming.operator, roaming.registration, roaming.signal = "Far EasTone", 5, 21
third.operator, third.signal = "Far EasTone", 24

SAMPLES = {  # Modem, sender, minutes ago, text; the last one is archived
    "zh": [
        (home, "0911000111", 3, "【範例銀行】您的網路銀行登入驗證碼為 482913，請於 5 分鐘內輸入。請勿將驗證碼提供給他人。"),
        (roaming, "10086", 48, "(验证密码)662022，尊敬的用户，您正在登录示例 APP，该验证码5分钟内有效。请勿泄露或转发他人。"),
        (home, "Google", 135, "G-731840 is your Google verification code."),
        (third, "0922000222", 20, "您的包裹已送達一樓管理室，取件資訊請見 https://parcel.example.com/t/8841"),
        (roaming, "95500", 1500, "您尾号 4471 的账户于 10 月 14 日完成一笔转账，金额 268.00 元。"),
        (home, "TWM", 4300, "本期電信帳單金額 499 元，繳費期限 10/25。"),
    ],
    "en": [
        (home, "ExampleBank", 3, "Your Example Bank sign-in code is 482913. It expires in 5 minutes. Never share this code with anyone."),
        (roaming, "10086", 48, "Verification code 662022 for signing in to Example App. Valid for 5 minutes. Do not share it."),
        (home, "Google", 135, "G-731840 is your Google verification code."),
        (third, "Courier", 20, "Your parcel is waiting at the front desk. Details: https://parcel.example.com/t/8841"),
        (roaming, "95500", 1500, "A transfer of 268.00 from your account ending 4471 was completed on 14 October."),
        (home, "Carrier", 4300, "Your bill for this period is 499. Please pay by 25 October."),
    ],
}
now = datetime.now(timezone(timedelta(hours=8)))
for modem, sender, minutes, text in SAMPLES[LANG]:
    modem.deliver(build_pdu(sender, text, sent_at=now - timedelta(minutes=minutes), encoding="ucs2"))

scratch = Path(tempfile.mkdtemp())
app = create_app(
    FakeTransport(home, roaming, third),
    scratch / "screenshots.db",
    poll_interval=0.5,
    scan_interval=0.2,
    telegram=TelegramSettings("0:fake", "0"),
    http_post=lambda url, payload: None,
    forward_interval=0.2,
    network_service_enabled=lambda: False,
    access=Allowed(),
    language=LANG,
    backup_dir=scratch / "backups",
)
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")
