# 01: Walking skeleton: a Message from a fake Modem appears on the web page

**What to build:** The thinnest complete path through SMS Mailroom. A scripted fake Modem delivers one single-Part SMS; SMS Mailroom decodes it, stores it as a Message belonging to a SIM, and the owner sees it on a web page listing Messages newest first. This ticket also sets up the Python project (`uv`, package `mailroom`), the Modem transport seam that every later ticket tests through, the PDU codec, the SQLite store and the test harness. See `../spec.md` for the module boundaries and testing decisions.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] The project installs and its test suite runs with a single `uv` command
- [x] A fake Modem can be scripted in tests to answer AT commands and emit new-message indications, and nothing above the transport seam knows it is fake
- [x] The PDU codec decodes SMS-DELIVER PDUs in UCS2 and GSM 7-bit, including numeric and alphanumeric senders and the network timestamp with its timezone
- [x] A single-Part Message delivered by the fake Modem is stored once against a SIM identified by ICCID
- [x] The web page lists stored Messages newest first, showing SIM, sender, text and time in Taipei time
- [x] Traditional Chinese, Simplified Chinese and mixed Chinese/English text display correctly
- [x] Tests assert on observable outcomes (stored Message, rendered page), not internal calls
