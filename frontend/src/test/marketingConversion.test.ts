/**
 * Conversion-path guards for the public marketing pages.
 *
 * These encode decisions that were wrong on the live site and are easy to
 * silently reintroduce, because none of them break a build or a render:
 *
 *  - Every high-intent SEO page (compare/*, use-cases/*, for/*) sent its
 *    primary CTA to /contact, which is a page of mailto: links. For an
 *    open-source product that is free to self-host, the highest-intent
 *    visitor wants a workspace, not a calendar invite.
 *  - Product pages pointed their only primary CTA at the Google OAuth URL,
 *    excluding anyone without a Google account, and their secondary CTA at
 *    /manifesto — a philosophy page with no next step.
 *  - Two pages carried invented social proof ("Join thousands of teams",
 *    "40% faster hiring"). The brand rule for this site is that every claim
 *    must be inspectable; fabricated numbers are also a manual-action risk.
 *
 * Source-scan rather than render: the point is to catch the wiring changing,
 * not to freeze the copy.
 */

import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, existsSync } from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..", "..");
const APP = join(ROOT, "src", "app");
const MARKETING = join(ROOT, "src", "components", "marketing");

const read = (...p: string[]) => readFileSync(join(...p), "utf8");
const productPages = () =>
  readdirSync(join(APP, "products")).filter((d) => existsSync(join(APP, "products", d, "page.tsx")));

describe("self-serve conversion path", () => {
  it("the shared SEO templates lead with the self-serve CTA", () => {
    for (const file of ["SeoLandingPage.tsx", "ComparisonPage.tsx"]) {
      const src = read(MARKETING, file);
      const loginAt = src.indexOf('href="/login"');
      const contactAt = src.indexOf('href="/contact"');
      expect(loginAt, `${file}: no /login CTA — the self-serve path is missing`).toBeGreaterThan(-1);
      expect(contactAt, `${file}: no /contact CTA — the demo path is missing`).toBeGreaterThan(-1);
      expect(
        loginAt,
        `${file}: /contact comes before /login, so the demo is the primary CTA again`,
      ).toBeLessThan(contactAt);
    }
  });

  it("no product page sends its CTA straight to a single OAuth provider", () => {
    // /login offers Google *and* GitHub and reads "Sign in or create your
    // workspace"; a bare provider URL forces one identity provider.
    const offenders = productPages().filter((slug) =>
      /auth\/(google|github)\/login/.test(read(APP, "products", slug, "page.tsx")),
    );
    expect(offenders, "product pages hardcoding one OAuth provider as the CTA").toEqual([]);
  });

  it("every product page offers a self-serve CTA before a sales one", () => {
    // The four server-rendered product pages (crm, ai-agents, gtm-intelligence,
    // mcp) each led with "Book demo" while the other twelve led with signup.
    const offenders: string[] = [];
    for (const slug of productPages()) {
      const src = read(APP, "products", slug, "page.tsx");
      const loginAt = src.indexOf('href="/login"');
      const contactAt = src.indexOf('href="/contact"');
      if (loginAt === -1) {
        offenders.push(`${slug}: no /login CTA`);
      } else if (contactAt > -1 && contactAt < loginAt) {
        offenders.push(`${slug}: /contact precedes /login`);
      }
    }
    expect(offenders, "product page leads with the sales CTA").toEqual([]);
  });

  it("no product page uses /manifesto as a call to action", () => {
    const offenders = productPages().filter((slug) =>
      read(APP, "products", slug, "page.tsx").includes('href="/manifesto"'),
    );
    expect(offenders, "/manifesto is a dead end from a product page").toEqual([]);
  });
});

describe("no fabricated proof", () => {
  // Deliberately narrow: these match invented volume and outcome claims, not
  // ordinary marketing adjectives.
  const BANNED = [
    /join (thousands|hundreds|[0-9,]+)/i,
    /(thousands|hundreds) of (teams|companies|users|developers|customers)/i,
    /trusted by [0-9]/i,
    /\b\d+% (faster|fewer|more|less|higher|lower)\b/i,
    /\b\d+x (faster|more|better)\b/i,
  ];

  function marketingSources(dir: string, acc: string[] = []): string[] {
    for (const name of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, name.name);
      if (name.isDirectory()) {
        if (name.name === "(app)" || name.name === "(admin)") continue;
        marketingSources(full, acc);
      } else if (name.name.endsWith(".tsx")) {
        acc.push(full);
      }
    }
    return acc;
  }

  it("no public marketing page claims a number it cannot show", () => {
    const hits: string[] = [];
    for (const file of [...marketingSources(APP), ...marketingSources(MARKETING)]) {
      const src = readFileSync(file, "utf8");
      for (const re of BANNED) {
        const m = src.match(re);
        if (m) hits.push(`${file.replace(ROOT + "/", "")}: "${m[0]}"`);
      }
    }
    expect(hits, "unsourced volume or outcome claim").toEqual([]);
  });
});

describe("structured data", () => {
  it("every product page emits SoftwareApplication and BreadcrumbList", () => {
    const missing = productPages().filter((slug) => {
      const page = read(APP, "products", slug, "page.tsx");
      const layoutPath = join(APP, "products", slug, "layout.tsx");
      const layout = existsSync(layoutPath) ? readFileSync(layoutPath, "utf8") : "";
      const both = page + layout;
      const hasProduct = /ProductJsonLd|"SoftwareApplication"/.test(both);
      const hasCrumb = /BreadcrumbJsonLd|"BreadcrumbList"/.test(both);
      return !hasProduct || !hasCrumb;
    });
    expect(missing, "product pages without SoftwareApplication + BreadcrumbList").toEqual([]);
  });

  it("no breadcrumb points at a section index that does not exist", () => {
    // /guides, /products, /compare, /use-cases and /for have no index page.
    // A BreadcrumbList item linking to one is a link to a 404.
    const sections = ["guides", "products", "compare", "use-cases", "for"];
    const phantom = sections.filter((s) => !existsSync(join(APP, s, "page.tsx")));
    const hits: string[] = [];
    for (const file of ["GuideArticle.tsx", "ComparisonPage.tsx", "SeoLandingPage.tsx", "StructuredData.tsx"]) {
      const src = read(MARKETING, file);
      for (const s of phantom) {
        if (src.includes(`aexy.io/${s}"`)) hits.push(`${file} → /${s}`);
      }
    }
    expect(hits, "breadcrumb item points at a 404 section index").toEqual([]);
  });
});
