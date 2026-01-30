"""Tests for configuration module."""

import pytest

from mailagent.config import Settings, get_settings


class TestSettings:
    """Tests for Settings class."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()

        assert settings.service_name == "mailagent"
        assert settings.debug is False
        assert settings.environment == "development"
        assert settings.api_prefix == "/api/v1"

    def test_rate_limit_defaults(self):
        """Test default rate limit settings."""
        settings = Settings()

        assert settings.rate_limit_enabled is True
        assert settings.default_requests_per_minute == 60
        assert settings.default_requests_per_day == 10000

    def test_warming_schedule_default(self):
        """Test default warming schedule."""
        settings = Settings()

        assert settings.default_warming_schedule == "moderate"

    def test_get_settings_cached(self):
        """Test that get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_custom_settings(self, monkeypatch):
        """Test settings from environment variables."""
        monkeypatch.setenv("SERVICE_NAME", "custom-mailagent")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Clear cache to pick up new env vars
        get_settings.cache_clear()
        settings = Settings()

        assert settings.service_name == "custom-mailagent"
        assert settings.debug is True
        assert settings.environment == "production"

        # Reset cache
        get_settings.cache_clear()

    def test_aws_settings_optional(self):
        """Test that AWS settings are optional."""
        settings = Settings()

        assert settings.aws_access_key_id is None
        assert settings.aws_secret_access_key is None
        assert settings.aws_region == "us-east-1"

    def test_smtp_settings_optional(self):
        """Test that SMTP settings are optional."""
        settings = Settings()

        assert settings.smtp_host is None
        assert settings.smtp_port == 587
        assert settings.smtp_use_tls is True
