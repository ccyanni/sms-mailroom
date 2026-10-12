import pytest

from mailroom.at import ATChannel
from mailroom.transport import ATError


class Wire:
    """A scripted byte stream: each read returns the next queued chunk."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = list(chunks)
        self.written: list[bytes] = []

    def read(self, timeout: float) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data: bytes) -> None:
        self.written.append(data)


def channel(*chunks: bytes) -> tuple[ATChannel, Wire]:
    wire = Wire(*chunks)
    return ATChannel(wire.read, wire.write), wire


def test_command_returns_information_lines_without_the_final_ok():
    at, wire = channel(b"\r\n+ICCID: 8988600000\r\n\r\nOK\r\n")

    assert at.command("AT+CICCID") == ["+ICCID: 8988600000"]
    assert wire.written == [b"AT+CICCID\r"]


def test_command_ignores_its_own_echo():
    at, _ = channel(b"AT+CSQ\r\r\n+CSQ: 28,99\r\n\r\nOK\r\n")

    assert at.command("AT+CSQ") == ["+CSQ: 28,99"]


def test_response_split_across_reads_is_reassembled():
    at, _ = channel(b"\r\n+CMGL: 1,0,,40\r\n0791", b"8896\r\n\r\nO", b"K\r\n")

    assert at.command("AT+CMGL=4") == ["+CMGL: 1,0,,40", "07918896"]


@pytest.mark.parametrize("failure", [b"ERROR", b"+CME ERROR: SIM not inserted", b"+CMS ERROR: unknown error"])
def test_error_response_raises(failure):
    at, _ = channel(b"\r\n" + failure + b"\r\n")

    with pytest.raises(ATError, match="AT\\+CPIN\\?"):
        at.command("AT+CPIN?")


def test_no_response_raises():
    at, _ = channel()

    with pytest.raises(ATError, match="no response"):
        at.command("AT", timeout=0.05)


def test_indication_arriving_inside_a_response_is_kept_for_later():
    at, _ = channel(b'\r\n+CMGL: 1,0,,2\r\nABCD\r\n\r\n+CMTI: "SM",2\r\n\r\nOK\r\n')

    assert at.command("AT+CMGL=4") == ["+CMGL: 1,0,,2", "ABCD"]
    assert at.wait_indication(0) == '+CMTI: "SM",2'
    assert at.wait_indication(0) is None


def test_answer_to_a_query_is_not_mistaken_for_an_indication():
    at, _ = channel(b"\r\n+CEREG: 0,5\r\n\r\nOK\r\n")

    assert at.command("AT+CEREG?") == ["+CEREG: 0,5"]


def test_indications_between_commands_are_returned_in_order():
    at, _ = channel(b'\r\n+CMTI: "SM",1\r\n\r\n+CGEV: ME PDN ACT 1\r\n')

    assert at.wait_indication(0) == '+CMTI: "SM",1'
    assert at.wait_indication(0) == "+CGEV: ME PDN ACT 1"
