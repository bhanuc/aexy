"""Amazon SES email provider."""

import boto3
from botocore.exceptions import ClientError
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional

from mailagent.providers.base import (
    EmailProvider,
    ProviderType,
    ProviderConfig,
    EmailMessage,
    SendResult,
)


class SESProvider(EmailProvider):
    """Amazon SES email provider."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

        self._client = boto3.client(
            'ses',
            aws_access_key_id=self._get_credential('access_key_id'),
            aws_secret_access_key=self._get_credential('secret_access_key'),
            region_name=self._get_credential('region', required=False) or 'us-east-1',
        )

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.SES

    async def send(self, message: EmailMessage) -> SendResult:
        """Send email via SES."""
        try:
            # Build MIME message
            mime_message = self._build_mime_message(message)

            # Get all recipients
            destinations = [addr.address for addr in message.to_addresses]
            destinations += [addr.address for addr in message.cc_addresses]
            destinations += [addr.address for addr in message.bcc_addresses]

            # Send raw email
            response = self._client.send_raw_email(
                Source=message.from_address.formatted(),
                Destinations=destinations,
                RawMessage={'Data': mime_message.as_string()},
                Tags=[{'Name': tag, 'Value': 'true'} for tag in message.tags[:10]],
            )

            return SendResult(
                success=True,
                message_id=response['MessageId'],
                provider='ses',
                provider_message_id=response['MessageId'],
            )

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            return SendResult(
                success=False,
                provider='ses',
                error=f"{error_code}: {error_message}",
            )

        except Exception as e:
            return SendResult(
                success=False,
                provider='ses',
                error=str(e),
            )

    async def verify_credentials(self) -> bool:
        """Verify SES credentials by getting account info."""
        try:
            self._client.get_account()
            return True
        except Exception:
            return False

    def _build_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Build a MIME message from EmailMessage."""
        msg = MIMEMultipart('mixed')

        # Headers
        msg['From'] = message.from_address.formatted()
        msg['To'] = ', '.join(addr.formatted() for addr in message.to_addresses)
        msg['Subject'] = message.subject

        if message.cc_addresses:
            msg['Cc'] = ', '.join(addr.formatted() for addr in message.cc_addresses)

        if message.reply_to:
            msg['Reply-To'] = message.reply_to.formatted()

        if message.in_reply_to:
            msg['In-Reply-To'] = message.in_reply_to

        if message.references:
            msg['References'] = ' '.join(message.references)

        # Custom headers
        for key, value in message.headers.items():
            msg[key] = value

        # Body
        body_part = MIMEMultipart('alternative')

        if message.body_text:
            text_part = MIMEText(message.body_text, 'plain', 'utf-8')
            body_part.attach(text_part)

        if message.body_html:
            html_part = MIMEText(message.body_html, 'html', 'utf-8')
            body_part.attach(html_part)

        msg.attach(body_part)

        # Attachments
        for attachment in message.attachments:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.content)
            encoders.encode_base64(part)

            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{attachment.filename}"'
            )

            if attachment.content_id:
                part.add_header('Content-ID', f'<{attachment.content_id}>')

            msg.attach(part)

        return msg

    async def send_batch(self, messages: list[EmailMessage]) -> list[SendResult]:
        """Send batch of emails via SES."""
        # SES doesn't have a true batch API for different messages,
        # so we send sequentially but could parallelize with asyncio
        import asyncio

        tasks = [self.send(msg) for msg in messages]
        return await asyncio.gather(*tasks)
