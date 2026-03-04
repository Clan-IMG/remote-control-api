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
        f"  {code[:3]} — {code[3:]}\n\n"
        f"This code expires in {OTP_TTL_SECONDS // 60} minutes.\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"— The Pixelkid Team"
    )

    # split code visually: "123456" → "123" and "456"
    code_a = code[:3]
    code_b = code[3:]

    def _digit_cell(ch: str) -> str:
        return (
            f'<td style="width:48px;height:56px;text-align:center;vertical-align:middle;'
            f'font-size:28px;font-weight:700;color:#ffffff;letter-spacing:0;'
            f'background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);'
            f'border-radius:10px;font-family:monospace;">'
            f'{ch}</td>'
        )

    digits_a = ''.join(_digit_cell(c) for c in code_a)
    digits_b = ''.join(_digit_cell(c) for c in code_b)

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Verify your email – Pixelkid</title>
</head>
<body style="margin:0;padding:0;background:#000000;font-family:Inter,system-ui,-apple-system,sans-serif;">

  <!-- Outer wrapper: full-bleed black -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#000000;min-height:100vh;padding:48px 20px;">
    <tr>
      <td align="center">

        <!-- Glow backdrop (simulated Gaussian blur via radial gradient) -->
        <table width="560" cellpadding="0" cellspacing="0"
               style="position:relative;border-radius:24px;
                      background:radial-gradient(ellipse 420px 260px at 50% -40px,
                        rgba(255,255,255,0.07) 0%, transparent 70%),
                        linear-gradient(180deg,#111111 0%,#0a0a0a 100%);
                      border:1px solid rgba(255,255,255,0.10);
                      box-shadow:0 0 80px 0 rgba(0,0,0,0.8),
                                 inset 0 1px 0 rgba(255,255,255,0.08);
                      padding:0;">

          <!-- Top glow strip -->
          <tr>
            <td style="height:4px;border-radius:24px 24px 0 0;
                       background:linear-gradient(90deg,transparent,rgba(255,255,255,0.20),transparent);">
            </td>
          </tr>

          <!-- Content padding wrapper -->
          <tr>
            <td style="padding:40px 48px 48px;">
              <table width="100%" cellpadding="0" cellspacing="0">

                <!-- Logo -->
                <tr>
                  <td align="center" style="padding-bottom:36px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.10);
                                   border-radius:12px;padding:10px 20px;">
                          <span style="font-size:18px;font-weight:700;color:#ffffff;
                                       letter-spacing:-0.3px;">pixelkid</span><span
                                style="font-size:18px;font-weight:700;color:rgba(255,255,255,0.35);">.app</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- Heading -->
                <tr>
                  <td align="center" style="padding-bottom:10px;">
                    <span style="font-size:26px;font-weight:700;color:#ffffff;
                                 letter-spacing:-0.5px;">Verify your email address</span>
                  </td>
                </tr>

                <!-- Subtext -->
                <tr>
                  <td align="center" style="padding-bottom:36px;">
                    <span style="font-size:14px;color:rgba(255,255,255,0.45);line-height:1.7;">
                      Hi <span style="color:rgba(255,255,255,0.80);font-weight:500;">{username}</span>,
                      enter this one-time code in Pixelkid to confirm your email address.
                    </span>
                  </td>
                </tr>

                <!-- OTP Code group: 3 – 3 -->
                <tr>
                  <td align="center" style="padding-bottom:12px;">
                    <!-- Glow card behind the digits -->
                    <table cellpadding="0" cellspacing="0"
                           style="background:radial-gradient(ellipse 300px 120px at 50% 50%,
                                    rgba(255,255,255,0.06) 0%,transparent 70%);
                                  border:1px solid rgba(255,255,255,0.08);
                                  border-radius:16px;padding:24px 28px;">
                      <tr valign="middle">
                        <!-- Group A -->
                        <td>
                          <table cellpadding="0" cellspacing="6">
                            <tr>
                              {digits_a}
                            </tr>
                          </table>
                        </td>
                        <!-- Separator dash -->
                        <td style="padding:0 14px;color:rgba(255,255,255,0.25);font-size:28px;
                                   font-weight:300;vertical-align:middle;line-height:1;">—</td>
                        <!-- Group B -->
                        <td>
                          <table cellpadding="0" cellspacing="6">
                            <tr>
                              {digits_b}
                            </tr>
                          </table>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- Expiry note -->
                <tr>
                  <td align="center" style="padding-bottom:36px;">
                    <span style="font-size:12px;color:rgba(255,255,255,0.28);">
                      Expires in
                      <span style="color:rgba(255,255,255,0.55);font-weight:500;">
                        {OTP_TTL_SECONDS // 60}&nbsp;minutes
                      </span>.
                      Didn't request this? You can safely ignore this email.
                    </span>
                  </td>
                </tr>

                <!-- Divider -->
                <tr>
                  <td style="border-top:1px solid rgba(255,255,255,0.07);padding-top:28px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="color:rgba(255,255,255,0.20);font-size:11px;">
                          © 2026 Pixelkid
                        </td>
                        <td align="right">
                          <a href="https://pixelkid.app"
                             style="color:rgba(255,255,255,0.25);font-size:11px;
                                    text-decoration:none;">pixelkid.app</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
        <!-- /card -->

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
