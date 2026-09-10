import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  SETTINGS_GROUPS,
  SettingsGroupTabs,
  type SettingsGroupKey,
} from "@/components/settings/SettingsGroupPage";

/**
 * The sibling strip for each settings area, over every route it covers.
 *
 * Driven from the same definition the component uses, so adding an area or a
 * tab is covered without touching this file — the point being that these
 * areas used to hand-roll their navigation and drift apart. `useTranslations`
 * is backed by the real English messages (see `src/test/setup.ts`), so a
 * missing label key fails here rather than rendering the key itself.
 */

let pathname = "/settings";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

// `next/link` needs no router in this context; render it as a plain anchor.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const GROUP_KEYS = Object.keys(SETTINGS_GROUPS) as SettingsGroupKey[];

describe("settings area navigation", () => {
  beforeEach(() => {
    pathname = "/settings";
  });

  it("covers every area defined", () => {
    // Guards against an area being added to the app but not to the strip.
    expect(GROUP_KEYS).toEqual(["access", "identity", "serviceDesk"]);
  });

  for (const key of GROUP_KEYS) {
    const group = SETTINGS_GROUPS[key];

    describe(key, () => {
      it("offers every sibling from every sibling", () => {
        for (const tab of group.tabs) {
          pathname = tab.href;
          const { unmount } = render(<SettingsGroupTabs group={key} />);
          const links = screen.getAllByRole("link");
          expect(links).toHaveLength(group.tabs.length);
          for (const sibling of group.tabs) {
            expect(
              links.some((l) => l.getAttribute("href") === sibling.href),
            ).toBe(true);
          }
          unmount();
        }
      });

      it("marks exactly the current tab, on the tab's own route and below it", () => {
        for (const tab of group.tabs) {
          for (const path of [tab.href, `${tab.href}/something`]) {
            // A tab whose href is a prefix of a longer sibling must not win on
            // that sibling's route — the area root is a prefix of them all.
            const longestMatch = group.tabs
              .filter((t) => path === t.href || path.startsWith(t.href + "/"))
              .sort((a, b) => b.href.length - a.href.length)[0];
            if (longestMatch?.key !== tab.key) continue;

            pathname = path;
            const { unmount } = render(<SettingsGroupTabs group={key} />);
            const current = screen
              .getAllByRole("link")
              .filter((l) => l.getAttribute("aria-current") === "page");
            expect(current).toHaveLength(1);
            expect(current[0].getAttribute("href")).toBe(tab.href);
            unmount();
          }
        }
      });

      it("renders real labels, not message keys", () => {
        pathname = group.tabs[0].href;
        render(<SettingsGroupTabs group={key} />);
        for (const link of screen.getAllByRole("link")) {
          const text = link.textContent?.trim() ?? "";
          expect(text).not.toBe("");
          // A missing key renders as the key path itself.
          expect(text).not.toMatch(/^settingsGroups\./);
          expect(text).not.toMatch(/^tabs\./);
        }
      });

      it("names the strip for screen readers", () => {
        pathname = group.tabs[0].href;
        render(<SettingsGroupTabs group={key} />);
        const nav = screen.getByRole("navigation");
        const label = nav.getAttribute("aria-label") ?? "";
        expect(label).not.toBe("");
        expect(label).not.toMatch(/^settingsGroups\./);
      });
    });
  }

  it("gives every tab a distinct href within its area", () => {
    for (const key of GROUP_KEYS) {
      const hrefs = SETTINGS_GROUPS[key].tabs.map((t) => t.href);
      expect(new Set(hrefs).size).toBe(hrefs.length);
    }
  });
});
