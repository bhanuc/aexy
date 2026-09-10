/**
 * E2E: moving a task from one project to another, through the UI.
 *
 * "Move" here is fork-and-link, not a reparent: a new task is created in the
 * destination project, linked back to the original as a `duplicates`
 * dependency, and the original is archived or marked done at the operator's
 * choice (see `SprintTaskService.move_to_project`). These assertions follow
 * that contract rather than expecting the source row's project to change.
 *
 * Covers the whole path — board → task detail → "Move to project…" → the
 * destination picker → the resulting rows on both boards — because the service
 * layer already has unit coverage (`tests/unit/test_task_move_to_project.py`)
 * and what was untested was whether the UI reaches it at all.
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
    data: { name, description: "created by task-move e2e" },
  });
  expect(resp.ok(), `project create failed: ${resp.status()}`).toBe(true);
  return await resp.json();
}

async function createTask(
  request: APIRequestContext,
  projectId: string,
  title: string,
) {
  const resp = await request.post(`${API_BASE}/teams/${projectId}/tasks`, {
    headers: authHeaders(),
    data: { title, description: "moved by e2e" },
  });
  expect(resp.ok(), `task create failed: ${resp.status()}`).toBe(true);
  return await resp.json();
}

/**
 * Subtasks go through the workspace-scoped create: `ProjectTaskCreate` (the
 * body of POST /teams/{id}/tasks) has no `parent_task_id` field at all, so a
 * parent passed there is dropped without complaint and you get a sibling.
 */
async function createSubtask(
  request: APIRequestContext,
  projectId: string,
  parentTaskId: string,
  title: string,
) {
  const resp = await request.post(`${API_BASE}/workspaces/${WS()}/tasks`, {
    headers: authHeaders(),
    data: {
      title,
      project_id: projectId,
      parent_task_id: parentTaskId,
      description: "subtask by e2e",
    },
  });
  expect(resp.ok(), `subtask create failed: ${resp.status()}`).toBe(true);
  const created = await resp.json();
  expect(
    String(created.parent_task_id),
    "the subtask was created without its parent link",
  ).toBe(String(parentTaskId));
  return created;
}

async function listTasks(request: APIRequestContext, projectId: string) {
  const resp = await request.get(`${API_BASE}/teams/${projectId}/tasks`, {
    headers: authHeaders(),
  });
  expect(resp.ok(), `task list failed: ${resp.status()}`).toBe(true);
  const body = await resp.json();
  return (Array.isArray(body) ? body : body.tasks) as Array<
    Record<string, any>
  >;
}

test.describe("Move a task between projects (live)", () => {
  const projectIds: string[] = [];

  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
  });

  test.afterEach(async ({ request }) => {
    for (const id of projectIds.splice(0)) {
      await request
        .delete(`${API_BASE}/workspaces/${WS()}/projects/${id}`, {
          headers: authHeaders(),
        })
        .catch(() => {});
    }
  });

  test("the move lands the task on the destination board and closes the original", async ({
    page,
    request,
  }) => {
    const stamp = Date.now();
    const source = await createProject(request, `e2e-move-src-${stamp}`);
    const target = await createProject(request, `e2e-move-dst-${stamp}`);
    projectIds.push(source.id, target.id);

    const title = `Move me ${stamp}`;
    const task = await createTask(request, source.id, title);

    await page.goto(`/sprints/${source.id}/board`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    // Open the task's detail modal from its card on the board.
    const card = page.getByText(title, { exact: false }).first();
    await expect(card, "the task never appeared on its own board").toBeVisible({
      timeout: 30_000,
    });
    await card.click();

    const moveTrigger = page.getByRole("button", { name: /Move to project/i });
    await expect(
      moveTrigger,
      "the task detail offers no way to move the task to another project",
    ).toBeVisible({ timeout: 20_000 });
    await moveTrigger.click();

    // The destination picker.
    const modal = page.getByTestId("move-to-project-modal");
    await expect(modal).toBeVisible({ timeout: 15_000 });
    await expect(
      modal.getByText("Move task to another project"),
    ).toBeVisible();

    const select = page.getByTestId("move-destination-project");
    await expect(select).toBeVisible();
    await select.selectOption(target.id);

    const submit = page.getByRole("button", { name: /^Move( task)?$/i });
    await expect(submit).toBeEnabled({ timeout: 10_000 });
    await submit.click();

    // The modal closes on success.
    await expect(modal).toBeHidden({ timeout: 30_000 });

    // Destination board now carries a task with the same title…
    await expect
      .poll(
        async () => (await listTasks(request, target.id)).map((t) => t.title),
        {
          message: "the moved task never showed up on the destination project",
          timeout: 30_000,
        },
      )
      .toContain(title);

    // …and the original is closed out rather than left open on two boards.
    const moved = (await listTasks(request, target.id)).find(
      (t) => t.title === title,
    )!;
    expect(moved.id, "the destination task is the same row, not a fork").not.toBe(
      task.id,
    );
    expect(String(moved.team_id)).toBe(String(target.id));

    const srcResp = await request.get(
      `${API_BASE}/teams/${source.id}/tasks/${task.id}`,
      { headers: authHeaders() },
    );
    expect(srcResp.ok()).toBe(true);
    const src = await srcResp.json();
    expect(
      src.is_archived === true || /done|complete/i.test(String(src.status)),
      `the original task is still open (archived=${src.is_archived}, status=${src.status})`,
    ).toBe(true);

    // The fork records where it came from, so the trail isn't lost.
    expect(
      String(moved.description ?? ""),
      "the moved task carries no 'Moved from' breadcrumb",
    ).toMatch(/Moved from/i);
  });

  test("the destination list excludes the project the task is already on", async ({
    page,
    request,
  }) => {
    const stamp = Date.now();
    const source = await createProject(request, `e2e-move-self-${stamp}`);
    const target = await createProject(request, `e2e-move-other-${stamp}`);
    projectIds.push(source.id, target.id);
    const title = `Self move ${stamp}`;
    await createTask(request, source.id, title);

    await page.goto(`/sprints/${source.id}/board`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    const card = page.getByText(title, { exact: false }).first();
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.click();
    await page.getByRole("button", { name: /Move to project/i }).click();
    await expect(page.getByTestId("move-to-project-modal")).toBeVisible({
      timeout: 15_000,
    });

    // Wait for the projects query to land before reading the option list —
    // the select renders as soon as the modal opens, initially short.
    const select = page.getByTestId("move-destination-project");
    await expect(
      select.locator("option", { hasText: `e2e-move-other-${stamp}` }),
      "the other project is missing from the destination list",
    ).toHaveCount(1, { timeout: 20_000 });

    await expect(
      select.locator("option", { hasText: `e2e-move-self-${stamp}` }),
      "the task's own project is offered as a destination — the API rejects that as same_project_move",
    ).toHaveCount(0);
  });

  test("a task with subtasks is refused rather than half-moved", async ({
    request,
  }) => {
    const stamp = Date.now();
    const source = await createProject(request, `e2e-move-sub-src-${stamp}`);
    const target = await createProject(request, `e2e-move-sub-dst-${stamp}`);
    projectIds.push(source.id, target.id);

    const parent = await createTask(request, source.id, `Parent ${stamp}`);
    await createSubtask(request, source.id, parent.id, `Child ${stamp}`);

    // Default strategy is "block" — the guard that keeps a subtree from being
    // split across two projects.
    const blocked = await request.post(
      `${API_BASE}/teams/${source.id}/tasks/${parent.id}/move-to-project`,
      {
        headers: authHeaders(),
        data: {
          target_project_id: target.id,
          source_action: "archive",
          subtask_strategy: "block",
        },
      },
    );
    expect(blocked.status(), await blocked.text()).toBe(400);
    expect(await blocked.text()).toContain("task_has_subtasks");

    // Nothing was created on the destination by the refused attempt.
    expect((await listTasks(request, target.id)).length).toBe(0);

    // Cascade carries the subtree across.
    const cascaded = await request.post(
      `${API_BASE}/teams/${source.id}/tasks/${parent.id}/move-to-project`,
      {
        headers: authHeaders(),
        data: {
          target_project_id: target.id,
          source_action: "archive",
          subtask_strategy: "cascade",
        },
      },
    );
    expect(cascaded.ok(), await cascaded.text()).toBe(true);
    const titles = (await listTasks(request, target.id)).map((t) => t.title);
    expect(titles).toContain(`Parent ${stamp}`);
    expect(
      titles,
      "cascade should have brought the subtask across too",
    ).toContain(`Child ${stamp}`);
  });
});
