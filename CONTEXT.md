# SMS Mailroom

SMS Mailroom receives SMS on several SIMs through cellular modems attached to one always-on computer, so the owner can read them remotely and have them forwarded, instead of leaving phones at home.

## Language

**SMS Mailroom**:
The software service as a whole. This is the name people read; identifiers, paths and the package keep the short form `mailroom`.
_Avoid_: Hub, 4g-hub, SIM box

**Modem**:
One physical cellular module, identified by its IMEI. It holds at most one SIM at a time and is interchangeable hardware.
_Avoid_: Module, dongle, device, stick

**SIM**:
One SIM card, identified by its ICCID and carrying a phone number and an owner-given label. It is the thing a Message belongs to.
_Avoid_: Line, number, card, account

**Message**:
One SMS received by a SIM, with its sender, text and the time the network stamped it. A Message stays with its SIM even if the SIM moves to another Modem.
_Avoid_: Text, SMS record, notification

**Part**:
One segment of a Message that the network delivered separately because the text was too long for a single SMS. A Message is incomplete while any of its Parts is missing.
_Avoid_: Segment, fragment, chunk

**Archive**:
Where the owner keeps a Message worth holding on to, out of the inbox. An archived Message is still stored and searchable and can be moved back; archiving is not deleting.
_Avoid_: Hide, dismiss, folder, read/unread

**Forwarding**:
Delivering a copy of a Message to the owner's Telegram chat. It is switched on or off per SIM.
_Avoid_: Relay, push, notification

**Alert**:
A notice SMS Mailroom itself sends to the owner's Telegram chat when a Modem or SIM stops working or recovers. It is not a Message and is never subject to Forwarding settings.
_Avoid_: Warning, notification, health message

**USB hub**:
The physical hub the Modems plug into. Always written in full; never shortened to "hub".
_Avoid_: Hub
