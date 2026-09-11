"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useEditor, useEditorState, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import { Markdown } from "tiptap-markdown";
import { cn } from "@/lib/utils";
import { User, File, Code, Type } from "lucide-react";

import { MentionSuggestion, setMentionSources } from "@/components/mentions/MentionSuggestion";
import {
  MENTION_HREF,
  collectMentions,
  type MentionSet,
} from "@/components/mentions/mentionModel";

type EditorMode = "rich" | "markdown";

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
  onChange?: (content: Record<string, unknown>, mentions: MentionSet) => void;
  placeholder?: string;
  readOnly?: boolean;
  users?: MentionUser[];
  files?: MentionFile[];
  className?: string;
  minHeight?: string;
}

export interface TaskDescriptionEditorRef {
  getContent: () => Record<string, unknown>;
  getMentions: () => MentionSet;
  clearContent: () => void;
}

const NO_MENTIONS: MentionSet = { user_ids: [], file_paths: [] };

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
  const [editorMode, setEditorMode] = useState<EditorMode>("rich");
  const [markdownContent, setMarkdownContent] = useState("");

  // useEditor captures its options once, so the change handler is read
  // through a ref that follows the latest render.
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

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
        // Mentions are link marks with a `mention:` href. The Link extension
        // only renders hrefs whose protocol it knows, so without this the
        // mark survived in the JSON but rendered as `href=""`.
        isAllowedUri: (url, ctx) => MENTION_HREF.test(url) || ctx.defaultValidate(url),
        HTMLAttributes: {
          target: "_blank",
          rel: "noopener noreferrer nofollow",
          class: "text-blue-400 hover:text-blue-300 underline cursor-pointer",
        },
      }),
      MentionSuggestion,
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
    },
    onUpdate: ({ editor }) => {
      const json = editor.getJSON() as Record<string, unknown>;
      onChangeRef.current?.(json, collectMentions(json));
    },
  });

  // The lists offered on "@" and "#" live in the extension's storage, so they
  // can change without rebuilding the editor.
  useEffect(() => {
    if (!editor) return;
    setMentionSources(editor, {
      users,
      files: files.map((f) => ({ id: f.path, name: f.name })),
    });
  }, [editor, users, files]);

  // Who and what the text currently mentions — read from the document on
  // every change, so it cannot drift from the words on screen.
  const mentions = useEditorState({
    editor,
    selector: ({ editor: e }) => (e ? collectMentions(e.getJSON()) : NO_MENTIONS),
  }) ?? NO_MENTIONS;

  const notify = useCallback((target: NonNullable<typeof editor>) => {
    const json = target.getJSON() as Record<string, unknown>;
    onChange?.(json, collectMentions(json));
  }, [onChange]);

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
        notify(editor);
      } catch (error) {
        console.error("Failed to parse markdown:", error);
      }
    }
  }, [editor, editorMode, markdownContent, notify]);

  // Handle markdown textarea change
  const handleMarkdownChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newContent = e.target.value;
      setMarkdownContent(newContent);

      // Update editor content in background so parent gets valid JSON
      if (editor) {
        editor.commands.setContent(newContent);
        notify(editor);
      }
    },
    [editor, notify]
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

  // Expose methods via ref
  useImperativeHandle(ref, () => ({
    getContent: () => editor?.getJSON() as Record<string, unknown> || {},
    getMentions: () => (editor ? collectMentions(editor.getJSON()) : NO_MENTIONS),
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

      {/* Mentioned items display */}
      {(mentions.user_ids.length > 0 || mentions.file_paths.length > 0) && (
        <div className="border-t border-border px-3 py-2 flex flex-wrap gap-1.5">
          {mentions.user_ids.map((userId) => {
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
          {mentions.file_paths.map((path) => {
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
