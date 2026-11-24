"""
SMS approval for Oracle's self-improvement proposals.

A Windows Python script cannot send a real SMS on its own - it needs a
messaging service. This starter uses Twilio, the most common one.

Set these environment variables on YOUR PC (never paste them in chat):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
  SMS_TO_NUMBER   - the number Oracle should text for approval.
                    Set this locally to your own number.
  (pip install twilio)

If Twilio is NOT configured, send_sms() returns False and prints the
message instead, so the proposal is still shown in the GUI and in
proposals/proposal-*.txt for you to approve there. Nothing is silently
approved.

Approval flow in monitor.py:
  1. Oracle finds a candidate improvement online.
  2. It explains it in plain language and texts you that explanation,
     asking "Reply YES to apply, NO to skip."
  3. It waits for a YES/NO reply (polling Twilio, up to 24 hours by
     default, or until you approve/decline in the GUI).
  4. Only a clear YES applies the change, with a backup first.
     Anything else = no change.
"""

import os


def send_sms(to_number, message):
    """Send an SMS via Twilio if configured. Returns True if sent."""
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    if not (sid and token and from_number and to_number):
        print("[sms] Twilio not configured - SMS not sent. Message would have been:")
        print(message)
        return False
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        msg = client.messages.create(body=message, from_=from_number, to=to_number)
        print(f"[sms] Sent, SID {msg.sid}")
        return True
    except Exception as e:
        print(f"[sms] Failed to send: {e}")
        return False


def check_sms_reply(to_number=None, timeout_minutes=5):
    """
    Poll Twilio for the latest incoming message.
    Returns "yes", "no", or None. This is a starter poller - in a
    production setup you would use a Twilio webhook instead, so replies
    arrive instantly instead of by polling.
    """
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not (sid and token):
        return None
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        msgs = client.messages.list(limit=5)
        for m in msgs:
            if m.direction == "inbound":
                body = (m.body or "").strip().lower()
                if body in ("yes", "y", "ok", "approve"):
                    return "yes"
                if body in ("no", "n", "stop", "skip"):
                    return "no"
    except Exception as e:
        print(f"[sms] Reply check failed: {e}")
    return None
