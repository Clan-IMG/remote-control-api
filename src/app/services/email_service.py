"""
Email service using aiosmtplib (async SMTP).

OTP codes are stored in Redis with a configurable TTL (default 10 min).
Redis key pattern:  pixelkid:otp:<user_id>
"""

import random
import string
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.app.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_FROM_EMAIL, SMTP_FROM_NAME, SMTP_USE_TLS,
    OTP_TTL_SECONDS,
)
from src.app.redis_client import redis_client

# Redis key prefix for OTP codes
_OTP_PREFIX = "pixelkid:otp:"


# ── OTP helpers ──────────────────────────────────────────────────────────────

def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP code."""
    return "".join(random.choices(string.digits, k=length))


async def store_otp(user_id: str, code: str) -> None:
    """Store the OTP in Redis with TTL."""
    key = f"{_OTP_PREFIX}{user_id}"
    await redis_client.setex(key, OTP_TTL_SECONDS, code)


async def verify_otp(user_id: str, code: str) -> bool:
    """Check the OTP. Returns True if correct and deletes it (one-time use)."""
    key = f"{_OTP_PREFIX}{user_id}"
    stored = await redis_client.get(key)
    if stored and stored == code:
        await redis_client.delete(key)
        return True
    return False


async def otp_ttl_remaining(user_id: str) -> int:
    """Return seconds remaining before OTP expires, or -1 if not found."""
    key = f"{_OTP_PREFIX}{user_id}"
    ttl = await redis_client.ttl(key)
    return int(ttl)


# ── Email sending ─────────────────────────────────────────────────────────────

def _build_verification_email(to_email: str, username: str, code: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Pixelkid verification code: {code}"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to_email

    plain = (
        f"Hi {username},\n\n"
        f"Your Pixelkid email verification code is:\n\n"
        f"  {code}\n\n"
        f"This code expires in {OTP_TTL_SECONDS // 60} minutes.\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"— The Pixelkid Team"
    )

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#09090b;font-family:system-ui,-apple-system,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#09090b;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="540" cellpadding="0" cellspacing="0" style="background:#18181b;border-radius:16px;border:1px solid rgba(255,255,255,0.08);padding:40px 32px;">
          <!-- Logo / Brand -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <span style="font-size:22px;font-weight:700;color:#a78bfa;letter-spacing:-0.5px;">Pixelkid</span>
            </td>
          </tr>
          <!-- Heading -->
          <tr>
            <td style="color:#e4e4e7;font-size:24px;font-weight:600;padding-bottom:12px;text-align:center;">
              Verify your email
            </td>
          </tr>
          <!-- Subtext -->
          <tr>
            <td style="color:#a1a1aa;font-size:14px;text-align:center;padding-bottom:32px;line-height:1.6;">
              Hi <strong style="color:#e4e4e7;">{username}</strong>, enter the code below in Pixelkid to verify your email address.
            </td>
          </tr>
          <!-- OTP Code box -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <div style="display:inline-block;background:#09090b;border:1px solid rgba(167,139,250,0.3);border-radius:12px;padding:20px 40px;">
                <span style="font-size:36px;font-weight:700;color:#a78bfa;letter-spacing:12px;font-variant-numeric:tabular-nums;">{code}</span>
              </div>
            </td>
          </tr>
          <!-- Expiry note -->
          <tr>
            <td style="color:#71717a;font-size:12px;text-align:center;padding-bottom:24px;">
              This code expires in <strong style="color:#a1a1aa;">{OTP_TTL_SECONDS // 60} minutes</strong>.
              If you didn't request this, you can safely ignore this email.
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="border-top:1px solid rgba(255,255,255,0.06);padding-top:24px;text-align:center;color:#52525b;font-size:11px;">
              © {2026} Pixelkid · <a href="https://pixelkid.app" style="color:#52525b;">pixelkid.app</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


async def send_verification_email(to_email: str, username: str, code: str) -> None:
    """Send a verification OTP email via aiosmtplib (STARTTLS)."""
    msg = _build_verification_email(to_email, username, code)

    await aiosmtplib.send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=SMTP_USERNAME,
        password=SMTP_PASSWORD,
        start_tls=SMTP_USE_TLS,
    )
