"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AtSign, User } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { type AnchorRect, placePopover } from "./anchoredPopover";

/**
 * Where the list attaches. A function is preferred: it is re-read on every
 * placement, so when the editor scrolls under the list (ProseMirror keeps the
 * caret in view as the query grows) the list follows the caret instead of
 * staying where the caret was.
 */
export type MentionAnchor = AnchorRect | (() => AnchorRect | null);

export interface MentionCandidate {
  id: string;
  name: string;
  avatar_url?: string;
}

/**
 * The @-mention list. Rendered in a portal with `position: fixed`, placed by
 * `placePopover` next to the caret and flipped above it when the screen runs
 * out — so it is never clipped by an editor's scroll container and never
 * pushed below the fold. Shared by the rich description editor and the
 * plain-text updates composer.
 *
 * Keyboard: the owner forwards ArrowUp/ArrowDown/Enter through `activeIndex`
 * and `onPick`; this component only draws.
 */
export function MentionSuggestions({
  anchor,
  candidates,
  query,
  activeIndex,
  onPick,
  onHover,
  kind = "user",
  testId = "mention-suggestions",
}: {
  anchor: MentionAnchor | null;
  candidates: MentionCandidate[];
  query: string;
  activeIndex: number;
  onPick: (candidate: MentionCandidate) => void;
  onHover?: (index: number) => void;
  /** What is being offered — decides the header text. */
  kind?: "user" | "file";
  testId?: string;
}) {
  const t = useTranslations("common");
  const title = kind === "file" ? t("mentions.referenceFile") : t("mentions.mentionMember");
  const ref = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<React.CSSProperties>({ visibility: "hidden" });

  // Measure after paint, then place. Re-run when the anchor or the list
  // changes; the viewport resize case is covered by the listener below.
  useLayoutEffect(() => {
    if (!anchor || !ref.current) return;
    const place = () => {
      const el = ref.current;
      if (!el) return;
      const rect = typeof anchor === "function" ? anchor() : anchor;
      if (!rect) return;
      const box = el.getBoundingClientRect();
      const { left, top, maxHeight, side } = placePopover(
        rect,
        { width: box.width || 288, height: el.scrollHeight || box.height },
        { width: window.innerWidth, height: window.innerHeight },
      );
      setStyle({ position: "fixed", left, top, maxHeight, visibility: "visible" });
      el.dataset.side = side;
    };
    place();
    window.addEventListener("resize", place);
    // Capture phase: the editor's scroll container does not bubble scroll
    // events to the window, and the caret moves with it.
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchor, candidates.length, query]);

  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  // Only ever rendered after a keystroke, so `document` exists; the guard is
  // for a stray server render of a parent.
  if (typeof document === "undefined" || !anchor || candidates.length === 0) return null;

  return createPortal(
    <div
      ref={ref}
      role="listbox"
      aria-label={title}
      data-testid={testId}
      style={style}
      className="z-[70] w-72 overflow-y-auto rounded-lg border border-border bg-popover text-popover-foreground shadow-xl"
    >
      <div className="sticky top-0 flex items-center gap-1.5 border-b border-border bg-popover px-3 py-1.5 text-xs text-muted-foreground">
        <AtSign className="h-3 w-3" />
        <span>{title}</span>
        {query && <span>({query})</span>}
      </div>
      {candidates.map((candidate, index) => (
        <button
          key={candidate.id}
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          data-index={index}
          data-testid="mention-option"
          // mousedown, not click: the click would first blur the editor and
          // collapse the selection the insert relies on.
          onMouseDown={(e) => {
            e.preventDefault();
            onPick(candidate);
          }}
          onMouseEnter={() => onHover?.(index)}
          className={cn(
            "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground transition-colors",
            index === activeIndex ? "bg-accent" : "hover:bg-accent/60",
          )}
        >
          {candidate.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={candidate.avatar_url} alt="" className="h-5 w-5 rounded-full" />
          ) : (
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted">
              <User className="h-3 w-3" />
            </span>
          )}
          <span className="truncate">{candidate.name}</span>
        </button>
      ))}
    </div>,
    document.body,
  );
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
