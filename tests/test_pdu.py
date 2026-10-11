from datetime import datetime, timedelta, timezone

import pytest

from mailroom.pdu import Concatenation, PduError, decode_deliver
from support import build_pdu

# Captured from a China Mobile SIM roaming in Taiwan: one Message in two Parts.
PART_2_OF_2 = "0891683108701305F06408A00180960100086201113285442314050003C40202300230104E2D56FD79FB52A83011"
PART_1_OF_2 = (
    "0891683108701305F06408A0018096010008620111328544238C050003C4020100289A8C8BC15BC678010029003500"
    "300034003100320036FF0C5C0A656C768475286237FF0C60A8768453F778016B6357284E004E2A65B08BBE59074E0A"
    "767B5F554E2D56FD79FB52A80020004100500050FF0C8BE59A8C8BC1780100355206949F51856709654830028BF752"
    "FF6CC4973262168F6C53D14ED64EBAFF0C8C28963288AB9A97"
)


def test_decodes_gsm_7bit_message_with_international_sender():
    delivery = decode_deliver("07911326040000F0040B911346610089F60000208062917314080CC8F71D14969741F977FD07")

    assert delivery.sender == "+31641600986"
    assert delivery.text == "How are you?"
    assert delivery.sent_at.replace(tzinfo=None) == datetime(2002, 8, 26, 19, 37, 41)
    assert delivery.concatenation is None


def test_decodes_ucs2_message_with_mixed_chinese_and_english():
    delivery = decode_deliver(build_pdu("0912345678", "測試 test 123"))

    assert delivery.sender == "0912345678"
    assert delivery.text == "測試 test 123"
    assert delivery.sent_at == datetime(2026, 10, 11, 23, 34, 7, tzinfo=timezone(timedelta(hours=8)))


def test_decodes_alphanumeric_sender():
    assert decode_deliver(build_pdu("Google", "G-123456", encoding="gsm7")).sender == "Google"


def test_decodes_gsm_7bit_text_whose_length_is_a_multiple_of_eight():
    assert decode_deliver(build_pdu("12345", "12345678", encoding="gsm7")).text == "12345678"


def test_decodes_timestamp_west_of_utc():
    sent_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-5)))

    assert decode_deliver(build_pdu("12345", "hi", sent_at=sent_at)).sent_at == sent_at


def test_decodes_captured_parts_of_a_multi_part_message():
    first, second = decode_deliver(PART_1_OF_2), decode_deliver(PART_2_OF_2)

    assert first.sender == second.sender == "10086910"
    assert first.concatenation == Concatenation(reference=0xC4, total=2, sequence=1)
    assert second.concatenation == Concatenation(reference=0xC4, total=2, sequence=2)
    assert first.text + second.text == (
        "(验证密码)504126，尊敬的用户，您的号码正在一个新设备上登录中国移动 APP，"
        "该验证码5分钟内有效。请勿泄露或转发他人，谨防被骗。【中国移动】"
    )
    assert first.sent_at == datetime(2026, 10, 11, 23, 58, 44, tzinfo=timezone(timedelta(hours=8)))


@pytest.mark.parametrize("garbage", ["", "zz", "0791", "07911326040000F0"])
def test_rejects_malformed_pdu(garbage):
    with pytest.raises(PduError):
        decode_deliver(garbage)
