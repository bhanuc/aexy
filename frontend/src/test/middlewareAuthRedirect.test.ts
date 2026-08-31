import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "@/middleware";
import { safeInternalPath } from "@/lib/oauth";

/**
 * The auth gate sends an unauthenticated request to the landing page with a
 * `?next=` return address. It used to store `pathname` alone, which quietly
 * changed which screen you came back to: `/sprints?tab=epics` is the Epics view
 * and `/sprints` is Projects, so anyone opening the epics URL without the
 * presence cookie yet was bounced through the gate and dropped on Projects —
 * indistinguishable, from the reader's side, from the Epics tab not working.
 *
 * `clone()` also carries the original query, so the params of the denied page
 * leaked onto the landing page next to `next`, producing the mangled
 * `/?tab=epics&next=%2Fsprints`.
 */
const denied = (url: string) => {
  const response = middleware(new NextRequest(new URL(url, "https://aexy.io")));
  return new URL(response!.headers.get("location")!);
};

describe("auth-gate return address", () => {
  it("carries the query string, not just the path", () => {
    const location = denied("/sprints?tab=epics");
    expect(location.pathname).toBe("/");
    expect(location.searchParams.get("next")).toBe("/sprints?tab=epics");
  });

  it("does not leak the denied page's params onto the landing page", () => {
    const location = denied("/sprints?tab=epics");
    // `next` is the only param. `tab` sitting here as well is the bug.
    expect([...location.searchParams.keys()]).toEqual(["next"]);
  });

  it("keeps every filter, not only the first", () => {
    const location = denied("/crm?stage=won&owner=me&page=3");
    expect(location.searchParams.get("next")).toBe("/crm?stage=won&owner=me&page=3");
  });

  it("still works for a path with no query", () => {
    expect(denied("/sprints").searchParams.get("next")).toBe("/sprints");
  });

  it("leaves an authenticated request alone", () => {
    const request = new NextRequest(new URL("/sprints?tab=epics", "https://aexy.io"));
    request.cookies.set("aexy_authed", "1");
    expect(middleware(request).headers.get("location")).toBeNull();
  });

  it("produces a return address the sanitizer accepts", () => {
    // The landing page runs every `next` through `safeInternalPath` before
    // acting on it. A query string must not trip the open-redirect guard, and
    // must not become a way to smuggle one past it either.
    expect(safeInternalPath("/sprints?tab=epics")).toBe("/sprints?tab=epics");
    expect(safeInternalPath("//evil.com?next=/sprints")).toBeNull();
    expect(safeInternalPath("/\\evil.com?x=1")).toBeNull();
  });
});
