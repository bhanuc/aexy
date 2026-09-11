/**
 * What a mention *is*, independent of any editor.
 *
 * Mentions live in rich text as link marks whose href is
 * `mention:<kind>:<id>`. That shape is shared with document comments and
 * ticket replies, is what the backend's `extract_mentioned_user_ids` looks
 * for, and survives the description's Markdown round trip as
 * `[@Name](mention:user:<id>)` — so it stays, and the editor plumbing around
 * it is what changes.
 */

export type MentionKind = "user" | "file";

export interface MentionCandidate {
  id: string;
  name: string;
  avatar_url?: string;
}

export interface MentionSet {
  user_ids: string[];
  file_paths: string[];
}

export const MENTION_HREF = /^mention:(user|file):(.+)$/;

export const MENTION_TRIGGER: Record<MentionKind, string> = { user: "@", file: "#" };

const MENTION_CLASS: Record<MentionKind, string> = {
  user: "bg-blue-500/20 text-blue-400 rounded px-1 py-0.5",
  file: "bg-amber-500/20 text-amber-400 rounded px-1 py-0.5",
};

export function mentionHref(kind: MentionKind, id: string): string {
  return `mention:${kind}:${id}`;
}

export function parseMentionHref(href: unknown): { kind: MentionKind; id: string } | null {
  if (typeof href !== "string") return null;
  const match = MENTION_HREF.exec(href);
  return match ? { kind: match[1] as MentionKind, id: match[2] } : null;
}

/**
 * The content a picked candidate becomes: the labelled link, then a plain
 * space so what is typed next is not part of the link.
 */
export function mentionContent(kind: MentionKind, candidate: MentionCandidate) {
  return [
    {
      type: "text",
      marks: [
        {
          type: "link",
          attrs: { href: mentionHref(kind, candidate.id), class: MENTION_CLASS[kind] },
        },
      ],
      text: `${MENTION_TRIGGER[kind]}${candidate.name}`,
    },
    { type: "text", text: " " },
  ];
}

/**
 * Every mention still present in a tiptap JSON document, in order of first
 * appearance, each once. Derived from the text rather than remembered from
 * picks, so deleting "@Ada" un-mentions Ada and a description loaded with
 * mentions in it reports them.
 */
export function collectMentions(doc: unknown): MentionSet {
  const users = new Set<string>();
  const files = new Set<string>();
  const visit = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    const { marks, content } = node as { marks?: unknown; content?: unknown };
    if (Array.isArray(marks)) {
      for (const mark of marks) {
        const m = mark as { type?: unknown; attrs?: { href?: unknown } } | null;
        if (m?.type !== "link") continue;
        const parsed = parseMentionHref(m.attrs?.href);
        if (!parsed) continue;
        (parsed.kind === "user" ? users : files).add(parsed.id);
      }
    }
    if (Array.isArray(content)) content.forEach(visit);
  };
  visit(doc);
  return { user_ids: [...users], file_paths: [...files] };
}

/** Case-insensitive prefix-then-substring match, capped for the popup. */
export function filterMentionCandidates<T extends { name: string }>(
  candidates: T[],
  query: string,
  limit = 6,
): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return candidates.slice(0, limit);
  const starts = candidates.filter((c) => c.name.toLowerCase().startsWith(q));
  const contains = candidates.filter(
    (c) => !c.name.toLowerCase().startsWith(q) && c.name.toLowerCase().includes(q),
  );
  return [...starts, ...contains].slice(0, limit);
}
