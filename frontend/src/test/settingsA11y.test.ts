/**
 * Icon-only controls in settings need an accessible name.
 *
 * A `<button>` whose entire content is an icon has no text for a screen
 * reader to read, so without `aria-label` (or a `title`) it is announced as
 * just "button" — which is what ten of them across the settings tree were
 * doing: two "add option" buttons, two deletes, a remove, a drag handle, a
 * row menu, a copy-URL and two add-to-list buttons. They were spread over six
 * files, which is why the class of bug is worth a test rather than ten fixes.
 *
 * The scan is deliberately narrow: only buttons whose children are *entirely*
 * self-closing capitalised elements (an icon component and nothing else). A
 * button with any text in it names itself.
 */

import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

const SETTINGS_ROOT = join(__dirname, "..", "app", "(app)", "settings");
const SETTINGS_COMPONENTS = join(__dirname, "..", "components", "settings");

function tsxFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...tsxFiles(full));
    else if (entry.endsWith(".tsx")) out.push(full);
  }
  return out;
}

/** `<button …>` followed only by self-closing capitalised elements. */
const ICON_ONLY_BUTTON =
  /<button\b((?:[^>]|\n)*?)>\s*((?:<[A-Z][A-Za-z0-9]*\b[^>]*\/>\s*)+)<\/button>/g;

function unnamedIconButtons(file: string): string[] {
  const src = readFileSync(file, "utf8");
  const hits: string[] = [];
  for (const m of src.matchAll(ICON_ONLY_BUTTON)) {
    const attrs = m[1];
    if (attrs.includes("aria-label") || attrs.includes("title=")) continue;
    const line = src.slice(0, m.index).split("\n").length;
    const icon = /<([A-Z][A-Za-z0-9]*)/.exec(m[2])?.[1] ?? "?";
    hits.push(`${file.split("/frontend/")[1]}:${line} <${icon} />`);
  }
  return hits;
}

describe("settings accessibility", () => {
  it("gives every icon-only button an accessible name", () => {
    const offenders = [
      ...tsxFiles(SETTINGS_ROOT),
      ...tsxFiles(SETTINGS_COMPONENTS),
    ].flatMap(unnamedIconButtons);

    expect(offenders).toEqual([]);
  });

  it("scans a meaningful number of files", () => {
    // Guards the guard: a broken path would make the test above vacuous.
    const files = [...tsxFiles(SETTINGS_ROOT), ...tsxFiles(SETTINGS_COMPONENTS)];
    expect(files.length).toBeGreaterThan(50);
  });
});
