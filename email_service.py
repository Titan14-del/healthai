import os
import logging

import resend

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
APP_URL = os.getenv("APP_URL", "")

if not RESEND_API_KEY:
    logger.warning("RESEND_API_KEY not set — password reset emails will not be sent")

resend.api_key = RESEND_API_KEY


def send_reset_email(to_email: str, reset_token: str) -> None:
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping password reset email")
        return

    reset_url = f"{APP_URL}/reset-password?token={reset_token}"

    try:
        r = resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": to_email,
            "subject": "Reset your HealthAI password",
            "html": (
                "<h2>Password Reset</h2>"
                "<p>Click the link below to reset your password. This link expires in 1 hour.</p>"
                f'<p><a href="{reset_url}">{reset_url}</a></p>'
                "<p>If you did not request this, you can safely ignore this email.</p>"
            ),
        })
        logger.info(f"Reset email sent to {to_email} — id={r.get('id')}")
    except Exception as e:
        logger.error(f"Failed to send reset email to {to_email}: {e}")
