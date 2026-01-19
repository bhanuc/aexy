# Aexy Backend

GitHub-Based Developer Profiling & Analytics Platform - Backend API

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Start development server
uvicorn aexy.main:app --reload
```

## Architecture

The backend is built with FastAPI and uses:
- SQLAlchemy for ORM
- PostgreSQL for data storage
- Redis for caching
- Celery for background tasks
- Anthropic/Ollama for LLM-powered analytics

## Configuration

Copy `.env.example` to `.env` and configure your environment variables.

### Email Configuration

Aexy supports two email providers for sending notifications: **AWS SES** and **SMTP**.

#### Option 1: AWS SES (Recommended for Production)

AWS Simple Email Service provides high deliverability and scales well for production use.

```bash
EMAIL_PROVIDER=ses
EMAIL_NOTIFICATIONS_ENABLED=true

# AWS Credentials
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_SES_REGION=us-east-1

# Sender Configuration
SES_SENDER_EMAIL=noreply@yourdomain.com
SES_SENDER_NAME=Aexy
```

**Setup Steps:**
1. Create an AWS account and navigate to IAM
2. Create a user with `AmazonSESFullAccess` permission
3. Generate access keys for the user
4. Verify your sender email/domain in SES console
5. If in sandbox mode, also verify recipient emails

#### Option 2: SMTP (Flexible for Any Provider)

SMTP works with any email provider including Gmail, SendGrid, Mailgun, etc.

```bash
EMAIL_PROVIDER=smtp
EMAIL_NOTIFICATIONS_ENABLED=true

# SMTP Server Settings
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_USE_TLS=true
SMTP_USE_SSL=false

# Sender Configuration
SMTP_SENDER_EMAIL=your_email@gmail.com
SMTP_SENDER_NAME=Aexy
```

**Common SMTP Providers:**

| Provider | Host | Port | Notes |
|----------|------|------|-------|
| Gmail | smtp.gmail.com | 587 | Requires App Password (2FA must be enabled) |
| SendGrid | smtp.sendgrid.net | 587 | Use API key as password |
| Mailgun | smtp.mailgun.org | 587 | Use SMTP credentials from dashboard |
| Amazon SES | email-smtp.{region}.amazonaws.com | 587 | Use SMTP credentials (different from API keys) |
| Outlook/Office365 | smtp.office365.com | 587 | Use account password or app password |

**Port Configuration:**
- Port `587` - Use with `SMTP_USE_TLS=true` (STARTTLS)
- Port `465` - Use with `SMTP_USE_SSL=true` (implicit SSL/TLS)
- Port `25` - Unencrypted (not recommended)

#### Gmail Setup

1. Enable 2-Factor Authentication on your Google account
2. Go to Google Account → Security → App Passwords
3. Generate a new app password for "Mail"
4. Use this app password as `SMTP_PASSWORD`

#### Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `EMAIL_PROVIDER` | `ses` | Email provider: `ses` or `smtp` |
| `EMAIL_NOTIFICATIONS_ENABLED` | `true` | Enable/disable email notifications |
| `AWS_ACCESS_KEY_ID` | - | AWS access key (for SES) |
| `AWS_SECRET_ACCESS_KEY` | - | AWS secret key (for SES) |
| `AWS_SES_REGION` | `us-east-1` | AWS region for SES |
| `SES_SENDER_EMAIL` | `noreply@aexy.io` | Sender email address (SES) |
| `SES_SENDER_NAME` | `Aexy` | Sender display name (SES) |
| `SMTP_HOST` | - | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USERNAME` | - | SMTP auth username |
| `SMTP_PASSWORD` | - | SMTP auth password |
| `SMTP_USE_TLS` | `true` | Use STARTTLS (port 587) |
| `SMTP_USE_SSL` | `false` | Use SSL/TLS (port 465) |
| `SMTP_SENDER_EMAIL` | - | Sender email (falls back to SES_SENDER_EMAIL) |
| `SMTP_SENDER_NAME` | - | Sender name (falls back to SES_SENDER_NAME) |

#### Testing Email Configuration

You can test your SMTP configuration using the `test_smtp_connection()` method:

```python
from aexy.services.email_service import email_service

# Test SMTP connection
result = await email_service.test_smtp_connection()
print(result)  # {"success": True, "message": "SMTP connection successful"}
```
