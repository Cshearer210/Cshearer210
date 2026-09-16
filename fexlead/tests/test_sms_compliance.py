"""SMS compliance, centered on the property that separates it from email:
you may not text a recipient with no consent record. Cold email is legal; cold SMS
is not."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fexlead.schema import Check  # noqa: E402
from fexlead.sms_compliance import (  # noqa: E402
    ConsentLedger, DryRunSmsSender, SmsCampaign, SmsConsent, SmsMessage,
    in_quiet_hours, is_opt_out_reply, validate_message,
)

NOON_CDT = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)   # 12:00 in Chicago
NIGHT_CDT = datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc)   # 23:00 in Chicago
CHI = ZoneInfo("America/Chicago")


def consent(phone):
    return SmsConsent(phone=phone, consented_at=NOON_CDT, consent_language="I agree to receive texts",
                      source="signup")


def good_msg():
    return SmsMessage(business_name="Lone Star", body="Your quote is ready.")


def test_no_consent_record_is_never_texted():
    led = ConsentLedger()
    res = SmsCampaign(DryRunSmsSender(), led).send(good_msg(), [("5125550101", CHI)], NOON_CDT)
    assert res.sent == 0
    assert res.no_consent == 1


def test_consented_daytime_recipient_is_texted():
    led = ConsentLedger()
    led.record_consent(consent("5125550101"))
    sender = DryRunSmsSender()
    res = SmsCampaign(sender, led).send(good_msg(), [("5125550101", CHI)], NOON_CDT)
    assert res.sent == 1
    assert len(sender.sent) == 1


def test_opted_out_beats_prior_consent():
    led = ConsentLedger()
    led.record_consent(consent("5125550101"))
    led.opt_out("5125550101")
    res = SmsCampaign(DryRunSmsSender(), led).send(good_msg(), [("5125550101", CHI)], NOON_CDT)
    assert res.opted_out == 1
    assert res.sent == 0


def test_fresh_consent_clears_prior_opt_out():
    led = ConsentLedger()
    led.opt_out("5125550101")
    led.record_consent(consent("5125550101"))
    assert led.status("5125550101") is Check.PASS


def test_quiet_hours_holds_the_send():
    led = ConsentLedger()
    led.record_consent(consent("5125550101"))
    res = SmsCampaign(DryRunSmsSender(), led).send(good_msg(), [("5125550101", CHI)], NIGHT_CDT)
    assert res.quiet_hours == 1
    assert res.sent == 0


def test_unknown_timezone_holds_the_send():
    led = ConsentLedger()
    led.record_consent(consent("5125550101"))
    res = SmsCampaign(DryRunSmsSender(), led).send(good_msg(), [("5125550101", None)], NOON_CDT)
    assert res.timezone_unknown == 1
    assert res.sent == 0


def test_quiet_hours_none_when_tz_unknown():
    assert in_quiet_hours(NOON_CDT, None) is None


def test_message_must_identify_business_and_offer_opt_out():
    problems = {c.name for c in validate_message(SmsMessage(business_name="", body="")) if not c.is_pass}
    assert "sender_id" in problems
    assert "body" in problems


def test_rendered_message_appends_opt_out_and_sender():
    r = SmsMessage(business_name="Lone Star", body="Your quote is ready.").rendered()
    assert "STOP" in r
    assert "Lone Star" in r


def test_noncompliant_message_goes_to_nobody():
    led = ConsentLedger()
    led.record_consent(consent("5125550101"))
    res = SmsCampaign(DryRunSmsSender(), led).send(SmsMessage(business_name="", body=""),
                                                   [("5125550101", CHI)], NOON_CDT)
    assert res.sent == 0
    assert res.blocked_message is not None


def test_stop_reply_detected():
    assert is_opt_out_reply("STOP")
    assert is_opt_out_reply("stop please")
    assert not is_opt_out_reply("hello")
