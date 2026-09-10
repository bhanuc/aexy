"""Pydantic schemas for the alerting (observability → tickets) integration."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RoutingRuleMatch(BaseModel):
    """Match conditions for a routing rule (all present conditions must hold)."""
    service: str | None = Field(default=None, description="Glob matched against the alert's service, e.g. 'payments-*'")
    severity_gte: str | None = Field(default=None, description="Minimum severity: low|medium|high|critical")
    environment: str | None = None


class RoutingRule(BaseModel):
    match: RoutingRuleMatch = Field(default_factory=RoutingRuleMatch)
    team_id: str | None = None
    assignee_id: str | None = None
    form_id: str | None = None
    priority: str | None = None


class AlertIntegrationCreate(BaseModel):
    provider: str = "openobserve"
    name: str
    base_url: str | None = None
    default_form_id: str | None = None
    routing_rules: list[RoutingRule] = Field(default_factory=list)
    fingerprint_template: str | None = None
    dedup_window_minutes: int = 60
    comment_throttle_minutes: int = 15
    auto_resolve: bool = True


class AlertIntegrationUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    default_form_id: str | None = None
    routing_rules: list[RoutingRule] | None = None
    fingerprint_template: str | None = None
    dedup_window_minutes: int | None = None
    comment_throttle_minutes: int | None = None
    auto_resolve: bool | None = None
    enabled: bool | None = None


class AlertIntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    provider: str
    name: str
    base_url: str | None
    default_form_id: str | None
    routing_rules: list[dict]
    fingerprint_template: str | None
    dedup_window_minutes: int
    comment_throttle_minutes: int
    auto_resolve: bool
    enabled: bool
    webhook_url: str
    created_at: datetime
    updated_at: datetime


class AlertIntegrationSecretResponse(AlertIntegrationResponse):
    """Returned only on create / secret rotation — includes the signing secret once."""
    signing_secret: str


class AlertEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    integration_id: str
    fingerprint: str | None
    ticket_id: str | None
    action_taken: str | None
    error_message: str | None
    received_at: datetime
    processed_at: datetime | None
    # Which integration, for a history that spans all of them. Resolved once
    # server-side rather than left to the client, which would otherwise need a
    # second request just to turn an id into a name.
    integration_name: str | None = None
    # So a row can link to the ticket it produced. `ticket_id` was returned all
    # along and never rendered, because a link needs a number to show and
    # fetching one per row is N+1. Null when the ticket was deleted — 213 of one
    # desk's 430 events are in that state, and "deleted" is a better answer than
    # a blank cell.
    ticket_number: int | None = None
    # What the provider actually sent. Stored on the model and deliberately
    # omitted from this schema until now, which meant the one question a
    # developer has about a `dropped` event — what was in the payload? — could
    # only be answered with database access.
    raw_payload: dict | None = None


class AlertEventListResponse(BaseModel):
    events: list[AlertEventResponse]
    total: int


class TestAlertResponse(BaseModel):
    action_taken: str | None
    ticket_id: str | None
    fingerprint: str | None
    error_message: str | None
