"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import tippy, { type Instance as TippyInstance } from "tippy.js";

import { MentionList, type MentionListProps } from "./MentionList";

/**
 * The mention list for a plain `<textarea>`, where a ProseMirror plugin
 * cannot run. The owner tracks the "@query" and the keys; this places the
 * list with the same tippy/popper setup the rich editor uses, so both popups
 * flip and follow scrolling the same way.
 */
export function MentionSuggestions({
  reference,
  ...list
}: MentionListProps & {
  /** Where to attach — typically the textarea's rectangle. */
  reference: () => DOMRect | null;
}) {
  // The portal target has to exist at render time, so it is made with the
  // component rather than in an effect. Only ever rendered after a
  // keystroke, so `document` exists.
  const [host] = useState(() =>
    typeof document === "undefined" ? null : document.createElement("div"),
  );
  const popupRef = useRef<TippyInstance | null>(null);

  useEffect(() => {
    if (!host) return;
    const popup = tippy(document.body, {
      getReferenceClientRect: () => reference() ?? document.body.getBoundingClientRect(),
      appendTo: () => document.body,
      content: host,
      showOnCreate: true,
      interactive: true,
      trigger: "manual",
      placement: "bottom-start",
      animation: false,
      maxWidth: "none",
    });
    popupRef.current = popup;
    return () => {
      popup.destroy();
      popupRef.current = null;
    };
  }, [host, reference]);

  // A narrowing query shortens the list; re-place so a flipped list keeps
  // its bottom edge on the caret.
  useEffect(() => {
    popupRef.current?.popperInstance?.update();
  }, [list.candidates.length, list.query]);

  if (!host || list.candidates.length === 0) return null;
  return createPortal(<MentionList {...list} />, host);
}
