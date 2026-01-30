"""Client for integrating with the Mailagent service."""

import httpx
from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel, EmailStr

from aexy.core.config import get_settings


class MailagentError(Exception):
    """Error from Mailagent service."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class EmailAddress(BaseModel):
    """Email address with optional name."""
    address: EmailStr
    name: Optional[str] = None


class SendEmailRequest(BaseModel):
    """Request to send an email."""
    from_address: EmailAddress
    to_addresses: list[EmailAddress]
    cc_addresses: list[EmailAddress] = []
    bcc_addresses: list[EmailAddress] = []
    reply_to: Optional[EmailAddress] = None
    subject: str
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    tags: list[str] = []
    metadata: dict = {}


class SendResult(BaseModel):
    """Result of sending an email."""
    success: bool
    message_id: Optional[str] = None
    provider: str
    error: Optional[str] = None


class AgentCreate(BaseModel):
    """Request to create an agent."""
    name: str
    agent_type: str
    description: Optional[str] = None
    llm_provider: str = "gemini"
    confidence_threshold: float = 0.70


class AgentResponse(BaseModel):
    """Agent response."""
    id: UUID
    name: str
    agent_type: str
    description: Optional[str]
    llm_provider: str
    is_active: bool
    total_processed: int
    mention_handle: Optional[str] = None


class AgentInfo(BaseModel):
    """Agent info for @mention discovery."""
    id: UUID
    name: str
    agent_type: str
    mention_handle: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class InvokeAgentRequest(BaseModel):
    """Request to invoke an agent."""
    agent_id: Optional[UUID] = None
    agent_handle: Optional[str] = None
    workspace_id: UUID
    source_type: str = "comment"
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None
    activity_id: Optional[UUID] = None
    invoked_by: UUID
    invoked_by_name: Optional[str] = None
    instruction: Optional[str] = None
    context: Optional[dict] = None


class InvocationResponse(BaseModel):
    """Response after invoking an agent."""
    id: UUID
    agent_id: UUID
    status: str


class AgentActionResponse(BaseModel):
    """Agent action details."""
    id: UUID
    invocation_id: UUID
    agent_id: UUID
    action_type: str
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[UUID] = None
    action_payload: dict
    confidence: float
    reasoning: Optional[str] = None
    preview_summary: Optional[str] = None
    requires_review: bool
    review_status: str
    reviewed_by: Optional[UUID] = None
    reviewed_by_name: Optional[str] = None
    executed: bool
    execution_result: Optional[dict] = None
    execution_error: Optional[str] = None


class MailagentClient:
    """Client for the Mailagent microservice.

    Provides a clean interface for the Aexy backend to interact with
    the Mailagent service for email operations and AI agents.

    Usage:
        client = MailagentClient()

        # Send an email
        result = await client.send_email(
            from_address=("sender@example.com", "Sender Name"),
            to_addresses=[("recipient@example.com", "Recipient")],
            subject="Hello",
            body_text="Hello, World!"
        )

        # Create an agent
        agent = await client.create_agent(
            name="Support Agent",
            agent_type="support",
            description="Handles customer support emails"
        )

        # Process incoming email
        result = await client.process_email(
            inbox_id=inbox_id,
            from_address="customer@example.com",
            subject="Help needed",
            body_text="I have a question..."
        )
    """

    def __init__(self, base_url: Optional[str] = None):
        """Initialize the client.

        Args:
            base_url: Mailagent service URL. Defaults to settings.mailagent_url
        """
        if base_url:
            self.base_url = base_url
        else:
            settings = get_settings()
            self.base_url = getattr(settings, 'mailagent_url', 'http://localhost:8001')
        self.api_prefix = "/api/v1"

    def _url(self, path: str) -> str:
        """Build full URL for endpoint."""
        return f"{self.base_url}{self.api_prefix}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> dict:
        """Make HTTP request to Mailagent."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(method, self._url(path), **kwargs)

                if response.status_code >= 400:
                    error_detail = response.text
                    try:
                        error_detail = response.json().get('detail', response.text)
                    except Exception:
                        pass
                    raise MailagentError(
                        f"Mailagent error: {error_detail}",
                        status_code=response.status_code
                    )

                if response.status_code == 204:
                    return {}

                return response.json()

            except httpx.RequestError as e:
                raise MailagentError(f"Connection error: {str(e)}")

    # ==========================================
    # EMAIL SENDING
    # ==========================================

    async def send_email(
        self,
        from_address: tuple[str, Optional[str]],
        to_addresses: list[tuple[str, Optional[str]]],
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        cc_addresses: Optional[list[tuple[str, Optional[str]]]] = None,
        bcc_addresses: Optional[list[tuple[str, Optional[str]]]] = None,
        reply_to: Optional[tuple[str, Optional[str]]] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> SendResult:
        """Send an email via Mailagent.

        Args:
            from_address: Tuple of (email, name) for sender
            to_addresses: List of (email, name) tuples for recipients
            subject: Email subject
            body_text: Plain text body
            body_html: HTML body
            cc_addresses: Optional CC recipients
            bcc_addresses: Optional BCC recipients
            reply_to: Optional reply-to address
            tags: Optional tags for tracking
            metadata: Optional metadata

        Returns:
            SendResult with success status and message ID
        """
        def make_addr(addr: tuple[str, Optional[str]]) -> dict:
            return {"address": addr[0], "name": addr[1]}

        payload = {
            "from_address": make_addr(from_address),
            "to_addresses": [make_addr(a) for a in to_addresses],
            "subject": subject,
        }

        if body_text:
            payload["body_text"] = body_text
        if body_html:
            payload["body_html"] = body_html
        if cc_addresses:
            payload["cc_addresses"] = [make_addr(a) for a in cc_addresses]
        if bcc_addresses:
            payload["bcc_addresses"] = [make_addr(a) for a in bcc_addresses]
        if reply_to:
            payload["reply_to"] = make_addr(reply_to)
        if tags:
            payload["tags"] = tags
        if metadata:
            payload["metadata"] = metadata

        result = await self._request("POST", "/send/email", json=payload)
        return SendResult(**result)

    async def send_batch(
        self,
        messages: list[SendEmailRequest],
        concurrency: int = 10,
    ) -> list[SendResult]:
        """Send multiple emails in batch.

        Args:
            messages: List of email requests
            concurrency: Max concurrent sends

        Returns:
            List of SendResults
        """
        result = await self._request(
            "POST",
            "/send/batch",
            json={
                "messages": [m.model_dump() for m in messages],
                "concurrency": concurrency,
            },
        )
        return [SendResult(**r) for r in result.get("results", [])]

    # ==========================================
    # AGENTS
    # ==========================================

    async def create_agent(
        self,
        name: str,
        agent_type: str,
        description: Optional[str] = None,
        llm_provider: str = "gemini",
        confidence_threshold: float = 0.70,
    ) -> AgentResponse:
        """Create a new AI email agent.

        Args:
            name: Agent name
            agent_type: Type (support, sales, scheduling, onboarding, recruiting, newsletter)
            description: Optional description
            llm_provider: LLM to use (gemini, claude)
            confidence_threshold: Auto-reply threshold

        Returns:
            Created agent details
        """
        result = await self._request(
            "POST",
            "/agents",
            json={
                "name": name,
                "agent_type": agent_type,
                "description": description,
                "llm_provider": llm_provider,
                "confidence_threshold": confidence_threshold,
            },
        )
        return AgentResponse(**result)

    async def get_agent(self, agent_id: UUID) -> AgentResponse:
        """Get agent by ID."""
        result = await self._request("GET", f"/agents/{agent_id}")
        return AgentResponse(**result)

    async def list_agents(
        self,
        agent_type: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> list[AgentResponse]:
        """List agents with optional filtering."""
        params = {}
        if agent_type:
            params["agent_type"] = agent_type
        if is_active is not None:
            params["is_active"] = is_active

        result = await self._request("GET", "/agents", params=params)
        return [AgentResponse(**a) for a in result.get("agents", [])]

    async def update_agent(
        self,
        agent_id: UUID,
        **updates,
    ) -> AgentResponse:
        """Update an agent."""
        result = await self._request("PATCH", f"/agents/{agent_id}", json=updates)
        return AgentResponse(**result)

    async def delete_agent(self, agent_id: UUID) -> None:
        """Delete an agent."""
        await self._request("DELETE", f"/agents/{agent_id}")

    async def assign_agent_to_inbox(
        self,
        inbox_id: UUID,
        agent_id: UUID,
        priority: int = 100,
    ) -> dict:
        """Assign an agent to an inbox."""
        return await self._request(
            "POST",
            f"/agents/inboxes/{inbox_id}/agents",
            json={"agent_id": str(agent_id), "priority": priority},
        )

    # ==========================================
    # EMAIL PROCESSING
    # ==========================================

    async def process_email(
        self,
        inbox_id: UUID,
        from_address: str,
        subject: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        from_name: Optional[str] = None,
        to_addresses: Optional[list[dict]] = None,
        message_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> dict:
        """Process an incoming email through AI agents.

        Args:
            inbox_id: Target inbox ID
            from_address: Sender email
            subject: Email subject
            body_text: Plain text body
            body_html: HTML body
            from_name: Sender name
            to_addresses: Recipient list
            message_id: RFC 5322 message ID
            in_reply_to: In-Reply-To header

        Returns:
            Processing result with agent decision
        """
        return await self._request(
            "POST",
            "/process/incoming",
            json={
                "inbox_id": str(inbox_id),
                "from_address": from_address,
                "from_name": from_name,
                "to_addresses": to_addresses or [{"email": "inbox@example.com"}],
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
                "message_id": message_id,
                "in_reply_to": in_reply_to,
            },
        )

    async def get_pending_approvals(
        self,
        inbox_id: Optional[UUID] = None,
    ) -> dict:
        """Get pending agent decisions awaiting approval."""
        params = {}
        if inbox_id:
            params["inbox_id"] = str(inbox_id)
        return await self._request("GET", "/process/pending", params=params)

    async def approve_decision(
        self,
        decision_id: UUID,
        modified_response: Optional[str] = None,
    ) -> dict:
        """Approve and execute an agent decision."""
        params = {}
        if modified_response:
            params["modified_response"] = modified_response
        return await self._request("POST", f"/process/approve/{decision_id}", params=params)

    async def reject_decision(
        self,
        decision_id: UUID,
        feedback: Optional[str] = None,
    ) -> dict:
        """Reject an agent decision with optional feedback."""
        params = {}
        if feedback:
            params["feedback"] = feedback
        return await self._request("POST", f"/process/reject/{decision_id}", params=params)

    # ==========================================
    # DOMAINS & INBOXES
    # ==========================================

    async def list_domains(self) -> list[dict]:
        """List all domains."""
        result = await self._request("GET", "/domains")
        return result.get("domains", [])

    async def get_domain(self, domain_id: UUID) -> dict:
        """Get domain details."""
        return await self._request("GET", f"/domains/{domain_id}")

    async def list_inboxes(self, domain_id: Optional[UUID] = None) -> list[dict]:
        """List inboxes, optionally filtered by domain."""
        params = {}
        if domain_id:
            params["domain_id"] = str(domain_id)
        result = await self._request("GET", "/admin/inboxes", params=params)
        return result.get("inboxes", [])

    # ==========================================
    # HEALTH & STATUS
    # ==========================================

    async def health_check(self) -> dict:
        """Check Mailagent service health."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{self.base_url}/health")
                return response.json()
            except Exception as e:
                return {"status": "unhealthy", "error": str(e)}

    async def get_agent_metrics(self, agent_id: UUID) -> dict:
        """Get metrics for an agent."""
        return await self._request("GET", f"/agents/{agent_id}/metrics")

    # ==========================================
    # AGENT INVOCATIONS
    # ==========================================

    async def get_workspace_agents(
        self,
        workspace_id: UUID,
    ) -> list[AgentInfo]:
        """Get all agents available in a workspace for @mention discovery.

        Args:
            workspace_id: Workspace ID

        Returns:
            List of agents with their mention handles
        """
        result = await self._request(
            "GET",
            "/invocations/agents",
            params={"workspace_id": str(workspace_id)},
        )
        return [AgentInfo(**a) for a in result]

    async def parse_mentions(
        self,
        text: str,
        workspace_id: UUID,
    ) -> list[AgentInfo]:
        """Parse @mentions from text and return matching agents.

        Args:
            text: Text containing @mentions (e.g., "Hey @support-agent please help")
            workspace_id: Workspace ID

        Returns:
            List of agents that were mentioned
        """
        result = await self._request(
            "POST",
            "/invocations/parse-mentions",
            json={"text": text, "workspace_id": str(workspace_id)},
        )
        return [AgentInfo(**a) for a in result.get("agents", [])]

    async def invoke_agent(
        self,
        workspace_id: UUID,
        invoked_by: UUID,
        agent_id: Optional[UUID] = None,
        agent_handle: Optional[str] = None,
        source_type: str = "comment",
        entity_type: Optional[str] = None,
        entity_id: Optional[UUID] = None,
        activity_id: Optional[UUID] = None,
        invoked_by_name: Optional[str] = None,
        instruction: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> InvocationResponse:
        """Invoke an agent to process a request.

        The agent will analyze the context and generate proposed actions.
        Actions may require human review based on confidence.

        Args:
            workspace_id: Workspace ID
            invoked_by: User ID invoking the agent
            agent_id: Agent ID (optional if agent_handle provided)
            agent_handle: Agent @mention handle (optional if agent_id provided)
            source_type: How the agent was invoked (comment, direct, scheduled)
            entity_type: Type of entity (task, ticket, crm_record, etc.)
            entity_id: ID of the entity being worked on
            activity_id: ID of the activity/comment that triggered this
            invoked_by_name: User's display name
            instruction: Instruction/prompt for the agent
            context: Additional context for the agent

        Returns:
            InvocationResponse with the invocation ID
        """
        payload = {
            "workspace_id": str(workspace_id),
            "invoked_by": str(invoked_by),
            "source_type": source_type,
        }

        if agent_id:
            payload["agent_id"] = str(agent_id)
        if agent_handle:
            payload["agent_handle"] = agent_handle
        if entity_type:
            payload["entity_type"] = entity_type
        if entity_id:
            payload["entity_id"] = str(entity_id)
        if activity_id:
            payload["activity_id"] = str(activity_id)
        if invoked_by_name:
            payload["invoked_by_name"] = invoked_by_name
        if instruction:
            payload["instruction"] = instruction
        if context:
            payload["context"] = context

        result = await self._request("POST", "/invocations/invoke", json=payload)
        return InvocationResponse(**result)

    async def get_pending_actions(
        self,
        workspace_id: UUID,
        agent_id: Optional[UUID] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[UUID] = None,
        limit: int = 50,
    ) -> list[AgentActionResponse]:
        """Get pending actions requiring human review.

        Args:
            workspace_id: Workspace ID
            agent_id: Optional filter by agent
            entity_type: Optional filter by entity type
            entity_id: Optional filter by specific entity
            limit: Maximum number of actions to return

        Returns:
            List of pending actions
        """
        params = {
            "workspace_id": str(workspace_id),
            "limit": limit,
        }
        if agent_id:
            params["agent_id"] = str(agent_id)
        if entity_type:
            params["entity_type"] = entity_type
        if entity_id:
            params["entity_id"] = str(entity_id)

        result = await self._request("GET", "/invocations/pending", params=params)
        return [AgentActionResponse(**a) for a in result.get("actions", [])]

    async def approve_action(
        self,
        action_id: UUID,
        reviewed_by: UUID,
        reviewed_by_name: Optional[str] = None,
        notes: Optional[str] = None,
        modified_payload: Optional[dict] = None,
    ) -> AgentActionResponse:
        """Approve an agent action for execution.

        Args:
            action_id: ID of the action to approve
            reviewed_by: User ID approving the action
            reviewed_by_name: User's display name
            notes: Optional review notes
            modified_payload: Optional modified payload to use instead

        Returns:
            Updated action
        """
        payload = {"reviewed_by": str(reviewed_by)}
        if reviewed_by_name:
            payload["reviewed_by_name"] = reviewed_by_name
        if notes:
            payload["notes"] = notes
        if modified_payload:
            payload["modified_payload"] = modified_payload

        result = await self._request(
            "POST",
            f"/invocations/actions/{action_id}/approve",
            json=payload,
        )
        return AgentActionResponse(**result)

    async def reject_action(
        self,
        action_id: UUID,
        reviewed_by: UUID,
        reviewed_by_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> AgentActionResponse:
        """Reject an agent action.

        Args:
            action_id: ID of the action to reject
            reviewed_by: User ID rejecting the action
            reviewed_by_name: User's display name
            notes: Optional rejection reason

        Returns:
            Updated action
        """
        payload = {"reviewed_by": str(reviewed_by)}
        if reviewed_by_name:
            payload["reviewed_by_name"] = reviewed_by_name
        if notes:
            payload["notes"] = notes

        result = await self._request(
            "POST",
            f"/invocations/actions/{action_id}/reject",
            json=payload,
        )
        return AgentActionResponse(**result)

    async def list_actions(
        self,
        workspace_id: UUID,
        invocation_id: Optional[UUID] = None,
        review_status: Optional[str] = None,
        executed: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentActionResponse]:
        """List agent actions with filters.

        Args:
            workspace_id: Workspace ID
            invocation_id: Optional filter by invocation
            review_status: Optional filter by status (pending, approved, rejected)
            executed: Optional filter by execution status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of actions
        """
        params = {
            "workspace_id": str(workspace_id),
            "limit": limit,
            "offset": offset,
        }
        if invocation_id:
            params["invocation_id"] = str(invocation_id)
        if review_status:
            params["review_status"] = review_status
        if executed is not None:
            params["executed"] = executed

        result = await self._request("GET", "/invocations/actions", params=params)
        return [AgentActionResponse(**a) for a in result.get("actions", [])]


# Singleton instance
_client: Optional[MailagentClient] = None


def get_mailagent_client() -> MailagentClient:
    """Get or create the Mailagent client singleton."""
    global _client
    if _client is None:
        _client = MailagentClient()
    return _client
