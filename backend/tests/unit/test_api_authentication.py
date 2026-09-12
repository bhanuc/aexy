"""Every API route either requires a token or is on the reviewed public list.

Seven routers answered anyone who asked. `/admin/*` handed out platform-wide
LLM spend, provider configuration and a cache flush to unauthenticated
callers; `/analysis`, `/career` and `/learning/activities` took a developer id
in the URL and answered for whoever was named; the workflow-event webhooks
accepted invented events for any workspace id.

The inventory below is the point of this file. A new route that takes no
authentication fails it, and adding a line to `PUBLIC_BY_DESIGN` is a
deliberate act with a reason attached rather than an oversight.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from aexy.api import access_guard, workflow_events
from aexy.main import app
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember


PUBLIC_BY_DESIGN: frozenset[str] = frozenset({
    # Public product surfaces — a customer, candidate or reader who has no
    # account at all is the intended caller.
    "GET /api/v1/public/projects/{public_slug}",
    "GET /api/v1/public/projects/{public_slug}/backlog",
    "GET /api/v1/public/projects/{public_slug}/board",
    "GET /api/v1/public/projects/{public_slug}/bugs",
    "GET /api/v1/public/projects/{public_slug}/goals",
    "GET /api/v1/public/projects/{public_slug}/releases",
    "GET /api/v1/public/projects/{public_slug}/roadmap",
    "GET /api/v1/public/projects/{public_slug}/roadmap-requests/{request_id}/comments",
    "GET /api/v1/public/projects/{public_slug}/sprints",
    "GET /api/v1/public/projects/{public_slug}/stories",
    "GET /api/v1/public/projects/{public_slug}/timeline",
    "GET /api/v1/public/community",
    "GET /api/v1/public/community/{community_slug}",
    "GET /api/v1/public/community/{community_slug}/channels/{channel_slug}",
    "GET /api/v1/public/community/{community_slug}/channels/{channel_slug}/topics/{topic_param}",
    "GET /api/v1/public/community/{community_slug}/feed",
    "GET /api/v1/public/community/{community_slug}/members/{handle}",
    "GET /api/v1/public/community/{community_slug}/search",
    "GET /api/v1/public/community/{community_slug}/sitemap",
    "GET /api/v1/public/forms/{public_token}",
    "POST /api/v1/public/forms/{public_token}/uploads",
    "POST /api/v1/public/forms/{public_token}/verify-email",
    "POST /api/v1/public/forms/{public_token}/submit",
    "POST /api/v1/public/forms/{public_token}/verify",
    "GET /api/v1/public/tickets/{token}/attachments/{attachment_id}",
    "GET /api/v1/public/tables/{token}",
    "GET /api/v1/public/tables/{token}/records",
    "POST /api/v1/public/tables/{token}/records",
    "GET /api/v1/public/book/booking/{booking_id}",
    "GET /api/v1/public/book/{workspace_slug}",
    "GET /api/v1/public/book/{workspace_slug}/team/{team_id}",
    "GET /api/v1/public/book/{workspace_slug}/teams",
    "GET /api/v1/public/book/{workspace_slug}/{event_slug}",
    "GET /api/v1/public/book/{workspace_slug}/{event_slug}/slots",
    "POST /api/v1/public/book/booking/{booking_id}/cancel",
    "POST /api/v1/public/book/booking/{booking_id}/reschedule",
    "POST /api/v1/public/book/{workspace_slug}/{event_slug}/book",
    "GET /api/v1/booking/rsvp/{token}",
    "POST /api/v1/booking/rsvp/{token}/respond",
    "GET /api/v1/preferences/{token}",
    "GET /api/v1/preferences/{token}/page",
    "POST /api/v1/preferences/{token}",
    "POST /api/v1/preferences/{token}/resubscribe",
    "POST /api/v1/preferences/{token}/unsubscribe",
    "GET /api/v1/assessments/public/{public_token}",
    "POST /api/v1/assessments/public/{public_token}/register",
    "GET /api/v1/take/{token}",
    "GET /api/v1/take/{token}/questions",
    "GET /api/v1/take/{token}/status",
    "POST /api/v1/take/{token}/complete",
    "POST /api/v1/take/{token}/proctoring/event",
    "POST /api/v1/take/{token}/recording/complete",
    "POST /api/v1/take/{token}/recording/direct-complete",
    "POST /api/v1/take/{token}/recording/direct-upload",
    "POST /api/v1/take/{token}/recording/initiate",
    "POST /api/v1/take/{token}/recording/presigned-url",
    "POST /api/v1/take/{token}/start",
    "POST /api/v1/take/{token}/submit/{question_id}",
    "GET /api/v1/invites/{token}",
    "GET /api/v1/kb/search",

    # Getting a token in the first place, and the OAuth callbacks providers
    # redirect to. Each verifies its own state/code.
    "GET /api/v1/auth/demo/status",
    "GET /api/v1/auth/device/login",
    "GET /api/v1/auth/github/callback",
    "GET /api/v1/auth/github/login",
    "GET /api/v1/auth/google/callback",
    "GET /api/v1/auth/google/connect-crm",
    "GET /api/v1/auth/google/login",
    "GET /api/v1/auth/microsoft/callback",
    "GET /api/v1/auth/microsoft/connect-crm",
    "GET /api/v1/auth/microsoft/login",
    "POST /api/v1/auth/demo/login",
    "GET /.well-known/oauth-authorization-server",
    "GET /.well-known/oauth-protected-resource",
    "GET /oauth/authorize",
    "GET /oauth/authorize/prompt",
    "POST /oauth/register",
    "POST /oauth/revoke",
    "POST /oauth/token",
    "GET /api/v1/integrations/google/callback",
    "GET /api/v1/workspaces/{workspace_id}/integrations/google/callback",
    "GET /api/v1/workspaces/{workspace_id}/integrations/google-calendar/callback",
    "GET /api/v1/booking/calendars/callback/{provider}",

    # Machine callers that authenticate with a signature or a shared secret
    # rather than a bearer token — a sender cannot hold a user's session.
    "GET /api/v1/webhooks/github/status",
    "POST /api/v1/webhooks/automations/{automation_id}/trigger",
    "POST /api/v1/webhooks/github",
    "POST /api/v1/webhooks/email/inbound",
    "POST /api/v1/webhooks/email/mailgun",
    "POST /api/v1/webhooks/email/postmark",
    "POST /api/v1/webhooks/email/sendgrid",
    "POST /api/v1/webhooks/email/ses",
    "GET /api/v1/slack/callback",
    "POST /api/v1/slack/commands",
    "POST /api/v1/slack/events",
    "POST /api/v1/slack/interactions",
    "POST /api/v1/webhooks/gmail/push",
    "POST /api/v1/webhooks/alerts/{inbound_token}",
    "POST /api/v1/workspaces/{workspace_id}/workflow-events/webhooks/custom/{webhook_id}",
    "POST /api/v1/workspaces/{workspace_id}/workflow-events/webhooks/email-tracking",
    "POST /api/v1/workspaces/{workspace_id}/workflow-events/webhooks/form-submission",
    "POST /api/v1/workspaces/{workspace_id}/workflow-events/webhooks/meeting",
    "POST /api/v1/t/{workspace_key}/events",

    # Reads its bearer itself: three different token kinds, none of them the
    # session cookie scheme OpenAPI knows about.
    "POST /api/v1/mcp",

    # Deliberately anonymous: liveness, a public signing key, the price list.
    "GET /api/v1/health",
    "GET /api/v1/ready",
    "GET /api/v1/notifications/push-vapid-key",
    "GET /api/v1/billing/plans",
    "POST /api/v1/billing/webhook",

})


def _operations_without_bearer() -> set[str]:
    spec = app.openapi()
    return {
        f"{method.upper()} {path}"
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
        if method in ("get", "post", "put", "patch", "delete") and not op.get("security")
    }


class TestRouteInventory:
    def test_no_route_is_unauthenticated_without_a_stated_reason(self):
        unexpected = _operations_without_bearer() - PUBLIC_BY_DESIGN
        assert not unexpected, (
            "These routes take no authentication. Add the dependency, or add "
            "the route to PUBLIC_BY_DESIGN under the group that says why:\n  "
            + "\n  ".join(sorted(unexpected))
        )

    def test_the_public_list_has_no_leftovers(self):
        """A route that was made to require a token should leave the list."""
        stale = PUBLIC_BY_DESIGN - _operations_without_bearer()
        assert not stale, (
            "These are on the public list but now require authentication; "
            "drop them from PUBLIC_BY_DESIGN:\n  " + "\n  ".join(sorted(stale))
        )

    def test_no_admin_route_is_public(self):
        """The router that started this: platform-wide LLM spend, provider
        config and a cache flush, none of it workspace-scoped."""
        admin = {
            op
            for op in _operations_without_bearer() | PUBLIC_BY_DESIGN
            if " /api/v1/admin" in op
        }
        assert not admin, f"must require a platform admin: {sorted(admin)}"


class TestPersonalRecordsAreYourOwn:
    """`/learning/activities` addresses one person's log by query parameter."""

    @pytest.mark.asyncio
    async def test_your_own_id_passes(self):
        assert (
            await access_guard.require_own_developer_id(
                developer_id="dev-1", current_developer_id="dev-1"
            )
            == "dev-1"
        )

    @pytest.mark.asyncio
    async def test_somebody_elses_id_is_refused(self):
        with pytest.raises(HTTPException) as exc:
            await access_guard.require_own_developer_id(
                developer_id="dev-2", current_developer_id="dev-1"
            )
        assert exc.value.status_code == 403


@pytest.mark.asyncio
class TestSharedWorkspaceIsTheRule:
    """Reading a developer's profile takes a workspace in common."""

    async def _seed(self, db):
        owner = Developer(email="owner@example.com", name="Owner")
        colleague = Developer(email="colleague@example.com", name="Colleague")
        former = Developer(email="former@example.com", name="Former")
        stranger = Developer(email="stranger@example.com", name="Stranger")
        db.add_all([owner, colleague, former, stranger])
        await db.flush()

        ours = Workspace(name="Ours", slug="ours", owner_id=owner.id)
        theirs = Workspace(name="Theirs", slug="theirs", owner_id=stranger.id)
        db.add_all([ours, theirs])
        await db.flush()

        db.add_all(
            [
                WorkspaceMember(
                    workspace_id=ours.id, developer_id=owner.id,
                    role="owner", status="active",
                ),
                WorkspaceMember(
                    workspace_id=ours.id, developer_id=colleague.id,
                    role="member", status="active",
                ),
                # Kept for historical attribution, no longer a colleague.
                WorkspaceMember(
                    workspace_id=ours.id, developer_id=former.id,
                    role="member", status="removed",
                ),
                WorkspaceMember(
                    workspace_id=theirs.id, developer_id=stranger.id,
                    role="owner", status="active",
                ),
            ]
        )
        await db.commit()
        return owner, colleague, former, stranger

    async def test_a_colleague_is_visible(self, db_session):
        owner, colleague, _, _ = await self._seed(db_session)
        assert await access_guard.shares_active_workspace(
            db_session, str(owner.id), str(colleague.id)
        )

    async def test_you_can_always_see_yourself(self, db_session):
        owner, _, _, _ = await self._seed(db_session)
        assert await access_guard.shares_active_workspace(
            db_session, str(owner.id), str(owner.id)
        )

    async def test_a_stranger_is_not(self, db_session):
        owner, _, _, stranger = await self._seed(db_session)
        assert not await access_guard.shares_active_workspace(
            db_session, str(owner.id), str(stranger.id)
        )

    async def test_a_removed_member_stops_counting(self, db_session):
        owner, _, former, _ = await self._seed(db_session)
        assert not await access_guard.shares_active_workspace(
            db_session, str(owner.id), str(former.id)
        )

    async def test_the_guard_answers_not_found_for_a_stranger(self, db_session):
        """404 rather than 403: a stranger's id is a UUID like any other, and
        "forbidden" would confirm that the person exists."""
        owner, _, _, stranger = await self._seed(db_session)
        with pytest.raises(HTTPException) as exc:
            await access_guard.require_developer_access(
                developer_id=str(stranger.id),
                current_developer_id=str(owner.id),
                db=db_session,
            )
        assert exc.value.status_code == 404

    async def test_the_candidate_pool_is_the_people_you_share_a_workspace_with(
        self, db_session
    ):
        """What the matcher, the peer benchmark and the what-if scenarios
        score. It used to be `select(Developer)` — everyone on the platform."""
        owner, colleague, former, stranger = await self._seed(db_session)
        rows = await db_session.execute(
            access_guard.accessible_developers_stmt(str(owner.id))
        )
        ids = {str(d.id) for d in rows.scalars().all()}
        assert ids == {str(owner.id), str(colleague.id)}
        assert str(stranger.id) not in ids
        assert str(former.id) not in ids

    async def test_a_workspace_you_are_not_in_is_refused(self, db_session):
        owner, _, _, stranger = await self._seed(db_session)
        theirs = (
            await db_session.execute(select(Workspace).where(Workspace.slug == "theirs"))
        ).scalar_one()
        with pytest.raises(HTTPException) as exc:
            await access_guard.ensure_active_member(
                db_session, str(theirs.id), str(owner.id)
            )
        assert exc.value.status_code == 403
        await access_guard.ensure_active_member(
            db_session, str(theirs.id), str(stranger.id)
        )


@pytest.mark.asyncio
class TestWorkflowWebhookSecret:
    """The receivers are called by form tools and calendars, which cannot hold
    a bearer token — so they present the workspace's derived secret instead."""

    WS = "11111111-1111-4111-8111-111111111111"
    OTHER = "22222222-2222-4222-8222-222222222222"

    def _secret(self, workspace_id=None):
        return workflow_events.derive_workflow_webhook_secret(workspace_id or self.WS)

    async def test_the_header_is_accepted(self):
        await workflow_events.verify_webhook_secret(
            workspace_id=self.WS, presented_header=self._secret(), secret=None
        )

    async def test_a_query_parameter_works_for_senders_that_cannot_set_headers(self):
        await workflow_events.verify_webhook_secret(
            workspace_id=self.WS, presented_header=None, secret=self._secret()
        )

    async def test_nothing_presented_is_refused(self):
        with pytest.raises(HTTPException) as exc:
            await workflow_events.verify_webhook_secret(
                workspace_id=self.WS, presented_header=None, secret=None
            )
        assert exc.value.status_code == 401

    async def test_a_wrong_secret_is_refused(self):
        with pytest.raises(HTTPException) as exc:
            await workflow_events.verify_webhook_secret(
                workspace_id=self.WS, presented_header="not-the-secret", secret=None
            )
        assert exc.value.status_code == 401

    async def test_one_workspaces_secret_does_not_open_another(self):
        with pytest.raises(HTTPException) as exc:
            await workflow_events.verify_webhook_secret(
                workspace_id=self.OTHER, presented_header=self._secret(), secret=None
            )
        assert exc.value.status_code == 401

    async def test_the_secret_is_stable_and_distinct_per_workspace(self):
        assert self._secret() == self._secret()
        assert self._secret() != self._secret(self.OTHER)
