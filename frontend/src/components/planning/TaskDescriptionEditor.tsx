"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import { Markdown } from "tiptap-markdown";
import { cn } from "@/lib/utils";
import { User, File, Code, Type } from "lucide-react";

import {
  MentionSuggestions,
  filterMentionCandidates,
  type MentionAnchor,
} from "@/components/mentions/MentionSuggestions";

type EditorMode = "rich" | "markdown";
type SuggestionKind = "user" | "file";

export interface MentionUser {
  id: string;
  name: string;
  avatar_url?: string;
}

export interface MentionFile {
  path: string;
  name: string;
}

interface TaskDescriptionEditorProps {
  content: Record<string, unknown> | null;
  onChange?: (content: Record<string, unknown>, mentions: {
    user_ids: string[];
    file_paths: string[];
  }) => void;
  placeholder?: string;
  readOnly?: boolean;
  users?: MentionUser[];
  files?: MentionFile[];
  className?: string;
  minHeight?: string;
}

export interface TaskDescriptionEditorRef {
  getContent: () => Record<string, unknown>;
  getMentions: () => { user_ids: string[]; file_paths: string[] };
  clearContent: () => void;
}

// Mentions are stored as link marks with a `mention:` href. tiptap's Link
// extension only renders hrefs whose protocol it knows, so without this the
// mark survived in the JSON but rendered as `href=""` — a mention that looked
// like one and went nowhere.
const MENTION_HREF = /^mention:(user|file):/;

export const TaskDescriptionEditor = forwardRef<
  TaskDescriptionEditorRef,
  TaskDescriptionEditorProps
>(function TaskDescriptionEditor(
  {
    content,
    onChange,
    placeholder = "Add a description...",
    readOnly = false,
    users = [],
    files = [],
    className,
    minHeight = "100px",
  },
  ref
) {
  const [mentionedUserIds, setMentionedUserIds] = useState<Set<string>>(new Set());
  const [mentionedFilePaths, setMentionedFilePaths] = useState<Set<string>>(new Set());
  const [suggestion, setSuggestion] = useState<SuggestionKind | null>(null);
  const [suggestionQuery, setSuggestionQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [anchor, setAnchor] = useState<MentionAnchor | null>(null);
  const [editorMode, setEditorMode] = useState<EditorMode>("rich");
  const [markdownContent, setMarkdownContent] = useState("");

  const userCandidates = useMemo(
    () => filterMentionCandidates(users, suggestionQuery),
    [users, suggestionQuery],
  );
  const fileCandidates = useMemo(
    () =>
      filterMentionCandidates(
        files.map((f) => ({ id: f.path, name: f.name })),
        suggestionQuery,
      ),
    [files, suggestionQuery],
  );
  const candidates = useMemo(
    () => (suggestion === "user" ? userCandidates : suggestion === "file" ? fileCandidates : []),
    [suggestion, userCandidates, fileCandidates],
  );

  // Tiptap's useEditor captures `editorProps` (incl. handleKeyDown) ONCE at
  // creation — there is no deps array — so the handler would otherwise read
  // stale copies of this state/props. Mirror everything it needs into refs
  // and keep them current so the keydown handler always sees live values.
  const suggestionRef = useRef(suggestion);
  const queryRef = useRef(suggestionQuery);
  const usersRef = useRef(users);
  const filesRef = useRef(files);
  const candidatesRef = useRef(candidates);
  const activeIndexRef = useRef(activeIndex);
  const pickRef = useRef<(index: number) => void>(() => {});
  useEffect(() => { suggestionRef.current = suggestion; }, [suggestion]);
  useEffect(() => { queryRef.current = suggestionQuery; }, [suggestionQuery]);
  useEffect(() => { usersRef.current = users; }, [users]);
  useEffect(() => { filesRef.current = files; }, [files]);
  useEffect(() => { candidatesRef.current = candidates; }, [candidates]);
  useEffect(() => { activeIndexRef.current = activeIndex; }, [activeIndex]);

  // A new query starts the highlight at the top again.
  const updateQuery = useCallback((next: (q: string) => string) => {
    setSuggestionQuery(next);
    setActiveIndex(0);
  }, []);

  const closeSuggestions = useCallback(() => {
    setSuggestion(null);
    setSuggestionQuery("");
    setActiveIndex(0);
    setAnchor(null);
  }, []);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3],
        },
      }),
      Placeholder.configure({
        placeholder,
        emptyEditorClass: "is-editor-empty",
      }),
      Link.configure({
        // In edit mode (readOnly=false), single-click should land the cursor
        // on the link to edit it; only open on Cmd/Ctrl+click. In read-only
        // renders, click opens the link directly.
        openOnClick: readOnly,
        autolink: true,
        linkOnPaste: true,
        isAllowedUri: (url, ctx) => MENTION_HREF.test(url) || ctx.defaultValidate(url),
        HTMLAttributes: {
          target: "_blank",
          rel: "noopener noreferrer nofollow",
          class: "text-blue-400 hover:text-blue-300 underline cursor-pointer",
        },
      }),
      Markdown.configure({
        html: true,
        tightLists: true,
        bulletListMarker: "-",
        linkify: true,
        breaks: false,
        transformPastedText: true,
        transformCopiedText: true,
      }),
    ],
    content: content || undefined,
    editable: !readOnly,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: cn(
          "prose dark:prose-invert max-w-none focus:outline-none",
          "prose-p:my-1 prose-headings:my-2",
          "[&_.is-editor-empty:first-child::before]:text-muted-foreground",
          "[&_.is-editor-empty:first-child::before]:content-[attr(data-placeholder)]",
          "[&_.is-editor-empty:first-child::before]:float-left",
          "[&_.is-editor-empty:first-child::before]:h-0",
          "[&_.is-editor-empty:first-child::before]:pointer-events-none"
        ),
        style: `min-height: ${minHeight}`,
      },
      handleClick: (_view, _pos, event) => {
        // In edit mode, openOnClick is false so the cursor lands on the link
        // for editing. Still let Cmd/Ctrl+click open the link in a new tab.
        if (readOnly || !(event.metaKey || event.ctrlKey)) return false;
        const target = (event.target as HTMLElement | null)?.closest("a");
        const href = target?.getAttribute("href");
        if (!href || MENTION_HREF.test(href)) return false;
        window.open(href, "_blank", "noopener,noreferrer");
        return true;
      },
      handleKeyDown: (view, event) => {
        // Read live values via refs (see note above) — never the stale
        // closure copies captured when the editor was created.
        const open = suggestionRef.current;
        const query = queryRef.current;

        const openAt = (kind: SuggestionKind) => {
          // The list is placed next to the caret, not under the editor, so a
          // long description on a short screen cannot push it off the page.
          // Read live, so the list follows the caret if the editor scrolls.
          setAnchor(() => () => {
            const coords = view.coordsAtPos(view.state.selection.from);
            return { left: coords.left, top: coords.top, bottom: coords.bottom };
          });
          setSuggestion(kind);
          updateQuery(() => "");
        };

        // Handle @ for user mentions. Typed while the other list is open, it
        // switches — the character is still inserted and becomes the trigger.
        if (event.key === "@" && open !== "user" && usersRef.current.length > 0) {
          openAt("user");
          return false;
        }

        // Handle # for file mentions
        if (event.key === "#" && open !== "file" && filesRef.current.length > 0) {
          openAt("file");
          return false;
        }

        if (!open) return false;

        // Handle escape to close suggestions
        if (event.key === "Escape") {
          closeSuggestions();
          return true;
        }

        // Keyboard selection. Swallowed, because moving the cursor or breaking
        // the paragraph is not what these keys mean while the list is open.
        const list = candidatesRef.current;
        if (event.key === "ArrowDown" && list.length > 0) {
          setActiveIndex((i) => (i + 1) % list.length);
          return true;
        }
        if (event.key === "ArrowUp" && list.length > 0) {
          setActiveIndex((i) => (i - 1 + list.length) % list.length);
          return true;
        }
        // Enter picks once something has been typed. A bare "@" followed by
        // Enter is somebody starting a new line, not choosing the first name
        // in the list — that closes the list and lets the newline through.
        // Tab always picks.
        if (
          (event.key === "Tab" || (event.key === "Enter" && query.length > 0)) &&
          list.length > 0
        ) {
          pickRef.current(activeIndexRef.current);
          return true;
        }

        // While a suggestion box is open, keep the query in sync but NEVER
        // swallow the keystroke — every key must still reach ProseMirror so
        // the field can't get stuck. The typed characters land in the doc
        // and are what insertMention() later deletes on selection.
        if (event.key === "Backspace") {
          if (query.length > 0) {
            updateQuery((q) => q.slice(0, -1));
          } else {
            // Deleting the trigger char itself closes the box.
            closeSuggestions();
          }
          return false;
        }

        if (event.key === " " || event.key === "Enter") {
          closeSuggestions();
          return false;
        }

        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
          updateQuery((q) => q + event.key);
          return false;
        }

        return false;
      },
    },
    onUpdate: ({ editor }) => {
      const json = editor.getJSON() as Record<string, unknown>;
      onChange?.(json, {
        user_ids: Array.from(mentionedUserIds),
        file_paths: Array.from(mentionedFilePaths),
      });
    },
  });

  // Insert mention into editor
  const insertMention = useCallback((type: "user" | "file", id: string, label: string) => {
    if (!editor) return;

    // Delete the @ or # trigger character and query
    const triggerLength = 1 + suggestionQuery.length;
    editor.commands.deleteRange({
      from: editor.state.selection.from - triggerLength,
      to: editor.state.selection.from,
    });

    // Insert the mention as styled text
    const mentionClass = type === "user"
      ? "bg-blue-500/20 text-blue-400 rounded px-1 py-0.5"
      : "bg-amber-500/20 text-amber-400 rounded px-1 py-0.5";

    editor.commands.insertContent({
      type: "text",
      marks: [
        {
          type: "link",
          attrs: {
            href: type === "user" ? `mention:user:${id}` : `mention:file:${id}`,
            class: mentionClass,
          },
        },
      ],
      text: type === "user" ? `@${label}` : `#${label}`,
    });

    editor.commands.insertContent(" ");

    // Track the mention
    if (type === "user") {
      setMentionedUserIds((prev) => new Set([...prev, id]));
    } else {
      setMentionedFilePaths((prev) => new Set([...prev, id]));
    }

    closeSuggestions();

    // Notify parent
    const json = editor.getJSON() as Record<string, unknown>;
    onChange?.(json, {
      user_ids: type === "user"
        ? [...Array.from(mentionedUserIds), id]
        : Array.from(mentionedUserIds),
      file_paths: type === "file"
        ? [...Array.from(mentionedFilePaths), id]
        : Array.from(mentionedFilePaths),
    });
  }, [editor, suggestionQuery, mentionedUserIds, mentionedFilePaths, onChange, closeSuggestions]);

  const pickIndex = useCallback((index: number) => {
    const candidate = candidates[index];
    if (!candidate || !suggestion) return;
    insertMention(suggestion, candidate.id, candidate.name);
  }, [candidates, suggestion, insertMention]);
  useEffect(() => { pickRef.current = pickIndex; }, [pickIndex]);

  // Toggle editor mode
  const handleModeToggle = useCallback(() => {
    if (!editor) return;

    if (editorMode === "rich") {
      try {
        const markdown = editor.storage.markdown.getMarkdown();
        setMarkdownContent(markdown);
        setEditorMode("markdown");
      } catch (error) {
        console.error("Failed to extract markdown:", error);
      }
    } else {
      try {
        editor.commands.setContent(markdownContent);
        setEditorMode("rich");
        // Notify parent with updated JSON
        const json = editor.getJSON() as Record<string, unknown>;
        onChange?.(json, {
          user_ids: Array.from(mentionedUserIds),
          file_paths: Array.from(mentionedFilePaths),
        });
      } catch (error) {
        console.error("Failed to parse markdown:", error);
      }
    }
  }, [editor, editorMode, markdownContent, onChange, mentionedUserIds, mentionedFilePaths]);

  // Handle markdown textarea change
  const handleMarkdownChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newContent = e.target.value;
      setMarkdownContent(newContent);

      // Update editor content in background so parent gets valid JSON
      if (editor) {
        editor.commands.setContent(newContent);
        const json = editor.getJSON() as Record<string, unknown>;
        onChange?.(json, {
          user_ids: Array.from(mentionedUserIds),
          file_paths: Array.from(mentionedFilePaths),
        });
      }
    },
    [editor, onChange, mentionedUserIds, mentionedFilePaths]
  );

  // Sync content when it changes externally
  useEffect(() => {
    if (editor && content && !editor.isFocused) {
      const currentContent = JSON.stringify(editor.getJSON());
      const newContent = JSON.stringify(content);
      if (currentContent !== newContent) {
        editor.commands.setContent(content);
      }
    }
  }, [editor, content]);

  // Losing focus (a click elsewhere) closes the list.
  useEffect(() => {
    if (!editor) return;
    const onBlur = () => closeSuggestions();
    editor.on("blur", onBlur);
    return () => { editor.off("blur", onBlur); };
  }, [editor, closeSuggestions]);

  // Expose methods via ref
  useImperativeHandle(ref, () => ({
    getContent: () => editor?.getJSON() as Record<string, unknown> || {},
    getMentions: () => ({
      user_ids: Array.from(mentionedUserIds),
      file_paths: Array.from(mentionedFilePaths),
    }),
    clearContent: () => editor?.commands.clearContent(),
  }));

  return (
    <div className={cn("relative rounded-xl border border-border bg-background/70 shadow-inner ring-1 ring-white/5", className)}>
      {/* Mode toggle */}
      {!readOnly && (
        <div className="flex justify-end rounded-t-xl border-b border-border/60 bg-muted/30 px-2 py-1.5">
          <button
            type="button"
            onClick={handleModeToggle}
            className="flex items-center gap-1 rounded-md border border-border bg-background/70 px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {editorMode === "rich" ? (
              <>
                <Code className="w-3 h-3" />
                <span>Markdown</span>
              </>
            ) : (
              <>
                <Type className="w-3 h-3" />
                <span>Rich</span>
              </>
            )}
          </button>
        </div>
      )}

      {/* Always render EditorContent so the editor view stays attached */}
      <div className={editorMode === "rich" ? undefined : "hidden"}>
        <EditorContent
          editor={editor}
          className={cn(
            "px-4 py-3",
            "[&_.ProseMirror]:text-foreground [&_.ProseMirror]:text-sm",
            "[&_.ProseMirror]:leading-relaxed"
          )}
        />
      </div>
      {editorMode === "markdown" && (
        <div className="px-4 py-3">
          <textarea
            value={markdownContent}
            onChange={handleMarkdownChange}
            placeholder="Write in Markdown..."
            className="w-full resize-y border-none bg-transparent font-mono text-sm leading-relaxed text-foreground outline-none placeholder-muted-foreground"
            style={{ minHeight: minHeight }}
            spellCheck={false}
          />
        </div>
      )}

      {/* @ and # suggestions, placed at the caret and kept on screen */}
      {suggestion && (
        <MentionSuggestions
          anchor={anchor}
          candidates={candidates}
          query={suggestionQuery}
          activeIndex={activeIndex}
          onPick={(c) => insertMention(suggestion, c.id, c.name)}
          onHover={setActiveIndex}
          kind={suggestion}
          testId={suggestion === "user" ? "mention-suggestions" : "file-suggestions"}
        />
      )}

      {/* Mentioned items display */}
      {(mentionedUserIds.size > 0 || mentionedFilePaths.size > 0) && (
        <div className="border-t border-border px-3 py-2 flex flex-wrap gap-1.5">
          {Array.from(mentionedUserIds).map((userId) => {
            const user = users.find((u) => u.id === userId);
            return (
              <span
                key={userId}
                className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded-full text-xs"
              >
                <User className="w-3 h-3" />
                {user?.name || userId}
              </span>
            );
          })}
          {Array.from(mentionedFilePaths).map((path) => {
            const file = files.find((f) => f.path === path);
            return (
              <span
                key={path}
                className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded-full text-xs"
              >
                <File className="w-3 h-3" />
                {file?.name || path}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
});

export default TaskDescriptionEditor;
