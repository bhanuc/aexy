"use client";

/**
 * Every alert the desk received, and what it did with each one.
 *
 * The raw traffic behind the Alerts list. Deduplication means one ticket can
 * stand for hundreds of events — on the desk this was built for, 430 events
 * collapsed into 3 tickets — so "is this alert firing constantly?" and "why did
 * that one produce nothing?" are questions the ticket list structurally cannot
 * answer.
 *
 * The same data existed inside Settings → Alert Integrations as a collapsed
 * list per integration, capped at 50 rows with no pagination, no payload and no
 * link to the ticket. It is here because it is debugging, not configuration.
 */

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { History, X } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AlertEventLog, ALERT_ACTIONS } from "@/components/alerts/AlertEventLog";
import { useAlertEvents, useAlertIntegrations } from "@/hooks/useAlertIntegrations";
import { useWorkspace } from "@/hooks/useWorkspace";

const PAGE_SIZE = 50;

export default function AlertHistoryPage() {
  const t = useTranslations("alertHistory");
  const { currentWorkspace } = useWorkspace();
  const { data: integrations } = useAlertIntegrations(currentWorkspace?.id ?? null);

  const [action, setAction] = useState("");
  const [unresolvedOnly, setUnresolvedOnly] = useState(false);
  const [fingerprint, setFingerprint] = useState("");
  const [page, setPage] = useState(0);

  const query = useMemo(
    () => ({
      action: action ? [action] : undefined,
      fingerprint: fingerprint || undefined,
      unresolved_only: unresolvedOnly || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [action, fingerprint, unresolvedOnly, page],
  );

  const { data, isLoading } = useAlertEvents(currentWorkspace?.id ?? null, query);
  const events = data?.events ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const onFingerprint = (value: string) => {
    setFingerprint(value);
    setPage(0);
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
      </div>

      {/* No integration means no history, and an empty table cannot say which
          of the two it is. */}
      {integrations !== undefined && integrations.length === 0 ? (
        <Card className="p-8 text-center">
          <History className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
          <p className="text-sm font-medium">{t("noIntegrationTitle")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t("noIntegrationBody")}</p>
          <Link
            href="/settings/alerting"
            className="mt-3 inline-block text-sm underline underline-offset-2"
          >
            {t("noIntegrationAction")}
          </Link>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={action}
              onChange={(e) => {
                setAction(e.target.value);
                setPage(0);
              }}
              aria-label={t("filterAction")}
              className="h-9 rounded-md border border-input bg-background px-2 text-xs"
            >
              <option value="">{t("allActions")}</option>
              {ALERT_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {t(`action.${a}`)}
                </option>
              ))}
            </select>

            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={unresolvedOnly}
                onChange={(e) => {
                  setUnresolvedOnly(e.target.checked);
                  setPage(0);
                }}
              />
              {/* Dropped, errored, or never completed. The last of those is a
                  real state: a processing failure raises and Temporal retries,
                  so an event can sit with no action recorded at all. */}
              {t("unresolvedOnly")}
            </label>

            {fingerprint && (
              <button
                type="button"
                onClick={() => {
                  setFingerprint("");
                  setPage(0);
                }}
                className="flex items-center gap-1 rounded-md border border-input px-2 py-1 text-xs"
              >
                <span className="font-mono">{fingerprint.slice(0, 12)}</span>
                <X className="h-3 w-3" />
              </button>
            )}

            <span className="ml-auto text-xs text-muted-foreground">
              {t("count", { count: total })}
            </span>
          </div>

          <Card className="p-4">
            {isLoading && events.length === 0 ? (
              <div className="flex justify-center p-8">
                <Spinner />
              </div>
            ) : (
              <AlertEventLog
                events={events}
                isLoading={isLoading}
                onFingerprint={onFingerprint}
              />
            )}
          </Card>

          {pages > 1 && (
            <div className="flex items-center justify-end gap-2 text-xs">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="rounded-md border border-input px-2 py-1 disabled:opacity-40"
              >
                {t("previous")}
              </button>
              <span className="text-muted-foreground">
                {t("page", { page: page + 1, pages })}
              </span>
              <button
                type="button"
                disabled={page + 1 >= pages}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-md border border-input px-2 py-1 disabled:opacity-40"
              >
                {t("next")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
