import { test, expect, Page } from "@playwright/test";
import { mockUser } from "./fixtures/mock-data";

/**
 * The workspace app switch, on the page that owns the rest of access.
 *
 * It used to live on Settings → Organization, three layers away from the
 * department profiles and member overrides it overrules — so an admin could
 * grant a department an app, see nothing happen, and have no reason to look
 * at another page for the cause.
 *
 * The unit tests cover the panel in isolation. What needs a browser is the
 * part that spans pages: the Organization link lands on the right tab, the
 * `?tab=apps` URL contract resolves, and a real toggle round-trips to the API
 * with the whole settings map rather than the one key that changed.
 */

const API_BASE = "http://localhost:8000/api/v1";
const WS = "ws-1";

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

/** Three is enough to prove the whole map is sent; the real one has 27. */
const APP_SETTINGS = { crm: true, sprints: false, docs: true };

interface SetupOptions {
  /** Collects the body of any PATCH to /workspaces/{id}/apps. */
  saved?: unknown[];
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
  // Object, not a list: `useNotifications` reads `data.notifications.length`
  // straight off the response, and a bare `[]` throws into the dev overlay,
  // which then covers the page every assertion below is about.
  await page.route(`${API_BASE}/notifications**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        notifications: [],
        unread_count: 0,
        has_next: false,
      }),
    }),
  );

  // `TeamReviewCard` renders in this shell and reads `data.snapshots` behind
  // only a `!data` guard, so the catch-all's `{}` is truthy, `.snapshots` is
  // undefined, and the whole page lands in its error boundary.
  await page.route(`${API_BASE}/code-insights/**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ snapshots: [] }),
    }),
  );

  await page.route(`${API_BASE}/workspaces/**`, async (route) => {
    const request = route.request();
    const url = request.url();
    const path = url.split("?")[0];
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    // The settings shell gates these pages on the permission; without it the
    // whole page is replaced by the access-denied panel and nothing below is
    // on screen to assert about.
    if (url.includes("/my-permissions"))
      return json({
        permissions: ["can_manage_workspace_settings", "can_manage_roles"],
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
    // `/workspaces/{id}/apps` — the workspace app switch, GET to read and
    // PATCH to write. Checked after `/apps/effective`, which is a different
    // endpoint that merely starts the same way.
    if (path.endsWith("/apps")) {
      if (request.method() === "PATCH") {
        options.saved?.push(request.postDataJSON());
      }
      return json(APP_SETTINGS);
    }
    if (url.includes("/members")) return json(mockMembers);
    if (url.endsWith(`/workspaces/${WS}`)) return json(mockWorkspace);
    // Everything else under /workspaces/ is a collection. `{}` here is what
    // takes the app shell down — the sidebar's document spaces call
    // `spaces?.find`, which an object does not have.
    return json([]);
  });
}

/** The switch for one app, by the accessible name the panel gives it. */
const switchFor = (page: Page, label: string) =>
  page.getByRole("switch", { name: label, exact: true });

test.describe("the Apps tab", () => {
  test("is where ?tab=apps lands", async ({ page }) => {
    await setup(page);
    await page.goto("/settings/access?tab=apps");

    // An unrecognised tab id falls back to the members matrix, so a broken
    // contract would look like the link quietly going somewhere else.
    await expect(switchFor(page, "CRM")).toBeVisible({ timeout: 20000 });
    await expect(switchFor(page, "CRM")).toHaveAttribute("aria-checked", "true");
    await expect(switchFor(page, "Sprints")).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  test("is not what the page opens on", async ({ page }) => {
    await setup(page);
    await page.goto("/settings/access");

    // The tab strip reads broadest-first, but the landing tab stays the
    // members matrix — moving it would change what every bookmark opens on.
    await expect(page.getByRole("button", { name: "Apps" })).toBeVisible({
      timeout: 20000,
    });
    await expect(switchFor(page, "CRM")).toHaveCount(0);
  });

  test("sends the whole settings map when one app changes", async ({ page }) => {
    const saved: unknown[] = [];
    await setup(page, { saved });
    await page.goto("/settings/access?tab=apps");

    await expect(switchFor(page, "CRM")).toBeVisible({ timeout: 20000 });
    await switchFor(page, "CRM").click();

    await expect.poll(() => saved.length, { timeout: 10000 }).toBe(1);
    // The endpoint replaces the settings object. Sending `{crm: false}` alone
    // would drop `sprints: false` and turn Sprints back on as a side effect.
    expect(saved[0]).toEqual({
      apps: { crm: false, sprints: false, docs: true },
    });
  });
});

test.describe("the Organization page", () => {
  test("links to the tab rather than keeping a second copy", async ({ page }) => {
    await setup(page);
    await page.goto("/settings/organization");

    const link = page.getByRole("link", { name: /App Settings/i });
    await expect(link).toBeVisible({ timeout: 20000 });
    await expect(link).toHaveAttribute("href", "/settings/access?tab=apps");

    // No toggles of its own: two switches writing the same field can disagree
    // on screen, and only one is being looked at when the other changes.
    await expect(page.getByRole("switch", { name: "CRM" })).toHaveCount(0);

    await link.click();
    await expect(switchFor(page, "CRM")).toBeVisible({ timeout: 20000 });
  });
});
