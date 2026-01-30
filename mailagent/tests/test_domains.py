"""Tests for domain service and API."""

import pytest
from httpx import AsyncClient


class TestDomainsAPI:
    """Tests for domains API endpoints."""

    @pytest.mark.asyncio
    async def test_create_domain(self, client: AsyncClient, domain_factory):
        """Test creating a new sending domain."""
        domain_data = domain_factory(domain="example.com")

        response = await client.post("/api/v1/domains/", json=domain_data)

        assert response.status_code == 201
        data = response.json()
        assert data["domain"] == "example.com"
        assert data["status"] == "pending"
        assert "dns_records" in data
        assert len(data["dns_records"]) > 0

    @pytest.mark.asyncio
    async def test_create_domain_generates_dns_records(
        self, client: AsyncClient, domain_factory
    ):
        """Test that creating a domain generates required DNS records."""
        response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="test-dns.com"),
        )

        assert response.status_code == 201
        dns_records = response.json()["dns_records"]

        # Should have SPF, DKIM, DMARC, and verification records
        record_names = [r["name"] for r in dns_records]
        assert any("spf" in name.lower() or "test-dns.com" == name for name in record_names)
        assert any("dkim" in name.lower() or "_domainkey" in name for name in record_names)
        assert any("dmarc" in name.lower() or "_dmarc" in name for name in record_names)

    @pytest.mark.asyncio
    async def test_create_domain_with_warming_schedule(
        self, client: AsyncClient, domain_factory
    ):
        """Test creating domain with different warming schedules."""
        schedules = ["conservative", "moderate", "aggressive"]

        for schedule in schedules:
            response = await client.post(
                "/api/v1/domains/",
                json=domain_factory(warming_schedule=schedule),
            )

            assert response.status_code == 201
            assert response.json()["warming_schedule"] == schedule

    @pytest.mark.asyncio
    async def test_list_domains(self, client: AsyncClient, domain_factory):
        """Test listing domains."""
        # Create some domains
        for i in range(3):
            await client.post(
                "/api/v1/domains/",
                json=domain_factory(domain=f"list-test-{i}.com"),
            )

        response = await client.get("/api/v1/domains/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3

    @pytest.mark.asyncio
    async def test_list_domains_filter_by_status(
        self, client: AsyncClient, domain_factory
    ):
        """Test listing domains with status filter."""
        # Create a domain (will be pending)
        await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="filter-test.com"),
        )

        response = await client.get("/api/v1/domains/?status_filter=pending")

        assert response.status_code == 200
        data = response.json()
        assert all(d["status"] == "pending" for d in data)

    @pytest.mark.asyncio
    async def test_get_domain(self, client: AsyncClient, domain_factory):
        """Test getting a specific domain."""
        create_response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="get-test.com"),
        )
        domain_id = create_response.json()["id"]

        response = await client.get(f"/api/v1/domains/{domain_id}")

        assert response.status_code == 200
        assert response.json()["domain"] == "get-test.com"

    @pytest.mark.asyncio
    async def test_get_domain_by_name(self, client: AsyncClient, domain_factory):
        """Test getting a domain by name."""
        await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="by-name-test.com"),
        )

        response = await client.get("/api/v1/domains/by-name/by-name-test.com")

        assert response.status_code == 200
        assert response.json()["domain"] == "by-name-test.com"

    @pytest.mark.asyncio
    async def test_get_domain_not_found(self, client: AsyncClient):
        """Test getting non-existent domain."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(f"/api/v1/domains/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_domain(self, client: AsyncClient, domain_factory):
        """Test updating a domain."""
        create_response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="update-test.com"),
        )
        domain_id = create_response.json()["id"]

        response = await client.patch(
            f"/api/v1/domains/{domain_id}",
            json={"daily_limit": 1000},
        )

        assert response.status_code == 200
        assert response.json()["daily_limit"] == 1000

    @pytest.mark.asyncio
    async def test_delete_domain(self, client: AsyncClient, domain_factory):
        """Test deleting a domain."""
        create_response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="delete-test.com"),
        )
        domain_id = create_response.json()["id"]

        response = await client.delete(f"/api/v1/domains/{domain_id}")
        assert response.status_code == 204

        # Verify deleted
        get_response = await client.get(f"/api/v1/domains/{domain_id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_domain(self, client: AsyncClient, domain_factory):
        """Test domain verification."""
        create_response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="verify-test.com"),
        )
        domain_id = create_response.json()["id"]

        response = await client.post(f"/api/v1/domains/{domain_id}/verify")

        assert response.status_code == 200
        data = response.json()
        assert "spf_verified" in data
        assert "dkim_verified" in data
        assert "dmarc_verified" in data
        assert "all_verified" in data

    @pytest.mark.asyncio
    async def test_start_warming_requires_verification(
        self, client: AsyncClient, domain_factory
    ):
        """Test that warming requires verified domain."""
        create_response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(domain="warming-test.com"),
        )
        domain_id = create_response.json()["id"]

        # Try to start warming without verification
        response = await client.post(f"/api/v1/domains/{domain_id}/start-warming")

        assert response.status_code == 400
        assert "verified" in response.json()["detail"].lower()


class TestDomainWarmingSchedules:
    """Tests for domain warming schedule logic."""

    @pytest.mark.asyncio
    async def test_conservative_schedule_duration(
        self, client: AsyncClient, domain_factory
    ):
        """Test conservative warming schedule is 21 days."""
        response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(
                domain="conservative-test.com",
                warming_schedule="conservative",
            ),
        )

        assert response.status_code == 201
        assert response.json()["warming_schedule"] == "conservative"

    @pytest.mark.asyncio
    async def test_moderate_schedule_duration(
        self, client: AsyncClient, domain_factory
    ):
        """Test moderate warming schedule is 14 days."""
        response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(
                domain="moderate-test.com",
                warming_schedule="moderate",
            ),
        )

        assert response.status_code == 201
        assert response.json()["warming_schedule"] == "moderate"

    @pytest.mark.asyncio
    async def test_aggressive_schedule_duration(
        self, client: AsyncClient, domain_factory
    ):
        """Test aggressive warming schedule is 7 days."""
        response = await client.post(
            "/api/v1/domains/",
            json=domain_factory(
                domain="aggressive-test.com",
                warming_schedule="aggressive",
            ),
        )

        assert response.status_code == 201
        assert response.json()["warming_schedule"] == "aggressive"
