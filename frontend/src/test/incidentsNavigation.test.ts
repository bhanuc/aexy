/**
 * The on-call ticket queue has to be reachable, and reachable by the right people.
 *
 * An OpenObserve integration ingested 430 alerts into three tickets over two
 * months and nobody found them: the `tickets` app was fully registered and
 * permissioned, and had no sidebar entry in either layout. The API worked the
 * whole time. What was missing was a door.
 *
 * These are the properties that keep it open.
 */

import { describe, expect, it } from "vitest";

import { APP_CATALOG, SIDEBAR_TO_APP_MAP, getAppIdFromPath } from "@/config/appDefinitions";
import {
  GROUPED_LAYOUT,
  FLAT_LAYOUT,
  SIDEBAR_LAYOUTS,
  type SidebarItemConfig,
} from "@/config/sidebarLayouts";

const PARENT_HREF = "/tickets/alerts";
const SUB_HREFS = ["/tickets/alerts", "/tickets/submissions", "/tickets/alert-history"];

function topLevelItems(layout: { sections: { items: SidebarItemConfig[] }[] }) {
  return layout.sections.flatMap((section) => section.items);
}

function ticketsItem(layout: { sections: { items: SidebarItemConfig[] }[] }) {
  return topLevelItems(layout).find((item) => item.href === PARENT_HREF);
}

describe("the ticket queue is in the navigation", () => {
  it("appears in both layouts", () => {
    // An item added to GROUPED only vanishes for anybody who switched to Flat,
    // and Flat has no sections to carry a persona filter.
    for (const layout of [GROUPED_LAYOUT, FLAT_LAYOUT]) {
      expect(ticketsItem(layout), `missing from ${layout.id}`).toBeDefined();
    }
  });

  it("sits in Engineering, where developers can see it", () => {
    const section = GROUPED_LAYOUT.sections.find((s) => s.id === "engineering");
    expect(section).toBeDefined();
    expect(section!.items.some((item) => item.href === PARENT_HREF)).toBe(true);
  });

  it("is gated to personas the Engineering section also admits", () => {
    // An item persona list containing a persona the *section* excludes is
    // silently unreachable — the section filter runs first.
    const section = GROUPED_LAYOUT.sections.find((s) => s.id === "engineering")!;
    const item = ticketsItem(GROUPED_LAYOUT)!;
    for (const persona of item.personas ?? []) {
      expect(section.personas ?? [persona]).toContain(persona);
    }
    expect(item.personas).toContain("developer");
  });

  it("repeats its personas on the item in the flat layout", () => {
    // Nothing else gates it there.
    expect(ticketsItem(FLAT_LAYOUT)!.personas).toContain("developer");
  });

  it("stays clickable as a group", () => {
    // `Sidebar.tsx` drops a parent whose children all filter out unless one of
    // them shares its href. `/tickets` cannot be that href — it redirects to
    // Home for the command palette, the `t` shortcut and several widgets — so
    // Alerts carries it instead.
    for (const layout of [GROUPED_LAYOUT, FLAT_LAYOUT]) {
      const item = ticketsItem(layout)!;
      expect(item.items?.some((sub) => sub.href === item.href)).toBe(true);
    }
  });

  it("offers alerts, submissions and the alert history", () => {
    for (const layout of [GROUPED_LAYOUT, FLAT_LAYOUT]) {
      expect(ticketsItem(layout)!.items?.map((s) => s.href)).toEqual(SUB_HREFS);
    }
  });

  it("is not called Incidents", () => {
    // Uptime already has an item by that name for a different entity, and the
    // navigation file's own history is a run of fixes for one name meaning two
    // things. Guarding the label rather than trusting the comment.
    const labels = Object.values(SIDEBAR_LAYOUTS)
      .flatMap((layout) => topLevelItems(layout))
      .filter((item) => item.label === "Incidents")
      .map((item) => item.href);
    expect(labels).toEqual([]);
  });

  it("does not carry a badge", () => {
    // `useSidebarBadges` resolves exactly one key, for /review.
    for (const layout of [GROUPED_LAYOUT, FLAT_LAYOUT]) {
      expect(ticketsItem(layout)!.badge).toBeUndefined();
    }
  });
});

describe("the queue's routes are access-controlled", () => {
  it("resolves every sub-route to the tickets app", () => {
    // A route that resolves to no app is shown to everybody —
    // `canAccessItem` treats "not in the catalog" as "not gated".
    for (const href of SUB_HREFS) {
      expect(getAppIdFromPath(href), href).toBe("tickets");
    }
  });

  it("names them in the route map explicitly", () => {
    for (const href of SUB_HREFS) {
      expect(SIDEBAR_TO_APP_MAP[href], href).toBe("tickets");
    }
  });

  it("declares them as modules of the tickets app", () => {
    // Module ids are what the access resolver toggles and what the parity
    // fixture compares, so a sub-route with no module is un-gateable per-module.
    const routes = (APP_CATALOG.tickets.modules ?? []).map(
      (module) => `${APP_CATALOG.tickets.baseRoute}${module.route ?? ""}`,
    );
    for (const href of SUB_HREFS) {
      expect(routes, href).toContain(href);
    }
  });

  it("keeps the tickets app in Engineering", () => {
    // The nav item is in the Engineering section; an app filed under a
    // different category would group elsewhere in the access admin UI and read
    // as a different product.
    expect(APP_CATALOG.tickets.category).toBe("engineering");
  });
});
