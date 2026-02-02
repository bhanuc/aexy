"""Tests for admin service and API."""

import pytest
from httpx import AsyncClient


class TestAdminAPI:
    """Tests for admin API endpoints."""

    @pytest.mark.asyncio
    async def test_get_dashboard(self, client: AsyncClient):
        """Test getting admin dashboard."""
        response = await client.get("/api/v1/admin/dashboard")

        assert response.status_code == 200
        data = response.json()
        assert "total_providers" in data
        assert "active_providers" in data
        assert "total_domains" in data
        assert "verified_domains" in data
        assert "total_inboxes" in data

    @pytest.mark.asyncio
    async def test_create_provider(self, client: AsyncClient, provider_factory):
        """Test creating a new email provider."""
        provider_data = provider_factory(name="Test SES Provider")

        response = await client.post("/api/v1/admin/providers", json=provider_data)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test SES Provider"
        assert data["provider_type"] == "ses"
        assert data["status"] == "setup"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_provider_with_different_types(
        self, client: AsyncClient, provider_factory
    ):
        """Test creating providers with different types."""
        provider_types = ["ses", "sendgrid", "mailgun", "postmark", "smtp"]

        for ptype in provider_types:
            provider_data = provider_factory(
                name=f"Test {ptype.upper()} Provider",
                provider_type=ptype,
            )

            response = await client.post("/api/v1/admin/providers", json=provider_data)

            assert response.status_code == 201
            assert response.json()["provider_type"] == ptype

    @pytest.mark.asyncio
    async def test_list_providers(self, client: AsyncClient, provider_factory):
        """Test listing providers."""
        # Create some providers
        for i in range(3):
            await client.post(
                "/api/v1/admin/providers",
                json=provider_factory(name=f"Provider {i}"),
            )

        response = await client.get("/api/v1/admin/providers")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3

    @pytest.mark.asyncio
    async def test_list_providers_with_pagination(
        self, client: AsyncClient, provider_factory
    ):
        """Test listing providers with pagination."""
        # Create providers
        for i in range(5):
            await client.post(
                "/api/v1/admin/providers",
                json=provider_factory(name=f"Paginated Provider {i}"),
            )

        response = await client.get("/api/v1/admin/providers?limit=2&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_get_provider(self, client: AsyncClient, provider_factory):
        """Test getting a specific provider."""
        # Create provider
        create_response = await client.post(
            "/api/v1/admin/providers",
            json=provider_factory(name="Get Test Provider"),
        )
        provider_id = create_response.json()["id"]

        response = await client.get(f"/api/v1/admin/providers/{provider_id}")

        assert response.status_code == 200
        assert response.json()["name"] == "Get Test Provider"

    @pytest.mark.asyncio
    async def test_get_provider_not_found(self, client: AsyncClient):
        """Test getting non-existent provider."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(f"/api/v1/admin/providers/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_provider(self, client: AsyncClient, provider_factory):
        """Test updating a provider."""
        # Create provider
        create_response = await client.post(
            "/api/v1/admin/providers",
            json=provider_factory(name="Original Name"),
        )
        provider_id = create_response.json()["id"]

        # Update provider
        response = await client.patch(
            f"/api/v1/admin/providers/{provider_id}",
            json={"name": "Updated Name", "priority": 50},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["priority"] == 50

    @pytest.mark.asyncio
    async def test_update_provider_status(self, client: AsyncClient, provider_factory):
        """Test updating provider status."""
        # Create provider
        create_response = await client.post(
            "/api/v1/admin/providers",
            json=provider_factory(),
        )
        provider_id = create_response.json()["id"]

        # Update status
        response = await client.patch(
            f"/api/v1/admin/providers/{provider_id}",
            json={"status": "active"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "active"

    @pytest.mark.asyncio
    async def test_delete_provider(self, client: AsyncClient, provider_factory):
        """Test deleting a provider."""
        # Create provider
        create_response = await client.post(
            "/api/v1/admin/providers",
            json=provider_factory(),
        )
        provider_id = create_response.json()["id"]

        # Delete provider
        response = await client.delete(f"/api/v1/admin/providers/{provider_id}")
        assert response.status_code == 204

        # Verify deleted
        get_response = await client.get(f"/api/v1/admin/providers/{provider_id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_provider_not_found(self, client: AsyncClient):
        """Test deleting non-existent provider."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(f"/api/v1/admin/providers/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_test_provider_connection(
        self, client: AsyncClient, provider_factory
    ):
        """Test testing provider connection."""
        # Create provider
        create_response = await client.post(
            "/api/v1/admin/providers",
            json=provider_factory(),
        )
        provider_id = create_response.json()["id"]

        response = await client.post(f"/api/v1/admin/providers/{provider_id}/test")

        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    @pytest.mark.asyncio
    async def test_set_default_provider(self, client: AsyncClient, provider_factory):
        """Test setting a provider as default."""
        # Create first provider as default
        response1 = await client.post(
            "/api/v1/admin/providers",
            json=provider_factory(is_default=True),
        )
        provider1_id = response1.json()["id"]

        # Create second provider as default (should unset first)
        response2 = await client.post(
            "/api/v1/admin/providers",
            json=provider_factory(is_default=True),
        )
        provider2_id = response2.json()["id"]

        # Verify second is default
        get_response2 = await client.get(f"/api/v1/admin/providers/{provider2_id}")
        assert get_response2.json()["is_default"] is True

        # Verify first is no longer default
        get_response1 = await client.get(f"/api/v1/admin/providers/{provider1_id}")
        assert get_response1.json()["is_default"] is False
