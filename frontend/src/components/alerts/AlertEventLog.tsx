"use client";

/**
 * The alert history: every payload a provider sent and what the desk did with it.
 *
 * Extracted from `settings/alerting/page.tsx`, where it was a nested,
 * collapsed-by-default list of one integration's last 50 events. It rendered
 * the action, a truncated fingerprint and a relative time — and fetched
 * `ticket_id` without ever showing it, so there was no way to get from an
 * event to the ticket it produced.
 *
 * Shared now so the settings card and the standalone page cannot drift, with
 * `compact` switching between them: the card wants a glance, the page wants
 * something you can debug an alert with.
 */

import { formatDistanceToNow } from "date-fns";
import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";

import { AlertEvent } from "@/lib/api";

/**
 * Outcome → colour. Every value of the backend's `AlertEventAction`, plus the
 * null case.
 *
 * `pending` is not a value the enum defines: `ERROR` is declared and never
 * assigned, because a processing failure raises and Temporal retries. So an
 * event that never completed sits with a null action and a null `processed_at`
 * indefinitely. That is a real stuck state worth a colour of its own rather
 * than a fallback grey — half of one desk's history is in it.
 */
export const ALERT_ACTION_COLORS: Record<string, string> = {
  created: "text-emerald-400 bg-emerald-400/10",
  updated: "text-blue-400 bg-blue-400/10",
  throttled: "text-amber-400 bg-amber-400/10",
  reopened: "text-purple-400 bg-purple-400/10",
  resolved: "text-teal-400 bg-teal-400/10",
  dropped: "text-muted-foreground bg-muted",
  error: "text-red-400 bg-red-400/10",
  pending: "text-orange-400 bg-orange-400/10",
};

/** Every outcome a filter can ask for, in the order they read as a lifecycle. */
export const ALERT_ACTIONS = [
  "created",
  "updated",
  "throttled",
  "reopened",
  "resolved",
  "dropped",
  "error",
] as const;

function actionKey(event: AlertEvent): string {
  return event.action_taken ?? "pending";
}

/** How long the desk took to process it, when both ends are known. */
function latency(event: AlertEvent): string | null {
  if (!event.processed_at) return null;
  const ms =
    new Date(event.processed_at).getTime() - new Date(event.received_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function EventRow({
  event,
  compact,
  onFingerprint,
}: {
  event: AlertEvent;
  compact: boolean;
  onFingerprint?: (fingerprint: string) => void;
}) {
  const t = useTranslations("alertHistory");
  const [open, setOpen] = useState(false);
  const key = actionKey(event);
  const took = latency(event);

  return (
    <div className="border-b border-border/50 py-1.5 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 ${ALERT_ACTION_COLORS[key] ?? "bg-muted"}`}>
            {t(`action.${key}`)}
          </span>

          {/* Clickable: the row shows a truncated fingerprint, and "show me
              every event that shares this one" is the first thing anybody asks
              of a noisy alert. Matched as a prefix server-side. */}
          {event.fingerprint ? (
            onFingerprint ? (
              <button
                type="button"
                onClick={() => onFingerprint(event.fingerprint!)}
                className="font-mono text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
                title={t("filterByFingerprint")}
              >
                {event.fingerprint.slice(0, 12)}
              </button>
            ) : (
              <code className="text-muted-foreground">{event.fingerprint.slice(0, 12)}</code>
            )
          ) : (
            <code className="text-muted-foreground">—</code>
          )}

          {!compact && event.integration_name && (
            <span className="text-muted-foreground">{event.integration_name}</span>
          )}

          {/* A ticket number to click, or a plain statement that the ticket is
              gone. `ticket_id` with no number means the row was deleted and the
              FK nulled — showing nothing at all read as "no ticket was made". */}
          {event.ticket_number != null && event.ticket_id ? (
            <Link
              href={`/tickets/${event.ticket_id}`}
              className="text-foreground underline underline-offset-2"
            >
              TKT-{event.ticket_number}
            </Link>
          ) : event.action_taken === "created" || event.action_taken === "updated" ? (
            <span className="text-muted-foreground italic">{t("ticketDeleted")}</span>
          ) : null}

          {event.error_message && <span className="text-red-400">{event.error_message}</span>}
        </span>

        <span className="flex items-center gap-2 text-muted-foreground">
          {!compact && took && <span className="font-mono">{took}</span>}
          <span title={new Date(event.received_at).toLocaleString()}>
            {formatDistanceToNow(new Date(event.received_at), { addSuffix: true })}
          </span>
          {!compact && event.raw_payload && (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              className="flex items-center gap-0.5 hover:text-foreground"
            >
              {open ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {t("payload")}
            </button>
          )}
        </span>
      </div>

      {/* What the provider actually sent. Stored all along and never exposed,
          so the one question a dropped event raises could only be answered
          with database access. */}
      {open && event.raw_payload && (
        <pre className="mt-1.5 max-h-72 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed">
          {JSON.stringify(event.raw_payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function AlertEventLog({
  events,
  isLoading,
  compact = false,
  onFingerprint,
}: {
  events: AlertEvent[];
  isLoading: boolean;
  /** The settings card wants a glance; the page wants something debuggable. */
  compact?: boolean;
  onFingerprint?: (fingerprint: string) => void;
}) {
  const t = useTranslations("alertHistory");

  if (isLoading && events.length === 0) {
    return <Loader2 className="h-4 w-4 animate-spin" />;
  }
  if (events.length === 0) {
    return <p className="text-xs italic text-muted-foreground">{t("empty")}</p>;
  }
  return (
    <div className="space-y-1">
      {events.map((event) => (
        <EventRow
          key={event.id}
          event={event}
          compact={compact}
          onFingerprint={onFingerprint}
        />
      ))}
    </div>
  );
}
