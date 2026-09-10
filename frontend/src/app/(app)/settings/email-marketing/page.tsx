"use client";

/**
 * Email infrastructure — sending domains, providers and subscription categories.
 *
 * Moved here from `/email-marketing/settings`. It was the only place in the app
 * where "Settings" meant a page outside `/settings`, and its own back button
 * pointed at `/settings` — so the page already believed it belonged here.
 */

import { useState } from "react";
import { toast } from "sonner";
import {
  Globe,
  Zap,
  Plus,
  Loader2,
  AlertCircle,
  CheckCircle,
  XCircle,
  Play,
  Pause,
  Trash2,
  RefreshCw,
  Settings,
  Shield,
  TrendingUp,
  Mail,
  TestTube,
  Tags,
  Layers,
  Edit3,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
  ExternalLink,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useAuth } from "@/hooks/useAuth";
import {
  useSendingDomains,
  useEmailProviders,
  useSendingPools,
  useSubscriptionCategories,
} from "@/hooks/useEmailMarketing";
import { SendingDomain, EmailProvider, SubscriptionCategory, DNSRecord } from "@/lib/api";
import { AppAccessGuard } from "@/components/guards/AppAccessGuard";
import { SendingPoolsPanel } from "@/components/email-marketing/SendingPoolsPanel";
import {
  SettingsEmptyState,
  SettingsPage,
  SettingsSection,
} from "@/components/settings/SettingsPrimitives";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type TabType = "domains" | "providers" | "pools" | "categories";

/**
 * The error / spinner / empty triple each of the three tabs used to carry its own
 * copy of, differing only in the noun and the icon. Each empty state also
 * repeated the page's primary action as a hardcoded sky-blue button, so the same
 * "Add domain" appeared twice on screen in two different colours.
 */
function TabPlaceholder({
  error,
  isLoading,
  icon,
  title,
  description,
  onRetry,
  action,
}: {
  error: unknown;
  isLoading: boolean;
  icon: React.ReactNode;
  title: string;
  description: string;
  onRetry: () => void;
  action: React.ReactNode;
}) {
  const t = useTranslations("settingsEmailMarketing");

  if (error) {
    return (
      <SettingsSection>
        <SettingsEmptyState
          icon={<AlertCircle className="h-8 w-8 text-destructive" aria-hidden />}
          title={t("loadFailed")}
          action={
            <button
              onClick={onRetry}
              className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-accent"
            >
              {t("retry")}
            </button>
          }
        />
      </SettingsSection>
    );
  }

  if (isLoading) {
    return (
      <SettingsSection>
        <div className="flex justify-center py-8" aria-busy="true">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
        </div>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection>
      <SettingsEmptyState icon={icon} title={title} description={description} action={action} />
    </SettingsSection>
  );
}

function DNSRecordRow({
  record,
  label,
  description,
}: {
  record: DNSRecord;
  label: string;
  description?: string;
}) {
  const t = useTranslations("settingsEmailMarketing");
  const tc = useTranslations("common");
  const [copied, setCopied] = useState<"name" | "value" | null>(null);

  const copyToClipboard = async (text: string, field: "name" | "value") => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(field);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      const textArea = document.createElement("textarea");
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand("copy");
      document.body.removeChild(textArea);
      setCopied(field);
      setTimeout(() => setCopied(null), 2000);
    }
  };

  return (
    <div className="bg-muted/50 rounded-lg p-4 space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded text-xs font-medium">
            {record.record_type}
          </span>
          <span className="text-sm font-medium text-foreground">{label}</span>
          {record.verified ? (
            <CheckCircle className="h-4 w-4 text-emerald-400" />
          ) : (
            <AlertCircle className="h-4 w-4 text-amber-400" />
          )}
        </div>
        <span className={`text-xs ${record.verified ? "text-emerald-400" : "text-amber-400"}`}>
          {record.verified ? tc("verified") : tc("pending")}
        </span>
      </div>
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
      <div className="space-y-2">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">{t("dns.hostLabel")}</label>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-background rounded text-sm text-foreground font-mono overflow-x-auto">
              {record.name}
            </code>
            <button
              onClick={() => copyToClipboard(record.name, "name")}
              className="p-2 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition flex-shrink-0"
              title={t("dns.copyHost")}
            >
              {copied === "name" ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">{t("dns.valueLabel")}</label>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-background rounded text-sm text-foreground font-mono overflow-x-auto break-all">
              {record.value}
            </code>
            <button
              onClick={() => copyToClipboard(record.value, "value")}
              className="p-2 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition flex-shrink-0"
              title={t("dns.copyValue")}
            >
              {copied === "value" ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        </div>
      </div>
      {record.note && <p className="text-xs text-muted-foreground italic">{record.note}</p>}
    </div>
  );
}

function DomainCard({
  domain,
  onVerify,
  onPause,
  onResume,
  onStartWarming,
  onDelete,
}: {
  domain: SendingDomain;
  onVerify: () => Promise<unknown>;
  onPause: () => void;
  onResume: () => void;
  onStartWarming: () => void;
  onDelete: () => void;
}) {
  const tc = useTranslations("common");
  const t = useTranslations("settingsEmailMarketing");
  const [showDnsRecords, setShowDnsRecords] = useState(!domain.is_verified);
  const [isVerifying, setIsVerifying] = useState(false);

  const handleVerify = async () => {
    setIsVerifying(true);
    try {
      await onVerify();
      toast.success(t("dns.verified"));
    } catch (error) {
      toast.error(t("dns.verifyFailed"));
    } finally {
      setIsVerifying(false);
    }
  };

  const getStatusIcon = () => {
    if (!domain.is_active) return <Pause className="h-4 w-4 text-muted-foreground" />;
    if (!domain.is_verified) return <AlertCircle className="h-4 w-4 text-amber-400" />;
    if (domain.warming_status === "in_progress") return <TrendingUp className="h-4 w-4 text-amber-400" />;
    if (domain.health_score >= 90) return <CheckCircle className="h-4 w-4 text-emerald-400" />;
    if (domain.health_score >= 70) return <AlertCircle className="h-4 w-4 text-amber-400" />;
    return <XCircle className="h-4 w-4 text-red-400" />;
  };

  const getStatusText = () => {
    if (!domain.is_active) return "Paused";
    if (!domain.is_verified) return "Pending Verification";
    if (domain.warming_status === "in_progress") return `Warming (Day ${domain.warming_day})`;
    if (domain.health_score >= 90) return "Healthy";
    if (domain.health_score >= 70) return "Moderate";
    return "Poor Health";
  };

  const hasDnsRecords = domain.dns_records && (
    domain.dns_records.verification ||
    domain.dns_records.spf ||
    domain.dns_records.dkim?.length ||
    domain.dns_records.dmarc
  );

  return (
    <div className="bg-background/50 border border-border rounded-xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-500/20 rounded-lg">
            <Globe className="h-5 w-5 text-purple-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-foreground font-medium">{domain.domain}</h3>
              {!domain.is_verified && (
                <span className="px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded text-xs font-medium">
                  {t("domain.actionRequired")}
                </span>
              )}
              {domain.is_default && (
                <span className="px-2 py-0.5 bg-sky-500/20 text-sky-400 rounded text-xs font-medium">
                  {t("domain.default")}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1">
              {getStatusIcon()}
              <span className="text-sm text-muted-foreground">{getStatusText()}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {!domain.is_verified && (
            <button
              onClick={handleVerify}
              disabled={isVerifying}
              className="p-2 text-amber-400 hover:bg-amber-500/20 rounded-lg transition disabled:opacity-50"
              title={t("dns.verify")}
            >
              <RefreshCw className={`h-4 w-4 ${isVerifying ? "animate-spin" : ""}`} />
            </button>
          )}
          {domain.is_verified && domain.warming_status === "not_started" && (
            <button
              onClick={onStartWarming}
              className="p-2 text-emerald-400 hover:bg-emerald-500/20 rounded-lg transition"
              title={t("domain.startWarming")}
            >
              <TrendingUp className="h-4 w-4" />
            </button>
          )}
          {domain.is_active ? (
            <button
              onClick={onPause}
              className="p-2 text-muted-foreground hover:text-amber-400 hover:bg-muted rounded-lg transition"
              title={t("domain.pause")}
            >
              <Pause className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={onResume}
              className="p-2 text-muted-foreground hover:text-emerald-400 hover:bg-muted rounded-lg transition"
              title={t("domain.resume")}
            >
              <Play className="h-4 w-4" />
            </button>
          )}
          <button
            onClick={onDelete}
            className="p-2 text-muted-foreground hover:text-red-400 hover:bg-muted rounded-lg transition"
            title={tc("delete")}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
        <div className="text-center p-3 bg-muted/50 rounded-lg">
          <p className="text-lg font-semibold text-foreground">{domain.health_score}%</p>
          <p className="text-xs text-muted-foreground">{t("domain.healthScore")}</p>
        </div>
        <div className="text-center p-3 bg-muted/50 rounded-lg">
          <p className="text-lg font-semibold text-foreground">{domain.daily_limit.toLocaleString()}</p>
          <p className="text-xs text-muted-foreground">{t("domain.dailyLimit")}</p>
        </div>
        <div className="text-center p-3 bg-muted/50 rounded-lg">
          <p className="text-lg font-semibold text-foreground">{domain.daily_sent.toLocaleString()}</p>
          <p className="text-xs text-muted-foreground">{t("domain.sentToday")}</p>
        </div>
      </div>

      {/* DNS Records Section */}
      {hasDnsRecords && (
        <div className="border-t border-border pt-4 mt-4">
          <button
            onClick={() => setShowDnsRecords(!showDnsRecords)}
            className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 w-full text-left"
          >
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium text-foreground">{t("dns.heading")}</span>
              {!domain.is_verified && (
                <span className="text-xs text-amber-400">{t("dns.configRequired")}</span>
              )}
            </div>
            {showDnsRecords ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>

          {showDnsRecords && (
            <div className="mt-4 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 text-xs text-muted-foreground">
                <p>{t("dns.configRequiredHint")}</p>
                <a
                  href="https://github.com/bhanuc/aexy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-sky-400 hover:text-sky-300"
                >
                  <ExternalLink className="h-3 w-3" />
                  {t("dns.documentation")}
                </a>
              </div>

              {domain.dns_records.verification && (
                <DNSRecordRow
                  record={domain.dns_records.verification}
                  label="Domain Verification"
                  description="Proves ownership of this domain"
                />
              )}

              {domain.dns_records.spf && (
                <DNSRecordRow
                  record={domain.dns_records.spf}
                  label="SPF Record"
                  description="Authorizes mail servers to send on your behalf"
                />
              )}

              {domain.dns_records.dkim?.map((dkimRecord, idx) => (
                <DNSRecordRow
                  key={idx}
                  record={dkimRecord}
                  label={`DKIM Record ${domain.dns_records.dkim && domain.dns_records.dkim.length > 1 ? idx + 1 : ""}`}
                  description="Cryptographically signs emails to verify authenticity"
                />
              ))}

              {domain.dns_records.dmarc && (
                <DNSRecordRow
                  record={domain.dns_records.dmarc}
                  label="DMARC Policy"
                  description="Tells receiving servers how to handle authentication failures"
                />
              )}

              {!domain.is_verified && (
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-3 bg-muted/30 rounded-lg">
                  <p className="text-sm text-muted-foreground">
                    {t("dns.afterAdding")}
                  </p>
                  <button
                    onClick={handleVerify}
                    disabled={isVerifying}
                    className="flex items-center gap-2 px-3 py-1.5 bg-amber-500/20 text-amber-400 rounded-lg hover:bg-amber-500/30 transition text-sm disabled:opacity-50"
                  >
                    {isVerifying ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                    Verify DNS
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Fallback for domains without dns_records data */}
      {!hasDnsRecords && !domain.is_verified && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <p className="text-sm text-amber-400 mb-2">{t("dns.needsVerification")}</p>
          <div className="text-xs text-muted-foreground space-y-1">
            <p>{t("dns.needsVerificationHint")}</p>
            <code className="block p-2 bg-muted rounded mt-2 text-foreground">
              TXT @ aexy-verification={domain.verification_token || domain.id?.slice(0, 8)}
            </code>
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderCard({
  provider,
  onToggle,
  onTest,
  onEdit,
  onDelete,
}: {
  provider: EmailProvider;
  onToggle: () => void;
  onTest: () => Promise<unknown>;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("settingsEmailMarketing");
  const tc = useTranslations("common");
  const [isTesting, setIsTesting] = useState(false);

  const handleTest = async () => {
    setIsTesting(true);
    try {
      await onTest();
    } finally {
      setIsTesting(false);
    }
  };

  const hasCredentials = provider.has_credentials;

  return (
    <div className="bg-background/50 border border-border rounded-xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-amber-500/20 rounded-lg">
            <Zap className="h-5 w-5 text-amber-400" />
          </div>
          <div>
            <h3 className="text-foreground font-medium">{provider.name}</h3>
            <p className="text-sm text-muted-foreground capitalize">{provider.provider_type}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!hasCredentials && (
            <span className="px-2 py-1 bg-amber-500/20 text-amber-400 rounded-full text-xs font-medium">
              {t("provider.setupRequired")}
            </span>
          )}
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
            provider.is_active
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-muted text-muted-foreground"
          }`}>
            {provider.is_active ? tc("status.active") : tc("inactive")}
          </span>
          {provider.is_default && (
            <span className="px-2 py-1 bg-sky-500/20 text-sky-400 rounded-full text-xs font-medium">
              {t("provider.default")}
            </span>
          )}
        </div>
      </div>

      {provider.description && (
        <p className="text-sm text-muted-foreground mb-4">{provider.description}</p>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={onEdit}
          className="flex items-center gap-2 px-3 py-1.5 bg-sky-500/20 text-sky-400 hover:bg-sky-500/30 rounded-lg transition text-sm"
        >
          <Settings className="h-4 w-4" />
          {t("provider.configure")}
        </button>
        <button
          onClick={handleTest}
          disabled={isTesting || !hasCredentials}
          className="flex items-center gap-2 px-3 py-1.5 bg-muted text-foreground hover:text-foreground rounded-lg transition text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          title={!hasCredentials ? t("provider.configureFirst") : tc("testConnection")}
        >
          {isTesting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <TestTube className="h-4 w-4" />
          )}
          Test
        </button>
        <button
          onClick={onToggle}
          className={`px-3 py-1.5 rounded-lg text-sm transition ${
            provider.is_active
              ? "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
              : "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
          }`}
        >
          {provider.is_active ? tc("disable") : tc("enable")}
        </button>
        <button
          onClick={onDelete}
          aria-label={`Delete provider ${provider.name}`}
          className="p-1.5 text-muted-foreground hover:text-red-400 transition"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function CategoryCard({
  category,
  onToggle,
  onEdit,
  onDelete,
}: {
  category: SubscriptionCategory;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const tc = useTranslations("common");
  const t = useTranslations("settingsEmailMarketing");
  return (
    <div className="bg-background/50 border border-border rounded-xl p-5">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-500/20 rounded-lg">
            <Tags className="h-5 w-5 text-purple-400" />
          </div>
          <div>
            <h3 className="text-foreground font-medium">{category.name}</h3>
            <p className="text-xs text-muted-foreground font-mono">{category.slug}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
            category.is_active
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-muted text-muted-foreground"
          }`}>
            {category.is_active ? tc("status.active") : tc("inactive")}
          </span>
          {category.default_subscribed && (
            <span className="px-2 py-1 bg-sky-500/20 text-sky-400 rounded-full text-xs font-medium">
              {t("category.defaultOn")}
            </span>
          )}
          {category.required && (
            <span className="px-2 py-1 bg-amber-500/20 text-amber-400 rounded-full text-xs font-medium">
              {t("category.required")}
            </span>
          )}
        </div>
      </div>

      {category.description && (
        <p className="text-sm text-muted-foreground mb-4">{category.description}</p>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={onEdit}
          className="flex items-center gap-2 px-3 py-1.5 bg-muted text-foreground hover:text-foreground rounded-lg transition text-sm"
        >
          <Edit3 className="h-4 w-4" />
          {tc("edit")}
        </button>
        <button
          onClick={onToggle}
          className={`px-3 py-1.5 rounded-lg text-sm transition ${
            category.is_active
              ? "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
              : "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
          }`}
        >
          {category.is_active ? tc("disable") : tc("enable")}
        </button>
        {!category.required && (
          <button
            onClick={onDelete}
            aria-label={`Delete category ${category.name}`}
            className="p-1.5 text-muted-foreground hover:text-red-400 transition"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}

function EmailSettingsContent() {
  const t = useTranslations("settingsEmailMarketing");
  const tc = useTranslations("common");
  const { currentWorkspace } = useWorkspace();
  useAuth(); // Auth check
  const workspaceId = currentWorkspace?.id || null;

  const [activeTab, setActiveTab] = useState<TabType>("domains");
  const [showAddDomain, setShowAddDomain] = useState(false);
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [showAddCategory, setShowAddCategory] = useState(false);
  const [editingCategory, setEditingCategory] = useState<SubscriptionCategory | null>(null);
  const [editingProvider, setEditingProvider] = useState<EmailProvider | null>(null);
  const [newDomain, setNewDomain] = useState("");
  const [newProviderName, setNewProviderName] = useState("");
  const [newProviderType, setNewProviderType] = useState("ses");

  // Provider credentials state
  const [providerCredentials, setProviderCredentials] = useState<Record<string, string>>({});
  const [providerDescription, setProviderDescription] = useState("");

  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategorySlug, setNewCategorySlug] = useState("");
  const [newCategoryDescription, setNewCategoryDescription] = useState("");
  const [newCategoryDefaultSubscribed, setNewCategoryDefaultSubscribed] = useState(true);

  const {
    domains,
    isLoading: domainsLoading,
    error: domainsError,
    refetch: refetchDomains,
    createDomain,
    deleteDomain,
    verifyDomain,
    pauseDomain,
    resumeDomain,
    startWarming,
  } = useSendingDomains(workspaceId);

  const {
    providers,
    isLoading: providersLoading,
    error: providersError,
    refetch: refetchProviders,
    createProvider,
    updateProvider,
    deleteProvider,
    testProvider,
  } = useEmailProviders(workspaceId);

  const {
    categories,
    isLoading: categoriesLoading,
    error: categoriesError,
    refetch: refetchCategories,
    createCategory,
    updateCategory,
    deleteCategory,
  } = useSubscriptionCategories(workspaceId);

  // Only for the tab's count badge; the panel owns its own data.
  const { pools } = useSendingPools(workspaceId);

  const handleCreateDomain = async () => {
    if (!newDomain) return;
    try {
      await createDomain({ domain: newDomain });
      toast.success(`Domain ${newDomain} added successfully`);
      setNewDomain("");
      setShowAddDomain(false);
    } catch (error: unknown) {
      // Extract error message from API response
      const err = error as { response?: { data?: { detail?: string } }; message?: string };
      const message = err.response?.data?.detail || err.message || "Failed to add domain";
      toast.error(message);
    }
  };

  const handleCreateProvider = async () => {
    if (!newProviderName) return;
    try {
      await createProvider({
        name: newProviderName,
        provider_type: newProviderType,
        credentials: {},
      });
      setNewProviderName("");
      setShowAddProvider(false);
    } catch {
      // Error handled by mutation
    }
  };

  const handleDeleteDomain = async (id: string) => {
    if (confirm(t("domain.confirmDelete"))) {
      await deleteDomain(id);
    }
  };

  const handleDeleteProvider = async (id: string) => {
    if (confirm(t("provider.confirmDelete"))) {
      await deleteProvider(id);
    }
  };

  const openEditProvider = (provider: EmailProvider) => {
    setEditingProvider(provider);
    setNewProviderName(provider.name);
    setProviderDescription(provider.description || "");
    // Extract credentials (they may be masked on backend, but we show what we have)
    // Convert unknown values to strings for the form
    const creds: Record<string, string> = {};
    if (provider.credentials) {
      for (const [key, value] of Object.entries(provider.credentials)) {
        creds[key] = String(value ?? "");
      }
    }
    setProviderCredentials(creds);
  };

  const closeEditProvider = () => {
    setEditingProvider(null);
    setNewProviderName("");
    setProviderDescription("");
    setProviderCredentials({});
  };

  const handleUpdateProvider = async () => {
    if (!editingProvider) return;
    try {
      await updateProvider({
        providerId: editingProvider.id,
        data: {
          name: newProviderName,
          description: providerDescription || undefined,
          credentials: providerCredentials,
        },
      });
      closeEditProvider();
    } catch {
      // Error handled by mutation
    }
  };

  type CredentialField = {
    key: string;
    label: string;
    type: "text" | "password" | "number" | "select" | "checkbox";
    placeholder?: string;
    options?: { value: string; label: string }[];
  };

  const getCredentialFields = (providerType: string): CredentialField[] => {
    switch (providerType) {
      case "ses":
        return [
          { key: "access_key_id", label: "Access Key ID", type: "text", placeholder: "AKIAIOSFODNN7EXAMPLE" },
          { key: "secret_access_key", label: "Secret Access Key", type: "password", placeholder: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" },
          { key: "region", label: "Region", type: "text", placeholder: "us-east-1" },
          { key: "configuration_set", label: "Configuration Set (optional)", type: "text", placeholder: "my-configuration-set" },
        ];
      case "sendgrid":
        return [
          { key: "api_key", label: "API Key", type: "password", placeholder: "SG.xxxxxxxxxxxxxxxxxxxx" },
        ];
      case "mailgun":
        return [
          { key: "api_key", label: "API Key", type: "password", placeholder: "key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" },
          { key: "domain", label: "Domain", type: "text", placeholder: "mg.example.com" },
          { key: "region", label: "Region", type: "select", options: [{ value: "us", label: "US" }, { value: "eu", label: "EU" }] },
        ];
      case "postmark":
        return [
          { key: "server_token", label: "Server Token", type: "password", placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
        ];
      case "smtp":
        return [
          { key: "host", label: "SMTP Host", type: "text", placeholder: "smtp.example.com" },
          { key: "port", label: "Port", type: "number", placeholder: "587" },
          { key: "username", label: "Username", type: "text", placeholder: "user@example.com" },
          { key: "password", label: "Password", type: "password", placeholder: "password" },
          { key: "use_tls", label: "Use TLS", type: "checkbox" },
        ];
      default:
        return [];
    }
  };

  const handleCreateCategory = async () => {
    if (!newCategoryName) return;
    try {
      await createCategory({
        name: newCategoryName,
        slug: newCategorySlug || newCategoryName.toLowerCase().replace(/\s+/g, "-"),
        description: newCategoryDescription || undefined,
        default_subscribed: newCategoryDefaultSubscribed,
      });
      setNewCategoryName("");
      setNewCategorySlug("");
      setNewCategoryDescription("");
      setNewCategoryDefaultSubscribed(true);
      setShowAddCategory(false);
    } catch {
      // Error handled by mutation
    }
  };

  const handleUpdateCategory = async () => {
    if (!editingCategory) return;
    try {
      await updateCategory({
        categoryId: editingCategory.id,
        data: {
          name: newCategoryName,
          description: newCategoryDescription || undefined,
        },
      });
      setEditingCategory(null);
      setNewCategoryName("");
      setNewCategoryDescription("");
    } catch {
      // Error handled by mutation
    }
  };

  const handleDeleteCategory = async (id: string) => {
    if (confirm(t("category.confirmDelete"))) {
      await deleteCategory(id);
    }
  };

  const openEditCategory = (category: SubscriptionCategory) => {
    setEditingCategory(category);
    setNewCategoryName(category.name);
    setNewCategoryDescription(category.description || "");
  };

  if (!currentWorkspace) {
    return (
      <SettingsPage title={t("title")} description={t("description")} width="wide">
        <SettingsSection>
          <SettingsEmptyState
            icon={<AlertCircle className="h-8 w-8" aria-hidden />}
            title={t("noWorkspace")}
            description={t("noWorkspaceDetail")}
          />
        </SettingsSection>
      </SettingsPage>
    );
  }

  // The add button belongs to whichever tab is open — one primary action in the
  // page header rather than a second one repeated inside each tab body.
  const tabAction = {
    domains: {
      label: t("domains.add"),
      description: t("domains.description"),
      onClick: () => setShowAddDomain(true),
    },
    providers: {
      label: t("providers.add"),
      description: t("providers.description"),
      onClick: () => setShowAddProvider(true),
    },
    categories: {
      label: t("categories.add"),
      description: t("categories.description"),
      onClick: () => setShowAddCategory(true),
    },
    // Pools own their own create form inline — the shape of a pool (name,
    // strategy, members) is more than a header button can carry.
    pools: {
      label: null,
      description: t("pools.description"),
      onClick: () => {},
    },
  }[activeTab];

  const tabs: { id: TabType; label: string; icon: React.ReactNode; count: number }[] = [
    { id: "domains", label: t("domains.tab"), icon: <Globe className="h-4 w-4" />, count: domains.length },
    { id: "providers", label: t("providers.tab"), icon: <Zap className="h-4 w-4" />, count: providers.length },
    { id: "pools", label: t("pools.tab"), icon: <Layers className="h-4 w-4" />, count: pools.length },
    { id: "categories", label: t("categories.tab"), icon: <Tags className="h-4 w-4" />, count: categories.length },
  ];

  return (
    <>
      <SettingsPage
        title={t("title")}
        description={tabAction.description}
        width="wide"
        actions={
          tabAction.label ? (
            <button
              onClick={tabAction.onClick}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
              <Plus className="h-4 w-4" aria-hidden />
              {tabAction.label}
            </button>
          ) : undefined
        }
      >
          {/* Scrolls on narrow screens rather than widening the page. */}
          <div
            role="tablist"
            aria-label={t("tabsLabel")}
            className="flex gap-1 overflow-x-auto border-b border-border"
          >
            {tabs.map((tab) => (
              <button
                key={tab.id}
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
                  activeTab === tab.id
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:border-border hover:text-foreground"
                )}
              >
                {tab.icon}
                {tab.label}
                <span className="rounded bg-muted px-1.5 text-xs text-muted-foreground">{tab.count}</span>
              </button>
            ))}
          </div>

          {/* Domains Tab */}
          {activeTab === "domains" && (
            <div className="space-y-4">
              {domainsError || domainsLoading || domains.length === 0 ? (
                <TabPlaceholder
                  error={domainsError}
                  isLoading={domainsLoading}
                  onRetry={() => refetchDomains()}
                  icon={<Globe className="h-8 w-8" aria-hidden />}
                  title={t("domains.emptyTitle")}
                  description={t("domains.emptyDetail")}
                  action={
                    <button
                      onClick={() => setShowAddDomain(true)}
                      className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
                    >
                      <Plus className="h-4 w-4" aria-hidden />
                      {t("domains.add")}
                    </button>
                  }
                />
              ) : (
                <div className="grid grid-cols-1 gap-4">
                  {domains.map((domain) => (
                    <DomainCard
                      key={domain.id}
                      domain={domain}
                      onVerify={() => verifyDomain(domain.id)}
                      onPause={() => pauseDomain(domain.id)}
                      onResume={() => resumeDomain(domain.id)}
                      onStartWarming={() => startWarming({ domainId: domain.id })}
                      onDelete={() => handleDeleteDomain(domain.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Providers Tab */}
          {activeTab === "providers" && (
            <div className="space-y-4">
              {providersError || providersLoading || providers.length === 0 ? (
                <TabPlaceholder
                  error={providersError}
                  isLoading={providersLoading}
                  onRetry={() => refetchProviders()}
                  icon={<Zap className="h-8 w-8" aria-hidden />}
                  title={t("providers.emptyTitle")}
                  description={t("providers.emptyDetail")}
                  action={
                    <button
                      onClick={() => setShowAddProvider(true)}
                      className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
                    >
                      <Plus className="h-4 w-4" aria-hidden />
                      {t("providers.add")}
                    </button>
                  }
                />
              ) : (
                <div className="grid grid-cols-1 gap-4">
                  {providers.map((provider) => (
                    <ProviderCard
                      key={provider.id}
                      provider={provider}
                      onToggle={() => updateProvider({
                        providerId: provider.id,
                        data: { is_active: !provider.is_active }
                      })}
                      onTest={() => testProvider(provider.id)}
                      onEdit={() => openEditProvider(provider)}
                      onDelete={() => handleDeleteProvider(provider.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Pools Tab */}
          {activeTab === "pools" && (
            <SendingPoolsPanel workspaceId={workspaceId} domains={domains} />
          )}

          {/* Categories Tab */}
          {activeTab === "categories" && (
            <div className="space-y-4">
              {categoriesError || categoriesLoading || categories.length === 0 ? (
                <TabPlaceholder
                  error={categoriesError}
                  isLoading={categoriesLoading}
                  onRetry={() => refetchCategories()}
                  icon={<Tags className="h-8 w-8" aria-hidden />}
                  title={t("categories.emptyTitle")}
                  description={t("categories.emptyDetail")}
                  action={
                    <button
                      onClick={() => setShowAddCategory(true)}
                      className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
                    >
                      <Plus className="h-4 w-4" aria-hidden />
                      {t("categories.add")}
                    </button>
                  }
                />
              ) : (
                <div className="grid grid-cols-1 gap-4">
                  {categories.map((category) => (
                    <CategoryCard
                      key={category.id}
                      category={category}
                      onToggle={() => updateCategory({
                        categoryId: category.id,
                        data: { is_active: !category.is_active }
                      })}
                      onEdit={() => openEditCategory(category)}
                      onDelete={() => handleDeleteCategory(category.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
      </SettingsPage>

      {/* {t("domain.add")} Modal */}
      {showAddDomain && (
        <Dialog
          open
          onOpenChange={(next) => {
            if (!next) setShowAddDomain(false);
          }}
        >
          <DialogContent className="max-w-md p-0" aria-describedby={undefined}>
            <div className="p-4 border-b border-border">
              <DialogTitle className="text-lg font-medium text-foreground">{t("domain.addTitle")}</DialogTitle>
            </div>
            <div className="p-4">
              <label className="block text-sm text-muted-foreground mb-2">{t("domain.field")}</label>
              <input
                type="text"
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                placeholder="mail.example.com"
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
              <p className="text-xs text-muted-foreground mt-2">
                {t("domain.dnsNote")}
              </p>
            </div>
            <div className="p-4 border-t border-border flex justify-end gap-2">
              <button
                onClick={() => setShowAddDomain(false)}
                className="px-4 py-2 text-muted-foreground hover:text-foreground transition"
              >
                {tc("cancel")}
              </button>
              <button
                onClick={handleCreateDomain}
                disabled={!newDomain}
                className="px-4 py-2 bg-sky-500 text-white rounded-lg hover:bg-sky-600 transition disabled:opacity-50"
              >
                {t("domain.add")}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* {t("provider.add")} Modal */}
      {showAddProvider && (
        <Dialog
          open
          onOpenChange={(next) => {
            if (!next) setShowAddProvider(false);
          }}
        >
          <DialogContent className="max-w-md p-0" aria-describedby={undefined}>
            <div className="p-4 border-b border-border">
              <DialogTitle className="text-lg font-medium text-foreground">{t("provider.addTitle")}</DialogTitle>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("provider.name")}</label>
                <input
                  type="text"
                  value={newProviderName}
                  onChange={(e) => setNewProviderName(e.target.value)}
                  placeholder={t("provider.namePlaceholder")}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("provider.type")}</label>
                <select
                  value={newProviderType}
                  onChange={(e) => setNewProviderType(e.target.value)}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                >
                  <option value="ses">Amazon SES</option>
                  <option value="sendgrid">SendGrid</option>
                  <option value="mailgun">Mailgun</option>
                  <option value="postmark">Postmark</option>
                  <option value="smtp">SMTP</option>
                </select>
              </div>
              <p className="text-xs text-muted-foreground">
                {t("provider.credentialsNote")}
              </p>
            </div>
            <div className="p-4 border-t border-border flex justify-end gap-2">
              <button
                onClick={() => setShowAddProvider(false)}
                className="px-4 py-2 text-muted-foreground hover:text-foreground transition"
              >
                {tc("cancel")}
              </button>
              <button
                onClick={handleCreateProvider}
                disabled={!newProviderName}
                className="px-4 py-2 bg-sky-500 text-white rounded-lg hover:bg-sky-600 transition disabled:opacity-50"
              >
                {t("provider.add")}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* Edit Provider Modal */}
      {editingProvider && (
        <Dialog
          open
          onOpenChange={(next) => {
            if (!next) setEditingProvider(null);
          }}
        >
          <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto p-0" aria-describedby={undefined}>
            <div className="p-4 border-b border-border">
              <DialogTitle className="text-lg font-medium text-foreground">
                Configure {editingProvider.provider_type.toUpperCase()} Provider
              </DialogTitle>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("provider.name")}</label>
                <input
                  type="text"
                  value={newProviderName}
                  onChange={(e) => setNewProviderName(e.target.value)}
                  placeholder={t("provider.editNamePlaceholder")}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("provider.descriptionOptional")}</label>
                <input
                  type="text"
                  value={providerDescription}
                  onChange={(e) => setProviderDescription(e.target.value)}
                  placeholder={t("provider.descriptionPlaceholder")}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>

              <div className="border-t border-border pt-4">
                <h4 className="text-sm font-medium text-foreground mb-3">{t("provider.credentials")}</h4>
                <div className="space-y-3">
                  {getCredentialFields(editingProvider.provider_type).map((field) => (
                    <div key={field.key}>
                      <label className="block text-sm text-muted-foreground mb-1">{field.label}</label>
                      {field.type === "select" && field.options ? (
                        <select
                          value={providerCredentials[field.key] || ""}
                          onChange={(e) => setProviderCredentials({
                            ...providerCredentials,
                            [field.key]: e.target.value,
                          })}
                          className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                        >
                          <option value="">{t("provider.select")}</option>
                          {field.options.map((opt) => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      ) : field.type === "checkbox" ? (
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={providerCredentials[field.key] === "true"}
                            onChange={(e) => setProviderCredentials({
                              ...providerCredentials,
                              [field.key]: e.target.checked ? "true" : "false",
                            })}
                            className="w-4 h-4 rounded border-border bg-muted text-sky-500 focus:ring-sky-500"
                          />
                          <span className="text-sm text-foreground">{t("provider.enableTls")}</span>
                        </label>
                      ) : (
                        <input
                          type={field.type}
                          value={providerCredentials[field.key] || ""}
                          onChange={(e) => setProviderCredentials({
                            ...providerCredentials,
                            [field.key]: e.target.value,
                          })}
                          placeholder={field.placeholder}
                          className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-muted/50 rounded-lg p-3">
                <p className="text-xs text-muted-foreground">
                  <strong className="text-foreground">{t("provider.securityNote")}</strong> Credentials are encrypted and stored securely.
                  After saving, some credential values may be masked for security.
                </p>
              </div>
            </div>
            <div className="p-4 border-t border-border flex justify-end gap-2">
              <button
                onClick={closeEditProvider}
                className="px-4 py-2 text-muted-foreground hover:text-foreground transition"
              >
                {tc("cancel")}
              </button>
              <button
                onClick={handleUpdateProvider}
                disabled={!newProviderName}
                className="px-4 py-2 bg-sky-500 text-white rounded-lg hover:bg-sky-600 transition disabled:opacity-50"
              >
                {t("saveChanges")}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* {t("category.add")} Modal */}
      {showAddCategory && (
        <Dialog
          open
          onOpenChange={(next) => {
            if (!next) setShowAddCategory(false);
          }}
        >
          <DialogContent className="max-w-md p-0" aria-describedby={undefined}>
            <div className="p-4 border-b border-border">
              <DialogTitle className="text-lg font-medium text-foreground">{t("category.addTitle")}</DialogTitle>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("category.name")}</label>
                <input
                  type="text"
                  value={newCategoryName}
                  onChange={(e) => setNewCategoryName(e.target.value)}
                  placeholder={t("category.namePlaceholder")}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("category.slugOptional")}</label>
                <input
                  type="text"
                  value={newCategorySlug}
                  onChange={(e) => setNewCategorySlug(e.target.value)}
                  placeholder="product-updates"
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
                <p className="text-xs text-muted-foreground mt-1">{t("category.slugAutoNote")}</p>
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("provider.descriptionOptional")}</label>
                <textarea
                  value={newCategoryDescription}
                  onChange={(e) => setNewCategoryDescription(e.target.value)}
                  placeholder={t("category.descriptionPlaceholder")}
                  rows={3}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="defaultSubscribed"
                  checked={newCategoryDefaultSubscribed}
                  onChange={(e) => setNewCategoryDefaultSubscribed(e.target.checked)}
                  className="w-4 h-4 rounded border-border bg-muted text-sky-500 focus:ring-sky-500"
                />
                <label htmlFor="defaultSubscribed" className="text-sm text-foreground">
                  {t("category.subscribeByDefault")}
                </label>
              </div>
            </div>
            <div className="p-4 border-t border-border flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowAddCategory(false);
                  setNewCategoryName("");
                  setNewCategorySlug("");
                  setNewCategoryDescription("");
                  setNewCategoryDefaultSubscribed(true);
                }}
                className="px-4 py-2 text-muted-foreground hover:text-foreground transition"
              >
                {tc("cancel")}
              </button>
              <button
                onClick={handleCreateCategory}
                disabled={!newCategoryName}
                className="px-4 py-2 bg-sky-500 text-white rounded-lg hover:bg-sky-600 transition disabled:opacity-50"
              >
                {t("category.add")}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* {t("category.editTitle")} Modal */}
      {editingCategory && (
        <Dialog
          open
          onOpenChange={(next) => {
            if (!next) setEditingCategory(null);
          }}
        >
          <DialogContent className="max-w-md p-0" aria-describedby={undefined}>
            <div className="p-4 border-b border-border">
              <DialogTitle className="text-lg font-medium text-foreground">{t("category.editTitle")}</DialogTitle>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("category.name")}</label>
                <input
                  type="text"
                  value={newCategoryName}
                  onChange={(e) => setNewCategoryName(e.target.value)}
                  placeholder={t("category.namePlaceholder")}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("category.slug")}</label>
                <input
                  type="text"
                  value={editingCategory.slug}
                  disabled
                  className="w-full px-3 py-2 bg-muted/50 border border-border rounded-lg text-muted-foreground cursor-not-allowed"
                />
                <p className="text-xs text-muted-foreground mt-1">{t("category.slugLockedNote")}</p>
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-2">{t("provider.descriptionOptional")}</label>
                <textarea
                  value={newCategoryDescription}
                  onChange={(e) => setNewCategoryDescription(e.target.value)}
                  placeholder={t("category.descriptionPlaceholder")}
                  rows={3}
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
            </div>
            <div className="p-4 border-t border-border flex justify-end gap-2">
              <button
                onClick={() => {
                  setEditingCategory(null);
                  setNewCategoryName("");
                  setNewCategoryDescription("");
                }}
                className="px-4 py-2 text-muted-foreground hover:text-foreground transition"
              >
                {tc("cancel")}
              </button>
              <button
                onClick={handleUpdateCategory}
                disabled={!newCategoryName}
                className="px-4 py-2 bg-sky-500 text-white rounded-lg hover:bg-sky-600 transition disabled:opacity-50"
              >
                {t("saveChanges")}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

export default function EmailMarketingSettingsPage() {
  return (
    <AppAccessGuard appId="email_marketing">
      <EmailSettingsContent />
    </AppAccessGuard>
  );
}
