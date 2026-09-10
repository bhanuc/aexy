/**
 * Access outranks a persona nobody chose.
 *
 * The sidebar filtered by persona first and by access second, as a flat AND,
 * so a persona could hide an app the workspace had granted. That is how the
 * Operations team ended up with no Service Desk entry: they have access to it,
 * but nobody had picked a persona and the "developer" default hides the
 * Business section, so they had been reaching it by URL.
 *
 * These cases pin the precedence down, because "which wins" is the whole
 * decision and it is not visible from reading either filter alone:
 *
 *   - never chose a persona   -> access wins, always
 *   - chose one               -> it narrows, that was the point of choosing
 *   - chose one, but an app was switched on for them specifically
 *                             -> that grant wins anyway
 *   - no access               -> hidden either way
 *
 * The "never chose one" test is deliberately the *default* persona rather than
 * a department-derived one. No department in this workspace sets
 * `default_persona`, so the people this bug affects are on the bare default —
 * and `isPersonaDerived` reports false for them. Gating on that flag instead of
 * "no explicit choice" would have left the reported bug unfixed.
 */

import { describe, it, expect } from "vitest";

import { accessOverridesPersona, AccessSource } from "@/lib/sidebarAccess";

type Source = AccessSource;

/** Thin adapter so each case reads as the situation it describes. */
function keepDespitePersona(
  href: string,
  opts: {
    access?: boolean;
    source?: Source;
    chosenPersona?: string | null;
    inCatalog?: boolean;
  },
): boolean {
  return accessOverridesPersona({
    appId: opts.inCatalog === false ? null : href.slice(1),
    hasAccess: opts.access ?? true,
    source: opts.source ?? "role_fallback",
    chosenPersona: opts.chosenPersona ?? null,
  });
}

const SERVICE_DESK = "/service-desk";

describe("access vs persona in the sidebar", () => {
  it("shows an accessible app when the person never chose a persona", () => {
    // Operations: bare "developer" default, real Service Desk access.
    expect(
      keepDespitePersona(SERVICE_DESK, { chosenPersona: null }),
    ).toBe(true);
  });

  it("still shows it when the default came from a department suggestion", () => {
    // Same branch, but making the department-derived case explicit: neither
    // kind of unchosen persona should hide granted access.
    expect(
      keepDespitePersona(SERVICE_DESK, { chosenPersona: null, source: "department" }),
    ).toBe(true);
  });

  it("lets a persona the person picked narrow the sidebar", () => {
    expect(
      keepDespitePersona(
        SERVICE_DESK,
        { chosenPersona: "developer", source: "role_fallback" },
      ),
    ).toBe(false);
  });

  it("overrides even a chosen persona when the app was switched on for them", () => {
    expect(
      keepDespitePersona(
        SERVICE_DESK,
        { chosenPersona: "developer", source: "member_override" },
      ),
    ).toBe(true);
  });

  it("does not treat department or template grants as personal overrides", () => {
    // These are deliberate, but they are about a group. Someone who chose a
    // narrower view keeps it.
    for (const source of ["department", "member_template"] as const) {
      expect(
        keepDespitePersona(SERVICE_DESK, { chosenPersona: "developer", source }),
      ).toBe(false);
    }
  });

  it("never rescues an app the person cannot access", () => {
    for (const chosenPersona of [null, "developer"]) {
      expect(
        keepDespitePersona(SERVICE_DESK, { access: false, chosenPersona }),
      ).toBe(false);
    }
    // Not even an override on a workspace-disabled app.
    expect(
      keepDespitePersona(
        SERVICE_DESK,
        { access: false, source: "member_override", chosenPersona: null },
      ),
    ).toBe(false);
  });

  it("leaves routes outside the app catalogue to the persona", () => {
    // No app id means no access answer to defer to.
    expect(
      keepDespitePersona("/some/page", { inCatalog: false, chosenPersona: null }),
    ).toBe(false);
  });
});
