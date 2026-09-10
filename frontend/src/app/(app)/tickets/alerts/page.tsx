"use client";

/**
 * What is firing in production, worst first.
 *
 * These tickets existed for two months and were unreachable: the `tickets` app
 * had no sidebar entry, and `/tickets` redirects to Home. An OpenObserve
 * integration had ingested 430 events into three tickets that nobody could
 * find.
 *
 * The columns are the ones an alert actually has. Severity, not priority —
 * priority is derived from it. Occurrence count and last-seen, because an
 * incident that fired a minute ago and has recurred a hundred times is a
 * different thing from one that opened last week and went quiet, and `created`
 * cannot tell them apart.
 */

import { formatDistanceToNow } from "date-fns";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Siren } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { useTickets } from "@/hooks/useTicketing";
import { useWorkspace } from "@/hooks/useWorkspace";
import { TicketSeverity, TicketSortKey, TicketStatus } from "@/lib/api";
import { ticketFieldLabel } from "@/components/tickets/ticketLabels";

/**
 * The provider slugs `AlertProvider` defines. Listed rather than inferred from
 * "not a form submission", so a ticket from some future non-alert source never
 * turns up here by accident.
 */
const ALERT_SOURCES = ["openobserve", "grafana", "datadog", "sentry", "generic"];

/** Worst first. Separate from the stakeholder palette — this is a judgement
 *  about how bad, not about who holds it. */
const SEVERITY_CLASS: Record<string, string> = {
  critical: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
  high: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  medium: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  low: "bg-muted text-muted-foreground",
};

const SEVERITIES: TicketSeverity[] = ["critical", "high", "medium", "low"];
const OPEN_STATUSES: TicketStatus[] = [
  "new",
  "acknowledged",
  "in_progress",
  "waiting_on_submitter",
];

const PAGE_SIZE = 50;

export default function AlertTicketsPage() {
  const t = useTranslations("incidents");
  const { currentWorkspace } = useWorkspace();

  const [severity, setSeverity] = useState<TicketSeverity | "">("");
  const [showResolved, setShowResolved] = useState(false);
  const [sort, setSort] = useState<TicketSortKey>("last_seen");
  const [page, setPage] = useState(0);

  const params = useMemo(
    () => ({
      source: ALERT_SOURCES,
      severity: severity ? [severity] : undefined,
      // Default to what is still wrong. A queue that opens with six months of
      // resolved incidents buries the three that matter.
      status: showResolved ? undefined : OPEN_STATUSES,
      sort,
      direction: "desc" as const,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [severity, showResolved, sort, page],
  );

  const { tickets, total, isLoading } = useTickets(
    currentWorkspace?.id ?? null,
    params,
  );

  const pages = Math.max(1, Math.ceil((total ?? 0) / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("alerts.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("alerts.subtitle")}</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={severity}
          onChange={(e) => {
            setSeverity(e.target.value as TicketSeverity | "");
            setPage(0);
          }}
          aria-label={t("alerts.severity")}
          className="h-9 rounded-md border border-input bg-background px-2 text-xs"
        >
          <option value="">{t("alerts.allSeverities")}</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {t(`severity.${s}`)}
            </option>
          ))}
        </select>

        <select
          value={sort}
          onChange={(e) => {
            setSort(e.target.value as TicketSortKey);
            setPage(0);
          }}
          aria-label={t("alerts.sortBy")}
          className="h-9 rounded-md border border-input bg-background px-2 text-xs"
        >
          <option value="last_seen">{t("alerts.sortLastSeen")}</option>
          <option value="severity">{t("alerts.sortSeverity")}</option>
          <option value="occurrences">{t("alerts.sortOccurrences")}</option>
          <option value="created">{t("alerts.sortCreated")}</option>
        </select>

        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(e) => {
              setShowResolved(e.target.checked);
              setPage(0);
            }}
          />
          {t("alerts.includeResolved")}
        </label>

        <span className="ml-auto text-xs text-muted-foreground">
          {t("alerts.count", { count: total ?? 0 })}
        </span>
      </div>

      {isLoading && tickets.length === 0 ? (
        <div className="flex justify-center p-12">
          <Spinner />
        </div>
      ) : tickets.length === 0 ? (
        <Card className="p-8 text-center">
          <Siren className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
          <p className="text-sm font-medium">{t("alerts.emptyTitle")}</p>
          {/* Distinguishes "nothing is wrong" from "nothing is connected" —
              the same list looks identical in both cases otherwise. */}
          <p className="mt-1 text-sm text-muted-foreground">{t("alerts.emptyBody")}</p>
          <Link
            href="/settings/alerting"
            className="mt-3 inline-block text-sm underline underline-offset-2"
          >
            {t("alerts.emptyAction")}
          </Link>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">{t("alerts.severity")}</th>
                  <th className="px-3 py-2">{t("alerts.alert")}</th>
                  <th className="px-3 py-2">{t("alerts.service")}</th>
                  <th className="px-3 py-2 text-right">{t("alerts.seen")}</th>
                  <th className="px-3 py-2">{t("alerts.lastSeen")}</th>
                  <th className="px-3 py-2">{t("alerts.status")}</th>
                  <th className="px-3 py-2">{t("alerts.owner")}</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((tk) => (
                  <tr key={tk.id} className="border-t border-border hover:bg-accent/50">
                    <td className="px-3 py-2">
                      {tk.severity ? (
                        <span
                          className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs ${SEVERITY_CLASS[tk.severity]}`}
                        >
                          {t(`severity.${tk.severity}`)}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="max-w-sm truncate px-3 py-2">
                      {/* The alert path writes no `title` column — it goes into
                          field_values — so the headline comes from the shared
                          helper rather than the column. */}
                      <Link
                        href={`/tickets/${tk.id}`}
                        className="font-medium underline-offset-2 hover:underline"
                      >
                        {tk.title || `TKT-${tk.ticket_number}`}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {tk.form_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {tk.occurrence_count > 1 ? (
                        <Badge variant="secondary" className="text-[10px]">
                          ×{tk.occurrence_count}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">1</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                      {formatDistanceToNow(new Date(tk.last_seen_at ?? tk.created_at), {
                        addSuffix: true,
                      })}
                    </td>
                    <td className="px-3 py-2 text-xs">{ticketFieldLabel(tk.status)}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {tk.assignee_name ?? t("alerts.unassigned")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded-md border border-input px-2 py-1 disabled:opacity-40"
          >
            {t("alerts.previous")}
          </button>
          <span className="text-muted-foreground">
            {t("alerts.page", { page: page + 1, pages })}
          </span>
          <button
            type="button"
            disabled={page + 1 >= pages}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-input px-2 py-1 disabled:opacity-40"
          >
            {t("alerts.next")}
          </button>
        </div>
      )}
    </div>
  );
}
