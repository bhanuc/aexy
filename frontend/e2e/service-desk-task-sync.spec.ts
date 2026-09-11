/**
 * E2E: a ticket and the task it was converted into keep notes and updates in
 * step (0.39.0), and the switch on the ticket page turns that off.
 *
 * Drives the ticket page for the parts a person sees — the link to the task,
 * the note composer, the "from the task" tag, the switch — and reads the task
 * side through the API the board uses.
 *
 * Live backend, no LLM.
 */

import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe.configure({ timeout: 180_000 });

const WS = () => REAL_BACKEND_WORKSPACE_ID;

async function logManualTicket(request: APIRequestContext, subject: string) {
  const resp = await request.post(`${API_BASE}/workspaces/${WS()}/service-desk/tickets/manual`, {
    headers: authHeaders(),
    data: {
      subject,
      body: "Raised by the task-sync spec.",
      requester_email: "caller@example.com",
      requester_name: "A Caller",
    },
  });
  expect(resp.ok(), `manual ticket create failed: ${resp.status()}`).toBe(true);
  return (await resp.json()).ticket_id as string;
}

async function createProject(request: APIRequestContext, name: string) {
  const resp = await request.post(`${API_BASE}/workspaces/${WS()}/projects`, {
    headers: authHeaders(),
    data: { name },
  });
  expect(resp.ok(), `project create failed: ${resp.status()}`).toBe(true);
  return await resp.json();
}

async function taskComments(request: APIRequestContext, projectId: string, taskId: string) {
  const resp = await request.get(`${API_BASE}/teams/${projectId}/tasks/${taskId}/activities`, {
    headers: authHeaders(),
  });
  expect(resp.status(), await resp.text()).toBe(200);
  const body = await resp.json();
  return (body.activities as Array<{ action: string; comment: string | null; metadata: Record<string, unknown> }>)
    .filter((a) => a.action === "comment");
}

test.describe("Ticket ↔ task content sync (live)", () => {
  let projectId: string | null = null;

  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
  });

  test.afterEach(async ({ request }) => {
    if (projectId) {
      await request
        .delete(`${API_BASE}/workspaces/${WS()}/projects/${projectId}`, { headers: authHeaders() })
        .catch(() => {});
      projectId = null;
    }
  });

  test("a note on the ticket is a comment on the task, a task comment is a note on the ticket, and the switch stops it", async ({
    page,
    request,
  }) => {
    const stamp = Date.now();
    const ticketId = await logManualTicket(request, `e2e-task-sync-${stamp}`);
    const project = await createProject(request, `e2e-task-sync-${stamp}`);
    projectId = project.id;

    const convert = await request.post(
      `${API_BASE}/workspaces/${WS()}/service-desk/tickets/${ticketId}/convert-to-task`,
      { headers: authHeaders(), data: { project_id: project.id } },
    );
    expect(convert.ok(), await convert.text()).toBe(true);
    const taskId = (await convert.json()).task_id as string;

    await page.goto(`/service-desk/tickets/${ticketId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    // The link now opens the task, and the sync switch is on.
    const linked = page.getByTestId("sd-linked-task");
    await expect(linked).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("sd-linked-task-link")).toHaveAttribute(
      "href",
      `/sprints/${project.id}/board?task=${taskId}`,
    );
    const toggle = page.getByTestId("sd-task-sync");
    await expect(toggle).toBeChecked();

    // Ticket → task: a note typed here shows up as a comment on the task,
    // marked as having come from the ticket.
    const notes = page.getByTestId("sd-notes");
    await notes.getByRole("textbox").fill(`Customer confirmed the fix ${stamp}`);
    await notes.getByRole("button").last().click();
    await expect(notes).toContainText(`Customer confirmed the fix ${stamp}`, { timeout: 20_000 });

    await expect
      .poll(async () => (await taskComments(request, project.id, taskId)).map((c) => c.comment), {
        message: "the ticket note never reached the task",
        timeout: 20_000,
      })
      .toContain(`Customer confirmed the fix ${stamp}`);
    const mirrored = (await taskComments(request, project.id, taskId)).find(
      (c) => c.comment === `Customer confirmed the fix ${stamp}`,
    )!;
    expect(mirrored.metadata.synced_from_ticket_id).toBe(ticketId);
    expect(String(mirrored.metadata.ticket_label ?? "")).not.toBe("");

    // Task → ticket: a comment on the board lands here as an internal note,
    // tagged as the task talking.
    const comment = await request.post(`${API_BASE}/teams/${project.id}/tasks/${taskId}/comments`, {
      headers: authHeaders(),
      data: { comment: `Deployed to staging ${stamp}` },
    });
    expect(comment.ok(), await comment.text()).toBe(true);
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("sd-notes")).toContainText(`Deployed to staging ${stamp}`, {
      timeout: 30_000,
    });
    await expect(page.getByTestId("sd-note-from-task").first()).toBeVisible();

    // Never a customer-facing reply: the mirror is internal only.
    const detail = await (
      await request.get(`${API_BASE}/workspaces/${WS()}/service-desk/tickets/${ticketId}`, {
        headers: authHeaders(),
      })
    ).json();
    expect(
      (detail.correspondence as Array<{ content?: string; body?: string }>).some((c) =>
        JSON.stringify(c).includes(`Deployed to staging ${stamp}`),
      ),
      "a task comment leaked into the ticket's correspondence",
    ).toBe(false);
    expect(detail.sync_content_with_task).toBe(true);

    // The switch: off, and nothing more crosses in either direction. A click,
    // not uncheck(): the box is controlled by the ticket and only flips once
    // the save has round-tripped, which is what the poll below waits for.
    await page.getByTestId("sd-task-sync").click();
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get(`${API_BASE}/workspaces/${WS()}/service-desk/tickets/${ticketId}`, {
                headers: authHeaders(),
              })
            ).json()
          ).sync_content_with_task,
        { timeout: 15_000 },
      )
      .toBe(false);

    const later = await request.post(`${API_BASE}/teams/${project.id}/tasks/${taskId}/comments`, {
      headers: authHeaders(),
      data: { comment: `Only on the task ${stamp}` },
    });
    expect(later.ok()).toBe(true);
    const after = await (
      await request.get(`${API_BASE}/workspaces/${WS()}/service-desk/tickets/${ticketId}`, {
        headers: authHeaders(),
      })
    ).json();
    expect((after.notes as Array<{ content: string }>).map((n) => n.content)).not.toContain(
      `Only on the task ${stamp}`,
    );

    const noteOff = await request.post(
      `${API_BASE}/workspaces/${WS()}/service-desk/tickets/${ticketId}/notes`,
      { headers: authHeaders(), data: { content: `Only on the ticket ${stamp}` } },
    );
    expect(noteOff.ok()).toBe(true);
    expect((await taskComments(request, project.id, taskId)).map((c) => c.comment)).not.toContain(
      `Only on the ticket ${stamp}`,
    );
  });
});
