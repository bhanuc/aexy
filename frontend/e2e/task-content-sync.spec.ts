/**
 * E2E: a moved task and its original keep description, comments/updates and
 * attachments in step (0.39.0), through the API the UI calls.
 *
 * The move itself is exercised through the dialog in
 * `task-move-between-projects.spec.ts`; this spec is about what happens
 * *after* — edits on one side landing on the other, updates reading through
 * with a label, and one stored object behind two attachment rows — and drives
 * the modal for the parts a person would see: the Linked tasks section and the
 * origin label on a read-through update.
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

async function createProject(request: APIRequestContext, name: string) {
  const resp = await request.post(`${API_BASE}/workspaces/${WS()}/projects`, {
    headers: authHeaders(),
    data: { name, description: "created by content-sync e2e" },
  });
  expect(resp.ok(), `project create failed: ${resp.status()}`).toBe(true);
  return await resp.json();
}

async function createTask(request: APIRequestContext, projectId: string, title: string) {
  const resp = await request.post(`${API_BASE}/teams/${projectId}/tasks`, {
    headers: authHeaders(),
    data: { title, description: "original words" },
  });
  expect(resp.ok(), `task create failed: ${resp.status()}`).toBe(true);
  return await resp.json();
}

async function getTask(request: APIRequestContext, projectId: string, taskId: string) {
  const resp = await request.get(`${API_BASE}/teams/${projectId}/tasks/${taskId}`, {
    headers: authHeaders(),
  });
  expect(resp.ok(), `task fetch failed: ${resp.status()}`).toBe(true);
  return await resp.json();
}

async function moveKeepSynced(
  request: APIRequestContext,
  projectId: string,
  taskId: string,
  targetProjectId: string,
) {
  const resp = await request.post(
    `${API_BASE}/teams/${projectId}/tasks/${taskId}/move-to-project`,
    {
      headers: authHeaders(),
      data: {
        target_project_id: targetProjectId,
        source_action: "keep",
        sync_content: true,
      },
    },
  );
  expect(resp.ok(), `move failed: ${resp.status()} ${await resp.text()}`).toBe(true);
  return await resp.json();
}

test.describe("Content sync between a moved task and its original (live)", () => {
  test.skip(!backendOnlyReady(), "needs E2E_REAL_BACKEND=1 with a token and workspace");

  const projectIds: string[] = [];

  test.beforeEach(async ({ page }) => {
    await setupAiLiveAuth(page);
  });

  test.afterEach(async ({ request }) => {
    for (const id of projectIds.splice(0)) {
      await request
        .delete(`${API_BASE}/workspaces/${WS()}/projects/${id}`, { headers: authHeaders() })
        .catch(() => {});
    }
  });

  test("the description, an update and an attachment cross to the other task", async ({
    page,
    request,
  }) => {
    const stamp = Date.now();
    const source = await createProject(request, `e2e-sync-src-${stamp}`);
    const target = await createProject(request, `e2e-sync-dst-${stamp}`);
    projectIds.push(source.id, target.id);

    const task = await createTask(request, source.id, `Sync me ${stamp}`);
    const copy = await moveKeepSynced(request, source.id, task.id, target.id);
    expect(copy.description, "in sync, the copy starts with the same text").toBe("original words");

    // Description: edit the copy, read the original.
    const edit = await request.patch(`${API_BASE}/teams/${target.id}/tasks/${copy.id}`, {
      headers: authHeaders(),
      data: {
        description: "rewritten on the other board",
        description_json: {
          type: "doc",
          content: [{ type: "paragraph", content: [{ type: "text", text: "rewritten on the other board" }] }],
        },
      },
    });
    expect(edit.ok(), await edit.text()).toBe(true);
    await expect
      .poll(async () => (await getTask(request, source.id, task.id)).description, {
        message: "the original never received the copy's description",
        timeout: 15_000,
      })
      .toBe("rewritten on the other board");

    // Nothing else crossed.
    const prio = await request.patch(`${API_BASE}/teams/${target.id}/tasks/${copy.id}`, {
      headers: authHeaders(),
      data: { priority: "high" },
    });
    expect(prio.ok()).toBe(true);
    expect((await getTask(request, source.id, task.id)).priority).not.toBe("high");

    // Progress update: written on the original, read on the copy with a label.
    const post = await request.post(
      `${API_BASE}/workspaces/${WS()}/work-updates/task/${task.id}`,
      { headers: authHeaders(), data: { body: `Waiting on vendor ${stamp}` } },
    );
    expect(post.ok(), await post.text()).toBe(true);
    const list = await request.get(
      `${API_BASE}/workspaces/${WS()}/work-updates/task/${copy.id}`,
      { headers: authHeaders() },
    );
    const items = (await list.json()).items as Array<{ body: string; origin_label: string | null }>;
    const crossed = items.find((u) => u.body === `Waiting on vendor ${stamp}`);
    expect(crossed, "the update never appeared on the copy").toBeTruthy();
    expect(crossed!.origin_label, "a read-through update says where it was written").toBe(
      `#${task.task_key}`,
    );

    // Attachment: one upload, a row on each task, one stored object.
    // Only the bearer: `authHeaders()` also sets a JSON content type, which
    // would override the multipart boundary and lose the file.
    const upload = await request.post(`${API_BASE}/teams/${target.id}/tasks/${copy.id}/attachments`, {
      headers: { Authorization: authHeaders().Authorization },
      multipart: {
        files: { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello sync") },
      },
    });
    test.skip(upload.status() === 503, "file storage is not configured on this deployment");
    expect(upload.ok(), await upload.text()).toBe(true);
    const onOriginal = await request.get(`${API_BASE}/teams/${source.id}/tasks/${task.id}/attachments`, {
      headers: authHeaders(),
    });
    const mirrored = ((await onOriginal.json()).attachments as Array<{ id: string; file_name: string }>).find(
      (a) => a.file_name === "notes.txt",
    );
    expect(mirrored, "the file never appeared on the original").toBeTruthy();

    // Removing it on the original removes it from the copy too.
    const del = await request.delete(
      `${API_BASE}/teams/${source.id}/tasks/${task.id}/attachments/${mirrored!.id}`,
      { headers: authHeaders() },
    );
    expect(del.ok(), await del.text()).toBe(true);
    const onCopy = await request.get(`${API_BASE}/teams/${target.id}/tasks/${copy.id}/attachments`, {
      headers: authHeaders(),
    });
    expect(
      ((await onCopy.json()).attachments as Array<{ file_name: string }>).map((a) => a.file_name),
    ).not.toContain("notes.txt");

    // What a person sees: the copy's detail names the original under Linked
    // tasks, and shows the update with where it was written.
    await page.goto(`/sprints/${target.id}/board?task=${copy.id}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 30_000 });
    const linked = dialog.getByTestId("task-linked-tasks");
    await expect(linked).toBeVisible({ timeout: 20_000 });
    await expect(linked).toContainText(`#${task.task_key}`);
    await expect(linked).toContainText(/in sync/i);
    await expect(dialog.getByTestId("task-updates-section")).toBeVisible();
    await expect(dialog.getByTestId("work-update-origin").first()).toContainText(`#${task.task_key}`);
  });

  test("the History of a moved task loads and names the move", async ({ request }) => {
    const stamp = Date.now();
    const source = await createProject(request, `e2e-hist-src-${stamp}`);
    const target = await createProject(request, `e2e-hist-dst-${stamp}`);
    projectIds.push(source.id, target.id);
    const task = await createTask(request, source.id, `History me ${stamp}`);
    const copy = await moveKeepSynced(request, source.id, task.id, target.id);

    // Both `moved_to_project` and `created_from_move` used to fail response
    // validation, so this endpoint 500'd for every moved task.
    const src = await request.get(`${API_BASE}/teams/${source.id}/tasks/${task.id}/activities`, {
      headers: authHeaders(),
    });
    expect(src.status(), await src.text()).toBe(200);
    const actions = ((await src.json()).activities as Array<{ action: string }>).map((a) => a.action);
    expect(actions).toContain("moved_to_project");

    const dst = await request.get(`${API_BASE}/teams/${target.id}/tasks/${copy.id}/activities`, {
      headers: authHeaders(),
    });
    expect(dst.status(), await dst.text()).toBe(200);
    expect(((await dst.json()).activities as Array<{ action: string }>).map((a) => a.action)).toContain(
      "created_from_move",
    );
  });
});
