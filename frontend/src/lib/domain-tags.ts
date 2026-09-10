/**
 * Cleaning and checking the values Master Data matches senders against.
 *
 * An account or vendor row holds either a bare domain (`acme.com`) or a whole
 * address (`bob@acme.com`). Both are compared, lower-cased, against what
 * arrives in a message's `From:` — so anything stored with a stray space, a
 * `mailto:`, angle brackets or mixed case can never match, and there is no
 * error to notice: mail from that partner simply routes as if the row did not
 * exist.
 *
 * Kept out of the component so it can be tested directly, and so the desk's
 * rules live next to the desk rather than inside a generic input.
 */

/**
 * One label of a hostname: alphanumeric, inner hyphens allowed. Assembled into
 * a full name needing at least one dot, which is what rules out a typo like
 * `acme` reaching the store as a domain that matches nothing.
 */
const LABEL = "[a-z0-9](?:[a-z0-9-]*[a-z0-9])?";
const HOSTNAME = new RegExp(`^${LABEL}(?:\\.${LABEL})+$`);
const ADDRESS = new RegExp(`^[^@\\s]+@${LABEL}(?:\\.${LABEL})+$`);

/**
 * Clean one token into what the matcher will actually compare, or `""` to drop
 * it.
 *
 * Every transformation here exists because the value arrives pasted from
 * somewhere else — a mail client, a spreadsheet cell, a signature block — and
 * carries that context with it:
 *
 * - **all whitespace removed**, not just the ends. `" acme .com"` is a typo
 *   either way, and a value with an inner space is guaranteed never to match.
 * - **lower-cased**, because sender matching lower-cases what it compares.
 * - `mailto:` stripped — what a mail client puts on the clipboard.
 * - `<`/`>` stripped — from `Name <bob@acme.com>`.
 * - a leading `@` stripped, because `@acme.com` is how people write "anyone at
 *   this domain" and it is not what gets stored.
 * - leading and trailing dots and hyphens stripped, which is what a trailing
 *   comma or a line break leaves behind.
 */
export function normalizeDomainTag(raw: string): string {
  let v = raw.replace(/\s+/g, "").toLowerCase();
  if (!v) return "";
  if (v.startsWith("mailto:")) v = v.slice(7);
  v = v.replace(/^[<("']+/, "").replace(/[>)"',;]+$/, "");
  // Only when it is a prefix: an address's own `@` must survive.
  if (v.startsWith("@")) v = v.slice(1);
  v = v.replace(/^[.-]+/, "").replace(/[.-]+$/, "");
  // A token with no letter or digit in it is punctuation, not a value: a lone
  // "/" or "---" left over from a separator the caller did not split on.
  // Checked last so it catches whatever the strips above happen to leave.
  if (!/[a-z0-9]/.test(v)) return "";
  return v;
}

/**
 * Whether this value can ever match a sender: a hostname, or an address at a
 * hostname. Used to flag a chip, never to refuse one — a person pasting a list
 * needs to see which entries are wrong far more than they need to be stopped.
 */
export function isValidDomainTag(tag: string): boolean {
  return HOSTNAME.test(tag) || ADDRESS.test(tag);
}

/**
 * Split a stored value that was saved as one string before the chip field
 * existed, so the three known-bad rows open as editable chips rather than as a
 * single unmatchable blob the person has to retype.
 *
 * Applied on read only. A value that is already clean comes back as itself.
 */
export function splitStoredDomainValue(stored: string): string[] {
  const out: string[] = [];
  for (const part of stored.split(/[\s,;/|\\<>()[\]{}"']+/)) {
    const tag = normalizeDomainTag(part);
    if (tag && !out.includes(tag)) out.push(tag);
  }
  return out;
}

/** The same, over a whole row's domain list. */
export function splitStoredDomains(stored: string[]): string[] {
  const out: string[] = [];
  for (const value of stored) {
    for (const tag of splitStoredDomainValue(value)) {
      if (!out.includes(tag)) out.push(tag);
    }
  }
  return out;
}

/**
 * Whether a row's stored domains would change just by being cleaned — i.e. the
 * row holds one of the bad values. Lets the UI point at the rows that need
 * attention instead of asking somebody to audit 55 partners by eye.
 */
export function hasUnmatchableDomains(stored: string[]): boolean {
  return stored.some(
    (value) => splitStoredDomainValue(value).length > 1 || !isValidDomainTag(value),
  );
}
