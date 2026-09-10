/**
 * `TeamReviewCard` must not take its page down over its own data.
 *
 * The card picked its snapshot with `data.snapshots.find(...)` behind only a
 * `!data` guard. Any truthy response without a `snapshots` array — an error
 * envelope returned with a 200, a proxy, a stale cache — makes `.find` throw
 * during render. Both places this card is mounted (the Organization settings
 * page and the team detail page) catch that in a *page-level* boundary, so one
 * card's malformed response replaces the entire page with "Settings
 * encountered an error". Found while mocking `/settings/organization` for an
 * e2e test, where a catch-all returning `{}` blanked the whole page.
 *
 * `ReviewDigestCard`, the near-twin, already guarded this and says why in a
 * comment; this card was the copy that missed it.
 *
 * Every case renders inside an error boundary and asserts the boundary did not
 * fire. Asserting on the card's own output alone would not distinguish "the
 * card degraded" from "the card threw and something else caught it" — the
 * boundary is the thing the bug was about.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { Component, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TeamReviewCard } from "@/components/code-insights/TeamReviewCard";

const listSnapshots = vi.fn();

vi.mock("@/lib/code-insights-api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    codeInsightsApi: {
      ...(actual.codeInsightsApi as Record<string, unknown>),
      listSnapshots: (...args: unknown[]) => listSnapshots(...args),
    },
  };
});

/** Stands in for the page-level boundary both mount sites put this card in. */
class Boundary extends Component<{ children: ReactNode }, { threw: boolean }> {
  state = { threw: false };
  static getDerivedStateFromError() {
    return { threw: true };
  }
  render() {
    if (this.state.threw) return <div data-testid="page-crashed" />;
    return this.props.children;
  }
}

function renderCard(response: unknown) {
  listSnapshots.mockResolvedValue(response);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <Boundary>
      <QueryClientProvider client={client}>
        <TeamReviewCard
          scopeType="workspace"
          scopeId="ws-1"
          workspaceId="ws-1"
          defaultPeriod="quarterly"
        />
      </QueryClientProvider>
    </Boundary>,
  );
}

/** The card is on screen and the boundary never fired. */
async function expectSurvived() {
  expect(await screen.findByText("Team review")).toBeInTheDocument();
  expect(screen.queryByTestId("page-crashed")).toBeNull();
}

const snapshot = (periodType: string, headline: string) => ({
  id: `snap-${periodType}`,
  payload: { period_type: periodType, headline },
});

beforeEach(() => {
  listSnapshots.mockReset();
});

describe("a response the card cannot read", () => {
  // Each of these is a real shape the endpoint can produce through a proxy,
  // a cache, or an error path that still answers 200.
  const malformed: [string, unknown][] = [
    ["an empty object", {}],
    ["a bare array", []],
    ["an error envelope", { detail: "Not found" }],
    ["snapshots as null", { snapshots: null }],
    ["snapshots as an object", { snapshots: { "0": snapshot("quarterly", "x") } }],
    ["a string", "unavailable"],
  ];

  for (const [name, response] of malformed) {
    it(`degrades to the empty state on ${name}`, async () => {
      renderCard(response);
      await expectSurvived();
      // Not a blank card: the empty state and its way forward are both there.
      // `find*` because the empty state is behind `!isLoading`, so it appears
      // only once the query settles — the card title renders before that.
      expect(
        await screen.findByText("No team review summary yet"),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /generate/i }),
      ).toBeInTheDocument();
    });
  }
});

describe("a response the card can read", () => {
  it("still renders the matching snapshot", async () => {
    // The counter-test that keeps the guard honest. `if (!Array.isArray(x))
    // return undefined` written one character wrong swallows every response,
    // and every test above would still pass.
    renderCard({
      snapshots: [
        snapshot("monthly", "A month of work"),
        snapshot("quarterly", "A quarter of work"),
      ],
    });
    await expectSurvived();
    expect(await screen.findByText("A quarter of work")).toBeInTheDocument();
    expect(screen.queryByText("No team review summary yet")).toBeNull();
  });

  it("shows the empty state when no snapshot matches the period", async () => {
    // A well-formed response can legitimately have nothing for this period.
    // It must look the same as having no data — not like an error.
    renderCard({ snapshots: [snapshot("yearly", "A year of work")] });
    await expectSurvived();
    expect(await screen.findByText("No team review summary yet")).toBeInTheDocument();
    expect(screen.queryByText("A year of work")).toBeNull();
  });

  it("survives a snapshot with no payload at all", async () => {
    // The `.find` callback reads `s.payload?.period_type`; a row without one
    // must be skipped rather than throw inside the predicate.
    renderCard({ snapshots: [{ id: "snap-1" }, snapshot("quarterly", "Ok")] });
    await expectSurvived();
    expect(await screen.findByText("Ok")).toBeInTheDocument();
  });
});
