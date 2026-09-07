"use client";

import { getApiErrorMessage } from "@/lib/utils";
import { useState } from "react";
import { AlertCircle, Check, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { StatusCategory, TaskStatusConfig, WorkspaceStatusCategory } from "@/lib/api";

// The four semantics buckets are a property of a category, so their labels and
// tooltips come from the `statusCategories` namespace rather than a second copy
// here — this file used to hold its own, free to drift from the dialog that
// actually defines them.
const SEMANTICS_VALUES = ["open", "active", "done", "cancelled"] as const;

const PRESET_COLORS = [
  "#6B7280",
  "#EF4444",
  "#F59E0B",
  "#10B981",
  "#3B82F6",
  "#8B5CF6",
  "#EC4899",
  "#14B8A6",
  "#F97316",
  "#6366F1",
];

export interface StatusModalProps {
  status: TaskStatusConfig | null;
  categories: WorkspaceStatusCategory[];
  onClose: () => void;
  onSave: (data: {
    name: string;
    category: StatusCategory;
    color: string;
    icon?: string;
    is_default?: boolean;
  }) => Promise<void>;
  isSaving: boolean;
}

export function StatusModal({
  status,
  categories,
  onClose,
  onSave,
  isSaving,
}: StatusModalProps) {
  const t = useTranslations("taskStatuses");
  const tCat = useTranslations("statusCategories");
  const tc = useTranslations("common");
  const isKnownSemantics = (value: string): value is (typeof SEMANTICS_VALUES)[number] =>
    (SEMANTICS_VALUES as readonly string[]).includes(value);
  // A row could carry a semantics value this build doesn't know; show it raw
  // rather than letting a missing message key throw.
  const semanticsLabel = (value: string) =>
    isKnownSemantics(value) ? tCat(`semantics.${value}.label`) : value;
  const semanticsHint = (value: string) =>
    isKnownSemantics(value) ? tCat(`semantics.${value}.hint`) : value;

  const fallbackCategory = categories[0]?.slug ?? "todo";
  const [name, setName] = useState(status?.name || "");
  const [category, setCategory] = useState<StatusCategory>(
    status?.category || fallbackCategory,
  );
  const [color, setColor] = useState(status?.color || "#6B7280");
  const [isDefault, setIsDefault] = useState(status?.is_default || false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError(t("modal.errors.nameRequired"));
      return;
    }
    try {
      await onSave({ name: name.trim(), category, color, is_default: isDefault });
      onClose();
    } catch (err) {
      setError(getApiErrorMessage(err, t("modal.errors.saveFailed")));
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      {/* Modal semantics: without these the overlay is an anonymous div, so a
          screen reader neither announces it nor confines the user to it. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="status-modal-title"
        className="bg-card rounded-xl w-full max-w-md p-6"
      >
        <h3
          id="status-modal-title"
          className="text-xl font-semibold text-foreground mb-4"
        >
          {status ? t("modal.editTitle") : t("modal.createTitle")}
        </h3>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label
                htmlFor="status-name"
                className="block text-sm text-muted-foreground mb-1"
              >
                {t("modal.nameField")}
              </label>
              {/* Latin example in every locale: the slug the server derives
                  from this name drops Devanagari vowel signs, so a translated
                  example would suggest a name shape that does not round-trip. */}
              <input
                id="status-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("modal.namePlaceholder")}
                className="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary-500"
              />
            </div>

            <div>
              <label className="block text-sm text-muted-foreground mb-1">
                {t("modal.categoryField")}
              </label>
              {categories.length === 0 ? (
                <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                  {t("modal.categoryEmpty")}
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {categories.map((cat) => (
                    <button
                      key={cat.id}
                      type="button"
                      onClick={() => setCategory(cat.slug)}
                      title={semanticsHint(cat.semantics)}
                      className={`p-2 rounded-lg border text-center transition ${
                        category === cat.slug
                          ? "border-primary-500 bg-primary-900/20"
                          : "border-border hover:border-foreground/30"
                      }`}
                    >
                      <div
                        className="w-3 h-3 rounded-full mx-auto mb-1"
                        style={{ backgroundColor: cat.color }}
                      />
                      <span className="text-foreground text-sm">{cat.label}</span>
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground mt-0.5">
                        {semanticsLabel(cat.semantics)}
                      </div>
                    </button>
                  ))}
                </div>
              )}
              <p className="text-muted-foreground text-xs mt-1">
                {t("modal.categoryHint")}
              </p>
            </div>

            <div>
              <label className="block text-sm text-muted-foreground mb-1">
                {t("modal.colorField")}
              </label>
              <div className="flex flex-wrap gap-2">
                {PRESET_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setColor(c)}
                    className={`w-8 h-8 rounded-lg border-2 transition ${
                      color === c ? "border-white" : "border-transparent"
                    }`}
                    style={{ backgroundColor: c }}
                  />
                ))}
                <input
                  type="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="w-8 h-8 rounded-lg cursor-pointer"
                />
              </div>
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="w-4 h-4 rounded border-border bg-muted text-primary-500 focus:ring-primary-500"
              />
              <span className="text-foreground text-sm">
                {t("modal.defaultToggle")}
              </span>
            </label>

            {error && (
              <div className="flex items-center gap-2 text-red-400 text-sm">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}
          </div>

          <div className="flex gap-3 mt-6">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-muted hover:bg-accent text-foreground rounded-lg transition"
            >
              {tc("cancel")}
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="flex-1 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {isSaving ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  {t("modal.saving")}
                </>
              ) : (
                <>
                  <Check className="h-4 w-4" />
                  {tc("save")}
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
