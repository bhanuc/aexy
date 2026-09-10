/**
 * Everything that decides who can reach an app lives on one page.
 *
 * Access resolves in four layers — the workspace app switch, the role
 * fallback, the department profile, the member override — and until now the
 * outermost one was on a different page from the other three. That is not a
 * cosmetic split: the workspace switch beats all of them, so an admin could
 * grant a department an app, watch nothing happen, and have no reason to look
 * three pages away for the cause.
 *
 * These tests pin the consolidation rather than the layout. What matters is
 * that the switch is reachable from Access Control, that the Organization page
 * no longer owns a second copy of it, and that the `?tab=` contract the link
 * relies on still resolves.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

const SRC = join(__dirname, "..");

const read = (...parts: string[]) => readFileSync(join(SRC, ...parts), "utf8");

const ACCESS_PAGE = read("app", "(app)", "settings", "access", "page.tsx");
const ORG_PAGE = read("app", "(app)", "settings", "organization", "page.tsx");
const PANEL = read("components", "access", "WorkspaceAppsPanel.tsx");

describe("the workspace app switch is on the access page", () => {
  it("is rendered there", () => {
    expect(ACCESS_PAGE).toContain("WorkspaceAppsPanel");
  });

  it("has a tab whose id the URL contract accepts", () => {
    // The Organization page links to `?tab=apps`. A tab the initial-tab parser
    // doesn't recognise silently falls back to the matrix, and the link would
    // look like it worked while landing somewhere else.
    expect(ACCESS_PAGE).toMatch(/tabParam === "apps"/);
    expect(ACCESS_PAGE).toMatch(/setActiveTab\("apps"\)/);
    expect(ACCESS_PAGE).toMatch(/activeTab === "apps"/);
  });

  it("orders the tabs broadest-first", () => {
    // Workspace → department → member is the order access resolves in, and the
    // tab strip is the only place that model is visible to an admin.
    const order = ["apps", "departments", "matrix", "requests"].map((tab) =>
      ACCESS_PAGE.indexOf(`setActiveTab("${tab}")`),
    );
    expect(order.every((i) => i !== -1)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });
});

describe("the organization page no longer owns it", () => {
  it("has no toggle of its own", () => {
    // Two switches writing the same field is worse than one in the wrong
    // place: they can disagree on screen, and only one of them is being looked
    // at when the other is changed.
    expect(ORG_PAGE).not.toContain("AppSettingsSection");
    expect(ORG_PAGE).not.toContain("useWorkspaceAppSettings");
  });

  it("points at where it went", () => {
    // Owners have gone here for it for as long as it existed. Removing it
    // without a signpost turns a moved control into a missing one.
    expect(ORG_PAGE).toContain("/settings/access?tab=apps");
  });
});

describe("the switch stays owner-only", () => {
  it("takes an isOwner prop and gates on it", () => {
    // It overrules every other layer at once, so an admin who can edit
    // departments still must not be able to switch an app off workspace-wide.
    expect(PANEL).toMatch(/isOwner: boolean/);
    expect(PANEL).toMatch(/if \(!isOwner\) return;/);
    expect(PANEL).toMatch(/disabled=\{isUpdating \|\| !isOwner\}/);
  });

  it("is handed the owner check, not the admin one", () => {
    // `useIsWorkspaceAdmin` is true for admins too. Passing that here would
    // widen who can turn apps off without changing a single line in the panel.
    expect(ACCESS_PAGE).toContain("useIsWorkspaceOwner");
    expect(ACCESS_PAGE).not.toMatch(/isOwner=\{isWorkspaceAdmin\}/);
  });
});

describe("dashboard cannot be switched off", () => {
  it("is filtered out of the toggle list", () => {
    // It is the landing page and the redirect target of
    // `WorkspaceAppToggleGuard`; switching it off sends every blocked
    // navigation to a page that is itself blocked.
    expect(PANEL).toMatch(/filter\(\(\[id\]\) => id !== "dashboard"\)/);
  });
});
