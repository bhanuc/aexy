"""SendGrid email provider."""

import httpx
from typing import Optional

from mailagent.providers.base import (
    EmailProvider,
    ProviderType,
    ProviderConfig,
    EmailMessage,
    SendResult,
)


class SendGridProvider(EmailProvider):
    """SendGrid email provider."""

    BASE_URL = "https://api.sendgrid.com/v3"

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._api_key = self._get_credential('api_key')

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.SENDGRID

    async def send(self, message: EmailMessage) -> SendResult:
        """Send email via SendGrid."""
        try:
            payload = self._build_payload(message)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/mail/send",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30.0,
                )

                if response.status_code in (200, 201, 202):
                    # SendGrid returns message ID in header
                    message_id = response.headers.get('X-Message-Id', '')

                    return SendResult(
                        success=True,
                        message_id=message_id,
                        provider='sendgrid',
                        provider_message_id=message_id,
                    )
                else:
                    error_body = response.json() if response.content else {}
                    error_msg = error_body.get('errors', [{}])[0].get('message', response.text)

                    return SendResult(
                        success=False,
                        provider='sendgrid',
                        error=f"HTTP {response.status_code}: {error_msg}",
                    )

        except Exception as e:
            return SendResult(
                success=False,
                provider='sendgrid',
                error=str(e),
            )

    async def verify_credentials(self) -> bool:
        """Verify SendGrid credentials."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/user/profile",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=10.0,
                )
                return response.status_code == 200
        except Exception:
            return False

    def _build_payload(self, message: EmailMessage) -> dict:
        """Build SendGrid API payload."""
        payload = {
            "personalizations": [{
                "to": [{"email": addr.address, "name": addr.name}
                       for addr in message.to_addresses],
            }],
            "from": {
                "email": message.from_address.address,
                "name": message.from_address.name,
            },
            "subject": message.subject,
        }

        # CC
        if message.cc_addresses:
            payload["personalizations"][0]["cc"] = [
                {"email": addr.address, "name": addr.name}
                for addr in message.cc_addresses
            ]

        # BCC
        if message.bcc_addresses:
            payload["personalizations"][0]["bcc"] = [
                {"email": addr.address, "name": addr.name}
                for addr in message.bcc_addresses
            ]

        # Reply-To
        if message.reply_to:
            payload["reply_to"] = {
                "email": message.reply_to.address,
                "name": message.reply_to.name,
            }

        # Content
        content = []
        if message.body_text:
            content.append({"type": "text/plain", "value": message.body_text})
        if message.body_html:
            content.append({"type": "text/html", "value": message.body_html})
        payload["content"] = content

        # Headers
        if message.headers or message.in_reply_to or message.references:
            headers = dict(message.headers)
            if message.in_reply_to:
                headers["In-Reply-To"] = message.in_reply_to
            if message.references:
                headers["References"] = " ".join(message.references)
            payload["headers"] = headers

        # Tracking
        payload["tracking_settings"] = {
            "click_tracking": {"enable": message.track_clicks},
            "open_tracking": {"enable": message.track_opens},
        }

        # Categories (tags)
        if message.tags:
            payload["categories"] = message.tags[:10]

        # Custom args (metadata)
        if message.metadata:
            payload["personalizations"][0]["custom_args"] = {
                k: str(v) for k, v in message.metadata.items()
            }

        # Attachments
        if message.attachments:
            import base64
            payload["attachments"] = [
                {
                    "content": base64.b64encode(att.content).decode(),
                    "filename": att.filename,
                    "type": att.content_type,
                    "disposition": "inline" if att.content_id else "attachment",
                    **({"content_id": att.content_id} if att.content_id else {}),
                }
                for att in message.attachments
            ]

        return payload
