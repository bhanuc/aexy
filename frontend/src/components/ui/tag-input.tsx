"use client";

/**
 * A chip/token field for lists people paste rather than type — the Gmail
 * To/Cc box.
 *
 * Built because a plain text input cannot express "this is a list": it asks the
 * person to guess a separator, and silently keeps whatever they guessed as one
 * value. Master Data acquired three partners whose single "domain" was really
 * three addresses joined by " / " that way, and nothing downstream could ever
 * match them.
 *
 * So separators are not a convention the user has to learn. Every plausible one
 * splits — comma, semicolon, slash, pipe, whitespace, and the brackets and
 * quotes that come along when a list is pasted out of a mail client — and the
 * result is visibly a set of chips rather than a string that looks fine and
 * is not.
 *
 * Suspect values are flagged, never dropped: a chip that fails `isValidTag`
 * stays put wearing a warning, because a pasted list is usually 90% right and
 * silently discarding the rest is how you lose the two entries that mattered.
 */

import * as React from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Everything that might separate two items in a pasted list. Deliberately
 * greedy: no legal domain or email address contains any of these, so splitting
 * on all of them can only ever help — while requiring one specific separator
 * is what produced the bad rows in the first place.
 *
 * Whitespace is in here on purpose. "a@x.com b@y.com" is what Outlook and
 * Apple Mail hand over, and a domain with a space inside it is broken either
 * way — this way the person sees two wrong chips and fixes them, instead of one
 * wrong value that reads as fine.
 */
const SEPARATORS = /[\s,;/|\\<>()[\]{}"']+/;

export type TagInputProps = {
  value: string[];
  onChange: (next: string[]) => void;
  /** Cleans one raw token. Return "" to drop it entirely. */
  normalizeTag?: (raw: string) => string;
  /** Flags a tag as suspect. Suspect tags are kept and marked, never removed. */
  isValidTag?: (tag: string) => boolean;
  /** Tooltip and screen-reader text on a suspect chip. */
  invalidHint?: string;
  placeholder?: string;
  disabled?: boolean;
  ariaLabel: string;
  className?: string;
  id?: string;
};

export function TagInput({
  value,
  onChange,
  normalizeTag,
  isValidTag,
  invalidHint,
  placeholder,
  disabled = false,
  ariaLabel,
  className,
  id,
}: TagInputProps) {
  const [draft, setDraft] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  const clean = React.useCallback(
    (raw: string) => (normalizeTag ? normalizeTag(raw) : raw.trim()),
    [normalizeTag],
  );

  /**
   * Turn arbitrary text into chips. Takes the whole string rather than one
   * token so a paste and a typed entry travel the same path — there is no
   * "paste mode" to get out of step with typing.
   */
  const commit = React.useCallback(
    (raw: string) => {
      const added: string[] = [];
      // Compared against the live value AND what this call has already added,
      // so pasting the same address twice in one go yields one chip.
      const seen = new Set(value);
      for (const part of raw.split(SEPARATORS)) {
        const tag = clean(part);
        if (!tag || seen.has(tag)) continue;
        seen.add(tag);
        added.push(tag);
      }
      if (added.length > 0) onChange([...value, ...added]);
      return added.length;
    },
    [clean, onChange, value],
  );

  const remove = (tag: string) => {
    onChange(value.filter((v) => v !== tag));
    // Focus returns to the field: removing a chip is nearly always followed by
    // typing the corrected one, and hunting for the cursor afterwards is the
    // part people find tedious.
    inputRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    // Every separator key also commits, so the muscle memory from a mail client
    // works here: typing a comma ends the entry rather than entering a comma.
    if (e.key === "Enter" || e.key === "," || e.key === ";" || e.key === "/" || e.key === "|") {
      if (draft.trim()) {
        e.preventDefault();
        commit(draft);
        setDraft("");
      } else if (e.key !== "Enter") {
        // Nothing to commit, but the character must still not land in the
        // field — a lone "," is not the start of a domain.
        e.preventDefault();
      }
      return;
    }
    if (e.key === " ") {
      if (draft.trim()) {
        e.preventDefault();
        commit(draft);
        setDraft("");
      }
      return;
    }
    // Tab commits but keeps its normal job: a half-typed entry is not lost by
    // tabbing to the next control, and focus still moves.
    if (e.key === "Tab" && draft.trim()) {
      commit(draft);
      setDraft("");
      return;
    }
    // Backspace into the chips, one at a time — the mail-client behaviour, and
    // the fastest way to undo a wrong paste.
    if (e.key === "Backspace" && draft === "" && value.length > 0) {
      e.preventDefault();
      remove(value[value.length - 1]);
    }
  };

  return (
    <div
      className={cn(
        "flex min-h-10 w-full flex-wrap items-center gap-1 rounded-md border border-input bg-background px-2 py-1.5 text-sm ring-offset-background focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
      // Clicking the padding focuses the field, so the whole control is the
      // target rather than the thin input at the end of the chips.
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !disabled) {
          e.preventDefault();
          inputRef.current?.focus();
        }
      }}
    >
      {value.map((tag) => {
        const suspect = isValidTag ? !isValidTag(tag) : false;
        return (
          <span
            key={tag}
            title={suspect ? invalidHint : undefined}
            className={cn(
              "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-xs",
              suspect
                ? "border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                : "border-transparent bg-secondary text-secondary-foreground",
            )}
          >
            <span className="truncate">{tag}</span>
            {suspect && <span className="sr-only">{invalidHint}</span>}
            {!disabled && (
              <button
                type="button"
                onClick={() => remove(tag)}
                aria-label={`Remove ${tag}`}
                className="rounded-full text-muted-foreground hover:text-destructive focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        );
      })}
      <input
        ref={inputRef}
        id={id}
        type="text"
        value={draft}
        disabled={disabled}
        aria-label={ariaLabel}
        // Browsers offer email history here otherwise, which is noise over a
        // field whose values come from a partner's mail headers.
        autoComplete="off"
        placeholder={value.length === 0 ? placeholder : undefined}
        className="min-w-[8ch] flex-1 border-0 bg-transparent p-0.5 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        // Committing on blur is what stops a typed-but-not-entered value being
        // dropped when somebody types then clicks Add straight away.
        onBlur={() => {
          if (draft.trim()) {
            commit(draft);
            setDraft("");
          }
        }}
        onPaste={(e) => {
          const text = e.clipboardData.getData("text");
          if (!text) return;
          // Handled here rather than letting it land and splitting on change,
          // so a multi-entry paste never briefly exists as one bad value.
          e.preventDefault();
          commit(draft + text);
          setDraft("");
        }}
      />
    </div>
  );
}
