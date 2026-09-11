/**
 * Where to put a popup that must stay on screen.
 *
 * The @-mention list used to sit below its editor with `position: absolute`.
 * Inside a tall description on a 1280×720 screen that put it at y≈660 with
 * ~210px of height: the header row was visible and none of the names were,
 * which read as "mentions don't work". Anchoring to the caret and flipping
 * above it when the space below is short keeps the list where the eye is.
 *
 * Pure so it can be unit-tested without a DOM. Coordinates are viewport
 * coordinates, as `getBoundingClientRect()` and `coordsAtPos()` report them,
 * and the result is meant for `position: fixed`.
 */

export interface AnchorRect {
  left: number;
  top: number;
  bottom: number;
}

export interface Viewport {
  width: number;
  height: number;
}

export interface PopoverPlacement {
  left: number;
  top: number;
  /** Which side of the anchor the popup ended up on. */
  side: "below" | "above";
  /** Height the popup may use without leaving the viewport. */
  maxHeight: number;
}

const GAP = 6;
const EDGE = 8;

export function placePopover(
  anchor: AnchorRect,
  size: { width: number; height: number },
  viewport: Viewport,
): PopoverPlacement {
  const spaceBelow = viewport.height - anchor.bottom - GAP - EDGE;
  const spaceAbove = anchor.top - GAP - EDGE;

  // Below when it fits, or when below is still the roomier side; otherwise
  // above. A list that fits nowhere goes to the bigger side and scrolls.
  const below = size.height <= spaceBelow || spaceBelow >= spaceAbove;
  const maxHeight = Math.max(80, Math.floor(below ? spaceBelow : spaceAbove));
  const height = Math.min(size.height, maxHeight);

  const top = below ? anchor.bottom + GAP : anchor.top - GAP - height;

  // Slide left rather than overflow the right edge; never past the left edge.
  const left = Math.max(
    EDGE,
    Math.min(anchor.left, viewport.width - size.width - EDGE),
  );

  return { left, top, side: below ? "below" : "above", maxHeight };
}
