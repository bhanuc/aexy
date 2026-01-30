# Mailagent

Email administration, onboarding, and domain setup microservice for Aexy.

## Features

- **Admin Management**: CRUD operations for email providers (SES, SendGrid, Mailgun, Postmark, SMTP)
- **Domain Setup**: Domain registration, DNS verification (SPF/DKIM/DMARC), health scoring
- **Domain Warming**: Configurable warming schedules (conservative, moderate, aggressive)
- **Email Onboarding**: Inbox creation, verification flows, welcome sequences

## Quick Start

### Using Docker Compose (Recommended)

```bash
# From the aexy root directory
docker-compose up mailagent
```

The service will be available at http://localhost:8001

### Local Development

```bash
cd mailagent

# Install dependencies
pip install uv
uv pip install -e ".[dev]"

# Run tests
pytest

# Run service
uvicorn mailagent.main:app --host 0.0.0.0 --port 8001 --reload
```

## API Endpoints

### Health
- `GET /health` - Service health check
- `GET /ready` - Kubernetes readiness probe
- `GET /live` - Kubernetes liveness probe

### Admin (Provider Management)
- `GET /api/v1/admin/dashboard` - Dashboard statistics
- `POST /api/v1/admin/providers` - Create provider
- `GET /api/v1/admin/providers` - List providers
- `GET /api/v1/admin/providers/{id}` - Get provider
- `PATCH /api/v1/admin/providers/{id}` - Update provider
- `DELETE /api/v1/admin/providers/{id}` - Delete provider
- `POST /api/v1/admin/providers/{id}/test` - Test provider connection

### Domains
- `POST /api/v1/domains/` - Create domain
- `GET /api/v1/domains/` - List domains
- `GET /api/v1/domains/{id}` - Get domain
- `GET /api/v1/domains/by-name/{name}` - Get domain by name
- `PATCH /api/v1/domains/{id}` - Update domain
- `DELETE /api/v1/domains/{id}` - Delete domain
- `POST /api/v1/domains/{id}/verify` - Verify DNS records
- `POST /api/v1/domains/{id}/start-warming` - Start warming
- `POST /api/v1/domains/{id}/advance-warming` - Advance warming day

### Onboarding
- `POST /api/v1/onboarding/start` - Start onboarding process
- `POST /api/v1/onboarding/inboxes` - Create inbox
- `GET /api/v1/onboarding/inboxes` - List inboxes
- `GET /api/v1/onboarding/inboxes/{id}` - Get inbox
- `GET /api/v1/onboarding/inboxes/by-email/{email}` - Get inbox by email
- `DELETE /api/v1/onboarding/inboxes/{id}` - Delete inbox
- `POST /api/v1/onboarding/inboxes/{id}/verify` - Verify inbox
- `POST /api/v1/onboarding/inboxes/{id}/resend-verification` - Resend verification

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mailagent --cov-report=html

# Run specific module
pytest tests/test_admin.py -v

# Watch mode
ptw
```

## Configuration

See `.env.example` for all configuration options.

## Architecture

```
mailagent/
├── src/mailagent/
│   ├── api/           # FastAPI routers
│   ├── services/      # Business logic
│   ├── models.py      # SQLAlchemy models
│   ├── schemas.py     # Pydantic schemas
│   ├── config.py      # Settings
│   ├── database.py    # DB connection
│   ├── redis_client.py # Redis client
│   └── main.py        # Application entry
├── tests/             # Test suite
├── Dockerfile
├── pyproject.toml
└── TDD_TRACKER.md     # Development tracker
```
