"use client";

import { useEffect, useRef } from "react";
import { AtSign, User } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { MentionCandidate, MentionKind } from "./mentionModel";

export interface MentionListProps {
  candidates: MentionCandidate[];
  query: string;
  activeIndex: number;
  onPick: (candidate: MentionCandidate) => void;
  onHover?: (index: number) => void;
  /** What is being offered — decides the header text. */
  kind?: MentionKind;
  testId?: string;
}

/**
 * The list of people (or files) offered for a mention. Only draws: who is
 * highlighted and what the keys do belong to the owner — the editor's
 * suggestion plugin or the textarea hook — which is also what places it.
 */
export function MentionList({
  candidates,
  query,
  activeIndex,
  onPick,
  onHover,
  kind = "user",
  testId = "mention-suggestions",
}: MentionListProps) {
  const t = useTranslations("common");
  const title = kind === "file" ? t("mentions.referenceFile") : t("mentions.mentionMember");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  if (candidates.length === 0) return null;

  return (
    <div
      ref={ref}
      role="listbox"
      aria-label={title}
      data-testid={testId}
      className="z-[70] max-h-64 w-72 overflow-y-auto rounded-lg border border-border bg-popover text-popover-foreground shadow-xl"
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
    </div>
  );
}
