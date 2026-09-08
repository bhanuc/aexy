"use client";

import { useState } from "react";
import {
  Plus,
  Loader2,
  Copy,
  Check,
  Trash2,
  KeyRound,
  ToggleLeft,
  ToggleRight,
  ChevronDown,
  ChevronRight,
  Play,
  X,
  BookOpen,
} from "lucide-react";
import { useWorkspace } from "@/hooks/useWorkspace";
import { AlertEventLog } from "@/components/alerts/AlertEventLog";
import {
  useAlertIntegrations,
  useAlertIntegrationEvents,
  useAlertIntegrationMutations,
} from "@/hooks/useAlertIntegrations";
import {
  AlertIntegration,
  AlertIntegrationWithSecret,
  AlertRoutingRule,
  alertIntegrationsApi,
} from "@/lib/api";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { SettingsPage } from "@/components/settings/SettingsPrimitives";

function CopyButton({ value }: { value: string }) {
  const t = useTranslations("settingsAlerting");
  const tc = useTranslations("common");
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t("copied") : tc("copy")}
    </button>
  );
}

// Copy-pasteable body for a custom OpenObserve alert Template. Mirrors
// docs/integrations/openobserve.md. Curly-brace tokens are OpenObserve alert
// variables substituted at send time: alert_name/stream_name/alert_start_time/
// alert_url/alert_count/rows are built in; {service}/{severity}/{environment}
// resolve from STREAM FIELDS of those names ("all stream fields are variables").
// If your stream lacks them, replace the token with a literal, e.g. "critical".
const OPENOBSERVE_TEMPLATE = `{
  "alert_name": "{alert_name}",
  "service": "{service}",
  "severity": "{severity}",
  "environment": "{environment}",
  "stream": "{stream_name}",
  "start_time": "{alert_start_time}",
  "alert_url": "{alert_url}",
  "count": "{alert_count}",
  "rows": "{rows}"
}`;

function SecretBanner({ integration }: { integration: AlertIntegrationWithSecret }) {
  const t = useTranslations("settingsAlerting");
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 space-y-3">
      <p className="text-sm font-medium text-amber-300">
        {t("secretOnce")}
      </p>
      <div className="space-y-2">
        <div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{t("webhookUrl")}</span>
            <CopyButton value={integration.webhook_url} />
          </div>
          <code className="block text-xs break-all bg-background/60 rounded px-2 py-1 mt-1">
            {integration.webhook_url}
          </code>
        </div>
        <div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {t("signingSecretHeader")} <code>X-Aexy-Signature</code>)
            </span>
            <CopyButton value={integration.signing_secret} />
          </div>
          <code className="block text-xs break-all bg-background/60 rounded px-2 py-1 mt-1">
            {integration.signing_secret}
          </code>
        </div>
      </div>
    </div>
  );
}

// The step-by-step prose here is OpenObserve setup documentation, threaded
// through <code> literals that have to stay verbatim ({service},
// critical|high|medium|low, trace_id=…). Its discrete labels — the console
// paths, the template name, the section names — are translated; the
// sentences are not, because splitting them yields fragments like "Create a"
// that no translator can place. It wants one rich-text message per step if
// it is ever localized.
function SetupGuide() {
  const t = useTranslations("settingsAlerting");
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium"
      >
        <BookOpen className="h-4 w-4 text-muted-foreground" />
        How to connect OpenObserve
        {open ? (
          <ChevronDown className="ml-auto h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="ml-auto h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {open && (
        <div className="space-y-3 border-t border-border px-4 py-3 text-sm text-muted-foreground">
          <ol className="list-decimal space-y-2 pl-5">
            <li>
              <span className="text-foreground">{t("createIntegration")}</span> below.
              On save, Aexy shows a <strong>{t("webhookUrl")}</strong> and a{" "}
              <strong>signing secret</strong> — copy both (the secret is shown only once).
            </li>
            <li>
              In OpenObserve, go to{" "}
              <span className="text-foreground">{t("destinationsPath")}</span> and set:
              <div className="mt-1.5 overflow-x-auto">
                <table className="text-xs">
                  <tbody>
                    <tr>
                      <td className="pr-3 py-0.5 text-muted-foreground">URL</td>
                      <td className="text-foreground">the {t("webhookUrl")} from step 1</td>
                    </tr>
                    <tr>
                      <td className="pr-3 py-0.5 text-muted-foreground">{t("method")}</td>
                      <td className="text-foreground"><code>POST</code></td>
                    </tr>
                    <tr>
                      <td className="pr-3 py-0.5 text-muted-foreground">{t("header")}</td>
                      <td className="text-foreground">
                        <code>X-Aexy-Signature: &lt;signing secret&gt;</code>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              The header is accepted as the raw secret or an HMAC-SHA256 of the body
              (<code>sha256=</code> prefix optional).
            </li>
            <li>
              Create a <span className="text-foreground">custom Template</span> (not the
              <code>prebuilt_*</code> ones — those emit Slack/PagerDuty/etc. formats Aexy
              can&apos;t parse) with this JSON body:
              <div className="mt-2 rounded-md border border-border bg-background/60">
                <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
                  <span className="text-xs text-muted-foreground">{t("alertTemplate")}</span>
                  <CopyButton value={OPENOBSERVE_TEMPLATE} />
                </div>
                <pre className="overflow-x-auto px-3 py-2 text-xs text-foreground">
                  <code>{OPENOBSERVE_TEMPLATE}</code>
                </pre>
              </div>
              <code>{"{service}"}</code>, <code>{"{severity}"}</code> and{" "}
              <code>{"{environment}"}</code> resolve from your stream&apos;s fields of those
              names (OpenObserve: <em>&quot;all stream fields are variables&quot;</em>). If your
              stream doesn&apos;t have them, replace the token with a literal —{" "}
              e.g. <code>&quot;severity&quot;: &quot;critical&quot;</code> — and use one alert per
              tier. A token that resolves to nothing arrives as the literal text{" "}
              <code>{"{service}"}</code>, which is now ignored rather than used — so the
              ticket falls back to the stream name and a severity of{" "}
              <code>medium</code>, instead of being titled after the placeholder. Severity
              accepts <code>critical|high|medium|low</code> (missing →{" "}
              <code>medium</code>). <code>rows</code> becomes the ticket&apos;s log context and
              is scanned for <code>trace_id=…</code> to build trace links. Send a paired alert
              with <code>&quot;status&quot;:&quot;resolved&quot;</code> on recovery to auto-resolve.
              <span className="text-foreground">{t("attachDestination")}</span>{" "}
              OpenObserve routes <em>per alert</em>, not globally — a destination that
              isn&apos;t selected on an alert receives nothing. For each alert you want
              here, open <span className="text-foreground">{t("alertsPath")}</span>{" "}
              and add this destination to the alert&apos;s{" "}
              <span className="text-foreground">{t("destinations")}</span> list (it can coexist
              with Slack and others). Newly created alerts need this step too.
            </li>
            <li>
              {t("pointAlerts")} <span className="text-foreground">{t("template")}</span> at a JSON
              body with <code>service</code>, <code>severity</code>{" "}
              (<code>critical|high|medium|low</code>), <code>environment</code>,{" "}
              <code>alert_url</code>, and <code>rows</code> (the matched log lines →
              ticket log context + trace links). Send <code>&quot;status&quot;:&quot;resolved&quot;</code>{" "}
              on recovery to auto-resolve.
            </li>
            <li>
              Use <span className="text-foreground">{t("sendTest")}</span> on the integration
              to run the full pipeline, then check its event history to see{" "}
              <code>created / updated / throttled / reopened / resolved</code>.
            </li>
          </ol>
          <p className="text-xs">
            Recurring alerts of the same kind collapse into one ticket
            (fingerprint = provider:service:normalized alert name). Full reference:{" "}
            <code>docs/integrations/openobserve.md</code>.
          </p>
        </div>
      )}
    </div>
  );
}

function RoutingRulesEditor({
  rules,
  onChange,
}: {
  rules: AlertRoutingRule[];
  onChange: (rules: AlertRoutingRule[]) => void;
}) {
  const t = useTranslations("settingsAlerting");
  const update = (i: number, patch: Partial<AlertRoutingRule>) => {
    const next = rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
    onChange(next);
  };
  const updateMatch = (i: number, patch: Partial<AlertRoutingRule["match"]>) =>
    update(i, { match: { ...rules[i].match, ...patch } });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium">{t("routingRules")}</label>
        <button
          type="button"
          onClick={() => onChange([...rules, { match: {} }])}
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          <Plus className="h-3.5 w-3.5" /> {t("addRule")}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("rulesHint")}
      </p>
      {rules.length === 0 && (
        <p className="text-xs text-muted-foreground italic">
          {t("noRules")}
        </p>
      )}
      {rules.map((rule, i) => (
        <div key={i} className="grid grid-cols-1 md:grid-cols-4 gap-2 rounded border border-border p-2">
          <input
            className="text-sm bg-background border border-border rounded px-2 py-1"
            placeholder="service glob (payments-*)"
            value={rule.match.service ?? ""}
            onChange={(e) => updateMatch(i, { service: e.target.value || null })}
          />
          <select
            className="text-sm bg-background border border-border rounded px-2 py-1"
            value={rule.match.severity_gte ?? ""}
            onChange={(e) => updateMatch(i, { severity_gte: e.target.value || null })}
          >
            <option value="">any severity</option>
            <option value="low">≥ low</option>
            <option value="medium">≥ medium</option>
            <option value="high">≥ high</option>
            <option value="critical">≥ critical</option>
          </select>
          <select
            className="text-sm bg-background border border-border rounded px-2 py-1"
            value={rule.priority ?? ""}
            onChange={(e) => update(i, { priority: e.target.value || null })}
          >
            <option value="">default priority</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="urgent">urgent</option>
          </select>
          <div className="flex items-center gap-2">
            <input
              className="text-sm bg-background border border-border rounded px-2 py-1 flex-1"
              placeholder="team_id (optional)"
              value={rule.team_id ?? ""}
              onChange={(e) => update(i, { team_id: e.target.value || null })}
            />
            <button
              type="button"
              onClick={() => onChange(rules.filter((_, idx) => idx !== i))}
              aria-label={t("removeRule")}
              className="text-muted-foreground hover:text-red-400"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// The event log lives in `components/alerts/AlertEventLog` now, shared with
// the standalone Alert history page so the two cannot drift. `compact` keeps
// this card a glance rather than a debugging surface.
function EventLog({ workspaceId, integrationId }: { workspaceId: string; integrationId: string }) {
  const t = useTranslations("settingsAlerting");
  const { data, isLoading } = useAlertIntegrationEvents(workspaceId, integrationId);
  return (
    <AlertEventLog events={data?.events ?? []} isLoading={isLoading} compact />
  );
}

function IntegrationCard({
  integration,
  workspaceId,
}: {
  integration: AlertIntegration;
  workspaceId: string;
}) {
  const t = useTranslations("settingsAlerting");
  const tc = useTranslations("common");
  const { update, rotateSecret, remove } = useAlertIntegrationMutations(workspaceId);
  const [expanded, setExpanded] = useState(false);
  const [rotated, setRotated] = useState<AlertIntegrationWithSecret | null>(null);
  const [testing, setTesting] = useState(false);

  const sendTest = async () => {
    setTesting(true);
    try {
      const result = await alertIntegrationsApi.sendTest(workspaceId, integration.id, {
        alert_name: "Test alert from Aexy",
        service: "test-service",
        severity: "high",
        environment: "prod",
        rows: [{ message: "sample log line trace_id=abcdef123456" }],
      });
      toast.success(`Test → ${result.action_taken ?? "processed"}${result.ticket_id ? " (ticket created)" : ""}`);
    } catch {
      toast.error(t("testFailed"));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium">{integration.name}</span>
            <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
              {integration.provider}
            </span>
            {!integration.enabled && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">disabled</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            dedup {integration.dedup_window_minutes}m · throttle {integration.comment_throttle_minutes}m ·
            auto-resolve {integration.auto_resolve ? "on" : "off"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            title={integration.enabled ? tc("disable") : tc("enable")}
            onClick={() => update.mutate({ id: integration.id, data: { enabled: !integration.enabled } })}
            className="text-muted-foreground hover:text-foreground"
          >
            {integration.enabled ? <ToggleRight className="h-5 w-5 text-emerald-400" /> : <ToggleLeft className="h-5 w-5" />}
          </button>
          <button
            type="button"
            title={t("rotateSecret")}
            onClick={() => rotateSecret.mutate(integration.id, { onSuccess: (d) => setRotated(d) })}
            className="text-muted-foreground hover:text-foreground"
          >
            <KeyRound className="h-4 w-4" />
          </button>
          <button
            type="button"
            title={t("sendTestAlert")}
            onClick={sendTest}
            disabled={testing}
            className="text-muted-foreground hover:text-foreground"
          >
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          </button>
          <button
            type="button"
            title={tc("delete")}
            onClick={() => {
              if (confirm(`Delete integration "${integration.name}"?`)) remove.mutate(integration.id);
            }}
            className="text-muted-foreground hover:text-red-400"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs">
        <code className="break-all text-muted-foreground">{integration.webhook_url}</code>
        <CopyButton value={integration.webhook_url} />
      </div>

      {rotated && <SecretBanner integration={rotated} />}

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        Recent events
      </button>
      {expanded && <EventLog workspaceId={workspaceId} integrationId={integration.id} />}
    </div>
  );
}

function CreateForm({ workspaceId, onDone }: { workspaceId: string; onDone: () => void }) {
  const t = useTranslations("settingsAlerting");
  const tc = useTranslations("common");
  const { create } = useAlertIntegrationMutations(workspaceId);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [rules, setRules] = useState<AlertRoutingRule[]>([]);
  const [created, setCreated] = useState<AlertIntegrationWithSecret | null>(null);

  if (created) {
    return (
      <div className="space-y-3">
        <SecretBanner integration={created} />
        <button
          type="button"
          onClick={onDone}
          className="text-sm px-3 py-1.5 rounded bg-primary text-primary-foreground"
        >
          {t("done")}
        </button>
      </div>
    );
  }

  return (
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim()) return;
        create.mutate(
          { name: name.trim(), provider: "openobserve", base_url: baseUrl || null, routing_rules: rules },
          { onSuccess: (d) => setCreated(d) }
        );
      }}
    >
      <div>
        <label className="text-sm font-medium">{t("name")}</label>
        <input
          className="w-full text-sm bg-background border border-border rounded px-2 py-1.5 mt-1"
          placeholder={t("namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="text-sm font-medium">{t("baseUrl")}</label>
        <input
          className="w-full text-sm bg-background border border-border rounded px-2 py-1.5 mt-1"
          placeholder="https://openobserve.your-company.com"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </div>
      <RoutingRulesEditor rules={rules} onChange={setRules} />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={create.isPending || !name.trim()}
          className="inline-flex items-center gap-1 text-sm px-3 py-1.5 rounded bg-primary text-primary-foreground disabled:opacity-50"
        >
          {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Create integration
        </button>
        <button type="button" onClick={onDone} className="text-sm px-3 py-1.5 rounded border border-border">
          {tc("cancel")}
        </button>
      </div>
    </form>
  );
}

export default function AlertingSettingsPage() {
  const t = useTranslations("settingsAlerting");
  const { currentWorkspaceId } = useWorkspace();
  const { data: integrations, isLoading } = useAlertIntegrations(currentWorkspaceId);
  const [creating, setCreating] = useState(false);

  return (
    <SettingsPage
      title={t("title")}
      description={t("description")}
      actions={
        !creating ? (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            <Plus className="h-4 w-4" aria-hidden />
            {t("create")}
          </button>
        ) : undefined
      }
    >
      <SetupGuide />

      {creating && currentWorkspaceId && (
        <CreateForm workspaceId={currentWorkspaceId} onDone={() => setCreating(false)} />
      )}

      {isLoading ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : (
        <div className="space-y-3">
          {(integrations ?? []).map((integration) => (
            <IntegrationCard
              key={integration.id}
              integration={integration}
              workspaceId={currentWorkspaceId!}
            />
          ))}
          {!creating && (integrations ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">
              No integrations yet. Create one, then add its webhook URL as a Destination in OpenObserve.
            </p>
          )}
        </div>
      )}
    </SettingsPage>
  );
}
