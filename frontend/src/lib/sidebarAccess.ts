/**
 * Whether access overrules the persona for one sidebar item.
 *
 * The sidebar used to filter by persona and by access as a flat AND, so a
 * persona could hide an app the workspace had granted. That is how the
 * Operations team ended up with no Service Desk entry — they have access to
 * it, but nobody there had picked a persona and the "developer" default hides
 * the Business section, so they had been reaching it by URL.
 *
 * Access is an administrative decision about a person; a persona is a view
 * preference. When they disagree, the decision wins — unless the person chose
 * the view themselves, because narrowing is what choosing is for.
 *
 * A pure function rather than logic inside the hook so the precedence can be
 * tested directly. It is the whole of the rule; the hook only supplies the
 * data.
 */

/** Which layer decided an app's access. Mirrors the backend's `SOURCE_*`. */
export type AccessSource =
  | "workspace_disabled"
  | "role_fallback"
  | "department"
  | "member_template"
  | "member_override";

export interface PersonaOverrideInput {
  /** The app this route belongs to, or null if it is outside the catalogue. */
  appId: string | null;
  /** Whether the person may see the app at all. */
  hasAccess: boolean;
  /** Which layer granted it, when known. */
  source: AccessSource | null;
  /**
   * The persona the person picked, or null when they are on a department
   * suggestion or the bare default.
   */
  chosenPersona: string | null;
}

export function accessOverridesPersona({
  appId,
  hasAccess,
  source,
  chosenPersona,
}: PersonaOverrideInput): boolean {
  // Routes outside the app catalogue have no access answer to defer to.
  if (!appId) return false;

  // Access is a floor, never a lever: nothing rescues an app they cannot see.
  if (!hasAccess) return false;

  // A persona they never picked — a department suggestion, or the "developer"
  // default — is not a decision, so it does not get to hide granted access.
  //
  // The test is "never chose one" rather than "was derived from a department".
  // No department here sets `default_persona`, so the people this affects are
  // on the bare default; gating on derivation would leave them exactly as
  // stuck as before.
  if (!chosenPersona) return true;

  // They did pick a view, so it narrows — except for an app switched on for
  // them specifically. A `member_override` is the one grant made deliberately
  // about one person, so it outranks their own preference. Access that merely
  // arrives with a role, a department profile or a template does not: those
  // are about a group, and the personal choice is the more specific signal.
  return source === "member_override";
}
