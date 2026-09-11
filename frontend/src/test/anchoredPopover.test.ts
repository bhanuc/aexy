import { describe, expect, it } from "vitest";

import { placePopover } from "@/components/mentions/anchoredPopover";
import { filterMentionCandidates } from "@/components/mentions/MentionSuggestions";

// The geometry that made "@" look broken: a 1280×720 window, the caret at
// y≈646 after a long description, a six-row list ~211px tall. Below the caret
// there were 58px — the header and no names.
const viewport = { width: 1280, height: 720 };
const list = { width: 288, height: 211 };

describe("placePopover", () => {
  it("flips above the caret when the space below cannot show the names", () => {
    const placed = placePopover({ left: 300, top: 630, bottom: 646 }, list, viewport);
    expect(placed.side).toBe("above");
    expect(placed.top + list.height).toBeLessThanOrEqual(630);
    expect(placed.top).toBeGreaterThanOrEqual(0);
  });

  it("stays below the caret when it fits there", () => {
    const placed = placePopover({ left: 300, top: 200, bottom: 216 }, list, viewport);
    expect(placed.side).toBe("below");
    expect(placed.top).toBeGreaterThan(216);
    expect(placed.top + list.height).toBeLessThanOrEqual(viewport.height);
  });

  it("goes to the roomier side and caps its height when it fits nowhere", () => {
    const short = { width: 1280, height: 300 };
    const placed = placePopover({ left: 10, top: 100, bottom: 116 }, list, short);
    expect(placed.side).toBe("below");
    expect(placed.maxHeight).toBeLessThan(list.height);
    expect(placed.maxHeight).toBeGreaterThanOrEqual(80);
  });

  it("never runs past the right edge", () => {
    const placed = placePopover({ left: 1200, top: 100, bottom: 116 }, list, viewport);
    expect(placed.left + list.width).toBeLessThanOrEqual(viewport.width);
    expect(placed.left).toBeGreaterThanOrEqual(0);
  });
});

describe("filterMentionCandidates", () => {
  const people = [
    { id: "1", name: "Priya Raman" },
    { id: "2", name: "Ravi Priyadarshan" },
    { id: "3", name: "Arun" },
  ];

  it("ranks names that start with the query before names that merely contain it", () => {
    expect(filterMentionCandidates(people, "pri").map((p) => p.id)).toEqual(["1", "2"]);
  });

  it("is case-insensitive and shows everyone for an empty query", () => {
    expect(filterMentionCandidates(people, "ARUN")).toHaveLength(1);
    expect(filterMentionCandidates(people, "")).toHaveLength(3);
  });

  it("caps the list", () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ id: String(i), name: `Person ${i}` }));
    expect(filterMentionCandidates(many, "person")).toHaveLength(6);
  });
});
