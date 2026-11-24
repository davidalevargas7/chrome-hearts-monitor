
#!/usr/bin/env python3
"""
Notification backends:
  NOTIFY_METHOD=discord
  NOTIFY_METHOD=twilio
  NOTIFY_METHOD=email_sms
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.mime.text import MIMEText

import requests


def _http_error(service: str, resp: requests.Response) -> RuntimeError:
    return RuntimeError(
        f"{service} returned HTTP {resp.status_code}: {resp.text[:200]!r}"
    )


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"[notifier] missing env var: {name}", file=sys.stderr)
        raise SystemExit(1)
    return val


def _appointment_embed(body: str) -> dict | None:
    """Convert appointment alerts into a polished Discord embed."""

    lines = body.splitlines()

    if not lines or not lines[0].startswith("🟢 OPEN SLOT"):
        return None

    header = lines[0]
    location = header.split(" — ", 1)[1] if " — " in header else "Chrome Hearts"

    booking_url = None
    appointment_lines = []

    for line in lines[1:]:
        if line.startswith("Book now:"):
            booking_url = line.partition(":")[2].strip()
        elif line.strip():
            appointment_lines.append(line.strip())

    if not booking_url:
        return None

    description = "\n".join(appointment_lines)
    description += f"\n\n[**BOOK YOUR APPOINTMENT →**]({booking_url})"

    return {
        "title": "APPOINTMENT AVAILABLE",
        "url": booking_url,
        "description": description[:4096],
        "color": 0x292929,
        "fields": [
            {
                "name": "LOCATION",
                "value": location[:1024],
                "inline": False,
            },
            {
                "name": "STATUS",
                "value": "🟢 New appointment slot detected",
                "inline": False,
            },
        ],
        "footer": {
            "text": "CHROME HEARTS • WEST VILLAGE • LIVE MONITOR"
        },
    }


def _send_discord(
    body: str,
    *,
    suppress_embeds: bool = False,
    webhook_url: str | None = None,
) -> None:

    url = (
        webhook_url
        if webhook_url is not None
        else _env("DISCORD_WEBHOOK_URL")
    )

    payload = {
        "allowed_mentions": {"parse": []}
    }

    appointment_embed = None

    if not suppress_embeds and webhook_url is None:
        appointment_embed = _appointment_embed(body)

    if appointment_embed:
        payload["embeds"] = [appointment_embed]
    else:
        payload["content"] = body[:2000]

    if suppress_embeds:
        payload["flags"] = 1 << 2

    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as exc:
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            raise _http_error("Discord webhook", exc.response) from exc
        raise RuntimeError("Discord webhook request failed") from exc

    if resp.status_code >= 300:
        raise _http_error("Discord webhook", resp)

    print("[discord] sent")


def send_monitor_notification(body: str) -> None:
    """Send operational notices to the dedicated monitor-issues webhook."""

    url = os.environ.get("DISCORD_MONITOR_WEBHOOK_URL", "").strip()

    if not url:
        raise RuntimeError(
            "DISCORD_MONITOR_WEBHOOK_URL is not configured; "
            "monitor notice was not sent"
        )

    _send_discord(body, suppress_embeds=True, webhook_url=url)


def _send_twilio(body: str) -> None:
    sid = _env("TWILIO_ACCOUNT_SID")
    token = _env("TWILIO_AUTH_TOKEN")

    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={
                "From": _env("TWILIO_FROM"),
                "To": _env("TWILIO_TO"),
                "Body": body,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            raise _http_error("Twilio", exc.response) from exc
        raise RuntimeError("Twilio request failed") from exc

    if resp.status_code >= 300:
        raise _http_error("Twilio", resp)

    print("[twilio] sent")


def _send_email_sms(body: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")
    to_addr = _env("SMS_TO")

    msg = MIMEText(body)
    msg["From"], msg["To"], msg["Subject"] = user, to_addr, ""

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())

    print("[email_sms] sent")


def send_notification(body: str, *, suppress_embeds: bool = False) -> None:
    method = os.environ.get("NOTIFY_METHOD", "discord").lower()

    if method == "discord":
        _send_discord(body, suppress_embeds=suppress_embeds)
    elif method == "twilio":
        _send_twilio(body)
    elif method == "email_sms":
        _send_email_sms(body)
    else:
        print(
            f"[notifier] unknown NOTIFY_METHOD={method!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    send_notification(
        sys.argv[1] if len(sys.argv) > 1
        else "test from chrome hearts monitor"
    )
