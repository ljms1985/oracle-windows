"""
Email alerts for Oracle - replaces SMS texting.

Why email instead of SMS:
  * No Twilio account, no per-message cost, no phone number rental.
  * A Windows script CAN send email on its own with SMTP - unlike SMS,
    which needs a messaging service.

Set these on YOUR PC (never paste passwords in chat):
  ALERT_EMAIL_TO     - the email Oracle should send alerts to.
                       Set this locally to your own email address.
  ALERT_EMAIL_FROM   - the sending address (often the same as TO).
  SMTP_HOST          - default: smtp.gmail.com
  SMTP_PORT          - default: 587
  SMTP_USER          - your email address for login
  SMTP_PASS          - NOT your normal password. For Gmail, use an
                       App Password: Google Account > Security >
                       2-Step Verification > App passwords.
                       Treat it like a password - keep it in an
                       environment variable, never in code or chat.

For other providers, change SMTP_HOST/PORT:
  Outlook: smtp.office365.com:587
  Yahoo:   smtp.mail.yahoo.com:587

Approval by email (for self-improvement proposals):
  Oracle emails you the proposal and asks you to reply YES or NO.
  If you also set IMAP_HOST/IMAP_USER/IMAP_PASS, check_email_reply()
  will poll your inbox for a reply to that proposal. If IMAP is not
  set, approve in the GUI or by creating proposals/<name>.approved -
  nothing changes without a clear YES in one of those places.
"""

import os
import smtplib
from email.message import EmailMessage


def _config():
    return {
        "to": os.environ.get("ALERT_EMAIL_TO", ""),
        "from": os.environ.get("ALERT_EMAIL_FROM", os.environ.get("SMTP_USER", "")),
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASS", ""),
    }


def send_email(subject, body, to=None):
    """Send an email via SMTP. Returns True if sent, False otherwise."""
    cfg = _config()
    recipient = to or cfg["to"]
    if not (recipient and cfg["user"] and cfg["password"]):
        print("[email] SMTP not configured - email not sent. Set ALERT_EMAIL_TO, SMTP_USER, SMTP_PASS.")
        print(f"Subject would have been: {subject}\n{body}")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"] or cfg["user"]
    msg["To"] = recipient
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
        print(f"[email] Sent to {recipient}: {subject}")
        return True
    except Exception as e:
        print(f"[email] Failed to send: {e}")
        return False


def check_email_reply(subject_contains, timeout_minutes=5):
    """
    Starter IMAP poller for YES/NO replies. Returns "yes", "no", or None.
    Requires IMAP_HOST, IMAP_USER, IMAP_PASS. If not configured, returns None
    immediately - approval then happens via GUI / .approved file instead.
    """
    host = os.environ.get("IMAP_HOST", "")
    user = os.environ.get("IMAP_USER", "")
    password = os.environ.get("IMAP_PASS", "")
    if not (host and user and password):
        return None
    try:
        import imaplib, email
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select("INBOX")
        # Search recent mail for the proposal subject.
        _, data = mail.search(None, "UNSEEN")
        for num in reversed(data[0].split()[-10:]):
            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subj = str(msg.get("Subject", ""))
            if subject_contains.lower() not in subj.lower():
                continue
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body += part.get_payload(decode=True).decode(errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore") if msg.get_payload(decode=True) else ""
            low = body.strip().lower()
            if low.startswith("yes") or "\nyes" in low:
                return "yes"
            if low.startswith("no") or "\nno" in low:
                return "no"
        mail.logout()
    except Exception as e:
        print(f"[email] Reply check failed: {e}")
    return None
