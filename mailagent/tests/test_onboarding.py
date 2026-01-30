"""Tests for onboarding service and API."""

import pytest
from httpx import AsyncClient


class TestOnboardingAPI:
    """Tests for onboarding API endpoints."""

    @pytest.mark.asyncio
    async def test_start_onboarding(self, client: AsyncClient):
        """Test starting the onboarding process."""
        response = await client.post(
            "/api/v1/onboarding/start",
            json={
                "email": "newuser@example.com",
                "display_name": "New User",
                "send_welcome_email": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert "inbox_id" in data
        assert "next_steps" in data
        assert len(data["next_steps"]) > 0

    @pytest.mark.asyncio
    async def test_start_onboarding_minimal(self, client: AsyncClient):
        """Test starting onboarding with minimal data."""
        response = await client.post(
            "/api/v1/onboarding/start",
            json={"email": "minimal@example.com"},
        )

        assert response.status_code == 200
        assert response.json()["email"] == "minimal@example.com"

    @pytest.mark.asyncio
    async def test_create_inbox(self, client: AsyncClient, inbox_factory):
        """Test creating a new inbox."""
        inbox_data = inbox_factory(email="test@example.com")

        response = await client.post("/api/v1/onboarding/inboxes", json=inbox_data)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["is_verified"] is False
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_inbox_with_display_name(
        self, client: AsyncClient, inbox_factory
    ):
        """Test creating inbox with display name."""
        inbox_data = inbox_factory(
            email="display@example.com",
            display_name="Display Name User",
        )

        response = await client.post("/api/v1/onboarding/inboxes", json=inbox_data)

        assert response.status_code == 201
        assert response.json()["display_name"] == "Display Name User"

    @pytest.mark.asyncio
    async def test_list_inboxes(self, client: AsyncClient, inbox_factory):
        """Test listing inboxes."""
        # Create some inboxes
        for i in range(3):
            await client.post(
                "/api/v1/onboarding/inboxes",
                json=inbox_factory(email=f"list{i}@example.com"),
            )

        response = await client.get("/api/v1/onboarding/inboxes")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3

    @pytest.mark.asyncio
    async def test_list_inboxes_verified_only(
        self, client: AsyncClient, inbox_factory
    ):
        """Test listing only verified inboxes."""
        # Create an inbox (unverified by default)
        await client.post(
            "/api/v1/onboarding/inboxes",
            json=inbox_factory(email="unverified@example.com"),
        )

        response = await client.get("/api/v1/onboarding/inboxes?verified_only=true")

        assert response.status_code == 200
        data = response.json()
        # All returned should be verified
        assert all(inbox["is_verified"] for inbox in data)

    @pytest.mark.asyncio
    async def test_get_inbox(self, client: AsyncClient, inbox_factory):
        """Test getting a specific inbox."""
        create_response = await client.post(
            "/api/v1/onboarding/inboxes",
            json=inbox_factory(email="get@example.com"),
        )
        inbox_id = create_response.json()["id"]

        response = await client.get(f"/api/v1/onboarding/inboxes/{inbox_id}")

        assert response.status_code == 200
        assert response.json()["email"] == "get@example.com"

    @pytest.mark.asyncio
    async def test_get_inbox_by_email(self, client: AsyncClient, inbox_factory):
        """Test getting inbox by email address."""
        await client.post(
            "/api/v1/onboarding/inboxes",
            json=inbox_factory(email="byemail@example.com"),
        )

        response = await client.get(
            "/api/v1/onboarding/inboxes/by-email/byemail@example.com"
        )

        assert response.status_code == 200
        assert response.json()["email"] == "byemail@example.com"

    @pytest.mark.asyncio
    async def test_get_inbox_not_found(self, client: AsyncClient):
        """Test getting non-existent inbox."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(f"/api/v1/onboarding/inboxes/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_inbox(self, client: AsyncClient, inbox_factory):
        """Test deleting an inbox."""
        create_response = await client.post(
            "/api/v1/onboarding/inboxes",
            json=inbox_factory(email="delete@example.com"),
        )
        inbox_id = create_response.json()["id"]

        response = await client.delete(f"/api/v1/onboarding/inboxes/{inbox_id}")
        assert response.status_code == 204

        # Verify deleted
        get_response = await client.get(f"/api/v1/onboarding/inboxes/{inbox_id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_inbox_invalid_token(
        self, client: AsyncClient, inbox_factory
    ):
        """Test inbox verification with invalid token."""
        create_response = await client.post(
            "/api/v1/onboarding/inboxes",
            json=inbox_factory(email="verify@example.com"),
        )
        inbox_id = create_response.json()["id"]

        response = await client.post(
            f"/api/v1/onboarding/inboxes/{inbox_id}/verify?token=invalid-token"
        )

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_resend_verification(self, client: AsyncClient, inbox_factory):
        """Test resending verification email."""
        create_response = await client.post(
            "/api/v1/onboarding/inboxes",
            json=inbox_factory(email="resend@example.com"),
        )
        inbox_id = create_response.json()["id"]

        response = await client.post(
            f"/api/v1/onboarding/inboxes/{inbox_id}/resend-verification"
        )

        assert response.status_code == 200
        assert response.json()["sent"] is True


class TestOnboardingNextSteps:
    """Tests for onboarding next steps logic."""

    @pytest.mark.asyncio
    async def test_next_steps_include_verification(self, client: AsyncClient):
        """Test that next steps include verification for new inbox."""
        response = await client.post(
            "/api/v1/onboarding/start",
            json={"email": "nextsteps@example.com"},
        )

        next_steps = response.json()["next_steps"]
        assert any("verify" in step.lower() for step in next_steps)

    @pytest.mark.asyncio
    async def test_next_steps_include_domain_setup(self, client: AsyncClient):
        """Test that next steps include domain configuration."""
        response = await client.post(
            "/api/v1/onboarding/start",
            json={"email": "domain@example.com"},
        )

        next_steps = response.json()["next_steps"]
        assert any("domain" in step.lower() for step in next_steps)

    @pytest.mark.asyncio
    async def test_next_steps_include_dns(self, client: AsyncClient):
        """Test that next steps include DNS setup."""
        response = await client.post(
            "/api/v1/onboarding/start",
            json={"email": "dns@example.com"},
        )

        next_steps = response.json()["next_steps"]
        assert any(
            "spf" in step.lower() or "dkim" in step.lower() or "dmarc" in step.lower()
            for step in next_steps
        )
