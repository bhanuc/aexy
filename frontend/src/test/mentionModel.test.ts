import { describe, expect, it } from "vitest";

import {
  collectMentions,
  filterMentionCandidates,
  mentionContent,
  mentionHref,
  parseMentionHref,
} from "@/components/mentions/mentionModel";

const link = (href: string) => ({ type: "link", attrs: { href } });

describe("collectMentions", () => {
  it("lists the people and files a document still mentions, in order, once each", () => {
    const doc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "Ask " },
            { type: "text", marks: [link("mention:user:u-1")], text: "@Ada" },
            { type: "text", text: " about " },
            { type: "text", marks: [link("mention:file:src/a.ts")], text: "#a.ts" },
          ],
        },
        {
          type: "bulletList",
          content: [
            {
              type: "listItem",
              content: [
                {
                  type: "paragraph",
                  content: [
                    { type: "text", marks: [link("mention:user:u-2")], text: "@Bo" },
                    { type: "text", marks: [link("mention:user:u-1")], text: "@Ada" },
                    { type: "text", marks: [link("https://example.com")], text: "a link" },
                  ],
                },
              ],
            },
          ],
        },
      ],
    };
    expect(collectMentions(doc)).toEqual({
      user_ids: ["u-1", "u-2"],
      file_paths: ["src/a.ts"],
    });
  });

  it("reports nothing for an empty or absent document", () => {
    expect(collectMentions(null)).toEqual({ user_ids: [], file_paths: [] });
    expect(collectMentions({ type: "doc", content: [] })).toEqual({ user_ids: [], file_paths: [] });
  });

  it("ignores marks that are not mention links", () => {
    const doc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", marks: [{ type: "bold" }], text: "loud" },
            { type: "text", marks: [link("mailto:ada@example.com")], text: "mail" },
            { type: "text", marks: [{ type: "link", attrs: {} }], text: "bare" },
          ],
        },
      ],
    };
    expect(collectMentions(doc)).toEqual({ user_ids: [], file_paths: [] });
  });
});

describe("mention hrefs", () => {
  it("round-trip through the stored link format", () => {
    expect(parseMentionHref(mentionHref("user", "u-1"))).toEqual({ kind: "user", id: "u-1" });
    expect(parseMentionHref(mentionHref("file", "src/deep/path.ts"))).toEqual({
      kind: "file",
      id: "src/deep/path.ts",
    });
    expect(parseMentionHref("https://example.com")).toBeNull();
    expect(parseMentionHref("mention:user:")).toBeNull();
    expect(parseMentionHref(undefined)).toBeNull();
  });

  it("a picked candidate becomes a labelled link followed by a plain space", () => {
    const [mention, space] = mentionContent("user", { id: "u-1", name: "Ada" });
    expect(mention.text).toBe("@Ada");
    expect(mention.marks?.[0].attrs.href).toBe("mention:user:u-1");
    expect(space).toEqual({ type: "text", text: " " });
    expect(collectMentions({ type: "doc", content: [{ type: "paragraph", content: [mention, space] }] }))
      .toEqual({ user_ids: ["u-1"], file_paths: [] });
  });
});

describe("filterMentionCandidates", () => {
  const people = [
    { id: "1", name: "Bhanu" },
    { id: "2", name: "Abhinav" },
    { id: "3", name: "Anu" },
  ];

  it("puts prefix matches before substring matches, case-insensitively", () => {
    expect(filterMentionCandidates(people, "an").map((p) => p.name)).toEqual(["Anu", "Bhanu"]);
    expect(filterMentionCandidates(people, "BH").map((p) => p.name)).toEqual(["Bhanu", "Abhinav"]);
  });

  it("offers the first few when nothing has been typed yet", () => {
    expect(filterMentionCandidates(people, "", 2).map((p) => p.name)).toEqual(["Bhanu", "Abhinav"]);
  });
});
