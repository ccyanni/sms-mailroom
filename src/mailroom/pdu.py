"""Decode SMS-DELIVER PDUs (3GPP TS 23.040) as returned by AT+CMGL / AT+CMGR in PDU mode."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_GSM_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXTENSION = {
    0x0A: "\f", 0x14: "^", 0x28: "{", 0x29: "}", 0x2F: "\\",
    0x3C: "[", 0x3D: "~", 0x3E: "]", 0x40: "|", 0x65: "€",
}
_ESCAPE = 0x1B


class PduError(ValueError):
    """The PDU is malformed or of a kind Mailroom does not handle."""


@dataclass(frozen=True)
class Concatenation:
    """Position of a Part within a multi-Part Message."""

    reference: int
    total: int
    sequence: int


@dataclass(frozen=True)
class Delivery:
    """One decoded SMS-DELIVER: a whole Message, or a single Part of one."""

    sender: str
    sent_at: datetime
    text: str
    concatenation: Concatenation | None = None


def decode_deliver(pdu_hex: str) -> Delivery:
    try:
        raw = bytes.fromhex(pdu_hex.strip())
        return _decode(raw)
    except PduError:
        raise
    except (ValueError, IndexError) as exc:
        raise PduError(f"malformed PDU: {exc}") from exc


def _decode(raw: bytes) -> Delivery:
    pos = 1 + raw[0]  # skip the service centre address
    first_octet = raw[pos]
    pos += 1
    if first_octet & 0x03 != 0x00:
        raise PduError("not an SMS-DELIVER")
    has_header = bool(first_octet & 0x40)

    digits = raw[pos]
    type_of_address = raw[pos + 1]
    pos += 2
    address_octets = (digits + 1) // 2
    sender = _decode_address(raw[pos:pos + address_octets], digits, type_of_address)
    pos += address_octets

    dcs = raw[pos + 1]  # raw[pos] is the protocol identifier
    pos += 2
    sent_at = _decode_timestamp(raw[pos:pos + 7])
    pos += 7
    length = raw[pos]
    data = raw[pos + 1:]

    header = b""
    if has_header:
        header = data[1:1 + data[0]]
    header_octets = len(header) + 1 if has_header else 0

    alphabet = _alphabet(dcs)
    if alphabet == "gsm7":
        septets = _unpack_septets(data, length)
        skip = -(-header_octets * 8 // 7)
        text = _gsm_to_text(septets[skip:])
    elif alphabet == "ucs2":
        text = data[header_octets:length].decode("utf-16-be", errors="replace")
    else:
        text = data[header_octets:length].decode("latin-1")

    return Delivery(sender, sent_at, text, _concatenation(header))


def _alphabet(dcs: int) -> str:
    group = dcs >> 4
    if group <= 0x7:
        code = (dcs >> 2) & 0x03
    elif group == 0xE:
        code = 2
    elif group == 0xF:
        code = (dcs >> 2) & 0x01
    else:
        code = 0
    return {0: "gsm7", 1: "data", 2: "ucs2"}.get(code, "gsm7")


def _decode_address(octets: bytes, digits: int, type_of_address: int) -> str:
    if type_of_address & 0x70 == 0x50:  # alphanumeric
        septets = _unpack_septets(octets, digits * 4 // 7)
        # Seven characters fill seven octets with seven bits to spare, which read as an eighth, empty septet.
        if digits * 4 % 7 == 0 and septets and septets[-1] == 0:
            septets.pop()
        return _gsm_to_text(septets)
    number = "".join(f"{o & 0x0F:x}{o >> 4:x}" for o in octets)[:digits]
    number = number.replace("a", "*").replace("b", "#")
    return ("+" if type_of_address & 0x70 == 0x10 else "") + number


def _decode_timestamp(octets: bytes) -> datetime:
    year, month, day, hour, minute, second = (
        (o & 0x0F) * 10 + (o >> 4) for o in octets[:6]
    )
    zone = octets[6]
    quarters = (zone & 0x07) * 10 + (zone >> 4)
    offset = timedelta(minutes=15 * quarters)
    if zone & 0x08:
        offset = -offset
    return datetime(2000 + year, month, day, hour, minute, second, tzinfo=timezone(offset))


def _unpack_septets(octets: bytes, count: int) -> list[int]:
    bits = int.from_bytes(octets, "little")
    return [(bits >> (7 * i)) & 0x7F for i in range(count)]


def _gsm_to_text(septets: list[int]) -> str:
    out = []
    escaped = False
    for septet in septets:
        if escaped:
            out.append(_GSM_EXTENSION.get(septet, _GSM_BASIC[septet]))
            escaped = False
        elif septet == _ESCAPE:
            escaped = True
        else:
            out.append(_GSM_BASIC[septet])
    return "".join(out)


def _concatenation(header: bytes) -> Concatenation | None:
    pos = 0
    while pos + 2 <= len(header):
        element, size = header[pos], header[pos + 1]
        body = header[pos + 2:pos + 2 + size]
        if element == 0x00 and size == 3:
            return Concatenation(body[0], body[1], body[2])
        if element == 0x08 and size == 4:
            return Concatenation(int.from_bytes(body[:2], "big"), body[2], body[3])
        pos += 2 + size
    return None
