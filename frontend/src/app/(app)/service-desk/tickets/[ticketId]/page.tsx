"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Clock, GitBranch, Mail, Scissors, Send } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  useServiceDeskTicket,
  useServiceDeskMutations,
  useServiceDeskSettings,
  useLobs,
  usePartners,
} from "@/hooks/useServiceDesk";
import { useAuth } from "@/hooks/useAuth";
import { useProjects } from "@/hooks/useProjects";
import { useWorkspace, useWorkspaceMembers } from "@/hooks/useWorkspace";
import { PendingWith, RequestType } from "@/lib/service-desk-api";
import {
  SERVICE_DESK_BREACH_COLORS,
  SERVICE_DESK_PENDING_WITH_COLORS,
  SERVICE_DESK_PENDING_WITH_LABELS,
  SERVICE_DESK_REQUEST_TYPE_LABELS,
} from "@/lib/statusColors";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

const PENDING_OPTIONS: PendingWith[] = [
  "kam", "insurer", "partner", "sales", "third_party", "finance", "marketing", "closed",
];

const REQUEST_TYPE_OPTIONS: RequestType[] = ["query", "policy_issuance", "claims", "payout"];

function fmtDays(seconds: number): string {
  const d = seconds / 86400;
  if (d >= 1) return `${d.toFixed(1)}d`;
  const h = seconds / 3600;
  if (h >= 1) return `${h.toFixed(1)}h`;
  return `${Math.max(0, Math.round(seconds / 60))}m`;
}

export default function ServiceDeskTicketDetailPage() {
  const t = useTranslations("serviceDesk");
  const router = useRouter();
  const params = useParams();
  const ticketId = params.ticketId as string;

  const { data: ticket, isLoading } = useServiceDeskTicket(ticketId);
  const { changePendingWith, convertToTask, splitDetectedIssues, updateTicket, emailStakeholder } =
    useServiceDeskMutations();
  const { data: settings } = useServiceDeskSettings();
  const { user } = useAuth();
  const { currentWorkspace } = useWorkspace();
  const { projects } = useProjects(currentWorkspace?.id ?? null);
  const { data: lobs } = useLobs();
  const { data: partners } = usePartners();
  const { members } = useWorkspaceMembers(currentWorkspace?.id ?? null);

  const [target, setTarget] = useState<PendingWith | "">("");
  const [note, setNote] = useState("");
  const [projectId, setProjectId] = useState("");
  const [selectedIssueIndexes, setSelectedIssueIndexes] = useState<number[]>([]);
  // Only the fields the KAM has actually touched. Anything absent keeps whatever
  // the ticket already holds, so a background refetch never fights the form.
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [mailTo, setMailTo] = useState("");
  const [mailSubject, setMailSubject] = useState("");
  const [mailBody, setMailBody] = useState("");

  if (isLoading) return <div className="flex justify-center py-16"><Spinner /></div>;
  if (!ticket) return <div className="p-6 text-muted-foreground">Not found.</div>;

  // Write authority, mirroring the server: a Service Desk Manager may act on any
  // ticket, a KAM only on their own. An Ops Lead sees every ticket and edits
  // none, so visibility alone must not unlock a single control here.
  const canEdit =
    !!settings?.can_manage || (!!user?.id && ticket.assigned_kam_id === user.id);

  const pc = SERVICE_DESK_PENDING_WITH_COLORS[ticket.pending_with];
  const bc = SERVICE_DESK_BREACH_COLORS[ticket.tat.breach_level];
  const detectedIssues = ticket.detected_issues ?? [];
  const splitDoneIndexes = new Set(ticket.split_done_indexes ?? []);

  const apply = async () => {
    if (!target) return;
    await changePendingWith.mutateAsync({ id: ticketId, pending_with: target, note: note || undefined });
    setTarget("");
    setNote("");
  };

  const pick = (key: string, current: string | null | undefined) =>
    draft[key] !== undefined ? draft[key] : current ?? "";

  const saveFields = async () => {
    const payload: Record<string, string | null | boolean> = {};
    Object.entries(draft).forEach(([key, value]) => { payload[key] = value === "" ? null : value; });
    // Saving IS the triage: the KAM has just confirmed the product, the request
    // type and the owner, which is exactly what the flag was asking for.
    if (ticket.needs_triage) payload.needs_triage = false;
    await updateTicket.mutateAsync({ id: ticketId, data: payload });
    setDraft({});
  };

  const sendMail = async () => {
    if (!mailTo || !mailSubject.trim() || !mailBody.trim()) return;
    await emailStakeholder.mutateAsync({
      id: ticketId,
      data: { to: mailTo, subject: mailSubject.trim(), body: mailBody.trim() },
    });
    setMailSubject("");
    setMailBody("");
  };

  const toggleIssue = (index: number, checked: boolean) => {
    setSelectedIssueIndexes((current) => (
      checked
        ? [...current, index].sort((a, b) => a - b)
        : current.filter((value) => value !== index)
    ));
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <button onClick={() => router.push("/service-desk")} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> {t("detail.back")}
      </button>

      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold">{ticket.display_id}</h1>
          {ticket.needs_triage && <Badge variant="outline" className="text-amber-600">{t("detail.needsTriage")}</Badge>}
          {!canEdit && <Badge variant="secondary">{t("detail.readOnly")}</Badge>}
        </div>
        <p className="text-muted-foreground">{ticket.subject ?? "—"}</p>
      </div>

      {/* Fields — auto-filled where a rule could, editable everywhere */}
      <Card className="space-y-4 p-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Field label={t("detail.requester")} value={ticket.requester_name || ticket.requester_email || "—"} />
          <Field
            label={t("detail.pendingWith")}
            value={<span className={`inline-flex rounded px-1.5 py-0.5 text-xs ${pc?.bg} ${pc?.text}`}>{SERVICE_DESK_PENDING_WITH_LABELS[ticket.pending_with] ?? ticket.pending_with}</span>}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Picker
            label={t("detail.requestType")}
            value={pick("request_type", ticket.request_type)}
            onChange={(v) => setDraft((d) => ({ ...d, request_type: v }))}
            disabled={!canEdit}
            options={REQUEST_TYPE_OPTIONS.map((o) => ({
              value: o,
              label: SERVICE_DESK_REQUEST_TYPE_LABELS[o] ?? o,
            }))}
          />
          <Picker
            label={t("detail.lob")}
            value={pick("lob_id", ticket.lob_id)}
            onChange={(v) => setDraft((d) => ({ ...d, lob_id: v }))}
            placeholder={t("manual.none")}
            disabled={!canEdit}
            options={(lobs ?? []).map((l) => ({ value: l.id, label: l.name }))}
          />
          <Picker
            label={t("detail.partner")}
            value={pick("partner_id", ticket.partner_id)}
            onChange={(v) => setDraft((d) => ({ ...d, partner_id: v }))}
            placeholder={t("manual.none")}
            disabled={!canEdit}
            options={(partners ?? []).map((p) => ({ value: p.id, label: p.name }))}
          />
          <Picker
            label={t("detail.assignedKam")}
            value={pick("assigned_kam_id", ticket.assigned_kam_id)}
            onChange={(v) => setDraft((d) => ({ ...d, assigned_kam_id: v }))}
            placeholder={t("manual.none")}
            disabled={!canEdit}
            options={(members ?? [])
              .filter((m) => m.status === "active")
              .map((m) => ({
                value: m.developer_id,
                label: m.developer_name || m.developer_email || m.developer_id,
              }))}
          />
        </div>

        {canEdit && (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={Object.keys(draft).length === 0 || updateTicket.isPending}
              onClick={saveFields}
            >
              {updateTicket.isPending ? t("templates.saving") : t("templates.save")}
            </Button>
            {updateTicket.isError && (
              <span className="text-sm text-destructive">{t("detail.saveFailed")}</span>
            )}
          </div>
        )}
      </Card>

      {/* Outbound stakeholder email — sent as the watched mailbox, never a KAM's own inbox */}
      {canEdit && ticket.email_recipients.length > 0 && (
        <Card className="space-y-3 p-4">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-semibold">
              <Send className="h-4 w-4" /> {t("detail.emailStakeholder")}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t("detail.emailStakeholderHint")}</p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Picker
              label={t("detail.emailTo")}
              value={mailTo}
              onChange={setMailTo}
              placeholder={t("detail.emailSelectRecipient")}
              options={ticket.email_recipients.map((r) => ({
                value: r.email,
                label: `${r.label} — ${r.email}`,
              }))}
            />
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">{t("detail.emailSubject")}</label>
              <Input value={mailSubject} onChange={(e) => setMailSubject(e.target.value)} />
            </div>
          </div>
          <textarea
            value={mailBody}
            onChange={(e) => setMailBody(e.target.value)}
            rows={5}
            placeholder={t("detail.emailBody")}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={!mailTo || !mailSubject.trim() || !mailBody.trim() || emailStakeholder.isPending}
              onClick={sendMail}
            >
              {emailStakeholder.isPending ? t("detail.emailSending") : t("detail.emailSend")}
            </Button>
            {emailStakeholder.isError && (
              <span className="text-sm text-destructive">{t("detail.emailFailed")}</span>
            )}
          </div>
        </Card>
      )}

      {canEdit && detectedIssues.length > 1 && (
        <Card className="space-y-3 p-4">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-semibold">
              <Scissors className="h-4 w-4" /> {t("detail.detectedIssues")}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t("detail.detectedIssuesHint")}</p>
          </div>
          <div className="space-y-2">
            {detectedIssues.map((issue, offset) => {
              const index = offset + 1;
              const isPrimary = index === 1;
              const isDone = splitDoneIndexes.has(index);
              return (
                <label key={index} className="flex gap-3 rounded-md border border-border p-3">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4"
                    aria-label={`${t("detail.selectIssue")} ${index}`}
                    checked={selectedIssueIndexes.includes(index)}
                    disabled={isPrimary || isDone || splitDetectedIssues.isPending}
                    onChange={(event) => toggleIssue(index, event.target.checked)}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{issue.summary}</span>
                      {isPrimary && <Badge variant="secondary">{t("detail.primaryIssue")}</Badge>}
                      {isDone && <Badge variant="secondary">{t("detail.alreadySplit")}</Badge>}
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {SERVICE_DESK_REQUEST_TYPE_LABELS[issue.request_type] ?? issue.request_type}
                      {issue.lob ? ` · ${issue.lob}` : ""}
                      {` · ${Math.round(issue.confidence * 100)}% ${t("detail.confidence")}`}
                    </span>
                    {issue.split_reason && (
                      <span className="mt-1 block text-xs text-muted-foreground">{issue.split_reason}</span>
                    )}
                  </span>
                </label>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={selectedIssueIndexes.length === 0 || splitDetectedIssues.isPending}
              onClick={() => splitDetectedIssues.mutate(
                { id: ticketId, issue_indexes: selectedIssueIndexes },
                { onSuccess: () => setSelectedIssueIndexes([]) },
              )}
            >
              {splitDetectedIssues.isPending ? t("detail.splitting") : t("detail.splitIntoTickets")}
            </Button>
            {splitDetectedIssues.isError && (
              <span className="text-sm text-destructive">{t("detail.splitFailed")}</span>
            )}
          </div>
          {splitDetectedIssues.data && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span>{t("detail.createdTickets")}</span>
              {splitDetectedIssues.data.created_ticket_ids.map((id, index) => (
                <Button
                  key={id}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => router.push(`/service-desk/tickets/${id}`)}
                >
                  {splitDetectedIssues.data.created_ticket_display_ids[index] ?? id}
                </Button>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* TAT */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">{t("detail.overallTat")}</div>
          <div className="text-xl font-semibold">{ticket.tat.overall_days}d</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">{t("detail.currentStage")}</div>
          <div className="flex items-center gap-2">
            <span className="text-xl font-semibold">{ticket.tat.current_stage_days}d</span>
            <span className={`h-2.5 w-2.5 rounded-full ${bc?.dot}`} />
          </div>
        </Card>
        <Card className="p-4">
          <div className="mb-1 text-xs text-muted-foreground">{t("detail.stakeholderTat")}</div>
          <div className="space-y-0.5">
            {Object.entries(ticket.tat.stakeholder_seconds).map(([k, secs]) => (
              <div key={k} className="flex justify-between text-xs">
                <span>{SERVICE_DESK_PENDING_WITH_LABELS[k] ?? k}</span>
                <span className="text-muted-foreground">{fmtDays(secs)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Pending-with control */}
      {canEdit && (
      <Card className="space-y-3 p-4">
        <div className="text-sm font-semibold">{t("detail.changeTo")}</div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value as PendingWith)}
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
          >
            <option value="">—</option>
            {PENDING_OPTIONS.filter((o) => o !== ticket.pending_with).map((o) => (
              <option key={o} value={o}>{SERVICE_DESK_PENDING_WITH_LABELS[o]}</option>
            ))}
          </select>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("detail.note")} className="max-w-xs" />
          <Button onClick={apply} disabled={!target || changePendingWith.isPending}>{t("detail.apply")}</Button>
        </div>
      </Card>
      )}

      {/* Convert to project task */}
      {canEdit && (
      <Card className="space-y-3 p-4">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <GitBranch className="h-4 w-4" /> {t("detail.convertToTask")}
        </div>
        {ticket.linked_task_id ? (
          <Badge variant="secondary">{t("detail.linkedToTask")}</Badge>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="">{t("detail.selectProject")}</option>
              {projects.map((p: { id: string; name: string }) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <Button
              disabled={!projectId || convertToTask.isPending}
              onClick={() => convertToTask.mutate({ id: ticketId, data: { project_id: projectId } })}
            >
              {convertToTask.isPending ? t("detail.converting") : t("detail.convert")}
            </Button>
          </div>
        )}
      </Card>
      )}

      {ticket.correspondence.length > 0 && (
        <Card className="space-y-3 p-4">
          <div className="flex items-center gap-1.5 text-sm font-semibold"><Mail className="h-4 w-4" /> {t("detail.correspondence")}</div>
          <ol className="space-y-3">
            {ticket.correspondence.map((entry) => (
              <li key={entry.id} className="rounded-md border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{entry.author_email || t("detail.unknownSender")}</span>
                  <Badge variant={entry.direction === "outgoing" ? "default" : "secondary"}>
                    {entry.direction === "outgoing" ? t("detail.outgoing") : t("detail.incoming")}
                  </Badge>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{new Date(entry.created_at).toLocaleString()}</div>
                <p className="mt-2 whitespace-pre-wrap text-sm">{entry.content}</p>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {/* Timeline */}
      <Card className="p-4">
        <div className="mb-3 flex items-center gap-1.5 text-sm font-semibold"><Clock className="h-4 w-4" /> {t("detail.timeline")}</div>
        <ol className="space-y-3">
          {ticket.segments.map((s) => {
            const c = SERVICE_DESK_PENDING_WITH_COLORS[s.pending_with];
            return (
              <li key={s.id} className="flex gap-3">
                <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${c?.dot ?? "bg-muted-foreground"}`} />
                <div className="text-sm">
                  <div className="font-medium">{SERVICE_DESK_PENDING_WITH_LABELS[s.pending_with] ?? s.pending_with}</div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(s.entered_at).toLocaleString()}
                    {s.exited_at ? ` → ${new Date(s.exited_at).toLocaleString()}` : ` · ${t("detail.open")}`}
                    {s.duration_seconds != null && ` · ${fmtDays(s.duration_seconds)}`}
                  </div>
                  {s.note && <div className="text-xs text-muted-foreground">{s.note}</div>}
                </div>
              </li>
            );
          })}
        </ol>
      </Card>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

function Picker({
  label,
  value,
  onChange,
  options,
  placeholder,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs text-muted-foreground">{label}</label>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}
