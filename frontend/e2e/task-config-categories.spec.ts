import { test, expect, Page } from "@playwright/test";
import { mockUser } from "./fixtures/mock-data";

/**
 * Status categories in workspace task settings.
 *
 * This section used to be a fixed legend of three names ("To Do", "In
 * Progress", "Done") that ignored the workspace's real buckets and offered no
 * way to change them — while the project status page linked here to edit
 * shared buckets. These tests pin down that it is now the editor: the real set
 * renders, the workspace's own rows are editable, and a project that is still
 * inheriting says so instead of offering an edit that would reach every other
 * project.
 */

const API_BASE = "http://localhost:8000/api/v1";
const WS = "ws-1";
const PROJECT_ID = "proj-1";

const mockWorkspace = {
  id: WS,
  name: "Northwind",
  slug: "northwind",
  type: "business",
  avatar_url: null,
  owner_id: mockUser.id,
  member_count: 1,
  team_count: 1,
  is_active: true,
};

// The test user has to be an admin for any editing affordance to render.
const mockMembers = [
  {
    id: "wm-1",
    workspace_id: WS,
    developer_id: mockUser.id,
    name: mockUser.name,
    email: mockUser.email,
    avatar_url: null,
    role: "owner",
    status: "active",
    joined_at: "2026-01-01T00:00:00Z",
  },
];

const mockProjects = [
  { id: PROJECT_ID, workspace_id: WS, name: "Apollo", slug: "apollo", is_active: true },
];

function category(
  slug: string,
  label: string,
  semantics: string,
  position: number,
  projectId: string | null,
) {
  return {
    id: `cat-${projectId ? "p" : "w"}-${slug}`,
    workspace_id: WS,
    project_id: projectId,
    slug,
    label,
    color: "#6B7280",
    semantics,
    position,
    is_default: slug === "backlog",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

/** The canonical six, in a given scope. */
function sixCategories(projectId: string | null) {
  return [
    category("backlog", "Backlog", "open", 0, projectId),
    category("todo", "To Do", "open", 1, projectId),
    category("in_progress", "In Progress", "active", 2, projectId),
    // Renamed at the workspace level — proves the list is the real data and
    // not the old hardcoded legend, which called this "In Progress"/"Done".
    category("in_review", "Code Review", "active", 3, projectId),
    category("done", "Shipped", "done", 4, projectId),
    category("cancelled", "Cancelled", "cancelled", 5, projectId),
  ];
}

const workspaceStatus = {
  id: "st-1",
  workspace_id: WS,
  project_id: null,
  name: "Backlog",
  slug: "backlog",
  category: "backlog",
  color: "#9CA3AF",
  icon: null,
  position: 0,
  is_default: true,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

interface SetupOptions {
  /** Categories returned for `?project_id=proj-1`. */
  projectCategories?: unknown[];
  /** Collects the bodies of any POST to /status-categories. */
  createdCategories?: unknown[];
}

async function setup(page: Page, options: SetupOptions = {}) {
  await page.addInitScript(
    ([wsId]) => {
      localStorage.setItem("token", "fake-test-token");
      localStorage.setItem("current_workspace_id", wsId);
    },
    [WS],
  );
  await page.context().addCookies([
    { name: "aexy_authed", value: "1", url: "http://localhost:3000" },
  ]);

  // Catch-all FIRST — Playwright matches routes last-registered-first.
  await page.route(`${API_BASE}/**`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route(`${API_BASE}/workspaces`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([mockWorkspace]),
    }),
  );
  await page.route(`${API_BASE}/developers/me`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockUser),
    }),
  );
  await page.route(`${API_BASE}/notifications**`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );

  await page.route(`${API_BASE}/workspaces/**`, async (route) => {
    const request = route.request();
    const url = request.url();
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    if (url.includes("/status-categories")) {
      if (request.method() === "POST") {
        options.createdCategories?.push(request.postDataJSON());
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(
            category("design_review", "Design Review", "active", 6, null),
          ),
        });
      }
      const scoped = url.includes(`project_id=${PROJECT_ID}`);
      return json(
        scoped ? (options.projectCategories ?? sixCategories(null)) : sixCategories(null),
      );
    }
    if (url.includes("/task-statuses")) return json([workspaceStatus]);
    if (url.includes("/custom-fields")) return json([]);
    // The settings shell gates this page on can_manage_workspace_settings;
    // without it the whole page is replaced by the access-denied panel.
    if (url.includes("/my-permissions"))
      return json({
        permissions: ["can_manage_workspace_settings"],
        is_owner: true,
        role_name: "Owner",
      });
    // Before /members — the effective-access path is nested under it, and
    // answering that call with the member array crashes the app shell.
    if (url.includes("/apps/effective") || url.includes("/app-access/"))
      return json({
        apps: {},
        applied_template_id: null,
        applied_template_name: null,
        has_custom_overrides: false,
        is_admin: true,
      });
    if (url.includes("/members")) return json(mockMembers);
    if (url.includes("/projects")) return json(mockProjects);
    if (url.match(/\/(spaces|documents|invites|teams|notifications)/)) return json([]);
    if (url.endsWith(`/workspaces/${WS}`)) return json(mockWorkspace);
    return json({});
  });
}

/** The Status Categories section, scoped so status rows can't match. */
function categorySection(page: Page) {
  return page.getByRole("region", { name: "Status Categories" });
}

test.describe("workspace status categories", () => {
  test("renders the workspace's real category set, not a fixed legend", async ({
    page,
  }) => {
    await setup(page);
    await page.goto("/settings/task-config");

    await expect(
      page.getByRole("heading", { name: "Status Categories", level: 2 }),
    ).toBeVisible({ timeout: 20000 });

    const section = categorySection(page);
    // All six buckets, including the two the old legend had no concept of and
    // the two the workspace renamed.
    for (const label of [
      "Backlog",
      "To Do",
      "In Progress",
      "Code Review",
      "Shipped",
      "Cancelled",
    ]) {
      await expect(section.getByText(label, { exact: true })).toBeVisible();
    }
    // Semantics are surfaced — that's what burndown branches on. Two buckets
    // carry `active`, and no slug is spelled that way, so the count is exact.
    await expect(section.getByText("active", { exact: true })).toHaveCount(2);
    // The slug is shown so it can be matched against a status's category.
    await expect(section.getByText("in_review", { exact: true })).toBeVisible();
    // The bucket the old legend had no concept of, by slug.
    await expect(section.getByText("needs_revision")).toHaveCount(0);
  });

  test("workspace-owned categories are editable", async ({ page }) => {
    await setup(page);
    await page.goto("/settings/task-config");
    await expect(
      page.getByRole("heading", { name: "Status Categories", level: 2 }),
    ).toBeVisible({ timeout: 20000 });

    const section = categorySection(page);
    // No inherited note: these rows belong to the scope being edited.
    await expect(
      page.getByText(/inherited from the workspace/i),
    ).toHaveCount(0);

    // Every row offers the manage menu ...
    await expect(
      section.getByRole("button", { name: /^Manage category/ }),
    ).toHaveCount(6);

    // ... and it actually opens Edit / Delete.
    await section
      .getByRole("button", { name: "Manage category Code Review" })
      .click();
    await expect(section.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(section.getByRole("button", { name: "Delete" })).toBeVisible();

    await section.getByRole("button", { name: "Edit" }).click();
    // The edit modal opens on that row: the label is editable, and the slug
    // shows the existing value in the same read-only field, with the reason.
    await expect(page.getByRole("heading", { name: "Edit Category" })).toBeVisible();
    await expect(page.getByLabel("Label")).toHaveValue("Code Review");
    await expect(page.getByLabel("Slug")).toHaveValue("in_review");
    await expect(page.getByLabel("Slug")).toHaveAttribute("readonly", "");
    await expect(
      page.getByText(/statuses already reference it/),
    ).toBeVisible();
  });

  test("adding a workspace category posts no project scope", async ({ page }) => {
    const createdCategories: unknown[] = [];
    await setup(page, { createdCategories });
    await page.goto("/settings/task-config");
    await expect(
      page.getByRole("heading", { name: "Status Categories", level: 2 }),
    ).toBeVisible({ timeout: 20000 });

    await categorySection(page)
      .getByRole("button", { name: "Add Category" })
      .click();
    await expect(page.getByRole("heading", { name: "Create Category" })).toBeVisible();

    const labelField = page.getByLabel("Label");
    const slugField = page.getByLabel("Slug");

    // Empty until something is typed, so it reads as derived rather than as a
    // second thing to fill in.
    await expect(slugField).toHaveValue("");

    await labelField.fill("Design Review");
    // The slug tracks the label live, and is its own field rather than a
    // caption — the two are identical for one-word buckets, which is what
    // left people unsure which of them they had just typed.
    await expect(slugField).toHaveValue("design_review");
    // Not typeable — the label is the only way to change it. (Asserted, not
    // attempted: `fill()` waits for editability and would just time out.)
    await expect(slugField).not.toBeEditable();
    await expect(slugField).toHaveAttribute("readonly", "");
    await expect(labelField).toBeEditable();

    await page.getByRole("button", { name: /Save|Create/ }).click();

    await expect.poll(() => createdCategories.length).toBe(1);
    const body = createdCategories[0] as Record<string, unknown>;
    expect(body.slug).toBe("design_review");
    expect(body.label).toBe("Design Review");
    // Workspace scope — no project_id, so this doesn't fork anything.
    expect(body.project_id).toBeUndefined();
  });
});

test.describe("project-scoped status categories", () => {
  test("a project still inheriting says so and offers no edit", async ({ page }) => {
    // Project scope resolves to the workspace rows (project_id null).
    await setup(page, { projectCategories: sixCategories(null) });
    await page.goto(`/settings/task-config?project=${PROJECT_ID}`);
    await expect(
      page.getByRole("heading", { name: "Status Categories", level: 2 }),
    ).toBeVisible({ timeout: 20000 });

    const section = categorySection(page);
    // The rows are still listed — nothing looks deleted ...
    await expect(section.getByText("Code Review", { exact: true })).toBeVisible();
    // ... but they're named as inherited, and the note says adding one copies
    // the whole set in first (the bug this release fixes).
    await expect(page.getByText(/inherited from the workspace/i)).toBeVisible();
    await expect(page.getByText(/copies the full set into this project/i)).toBeVisible();

    // No edit/delete on a row this project doesn't own — using it would have
    // silently changed every other project that inherits it.
    await expect(
      section.getByRole("button", { name: /^Manage category/ }),
    ).toHaveCount(0);

    // Adding is still offered; that's the supported way to fork.
    await expect(
      section.getByRole("button", { name: "Add Category" }),
    ).toBeVisible();
  });

  test("a project that has forked owns its categories", async ({ page }) => {
    // Its own rows, plus the bucket that triggered the fork.
    await setup(page, {
      projectCategories: [
        ...sixCategories(PROJECT_ID),
        category("needs_revision", "Needs Revision", "open", 6, PROJECT_ID),
      ],
    });
    await page.goto(`/settings/task-config?project=${PROJECT_ID}`);
    await expect(
      page.getByRole("heading", { name: "Status Categories", level: 2 }),
    ).toBeVisible({ timeout: 20000 });

    const section = categorySection(page);
    // The inherited six survived the fork — this is the regression.
    for (const label of ["Backlog", "To Do", "Code Review", "Shipped", "Cancelled"]) {
      await expect(section.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(section.getByText("Needs Revision", { exact: true })).toBeVisible();

    // Owned rows: no inherited note, and all seven are editable.
    await expect(page.getByText(/inherited from the workspace/i)).toHaveCount(0);
    await expect(
      section.getByRole("button", { name: /^Manage category/ }),
    ).toHaveCount(7);
  });
});

test("a label with no Latin characters is refused with the reason", async ({
  page,
}) => {
  const createdCategories: unknown[] = [];
  await setup(page, { createdCategories });
  await page.goto("/settings/task-config");
  await categorySection(page)
    .getByRole("button", { name: "Add Category" })
    .click();

  // `slugify` keeps only Latin letters and digits, so a Devanagari label
  // reduces to an empty slug — which the API rejects on min_length. The modal
  // says so instead of posting it.
  await page.getByLabel("Label").fill("डिज़ाइन समीक्षा");
  await expect(page.getByLabel("Slug")).toHaveValue("");
  await page.getByRole("button", { name: /Save|Create/ }).click();

  await expect(page.getByText(/built from Latin letters/i)).toBeVisible();
  expect(createdCategories).toHaveLength(0);

  // Adding Latin characters clears the way.
  await page.getByLabel("Label").fill("Design Review 2");
  await expect(page.getByLabel("Slug")).toHaveValue("design_review_2");
  await page.getByRole("button", { name: /Save|Create/ }).click();
  await expect.poll(() => createdCategories.length).toBe(1);
});

test("the modal is translated, not hardcoded English", async ({ page }) => {
  await setup(page);
  // next-intl reads the locale from this cookie (no URL prefix).
  await page.context().addCookies([
    { name: "NEXT_LOCALE", value: "hi", url: "http://localhost:3000" },
  ]);
  await page.goto("/settings/task-config");
  await categorySection(page)
    .getByRole("button", { name: /Add Category|श्रेणी/ })
    .click();

  // Heading, both field labels and the derived-slug hint all come from
  // messages now. `Slug` stays Latin in hi by design — it is the wire value.
  await expect(page.getByRole("heading", { name: "श्रेणी बनाएँ" })).toBeVisible();
  await expect(page.getByLabel("लेबल")).toBeVisible();
  await expect(page.getByText(/लेबल से बनता है/)).toBeVisible();
  // Semantics options are translated too.
  await expect(page.getByRole("button", { name: /खुला/ })).toBeVisible();
  // And the footer uses the shared common strings.
  await expect(page.getByRole("button", { name: "रद्द करें" })).toBeVisible();
});

test("the status dialog shows category semantics as words, translated", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/settings/task-config");
  await page.getByRole("button", { name: "Add Status" }).first().click();

  const dialog = page.getByRole("dialog", { name: "Create Status" });
  await expect(dialog).toBeVisible({ timeout: 20000 });

  // The category cells used to print the raw semantics slug. They read the
  // same messages the category dialog defines, so the two can't drift.
  const shipped = dialog.getByRole("button", { name: /Shipped/ });
  await expect(shipped).toContainText("Done");
  await expect(shipped).toHaveAttribute(
    "title",
    "Completed — counts toward velocity",
  );
});

test("the status dialog is translated too", async ({ page }) => {
  await setup(page);
  await page.context().addCookies([
    { name: "NEXT_LOCALE", value: "hi", url: "http://localhost:3000" },
  ]);
  await page.goto("/settings/task-config");
  await page.getByRole("button", { name: /Add Status/ }).first().click();

  const dialog = page.getByRole("dialog", { name: "स्थिति बनाएँ" });
  await expect(dialog).toBeVisible({ timeout: 20000 });
  await expect(dialog.getByLabel("नाम")).toBeVisible();
  await expect(dialog.getByText("श्रेणी", { exact: true })).toBeVisible();
  await expect(
    dialog.getByText(/नए टास्क के लिए डिफ़ॉल्ट स्थिति/),
  ).toBeVisible();
  // Semantics come through the shared category namespace.
  await expect(dialog.getByRole("button", { name: /Shipped/ })).toContainText(
    "पूर्ण",
  );
});
