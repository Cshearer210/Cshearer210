"""CAN-SPAM compliance for cold email, the one outreach path that needs no prior consent.

Cold commercial email to US recipients is legal under CAN-SPAM without prior
consent, provided the message carries the required disclosures and every opt-out
is honored. That "provided" is the whole job of this module.

The design mirrors the call-side gate. A message is sendable only if every check
passes, and a recipient is mailable only if they are not suppressed. A check that
cannot run holds the send rather than allowing it, because a message you could not
verify as compliant is a $53,088-per-email liability, not a maybe.

Two honest limits, stated up front rather than buried:

- This validates federal CAN-SPAM. Several states impose stricter rules, and
  insurance marketing carries its own state-by-state content rules on top. Neither
  is modeled here. Confirm both with counsel before sending at volume.
- Legal and effective are different. Cold email to purchased addresses has poor
  deliverability and can harm a sending domain's reputation. Compliance is the
  floor, not the strategy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Protocol, Sequence

from .schema import Check

# Per-violation civil penalty, adjusted for inflation. One number, per email.
CAN_SPAM_MAX_PENALTY_USD = 53_088

# CAN-SPAM requires opt-outs be honored within 10 business days. We do not model
# federal holidays: leaving them out makes the deadline fall earlier, which is the
# conservative direction. A real calendar would only ever give you more time.
OPTOUT_HONOR_BUSINESS_DAYS = 10

# Subject-line phrasing that misrepresents a cold marketing email as something the
# recipient already has a relationship with. Deceptive subject lines are a
# standalone CAN-SPAM violation, independent of the body.
DECEPTIVE_SUBJECT_PATTERNS = [
    r"\bre:\s",           # fake reply
    r"\bfwd:\s",          # fake forward
    r"\byour (order|account|policy|claim|payment)\b",
    r"\bpayment (due|received|failed)\b",
    r"\baction required\b",
    r"\bfinal notice\b",
    r"\bwinner\b",
    r"\bfree\b.*\b(gift|money|cash)\b",
]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _looks_like_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value.strip()))


def business_days_between(start: datetime, end: datetime) -> int:
    """Count business days from start to end, excluding weekends.

    Holidays are intentionally not excluded; see the module docstring. Same-day and
    negative spans return 0.
    """
    if end <= start:
        return 0
    days = 0
    cursor = start.date()
    last = end.date()
    while cursor < last:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:  # Mon-Fri
            days += 1
    return days


@dataclass
class EmailMessage:
    """One commercial email, with the fields CAN-SPAM makes mandatory.

    physical_postal_address is required and must be a real address (a street
    address, a PO box registered with USPS, or a registered commercial mailbox).
    We can validate that it is present and non-trivial; we cannot validate that it
    is genuine, and the docstring on check_physical_address says so.
    """

    from_name: str
    from_email: str
    subject: str
    body: str
    physical_postal_address: str
    unsubscribe_url: Optional[str] = None
    unsubscribe_email: Optional[str] = None
    identifies_as_ad: bool = False


@dataclass
class MessageCheck:
    name: str
    status: Check
    reason: str

    @property
    def is_pass(self) -> bool:
        return self.status is Check.PASS


@dataclass
class MessageValidation:
    checks: list[MessageCheck] = field(default_factory=list)

    @property
    def sendable(self) -> bool:
        return bool(self.checks) and all(c.is_pass for c in self.checks)

    @property
    def problems(self) -> list[MessageCheck]:
        return [c for c in self.checks if not c.is_pass]

    def summary(self) -> str:
        if self.sendable:
            return "SENDABLE"
        return "NOT SENDABLE: " + "; ".join(f"{c.name} ({c.reason})" for c in self.problems)


def check_accurate_from(msg: EmailMessage) -> MessageCheck:
    if not msg.from_name.strip():
        return MessageCheck("from_line", Check.BLOCK, "no from-name; header must identify the sender")
    if not _looks_like_email(msg.from_email):
        return MessageCheck("from_line", Check.BLOCK, f"from-email {msg.from_email!r} is not a valid address")
    return MessageCheck("from_line", Check.PASS, "from line identifies the sender")


def check_subject_not_deceptive(msg: EmailMessage) -> MessageCheck:
    if not msg.subject.strip():
        return MessageCheck("subject", Check.BLOCK, "empty subject line")
    lowered = msg.subject.lower()
    for pat in DECEPTIVE_SUBJECT_PATTERNS:
        if re.search(pat, lowered):
            return MessageCheck(
                "subject", Check.BLOCK,
                f"subject matches a deceptive pattern ({pat!r}); it misrepresents the message",
            )
    return MessageCheck("subject", Check.PASS, "subject is not facially deceptive")


def check_identifies_as_advertisement(msg: EmailMessage) -> MessageCheck:
    """CAN-SPAM requires a clear disclosure that the message is an advertisement.

    Accepted either as the explicit flag or as recognizable ad language in the body.
    """
    if msg.identifies_as_ad:
        return MessageCheck("ad_disclosure", Check.PASS, "message flagged as an advertisement")
    body = msg.body.lower()
    if any(phrase in body for phrase in ("advertisement", "this is an ad", "promotional", "paid advertisement")):
        return MessageCheck("ad_disclosure", Check.PASS, "body discloses advertisement status")
    return MessageCheck(
        "ad_disclosure", Check.BLOCK,
        "no clear disclosure that this is an advertisement",
    )


def check_physical_address(msg: EmailMessage) -> MessageCheck:
    """A valid physical postal address is mandatory in every commercial email.

    We can confirm one is present and plausibly complete. We cannot confirm it is
    genuine or USPS-registered, so a present-but-fake address will pass this check
    and still violate the Act. That gap is the sender's to close.
    """
    addr = msg.physical_postal_address.strip()
    if not addr:
        return MessageCheck("physical_address", Check.BLOCK, "no physical postal address in the message")
    has_digit = any(ch.isdigit() for ch in addr)
    long_enough = len(addr) >= 12
    if not (has_digit and long_enough):
        return MessageCheck(
            "physical_address", Check.UNKNOWN,
            f"address {addr!r} does not look complete (needs a number and a full line); verify before sending",
        )
    return MessageCheck("physical_address", Check.PASS, "physical postal address present")


def check_optout_mechanism(msg: EmailMessage) -> MessageCheck:
    """A working opt-out must be present. It must stay live at least 30 days."""
    if msg.unsubscribe_url and _looks_like_url(msg.unsubscribe_url):
        return MessageCheck("optout", Check.PASS, "unsubscribe URL present")
    if msg.unsubscribe_email and _looks_like_email(msg.unsubscribe_email):
        return MessageCheck("optout", Check.PASS, "unsubscribe reply address present")
    return MessageCheck(
        "optout", Check.BLOCK,
        "no working opt-out mechanism (need an unsubscribe URL or a monitored reply address)",
    )


def _looks_like_url(value: str) -> bool:
    return bool(re.match(r"^https?://[^\s]+\.[^\s]+", value.strip()))


def validate_message(msg: EmailMessage) -> MessageValidation:
    return MessageValidation(checks=[
        check_accurate_from(msg),
        check_subject_not_deceptive(msg),
        check_identifies_as_advertisement(msg),
        check_physical_address(msg),
        check_optout_mechanism(msg),
    ])


@dataclass
class OptOut:
    email: str
    requested_at: datetime


@dataclass
class SuppressionList:
    """Opt-outs, honored immediately.

    The 10-business-day rule is the legal maximum grace, not a target. This
    suppresses on receipt, and offers an audit method to prove no opt-out is being
    honored slower than the law allows -- which, with immediate suppression, should
    always be empty, and the test proves the audit can still detect a violation if
    one is injected.
    """

    _opt_outs: dict[str, OptOut] = field(default_factory=dict)

    def opt_out(self, email: str, when: Optional[datetime] = None) -> None:
        key = email.strip().lower()
        when = when or datetime.now(timezone.utc)
        # Keep the earliest opt-out time; honoring is measured from first request.
        if key not in self._opt_outs or when < self._opt_outs[key].requested_at:
            self._opt_outs[key] = OptOut(email=key, requested_at=when)

    def is_suppressed(self, email: str) -> bool:
        return email.strip().lower() in self._opt_outs

    def overdue(self, now: Optional[datetime] = None) -> list[OptOut]:
        """Opt-outs older than the honoring window. Present-day proof of compliance.

        With immediate suppression this is always empty; it exists so a system that
        batches opt-out processing can detect when it has fallen behind the law.
        """
        now = now or datetime.now(timezone.utc)
        return [
            o for o in self._opt_outs.values()
            if business_days_between(o.requested_at, now) > OPTOUT_HONOR_BUSINESS_DAYS
        ]

    def __len__(self) -> int:
        return len(self._opt_outs)


class EmailSender(Protocol):
    """The actual transport. Stubbed here; a real one wraps SMTP or an ESP API."""

    def send(self, to_email: str, msg: EmailMessage) -> None: ...


@dataclass
class DryRunSender:
    """Records what would be sent without sending anything."""

    sent: list[str] = field(default_factory=list)

    def send(self, to_email: str, msg: EmailMessage) -> None:
        self.sent.append(to_email)


@dataclass
class SendResult:
    attempted: int = 0
    sent: int = 0
    suppressed: int = 0
    invalid_address: int = 0
    blocked_message: Optional[str] = None

    def summary(self) -> str:
        if self.blocked_message:
            return f"NOT SENT: message failed compliance -> {self.blocked_message}"
        return (
            f"{self.attempted} recipients: {self.sent} sent, "
            f"{self.suppressed} suppressed, {self.invalid_address} invalid"
        )


@dataclass
class EmailCampaign:
    """Validates the message once, then sends only to mailable recipients."""

    sender: EmailSender
    suppression: SuppressionList

    def send(self, msg: EmailMessage, recipients: Sequence[str], now: Optional[datetime] = None) -> SendResult:
        result = SendResult()
        validation = validate_message(msg)
        if not validation.sendable:
            # One bad message must not go to anyone. Fail the whole campaign.
            result.blocked_message = validation.summary()
            return result

        for raw in recipients:
            result.attempted += 1
            email = raw.strip().lower()
            if not _looks_like_email(email):
                result.invalid_address += 1
                continue
            if self.suppression.is_suppressed(email):
                result.suppressed += 1
                continue
            self.sender.send(email, msg)
            result.sent += 1
        return result
