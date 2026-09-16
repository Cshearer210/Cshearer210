"""SMS compliance for first-party marketing texts. The rules are stricter than email.

The one difference that matters, and the one that gets small businesses sued: you
may cold-email under CAN-SPAM without prior consent, but you may NOT cold-text.
Marketing SMS requires prior express written consent from each recipient, captured
before the first message. So this module is built around a consent ledger: a text
goes out only to a recipient with a consent record on file, and a recipient with no
record is never messaged -- not "probably opted in", not messaged.

This is the piece your customers most need built for them and most often get wrong.
Handing a business a texting feature without this is handing them a lawsuit.

Scope and limits, stated plainly:
- Federal TCPA plus CTIA messaging guidelines. State rules and carrier 10DLC
  registration (A2P brand/campaign approval) are operational requirements this does
  not enforce; you register the brand with the carriers separately.
- Consent must be genuine. This module records and checks consent; it cannot create
  it. A ledger entry you fabricate is a ledger entry you will answer for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Optional, Protocol, Sequence
from zoneinfo import ZoneInfo

from .schema import Check

# CTIA / common-practice quiet hours, in the recipient's local time.
QUIET_START = time(8, 0)
QUIET_END = time(21, 0)

# Opt-out keywords carriers require you to honor. STOP is mandatory.
OPT_OUT_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
OPT_IN_KEYWORDS = {"start", "unstop", "yes"}


@dataclass
class SmsConsent:
    phone: str
    consented_at: datetime
    consent_language: str
    source: str                       # where the opt-in happened
    double_opt_in_confirmed: bool = False


class ConsentLedger:
    """Record of who agreed to be texted, when, and to what.

    is_allowed() is the gate every send passes through. Opt-out is immediate and
    wins over any prior consent.
    """

    def __init__(self) -> None:
        self._consent: dict[str, SmsConsent] = {}
        self._opted_out: dict[str, datetime] = {}

    def record_consent(self, consent: SmsConsent) -> None:
        key = _norm(consent.phone)
        self._consent[key] = consent
        # A fresh opt-in clears a prior opt-out (the consumer changed their mind).
        self._opted_out.pop(key, None)

    def opt_out(self, phone: str, when: Optional[datetime] = None) -> None:
        self._opted_out[_norm(phone)] = when or datetime.now(timezone.utc)

    def is_opted_out(self, phone: str) -> bool:
        return _norm(phone) in self._opted_out

    def has_consent(self, phone: str) -> bool:
        return _norm(phone) in self._consent

    def status(self, phone: str) -> Check:
        key = _norm(phone)
        if key in self._opted_out:
            return Check.BLOCK
        if key in self._consent:
            return Check.PASS
        # No record either way. Not consent, not a proven opt-out. Never a pass.
        return Check.UNKNOWN


def _norm(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")[-10:]


@dataclass
class SmsMessage:
    business_name: str
    body: str
    includes_opt_out_instructions: bool = False

    def rendered(self) -> str:
        """The body a recipient sees. Opt-out language is appended if not already present."""
        text = self.body.strip()
        if not self.includes_opt_out_instructions and "stop" not in text.lower():
            text = f"{text}\nReply STOP to opt out."
        if self.business_name and self.business_name.lower() not in text.lower():
            text = f"{self.business_name}: {text}"
        return text


@dataclass
class MessageCheck:
    name: str
    status: Check
    reason: str

    @property
    def is_pass(self) -> bool:
        return self.status is Check.PASS


def validate_message(msg: SmsMessage) -> list[MessageCheck]:
    checks: list[MessageCheck] = []
    if msg.business_name.strip():
        checks.append(MessageCheck("sender_id", Check.PASS, "business is identified"))
    else:
        checks.append(MessageCheck("sender_id", Check.BLOCK, "message does not identify the business"))

    rendered = msg.rendered().lower()
    if any(k in rendered for k in ("stop", "opt out", "opt-out", "unsubscribe")):
        checks.append(MessageCheck("opt_out_notice", Check.PASS, "opt-out instructions present"))
    else:
        checks.append(MessageCheck("opt_out_notice", Check.BLOCK, "no opt-out instructions in the message"))

    if not msg.body.strip():
        checks.append(MessageCheck("body", Check.BLOCK, "empty message body"))
    else:
        checks.append(MessageCheck("body", Check.PASS, "message has content"))
    return checks


def in_quiet_hours(now: datetime, tz: Optional[ZoneInfo]) -> Optional[bool]:
    """True if now is inside quiet hours locally. None if timezone is unknown.

    None -> UNKNOWN at the call site, which holds the send. Texting someone at 3am
    because you could not resolve their timezone is a violation, not an edge case.
    """
    if tz is None:
        return None
    local = now.astimezone(tz).time()
    return not (QUIET_START <= local < QUIET_END)


def is_opt_out_reply(text: str) -> bool:
    return _first_word(text) in OPT_OUT_KEYWORDS


def is_opt_in_reply(text: str) -> bool:
    return _first_word(text) in OPT_IN_KEYWORDS


def _first_word(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").strip().lower().split(" ")[0]) if text else ""


class SmsSender(Protocol):
    def send(self, to_phone: str, text: str) -> None: ...


@dataclass
class DryRunSmsSender:
    sent: list[tuple[str, str]] = field(default_factory=list)

    def send(self, to_phone: str, text: str) -> None:
        self.sent.append((to_phone, text))


@dataclass
class SmsSendResult:
    attempted: int = 0
    sent: int = 0
    no_consent: int = 0
    opted_out: int = 0
    quiet_hours: int = 0
    timezone_unknown: int = 0
    blocked_message: Optional[str] = None

    def summary(self) -> str:
        if self.blocked_message:
            return f"NOT SENT: message failed validation -> {self.blocked_message}"
        return (
            f"{self.attempted} recipients: {self.sent} sent, {self.no_consent} no-consent, "
            f"{self.opted_out} opted-out, {self.quiet_hours} quiet-hours, "
            f"{self.timezone_unknown} tz-unknown"
        )


@dataclass
class SmsCampaign:
    sender: SmsSender
    ledger: ConsentLedger

    def send(
        self,
        msg: SmsMessage,
        recipients: Sequence[tuple[str, Optional[ZoneInfo]]],
        now: Optional[datetime] = None,
    ) -> SmsSendResult:
        """recipients: (phone, timezone). Timezone None holds that recipient."""
        now = now or datetime.now(timezone.utc)
        result = SmsSendResult()

        problems = [c for c in validate_message(msg) if not c.is_pass]
        if problems:
            result.blocked_message = "; ".join(f"{c.name} ({c.reason})" for c in problems)
            return result

        text = msg.rendered()
        for phone, tz in recipients:
            result.attempted += 1
            consent = self.ledger.status(phone)
            if consent is Check.BLOCK:
                result.opted_out += 1
                continue
            if consent is not Check.PASS:
                result.no_consent += 1  # UNKNOWN: no consent record -> never send
                continue
            quiet = in_quiet_hours(now, tz)
            if quiet is None:
                result.timezone_unknown += 1
                continue
            if quiet:
                result.quiet_hours += 1
                continue
            self.sender.send(phone, text)
            result.sent += 1
        return result
