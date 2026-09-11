import { Editor } from "@tiptap/core";
import Link from "@tiptap/extension-link";
import StarterKit from "@tiptap/starter-kit";
import { describe, expect, it } from "vitest";

import { MENTION_HREF, collectMentions } from "@/components/mentions/mentionModel";
import {
  MentionSuggestion,
  insertMention,
  setMentionSources,
} from "@/components/mentions/MentionSuggestion";

// A headless editor in jsdom: enough to prove what a pick writes into the
// document. Where the list appears and what the keys do run live in
// e2e/task-mentions.spec.ts.
function makeEditor(html: string) {
  return new Editor({
    extensions: [
      StarterKit,
      Link.configure({
        isAllowedUri: (url, ctx) => MENTION_HREF.test(url) || ctx.defaultValidate(url),
      }),
      MentionSuggestion,
    ],
    content: html,
  });
}

describe("insertMention", () => {
  it("replaces the typed @query with the mention link and a trailing space", () => {
    const editor = makeEditor("<p>ping @ad</p>");
    // "<p>" is position 0; the text starts at 1. "@ad" spans 6..9.
    insertMention(editor, { from: 6, to: 9 }, "user", { id: "u-1", name: "Ada" });

    expect(editor.getText()).toBe("ping @Ada ");
    expect(editor.getHTML()).toMatch(/href="mention:user:u-1"/);
    expect(collectMentions(editor.getJSON())).toEqual({ user_ids: ["u-1"], file_paths: [] });
    editor.destroy();
  });

  it("files are prefixed with # and tracked as paths", () => {
    const editor = makeEditor("<p>see #re</p>");
    insertMention(editor, { from: 5, to: 8 }, "file", { id: "docs/readme.md", name: "readme.md" });

    expect(editor.getText()).toBe("see #readme.md ");
    expect(collectMentions(editor.getJSON())).toEqual({
      user_ids: [],
      file_paths: ["docs/readme.md"],
    });
    editor.destroy();
  });

  it("deleting the mention text un-mentions the person", () => {
    const editor = makeEditor("<p>ping @ad</p>");
    insertMention(editor, { from: 6, to: 9 }, "user", { id: "u-1", name: "Ada" });
    editor.commands.setContent("<p>ping</p>");
    expect(collectMentions(editor.getJSON())).toEqual({ user_ids: [], file_paths: [] });
    editor.destroy();
  });
});

describe("MentionSuggestion", () => {
  it("registers one suggestion plugin per trigger", () => {
    const editor = makeEditor("<p></p>");
    const keys = editor.state.plugins
      .map((p) => (p.spec.key as { key?: string } | undefined)?.key ?? "")
      .filter((k) => k.startsWith("mention-"));
    expect(keys.map((k) => k.replace(/\$.*$/, "")).sort()).toEqual(["mention-file", "mention-user"]);
    editor.destroy();
  });

  it("offers whatever the sources hold at the time, without rebuilding the editor", () => {
    const editor = makeEditor("<p></p>");
    expect(editor.storage.mentionSuggestion.users).toEqual([]);
    setMentionSources(editor, { users: [{ id: "u-1", name: "Ada" }] });
    expect(editor.storage.mentionSuggestion.users).toEqual([{ id: "u-1", name: "Ada" }]);
    expect(editor.storage.mentionSuggestion.files).toEqual([]);
    editor.destroy();
  });
});
