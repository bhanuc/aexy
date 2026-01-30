# AI Agents

AI Agents in Aexy are intelligent automation assistants that can be configured to handle various tasks across your workspace. They leverage LLM providers (Claude, Gemini) to process information and take actions based on your defined rules.

## Overview

AI Agents provide:
- **Automated Responses**: Handle emails, support tickets, and inquiries automatically
- **CRM Integration**: Search contacts, enrich data, and update records
- **Workflow Automation**: Create tasks, schedule follow-ups, and escalate when needed
- **Customizable Behavior**: Fine-tune confidence thresholds, working hours, and approval workflows

## Agent Types

| Type | Description | Use Case |
|------|-------------|----------|
| **Support** | Customer support automation | Ticket responses, FAQ handling |
| **Sales** | Sales outreach and follow-ups | Lead qualification, email sequences |
| **Scheduling** | Calendar and meeting management | Booking confirmations, reminders |
| **Custom** | Fully configurable agent | Any workflow you define |

## Configuration

### Basic Settings

- **Name**: Display name for the agent
- **Description**: What this agent does
- **Mention Handle**: `@handle` for triggering the agent in conversations
- **Active Status**: Enable/disable the agent

### LLM Configuration

- **Provider**: Claude (Anthropic) or Gemini (Google)
- **Model**: Specific model version to use
- **Temperature**: 0.0 (deterministic) to 1.0 (creative)
- **Max Tokens**: Maximum response length

### Behavior Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `confidence_threshold` | Minimum confidence to auto-respond | 0.7 |
| `require_approval_below` | Require human approval below this confidence | 0.5 |
| `max_daily_responses` | Daily response limit (null = unlimited) | null |
| `response_delay_minutes` | Delay before sending responses | 0 |

### Working Hours

Configure when the agent is active:

```json
{
  "enabled": true,
  "timezone": "America/New_York",
  "start": "09:00",
  "end": "17:00",
  "days": [1, 2, 3, 4, 5]  // Monday-Friday
}
```

### Escalation

- **Escalation Email**: Email address for human escalation
- **Slack Channel**: Slack channel for escalation notifications

## Available Tools

Agents can be granted access to various tools:

### Agent Actions
- `reply` - Send email responses
- `forward` - Forward messages
- `escalate` - Escalate to human
- `schedule` - Schedule follow-ups
- `create_task` - Create tasks in the system
- `update_crm` - Update CRM records
- `wait` - Pause before next action

### CRM Tools
- `search_contacts` - Search contact database
- `get_record` - Retrieve CRM records
- `update_record` - Update CRM records
- `create_record` - Create new records
- `get_activities` - Get activity history

### Email Tools
- `send_email` - Send emails
- `create_draft` - Create email drafts
- `get_email_history` - Get email thread history
- `get_writing_style` - Analyze writing style

### Enrichment Tools
- `enrich_company` - Enrich company data
- `enrich_person` - Enrich person data
- `web_search` - Search the web for information

### Communication
- `send_slack` - Send Slack messages
- `send_sms` - Send SMS messages

## Prompts

### System Prompt
The system prompt defines the agent's persona and base instructions. This is sent with every request.

### Custom Instructions
Additional context or rules that supplement the system prompt.

**Variables available in prompts:**
- `{{workspace_name}}` - Current workspace name
- `{{agent_name}}` - Agent's name
- `{{current_time}}` - Current timestamp
- `{{sender_name}}` - Name of the person being responded to
- `{{sender_email}}` - Email of the sender

## API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/workspaces/{id}/agents` | List all agents |
| POST | `/api/v1/workspaces/{id}/agents` | Create new agent |
| GET | `/api/v1/workspaces/{id}/agents/{agentId}` | Get agent details |
| PUT | `/api/v1/workspaces/{id}/agents/{agentId}` | Update agent |
| DELETE | `/api/v1/workspaces/{id}/agents/{agentId}` | Delete agent |
| GET | `/api/v1/workspaces/{id}/agents/check-handle` | Check handle availability |
| GET | `/api/v1/workspaces/{id}/agents/{agentId}/metrics` | Get agent metrics |

### Example: Create Agent

```bash
curl -X POST "http://localhost:8000/api/v1/workspaces/{workspace_id}/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Support Bot",
    "agent_type": "support",
    "description": "Handles customer support inquiries",
    "mention_handle": "support",
    "llm_provider": "claude",
    "llm_model": "claude-3-5-sonnet-20241022",
    "temperature": 0.7,
    "tools": ["reply", "escalate", "search_contacts", "create_task"],
    "confidence_threshold": 0.7,
    "require_approval_below": 0.5,
    "system_prompt": "You are a helpful customer support agent..."
  }'
```

## Metrics & Monitoring

The agent dashboard provides:

- **Total Runs**: Number of times the agent has been invoked
- **Success Rate**: Percentage of successful executions
- **Average Duration**: Time to process requests
- **Average Confidence**: Mean confidence score across responses
- **Recent Executions**: List of recent agent activities with details

## Best Practices

1. **Start Conservative**: Begin with higher confidence thresholds and require approvals
2. **Monitor Closely**: Review agent responses regularly, especially early on
3. **Iterate on Prompts**: Refine system prompts based on observed behavior
4. **Use Working Hours**: Prevent off-hours responses that may seem robotic
5. **Set Response Delays**: Add natural delays to avoid instant responses
6. **Limit Daily Responses**: Prevent runaway agents with daily limits
7. **Configure Escalation**: Always have a human fallback path

## Troubleshooting

### Agent Not Responding
- Check if agent is active
- Verify working hours configuration
- Check daily response limit hasn't been reached
- Review confidence threshold settings

### Poor Response Quality
- Adjust temperature (lower for consistency)
- Refine system prompt with examples
- Add more context in custom instructions
- Review and update tool permissions

### Escalation Issues
- Verify escalation email is valid
- Check Slack channel permissions
- Ensure escalation threshold is configured
