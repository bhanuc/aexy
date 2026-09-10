/**
 * Theme tokens must be read through `hsl()`.
 *
 * `globals.css` defines the palette as bare HSL *components* — the shadcn
 * convention — so `--accent: 75 14% 89%` and not `--accent: hsl(75 14% 89%)`.
 * Tailwind's config wraps them (`hsl(var(--accent))`) for every class it
 * generates, which is why `bg-accent` works and hides the trap: written by
 * hand in an inline style or an SVG attribute, a bare `var(--accent)` is a
 * guaranteed-invalid value. The browser drops the whole declaration and paints
 * the initial value instead — transparent, or `none` for an SVG paint.
 *
 * It fails silently and looks like a behaviour bug rather than a styling one.
 * Five places had it independently:
 *
 *  - the docs `/` block menu had no background and no selection highlight, so
 *    arrow-key navigation appeared to do nothing (0.37.2);
 *  - `ReportDataView` and `PipelineAnalytics` lost their chart gridlines, axis
 *    labels and tooltip background;
 *  - two status dots (`TaskTableView`, the agent detail page) rendered
 *    invisible whenever they fell back to the token.
 *
 * So it is checked rather than remembered. Add a token to `PALETTE_TOKENS` when
 * you add one to `globals.css`.
 */

import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "fs";
import { join, relative } from "path";

const SRC = join(__dirname, "..");

/**
 * The bare-triplet tokens. Deliberately not every custom property in the app:
 * `--form-*` (the public form theme) and `--radius`/`--font-*` hold complete
 * values and are correct to use raw.
 */
const PALETTE_TOKENS = [
  "background",
  "foreground",
  "card",
  "card-foreground",
  "popover",
  "popover-foreground",
  "primary",
  "primary-foreground",
  "secondary",
  "secondary-foreground",
  "muted",
  "muted-foreground",
  "accent",
  "accent-foreground",
  "destructive",
  "destructive-foreground",
  "border",
  "input",
  "ring",
];

const RAW_TOKEN = new RegExp(
  `(?<!hsl\\()var\\(\\s*--(${PALETTE_TOKENS.join("|")})\\s*[,)]`,
  "g",
);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walk(full, out);
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

/** Strip comments so prose explaining the trap doesn't trip it. */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("theme token usage", () => {
  it("defines the palette as bare HSL components, which is what makes this a trap", () => {
    const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");
    // If this ever stops holding — tokens become full `hsl(...)` values — the
    // rule below is obsolete rather than merely unsatisfied, so fail loudly
    // here instead of leaving a check that no longer means anything.
    expect(
      css,
      "--accent is no longer a bare HSL triplet; revisit this whole test",
    ).toMatch(/--accent:\s*\d+\s+\d+%\s+\d+%/);
  });

  it("never reads a palette token without wrapping it in hsl()", () => {
    const offenders: string[] = [];

    for (const file of walk(SRC)) {
      const source = stripComments(readFileSync(file, "utf8"));
      const lines = source.split("\n");
      lines.forEach((line, i) => {
        for (const match of line.matchAll(RAW_TOKEN)) {
          offenders.push(
            `${relative(SRC, file)}:${i + 1}  var(--${match[1]})  →  hsl(var(--${match[1]}))`,
          );
        }
      });
    }

    expect(
      offenders,
      "these read a bare HSL-component token, so the declaration is invalid " +
        "at computed-value time and paints nothing:\n  " +
        offenders.join("\n  "),
    ).toEqual([]);
  });
});
