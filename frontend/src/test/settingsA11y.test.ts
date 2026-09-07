/**
 * Icon-only controls in settings need an accessible name.
 *
 * A `<button>` whose entire content is an icon has no text for a screen reader,
 * so without `aria-label` (or a `title`) it is announced as just "button" —
 * which is what 27 of them across the settings tree were doing: row menus,
 * deletes, removes, drag handles, add-to-list buttons, a copy-URL.
 *
 * The parsing matters more than it looks. A regex for the opening tag cannot
 * use `[^>]` to find the tag's end, because `onClick={() => …}` contains a `>`
 * — the first version of this test did exactly that and so skipped almost
 * every button in the codebase, reporting 10 offenders where there were 27.
 * `scanButtons` walks the tag tracking brace and quote depth instead.
 *
 * The second trap is what counts as "icon-only". An expression child renders
 * something: `<button><Icon/>{item.label}</button>` names itself, and stripping
 * `{…}` blind turns it into a false positive. Only comments, whitespace
 * expressions and the icons themselves are removed.
 */

import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

const SETTINGS_ROOT = join(__dirname, "..", "app", "(app)", "settings");
const SETTINGS_COMPONENTS = join(__dirname, "..", "components", "settings");

interface ButtonNode {
  index: number;
  attrs: string;
  body: string;
}

/** Find each `<button …>` opening tag, honouring `>` inside braces and strings. */
function scanButtons(src: string): ButtonNode[] {
  const out: ButtonNode[] = [];
  let i = 0;
  while ((i = src.indexOf("<button", i)) !== -1) {
    let j = i + "<button".length;
    let depth = 0;
    let quote: string | null = null;
    let end = -1;
    while (j < src.length) {
      const c = src[j];
      if (quote) {
        if (c === quote) quote = null;
      } else if (c === '"' || c === "'" || c === "`") {
        quote = c;
      } else if (c === "{") {
        depth++;
      } else if (c === "}") {
        depth--;
      } else if (c === ">" && depth === 0) {
        end = j;
        break;
      }
      j++;
    }
    if (end === -1) break;
    const close = src.indexOf("</button>", end);
    out.push({
      index: i,
      attrs: src.slice(i, end),
      body: close === -1 ? "" : src.slice(end + 1, close),
    });
    i = end + 1;
  }
  return out;
}

function isIconOnly(body: string): boolean {
  // Visually hidden text is a perfectly good name.
  if (/sr-only/.test(body)) return false;
  let rest = body
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "") // {/* comment */}
    .replace(/\{\s*(["'`])\s*\1\s*\}/g, ""); // {" "}
  const icons = rest.match(/<[A-Z][A-Za-z0-9]*\b[^>]*\/>/g) ?? [];
  if (icons.length === 0) return false;
  for (const icon of icons) rest = rest.replace(icon, "");
  return rest.trim() === "";
}

function tsxFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...tsxFiles(full));
    else if (entry.endsWith(".tsx")) out.push(full);
  }
  return out;
}

function unnamedIconButtons(file: string): string[] {
  const src = readFileSync(file, "utf8");
  return scanButtons(src)
    .filter(
      (b) =>
        isIconOnly(b.body) &&
        !b.attrs.includes("aria-label") &&
        !b.attrs.includes("title="),
    )
    .map((b) => {
      const line = src.slice(0, b.index).split("\n").length;
      const icon = /<([A-Z][A-Za-z0-9]*)/.exec(b.body)?.[1] ?? "?";
      return `${file.slice(file.indexOf("/src/") + 1)}:${line} <${icon} />`;
    });
}

const ALL_FILES = [...tsxFiles(SETTINGS_ROOT), ...tsxFiles(SETTINGS_COMPONENTS)];

describe("settings accessibility", () => {
  it("gives every icon-only button an accessible name", () => {
    expect(ALL_FILES.flatMap(unnamedIconButtons)).toEqual([]);
  });

  it("scans a meaningful number of files", () => {
    // Guards the guard: a wrong path would make the test above vacuous.
    expect(ALL_FILES.length).toBeGreaterThan(50);
  });

  it("finds the buttons it is meant to be looking at", () => {
    // The other half of guarding the guard. If a parser change stops matching
    // buttons at all, the first test passes for the wrong reason — as the
    // original `[^>]`-based version did.
    const buttons = ALL_FILES.flatMap((f) => scanButtons(readFileSync(f, "utf8")));
    expect(buttons.length).toBeGreaterThan(300);
    expect(buttons.filter((b) => isIconOnly(b.body)).length).toBeGreaterThan(50);
  });

  it("does not mistake a button with text for an icon-only one", () => {
    expect(isIconOnly('<Icon className="h-4" />')).toBe(true);
    expect(isIconOnly('<Icon className="h-4" />{item.label}')).toBe(false);
    expect(isIconOnly('<Icon className="h-4" /> Delete')).toBe(false);
    expect(isIconOnly('<Icon />{" "}')).toBe(true);
    expect(isIconOnly('<Icon /><span className="sr-only">Close</span>')).toBe(false);
    expect(isIconOnly("Delete")).toBe(false);
  });

  it("ends a button's opening tag past an arrow function", () => {
    // The bug that made the first version of this test near-vacuous.
    const src = '<button onClick={() => go()} className="x"><Icon /></button>';
    const [b] = scanButtons(src);
    expect(b.attrs).toContain("className");
    expect(b.body).toBe("<Icon />");
  });
});
