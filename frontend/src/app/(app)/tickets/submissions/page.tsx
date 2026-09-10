"use client";

/**
 * Bug reports and support requests — what people raised, as opposed to what
 * machines did.
 *
 * A sibling of Alerts rather than a filter on it. An alert is a recurring
 * signal with a fingerprint and an occurrence count; a submission is a person
 * asking for something, with a name to answer and a form they filled in. One
 * table serving both leaves half its columns blank on every row.
 */

import { formatDistanceToNow } from "date-fns";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Inbox } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { useTickets, useTicketForms } from "@/hooks/useTicketing";
import { useWorkspace } from "@/hooks/useWorkspace";
import { TicketPriority, TicketSortKey, TicketStatus } from "@/lib/api";
import { ticketFieldLabel } from "@/components/tickets/ticketLabels";

const PRIORITY_CLASS: Record<string, string> = {
  urgent: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
  high: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  medium: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  low: "bg-muted text-muted-foreground",
};

const PRIORITIES: TicketPriority[] = ["urgent", "high", "medium", "low"];
const OPEN_STATUSES: TicketStatus[] = [
  "new",
  "acknowledged",
  "in_progress",
  "waiting_on_submitter",
];

const PAGE_SIZE = 50;

export default function TicketSubmissionsPage() {
  const t = useTranslations("incidents");
  const { currentWorkspace } = useWorkspace();
  const { forms } = useTicketForms(currentWorkspace?.id ?? null);

  const [formId, setFormId] = useState("");
  const [priority, setPriority] = useState<TicketPriority | "">("");
  const [showClosed, setShowClosed] = useState(false);
  const [sort, setSort] = useState<TicketSortKey>("created");
  const [page, setPage] = useState(0);

  const params = useMemo(
    () => ({
      // Both, because most form-raised rows record no source at all and a list
      // of values cannot express null. Alert-sourced rows are excluded by
      // asking only for "form" and null.
      source: ["form"],
      source_is_null: true,
      form_id: formId || undefined,
      priority: priority ? [priority] : undefined,
      status: showClosed ? undefined : OPEN_STATUSES,
      sort,
      direction: "desc" as const,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [formId, priority, showClosed, sort, page],
  );

  const { tickets, total, isLoading } = useTickets(
    currentWorkspace?.id ?? null,
    params,
  );

  const pages = Math.max(1, Math.ceil((total ?? 0) / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("submissions.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("submissions.subtitle")}</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={formId}
          onChange={(e) => {
            setFormId(e.target.value);
            setPage(0);
          }}
          aria-label={t("submissions.form")}
          className="h-9 max-w-[220px] rounded-md border border-input bg-background px-2 text-xs"
        >
          <option value="">{t("submissions.allForms")}</option>
          {(forms ?? []).map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>

        <select
          value={priority}
          onChange={(e) => {
            setPriority(e.target.value as TicketPriority | "");
            setPage(0);
          }}
          aria-label={t("submissions.priority")}
          className="h-9 rounded-md border border-input bg-background px-2 text-xs"
        >
          <option value="">{t("submissions.allPriorities")}</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {t(`priority.${p}`)}
            </option>
          ))}
        </select>

        <select
          value={sort}
          onChange={(e) => {
            setSort(e.target.value as TicketSortKey);
            setPage(0);
          }}
          aria-label={t("submissions.sortBy")}
          className="h-9 rounded-md border border-input bg-background px-2 text-xs"
        >
          <option value="created">{t("submissions.sortNewest")}</option>
          <option value="updated">{t("submissions.sortUpdated")}</option>
          <option value="priority">{t("submissions.sortPriority")}</option>
        </select>

        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={showClosed}
            onChange={(e) => {
              setShowClosed(e.target.checked);
              setPage(0);
            }}
          />
          {t("submissions.includeClosed")}
        </label>

        <span className="ml-auto text-xs text-muted-foreground">
          {t("submissions.count", { count: total ?? 0 })}
        </span>
      </div>

      {isLoading && tickets.length === 0 ? (
        <div className="flex justify-center p-12">
          <Spinner />
        </div>
      ) : tickets.length === 0 ? (
        <Card className="p-8 text-center">
          <Inbox className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
          <p className="text-sm font-medium">{t("submissions.emptyTitle")}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("submissions.emptyBody")}
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">{t("submissions.ticket")}</th>
                  <th className="px-3 py-2">{t("submissions.subject")}</th>
                  <th className="px-3 py-2">{t("submissions.form")}</th>
                  <th className="px-3 py-2">{t("submissions.submitter")}</th>
                  <th className="px-3 py-2">{t("submissions.priority")}</th>
                  <th className="px-3 py-2">{t("submissions.status")}</th>
                  <th className="px-3 py-2 text-right">{t("submissions.age")}</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((tk) => (
                  <tr key={tk.id} className="border-t border-border hover:bg-accent/50">
                    <td className="whitespace-nowrap px-3 py-2 font-medium">
                      <Link
                        href={`/tickets/${tk.id}`}
                        className="underline-offset-2 hover:underline"
                      >
                        TKT-{tk.ticket_number}
                      </Link>
                      {tk.sla_breached && (
                        <Badge variant="outline" className="ml-1 text-[10px] text-red-600">
                          {t("submissions.breached")}
                        </Badge>
                      )}
                    </td>
                    <td className="max-w-sm truncate px-3 py-2">
                      {tk.title || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {tk.form_name ?? "—"}
                    </td>
                    <td className="max-w-[200px] truncate px-3 py-2 text-xs text-muted-foreground">
                      {tk.submitter_name || tk.submitter_email || "—"}
                    </td>
                    <td className="px-3 py-2">
                      {tk.priority ? (
                        <span
                          className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs ${PRIORITY_CLASS[tk.priority]}`}
                        >
                          {t(`priority.${tk.priority}`)}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">{ticketFieldLabel(tk.status)}</td>
                    <td
                      className="whitespace-nowrap px-3 py-2 text-right text-xs text-muted-foreground"
                      title={new Date(tk.created_at).toLocaleString()}
                    >
                      {formatDistanceToNow(new Date(tk.created_at), { addSuffix: true })}
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
