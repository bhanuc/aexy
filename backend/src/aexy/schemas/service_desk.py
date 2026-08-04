"""Bimaplan Service Desk Pydantic schemas (master data, intake, ticket views)."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RequestType = Literal["query", "policy_issuance", "claims", "payout"]
PendingWith = Literal[
    "insurer", "partner", "sales", "third_party", "finance", "kam", "marketing", "closed"
]
TicketOrigin = Literal["email", "manual", "internal"]
MailboxChannel = Literal["webhook", "gmail_sync"]


# ==================== Partners ====================

class PartnerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    assigned_kam_id: str | None = None
    domains: list[str] = Field(default_factory=list)
    is_active: bool = True


class PartnerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    assigned_kam_id: str | None = None
    domains: list[str] | None = None
    is_active: bool | None = None


class PartnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    assigned_kam_id: str | None = None
    is_active: bool = True
    domains: list[str] = Field(default_factory=list)
    created_at: datetime


# ==================== Insurers ====================

class InsurerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    domains: list[str] = Field(default_factory=list)
    is_active: bool = True


class InsurerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    domains: list[str] | None = None
    is_active: bool | None = None


class InsurerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    is_active: bool = True
    domains: list[str] = Field(default_factory=list)
    created_at: datetime


# ==================== LOBs ====================

class LOBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    is_active: bool = True


class LOBResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    is_active: bool = True
    created_at: datetime


# ==================== Mailboxes ====================

class MailboxCreate(BaseModel):
    address: str = Field(..., min_length=3, max_length=255)
    channel: MailboxChannel = "webhook"
    integration_id: str | None = None
    is_active: bool = True


class MailboxUpdate(BaseModel):
    channel: MailboxChannel | None = None
    integration_id: str | None = None
    is_active: bool | None = None


class MailboxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    address: str
    channel: MailboxChannel
    integration_id: str | None = None
    is_active: bool = True
    created_at: datetime


# ==================== Intake (internal, normalized email) ====================

class InboundAttachment(BaseModel):
    """A bounded, provider-normalized attachment summary for intake AI."""

    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    preview: str | None = None
    # The provider's handle for re-fetching the bytes later. Captured whether or
    # not AI is on, because it is an identifier and not content: without it a KAM
    # can see that a claim register arrived but can never forward it, which is
    # the whole reason the file was sent to the desk.
    attachment_id: str | None = None


class InboundEmail(BaseModel):
    """A provider/channel-agnostic inbound email handed to the intake service."""

    to: str
    from_email: str
    from_name: str | None = None
    subject: str = ""
    body_text: str = ""
    body_html: str | None = None
    message_id: str | None = None
    thread_id: str | None = None
    in_reply_to: str | None = None
    attachments: list[InboundAttachment] = Field(default_factory=list)
    # Raw message headers, keys lower-cased. Intake reads these to recognise
    # automatic responses and our own outbound mail; providers hand them over in
    # whatever case and value type they like, hence the normalisation below.
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("headers", mode="before")
    @classmethod
    def _normalise_headers(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(name).strip().lower(): str(item) for name, item in value.items()}


# ==================== Manual ticket logging ====================

class ManualTicketCreate(BaseModel):
    requester_email: str | None = None
    requester_name: str | None = None
    subject: str = Field(..., min_length=1)
    body: str = ""
    request_type: RequestType = "query"
    lob_id: str | None = None
    partner_id: str | None = None


# ==================== Ticket views ====================

class ServiceDeskTicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ticket_id: str
    workspace_id: str
    ticket_number: int | None = None
    display_id: str | None = None
    subject: str | None = None
    requester_email: str | None = None
    requester_name: str | None = None
    status: str | None = None
    lob_id: str | None = None
    partner_id: str | None = None
    partner_name: str | None = None
    insurer_id: str | None = None
    assigned_kam_id: str | None = None
    request_type: RequestType
    pending_with: PendingWith
    origin: TicketOrigin
    needs_triage: bool
    ai_confidence: float | None = None
    created_at: datetime


# ==================== Pending-With transitions & TAT (Phase 2) ====================

BreachLevel = Literal["green", "amber", "red"]


class PendingWithUpdate(BaseModel):
    pending_with: PendingWith
    note: str | None = None


class ConvertToTaskRequest(BaseModel):
    project_id: str
    sprint_id: str | None = None
    title: str | None = None
    priority: str = "medium"


class ConvertToTaskResponse(BaseModel):
    task_id: str
    task_title: str
    linked: bool


class TicketFieldsUpdate(BaseModel):
    """KAM corrections to AI-set / auto-assigned fields."""
    request_type: RequestType | None = None
    lob_id: str | None = None
    partner_id: str | None = None
    insurer_id: str | None = None
    needs_triage: bool | None = None
    assigned_kam_id: str | None = None


class DetectedIssue(BaseModel):
    summary: str = Field(..., min_length=1, max_length=240)
    request_type: RequestType
    lob: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    split_reason: str | None = None


class HumanSplitRequest(BaseModel):
    issue_indexes: list[int] = Field(..., min_length=1)


class HumanSplitResponse(BaseModel):
    created_ticket_ids: list[str]
    created_ticket_display_ids: list[str]


class SegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pending_with: PendingWith
    entered_at: datetime
    exited_at: datetime | None = None
    duration_seconds: int | None = None
    changed_by_id: str | None = None
    note: str | None = None


class TicketTAT(BaseModel):
    overall_seconds: int
    overall_days: float
    current_pending_with: PendingWith | None = None
    current_stage_seconds: int = 0
    current_stage_days: float = 0.0
    breach_level: BreachLevel = "green"
    # seconds spent with each stakeholder (excludes the terminal 'closed' state)
    stakeholder_seconds: dict[str, int] = Field(default_factory=dict)


class ServiceDeskCorrespondence(BaseModel):
    """An external email matched to this Service Desk ticket, either direction."""

    id: str
    author_email: str | None = None
    content: str
    created_at: datetime
    # "outgoing" is mail a KAM or manager sent from the ticket; "incoming" is a
    # stakeholder reply the mailbox sync matched onto it. The card must say
    # which, or a thread of both reads as if the stakeholder said everything.
    direction: Literal["incoming", "outgoing"] = "incoming"


class TicketEmailRecipient(BaseModel):
    """One address the ticket may be emailed from the desk."""

    email: str
    label: str


class TicketAttachment(BaseModel):
    """A file that arrived on the ticket's original email."""

    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    # False when the provider gave us no handle for the bytes, e.g. mail that
    # arrived before attachment ids were captured. The UI must not offer to
    # forward a file the send would then fail on.
    can_forward: bool = False


class StakeholderEmailRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=255)
    subject: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=20000)
    # Filenames chosen from the ticket's own attachments. Never a client-supplied
    # payload: the bytes are re-fetched from the original email, so a caller
    # cannot use the desk to send a file that never arrived on the ticket.
    attachment_filenames: list[str] = Field(default_factory=list, max_length=10)


class ServiceDeskTicketDetail(ServiceDeskTicketResponse):
    body: str | None = None
    linked_task_id: str | None = None
    detected_issues: list[DetectedIssue] = Field(default_factory=list)
    split_done_indexes: list[int] = Field(default_factory=list)
    segments: list[SegmentResponse] = Field(default_factory=list)
    correspondence: list[ServiceDeskCorrespondence] = Field(default_factory=list)
    email_recipients: list[TicketEmailRecipient] = Field(default_factory=list)
    attachments: list[TicketAttachment] = Field(default_factory=list)
    tat: TicketTAT


# ==================== Dashboard (stakeholder × age) ====================

class StakeholderBucket(BaseModel):
    pending_with: PendingWith
    green: int = 0   # 0–1 day in current stage
    amber: int = 0   # 1–2 days (watch)
    red: int = 0     # > 2 days (breach)
    total: int = 0


class DashboardTicket(BaseModel):
    ticket_id: str
    display_id: str
    subject: str | None = None
    lob_name: str | None = None
    partner_name: str | None = None
    request_type: RequestType
    pending_with: PendingWith
    assigned_kam_id: str | None = None
    days_in_stage: float = 0.0
    overall_days: float = 0.0
    breach_level: BreachLevel = "green"
    needs_triage: bool = False
    status: str | None = None


class ServiceDeskDashboard(BaseModel):
    stakeholders: list[StakeholderBucket] = Field(default_factory=list)
    tickets: list[DashboardTicket] = Field(default_factory=list)
    total_open: int = 0
    breaching: int = 0


# ==================== Org-level settings ====================

class TestStageSLA(BaseModel):
    """A deliberately short, test-only working-time threshold for one stage."""

    amber_minutes: int = Field(..., ge=1, le=240)
    red_minutes: int = Field(..., ge=2, le=240)

    @model_validator(mode="after")
    def _red_must_follow_amber(self):
        if self.red_minutes <= self.amber_minutes:
            raise ValueError("red_minutes must be greater than amber_minutes")
        return self


class TestSLAOverride(BaseModel):
    """Temporary minute rules for the three externally visible desk stages.

    The short expiry is an intentional safety rail: these values exist only to
    make a controlled test observable, never to replace the two-business-day
    operating target.
    """

    expires_at: datetime
    kam: TestStageSLA
    insurer: TestStageSLA
    partner: TestStageSLA

    @field_validator("expires_at")
    @classmethod
    def _must_be_a_short_future_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        now = datetime.now(timezone.utc)
        expires_at = value.astimezone(timezone.utc)
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")
        if expires_at > now + timedelta(hours=24):
            raise ValueError("test SLA overrides may last at most 24 hours")
        return expires_at

class ServiceDeskSettings(BaseModel):
    """Workspace-level Service Desk settings."""
    ai_classification_enabled: bool = False
    # Whether intake may auto-create a second ticket when one email carries two
    # clearly different, high-confidence requests. Off by default: everything
    # else stays a single ticket flagged for triage, which is the safe outcome.
    auto_split_enabled: bool = False
    # Whether the CALLER may edit master data / settings / templates, i.e. holds
    # can_manage_service_desk. Returned here so the Master Data page can hide
    # controls it would only get a 403 from; the server-side gate is still the
    # authority (api/service_desk.py::require_manage).
    can_manage: bool = False
    # How wide the caller's ticket view is: "all" (full-view or manager),
    # "function" (their department's pending-with queue), "assigned" (an Ops KAM,
    # who sees only their own tickets) or "none" (in no department, so no ticket
    # can ever match). Lets the tickets page distinguish "nothing to do" from
    # "you only ever see your own" and from "nobody has placed you in a
    # department yet". Defaults to "all" so a response from an older server can
    # never raise a false alarm.
    scope: Literal["all", "assigned", "function", "none"] = "all"
    # The working window the breach clock runs on, IST, as "HH:MM". Returned so
    # the Master Data page can show and edit it — the clock reads the same values
    # (services/service_desk_clock.py::load_clock).
    working_hours_start: str = "09:30"
    working_hours_end: str = "18:30"
    # ``None`` means the normal two-business-day target is in force. Expired
    # values are deliberately omitted by the service and ignored by the clock.
    test_sla: TestSLAOverride | None = None


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ServiceDeskSettingsUpdate(BaseModel):
    """Both fields optional so the page can PATCH either one on its own."""

    ai_classification_enabled: bool | None = None
    auto_split_enabled: bool | None = None
    working_hours_start: str | None = Field(None, pattern=_HHMM)
    working_hours_end: str | None = Field(None, pattern=_HHMM)
    # Send a complete replacement when starting or changing a test. Send only
    # ``clear_test_sla`` to remove it immediately after the test is complete.
    test_sla: TestSLAOverride | None = None
    clear_test_sla: bool = False

    @model_validator(mode="after")
    def _window_must_be_forward(self):
        """Reject an inverted window at the door.

        ``Clock`` falls back to a 9h day if it ever meets one, but that guard is
        for data written before this validation existed — it should not double as
        permission to save nonsense, which would silently change what every
        breach figure means.
        """
        if self.working_hours_start and self.working_hours_end:
            if self.working_hours_end <= self.working_hours_start:  # "HH:MM" sorts correctly
                raise ValueError("working_hours_end must be later than working_hours_start")
        if self.clear_test_sla and self.test_sla is not None:
            raise ValueError("send either test_sla or clear_test_sla, not both")
        return self


class ServiceDeskTemplate(BaseModel):
    key: str
    name: str
    subject: str
    body: str
    variables: list[str] = Field(default_factory=list)
    customised: bool = False


class ServiceDeskTemplateUpdate(BaseModel):
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
