"""Automations created before the builder was fixed must still run.

Two artefacts were baked into automations saved before commit 9502f717:

1. Node config was wrapped twice — ``{"config": {...actual...}}`` — so every
   action handler, which reads its keys off the top level, ran against an empty
   config. A create_task step ignored its title and produced "Automated Task";
   a send_email step lost its body.

2. Templates offered ``send_notification``, an action id the executor never
   implemented. Every run of such an automation failed the step as
   "Action type 'send_notification' is not supported" — which, because the
   executor fails the whole run on any step error, meant the automation had a
   100% failure rate for its entire existence.

``_execute_action`` now unwraps the double nesting and routes
``send_notification`` to ``notify_user``, defaulting the recipient to the
developer the trigger names when the stored config named none. These are the
regression checks.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aexy.services.crm_automation_service import CRMAutomationService


def _service():
    return CRMAutomationService(db=None)


@pytest.mark.asyncio
async def test_double_wrapped_config_is_unwrapped_before_the_handler_sees_it():
    service = _service()
    seen = {}

    async def _capture(config, *args, **kwargs):
        seen.update(config)
        return {"success": True}

    service._action_create_task = _capture  # type: ignore[assignment]

    await service._execute_action(
        "create_task",
        {"config": {"title": "Missed standup follow-up", "priority": "medium"}},
        None,
        "ws-1",
    )

    # The handler saw the real keys, not the wrapper.
    assert seen.get("title") == "Missed standup follow-up"
    assert seen.get("priority") == "medium"
    assert "config" not in seen


@pytest.mark.asyncio
async def test_a_legitimate_config_named_config_is_left_alone():
    # A single "config" key only unwraps when its value is a dict — a real
    # action never carries a lone dict under "config", but if some field were
    # literally named "config" with a non-dict value it must survive.
    service = _service()
    seen = {}

    async def _capture(config, *args, **kwargs):
        seen.update(config)
        return {"success": True}

    service._action_create_task = _capture  # type: ignore[assignment]

    await service._execute_action(
        "create_task", {"config": "not-a-dict"}, None, "ws-1"
    )
    assert seen.get("config") == "not-a-dict"


@pytest.mark.asyncio
async def test_send_notification_routes_to_notify_user_with_the_triggering_developer():
    service = _service()
    captured = {}

    async def _notify(config, *args, **kwargs):
        captured["config"] = config
        return {"success": True}

    service._action_notify_user = _notify  # type: ignore[assignment]

    result = await service._execute_action(
        "send_notification",
        {"channel": "slack"},  # the old standup template: a channel, no recipient
        None,
        "ws-1",
        trigger_data={"developer_id": "dev-42", "module": "tracking"},
    )

    assert result["success"] is True
    # Recipient defaulted to the developer the trigger named.
    assert captured["config"]["user_id"] == "dev-42"
    assert captured["config"]["channel"] == "slack"


@pytest.mark.asyncio
async def test_send_notification_keeps_an_explicit_recipient():
    service = _service()
    captured = {}

    async def _notify(config, *args, **kwargs):
        captured["config"] = config
        return {"success": True}

    service._action_notify_user = _notify  # type: ignore[assignment]

    await service._execute_action(
        "send_notification",
        {"user_id": "chosen-user", "channel": "email"},
        None,
        "ws-1",
        trigger_data={"developer_id": "dev-42"},
    )
    # An explicitly configured recipient is not overridden by the trigger.
    assert captured["config"]["user_id"] == "chosen-user"
