import logging
from typing import Optional

logger = logging.getLogger(__name__)

USE_REAL_SMTP = False   # <- поменяйте на True, когда купите домен и настроите SMTP

async def send_email(to_email: str, subject: str, body: str, html: Optional[str] = None) -> bool:
    if not USE_REAL_SMTP:
        # Режим разработки: логируем всю информацию
        logger.info("=" * 50)
        logger.info(f"[MOCK EMAIL] To: {to_email}")
        logger.info(f"[MOCK EMAIL] Subject: {subject}")
        logger.info(f"[MOCK EMAIL] Body:\n{body}")
        if html:
            logger.info(f"[MOCK EMAIL] HTML:\n{html}")
        logger.info("=" * 50)
        return True

    # Реальная отправка (для продакшена)
    try:
        import aiosmtplib
        from email.message import EmailMessage
        from config import settings

        message = EmailMessage()
        message["From"] = settings.SMTP_FROM
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        if html:
            message.add_alternative(html, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=True,
        )
        logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False