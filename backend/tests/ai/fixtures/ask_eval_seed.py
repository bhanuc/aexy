"""
Deterministic database seed for AexyEval Ask AI benchmarks.

This fixture creates a controlled Aexy workspace containing:
- 1 developer
- 1 workspace
- 1 team
- 1 active sprint
- 1 completed sprint
- 3 sprint tasks
- 1 ticket form
- 3 tickets

The data is intentionally deterministic so that Ask AI benchmark
results can be compared against known expected outcomes.
"""

from datetime import datetime, timezone
import pytest_asyncio
from aexy.models.workspace import Workspace
from aexy.models.developer import Developer
from aexy.models.team import Team
from aexy.models.sprint import Sprint, SprintTask
from aexy.models.ticketing import Ticket, TicketForm, TicketStatus




@pytest_asyncio.fixture
async def ask_eval_seed(ai_db_session):
    """
    Create deterministic application state for AexyEval.

    The returned dictionary contains entity IDs and expected semantic
    values that evaluation tests can use for assertions.
    """

    # ======================================================================
    # 1. DEVELOPER
    # ======================================================================

    developer = Developer(
        email="aexyeval@example.com",
        name="AexyEval Developer",
        has_completed_onboarding=True,
        account_type="internal",
    )

    ai_db_session.add(developer)
    await ai_db_session.flush()

    # ======================================================================
    # 2. WORKSPACE
    # ======================================================================

    workspace = Workspace(
        name="AexyEval Workspace",
        slug="aexyeval-workspace",
        type="internal",
        description=(
            "Controlled workspace used for AexyEval Ask AI benchmarks."
        ),
        owner_id=developer.id,
        settings={},
        next_task_key=4,
        is_active=True,
    )

    ai_db_session.add(workspace)
    await ai_db_session.flush()

    # ======================================================================
    # 3. TEAM
    # ======================================================================

    team = Team(
        workspace_id=workspace.id,
        name="AexyEval Team",
        slug="aexyeval-team",
        description=(
            "Controlled team used for AexyEval benchmark scenarios."
        ),
        type="manual",
        source_repository_ids=None,
        auto_sync_enabled=False,
        settings={},
        is_active=True,
    )

    ai_db_session.add(team)
    await ai_db_session.flush()

    # ======================================================================
    # 4. ACTIVE SPRINT
    # ======================================================================

    active_sprint = Sprint(
        team_id=team.id,
        workspace_id=workspace.id,
        name="AexyEval Active Sprint",
        goal="Complete authentication and dashboard improvements.",
        status="active",
        start_date=datetime(
            2026,
            8,
            1,
            0,
            0,
            tzinfo=timezone.utc,
        ),
        end_date=datetime(
            2026,
            8,
            14,
            23,
            59,
            tzinfo=timezone.utc,
        ),
        capacity_hours=80,
        velocity_commitment=20,
        settings={},
        created_by_id=developer.id,
    )

    ai_db_session.add(active_sprint)
    await ai_db_session.flush()

    # ======================================================================
    # 5. COMPLETED SPRINT
    # ======================================================================

    completed_sprint = Sprint(
        team_id=team.id,
        workspace_id=workspace.id,
        name="AexyEval Completed Sprint",
        goal="Complete database preparation work.",
        status="completed",
        start_date=datetime(
            2026,
            7,
            15,
            0,
            0,
            tzinfo=timezone.utc,
        ),
        end_date=datetime(
            2026,
            7,
            31,
            23,
            59,
            tzinfo=timezone.utc,
        ),
        capacity_hours=80,
        velocity_commitment=18,
        settings={},
        created_by_id=developer.id,
    )

    ai_db_session.add(completed_sprint)
    await ai_db_session.flush()

    # ======================================================================
    # 6. ACTIVE SPRINT TASK 1
    # ======================================================================

    active_task_1 = SprintTask(
        sprint_id=active_sprint.id,
        team_id=team.id,
        workspace_id=workspace.id,
        task_key=1,

        source_type="manual",
        source_id="aexyeval-task-001",

        title="Implement authentication API",
        description=(
            "Implement the authentication API for the evaluation workspace."
        ),

        story_points=5,
        priority="high",

        labels=[
            "backend",
            "authentication",
        ],

        mentioned_user_ids=[],
        mentioned_file_paths=[],

        assignee_id=developer.id,

        status="in_progress",

        custom_fields={},

        task_type="feature",

        contributes_to_goal=True,

        sync_status="synced",
    )

    # ======================================================================
    # 7. ACTIVE SPRINT TASK 2
    # ======================================================================

    active_task_2 = SprintTask(
        sprint_id=active_sprint.id,
        team_id=team.id,
        workspace_id=workspace.id,
        task_key=2,

        source_type="manual",
        source_id="aexyeval-task-002",

        title="Fix dashboard loading issue",
        description=(
            "Resolve the dashboard loading issue affecting workspace users."
        ),

        story_points=3,
        priority="medium",

        labels=[
            "frontend",
            "bug",
        ],

        mentioned_user_ids=[],
        mentioned_file_paths=[],

        assignee_id=developer.id,

        status="todo",

        custom_fields={},

        task_type="bug",

        contributes_to_goal=True,

        sync_status="synced",
    )

    # ======================================================================
    # 8. COMPLETED SPRINT TASK
    # ======================================================================

    completed_task = SprintTask(
        sprint_id=completed_sprint.id,
        team_id=team.id,
        workspace_id=workspace.id,
        task_key=3,

        source_type="manual",
        source_id="aexyeval-task-003",

        title="Create database migration",
        description=(
            "Create and verify the database migration required for the release."
        ),

        story_points=2,
        priority="low",

        labels=[
            "database",
        ],

        mentioned_user_ids=[],
        mentioned_file_paths=[],

        assignee_id=developer.id,

        status="done",

        custom_fields={},

        task_type="task",

        contributes_to_goal=True,

        sync_status="synced",

        completed_at=datetime(
            2026,
            7,
            29,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    ai_db_session.add_all(
        [
            active_task_1,
            active_task_2,
            completed_task,
        ]
    )

    await ai_db_session.flush()

    # ======================================================================
    # 9. TICKET FORM
    # ======================================================================

    ticket_form = TicketForm(
        workspace_id=workspace.id,

        name="AexyEval Ticket Form",
        slug="aexyeval-ticket-form",

        description=(
            "Controlled ticket form used for AexyEval Ask AI benchmarks."
        ),

        template_type=None,

        is_active=True,

        # Your model defaults to ANONYMOUS.
        # Explicitly setting the known string keeps the fixture deterministic.
        auth_mode="anonymous",

        require_email=True,

        theme={},

        success_message="Ticket submitted successfully.",

        destinations=[],

        auto_create_task=False,

        default_team_id=team.id,

        auto_assign_oncall=False,

        default_severity=None,
        default_priority="medium",

        conditional_rules=[],

        submission_count=3,

        default_share_enabled=False,

        created_by_id=developer.id,
    )

    ai_db_session.add(ticket_form)
    await ai_db_session.flush()

    # ======================================================================
    # 10. NEW + HIGH PRIORITY TICKET
    # ======================================================================

    new_high_ticket = Ticket(
        form_id=ticket_form.id,
        workspace_id=workspace.id,

        ticket_number=1,

        submitter_email="user1@example.com",
        submitter_name="Evaluation User 1",

        email_verified=True,

        field_values={
            "title": "Production login failure",
            "description": (
                "Users cannot log in to the production environment."
            ),
        },

        attachments=[],

        status=TicketStatus.NEW.value,
        priority="high",
        severity="high",

        assignee_id=developer.id,
        team_id=team.id,

        external_issues=[],

        source="form",

        occurrence_count=1,

        sla_breached=False,
    )

    # ======================================================================
    # 11. NEW + LOW PRIORITY TICKET
    # ======================================================================

    new_low_ticket = Ticket(
        form_id=ticket_form.id,
        workspace_id=workspace.id,

        ticket_number=2,

        submitter_email="user2@example.com",
        submitter_name="Evaluation User 2",

        email_verified=True,

        field_values={
            "title": "Update dashboard icon",
            "description": (
                "Replace the outdated dashboard icon with the new version."
            ),
        },

        attachments=[],

        status=TicketStatus.NEW.value,
        priority="low",
        severity="low",

        assignee_id=developer.id,
        team_id=team.id,

        external_issues=[],

        source="form",

        occurrence_count=1,

        sla_breached=False,
    )

    # ======================================================================
    # 12. CLOSED + HIGH PRIORITY TICKET
    # ======================================================================

    closed_high_ticket = Ticket(
        form_id=ticket_form.id,
        workspace_id=workspace.id,

        ticket_number=3,

        submitter_email="user3@example.com",
        submitter_name="Evaluation User 3",

        email_verified=True,

        field_values={
            "title": "Resolved payment service outage",
            "description": (
                "The payment service outage has been resolved."
            ),
        },

        attachments=[],

        status=TicketStatus.CLOSED.value,
        priority="high",
        severity="critical",

        assignee_id=developer.id,
        team_id=team.id,

        external_issues=[],

        source="form",

        occurrence_count=1,

        resolved_at=datetime(
            2026,
            7,
            25,
            10,
            0,
            tzinfo=timezone.utc,
        ),

        closed_at=datetime(
            2026,
            7,
            25,
            12,
            0,
            tzinfo=timezone.utc,
        ),

        sla_breached=False,
    )

    ai_db_session.add_all(
        [
            new_high_ticket,
            new_low_ticket,
            closed_high_ticket,
        ]
    )

    await ai_db_session.flush()

    # ======================================================================
    # 13. COMMIT CONTROLLED DATABASE STATE
    # ======================================================================

    await ai_db_session.commit()

    # ======================================================================
    # 14. RETURN BENCHMARK STATE
    # ======================================================================

    return {
        # ------------------------------------------------------------------
        # Developer / Workspace / Team
        # ------------------------------------------------------------------
        "developer_id": str(developer.id),
        "workspace_id": str(workspace.id),
        "team_id": str(team.id),

        # ------------------------------------------------------------------
        # Sprints
        # ------------------------------------------------------------------
        "active_sprint_id": str(active_sprint.id),
        "completed_sprint_id": str(completed_sprint.id),

        # ------------------------------------------------------------------
        # Sprint Tasks
        # ------------------------------------------------------------------
        "active_task_1_id": str(active_task_1.id),
        "active_task_2_id": str(active_task_2.id),
        "completed_task_id": str(completed_task.id),

        # ------------------------------------------------------------------
        # Ticket Form
        # ------------------------------------------------------------------
        "ticket_form_id": str(ticket_form.id),

        # ------------------------------------------------------------------
        # Tickets
        # ------------------------------------------------------------------
        "new_high_ticket_id": str(new_high_ticket.id),
        "new_low_ticket_id": str(new_low_ticket.id),
        "closed_high_ticket_id": str(closed_high_ticket.id),

        # ------------------------------------------------------------------
        # Expected values for benchmark evaluation
        # ------------------------------------------------------------------
        "expected": {
            "active_sprint": {
                "id": str(active_sprint.id),
                "name": "AexyEval Active Sprint",
                "status": "active",
            },

            "completed_sprint": {
                "id": str(completed_sprint.id),
                "name": "AexyEval Completed Sprint",
                "status": "completed",
            },

            "active_sprint_tasks": [
                {
                    "id": str(active_task_1.id),
                    "task_key": 1,
                    "title": "Implement authentication API",
                    "status": "in_progress",
                    "priority": "high",
                },
                {
                    "id": str(active_task_2.id),
                    "task_key": 2,
                    "title": "Fix dashboard loading issue",
                    "status": "todo",
                    "priority": "medium",
                },
            ],

            "completed_sprint_tasks": [
                {
                    "id": str(completed_task.id),
                    "task_key": 3,
                    "title": "Create database migration",
                    "status": "done",
                    "priority": "low",
                },
            ],

            "new_high_tickets": [
                {
                    "id": str(new_high_ticket.id),
                    "ticket_number": 1,
                    "title": "Production login failure",
                    "status": TicketStatus.NEW.value,
                    "priority": "high",
                },
            ],

            "new_low_tickets": [
                {
                    "id": str(new_low_ticket.id),
                    "ticket_number": 2,
                    "title": "Update dashboard icon",
                    "status": TicketStatus.NEW.value,
                    "priority": "low",
                },
            ],

            "closed_high_tickets": [
                {
                    "id": str(closed_high_ticket.id),
                    "ticket_number": 3,
                    "title": "Resolved payment service outage",
                    "status": TicketStatus.CLOSED.value,
                    "priority": "high",
                },
            ],

            "all_new_tickets": [
                {
                    "id": str(new_high_ticket.id),
                    "ticket_number": 1,
                    "title": "Production login failure",
                    "priority": "high",
                },
                {
                    "id": str(new_low_ticket.id),
                    "ticket_number": 2,
                    "title": "Update dashboard icon",
                    "priority": "low",
                },
            ],
        },
    }