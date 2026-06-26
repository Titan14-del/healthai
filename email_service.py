import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
APP_URL = os.getenv("APP_URL", "")
# Sender address must be a SendGrid-verified domain; make it configurable per deployment.
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "noreply@healthai.app")


def send_reset_email(to_email: str, reset_token: str) -> None:
    if not SENDGRID_API_KEY:
        logger.warning("SENDGRID_API_KEY not set — skipping password reset email")
        return

    reset_url = f"{APP_URL}/reset-password?token={reset_token}"

    message = Mail(
        from_email=SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject="Reset your HealthAI password",
        html_content=(
            "<h2>Password Reset</h2>"
            "<p>Click the link below to reset your password. This link expires in 1 hour.</p>"
            f'<p><a href="{reset_url}">{reset_url}</a></p>'
            "<p>If you did not request this, you can safely ignore this email.</p>"
        ),
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Reset email sent to {to_email} — status={response.status_code}")
    except Exception as e:
        logger.error(f"Failed to send reset email to {to_email}: {e}")
