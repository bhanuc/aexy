"use client";

import { getApiErrorMessage } from "@/lib/utils";
import { useState } from "react";
import { AlertCircle, Check, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import {
  CategorySemantics,
  WorkspaceStatusCategory,
} from "@/lib/api";

// Each value is also its key under `statusCategories.semantics`.
const SEMANTICS_VALUES: CategorySemantics[] = [
  "open",
  "active",
  "done",
  "cancelled",
];

const PRESET_COLORS = [
  "#9CA3AF", "#EF4444", "#F59E0B", "#10B981", "#3B82F6",
  "#8B5CF6", "#EC4899", "#14B8A6", "#F97316", "#6366F1",
];

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/[-\s]+/g, "_")
    .replace(/^_|_$/g, "");
}

export interface CategoryModalProps {
  category: WorkspaceStatusCategory | null;
  onClose: () => void;
  onSave: (data: {
    slug?: string;
    label: string;
    color: string;
    semantics: CategorySemantics;
  }) => Promise<void>;
  isSaving: boolean;
}

/**
 * Add / edit a status category. Slug is only editable at create time —
 * existing statuses reference it as a string, so a rename would orphan them.
 * Label, color, and semantics stay editable for the lifetime of the row.
 */
export function CategoryModal({ category, onClose, onSave, isSaving }: CategoryModalProps) {
  const t = useTranslations("statusCategories");
  const tc = useTranslations("common");
  const isEdit = category !== null;
  const [label, setLabel] = useState(category?.label ?? "");
  const [color, setColor] = useState(category?.color ?? "#6B7280");
  const [semantics, setSemantics] = useState<CategorySemantics>(
    category?.semantics ?? "open",
  );
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!label.trim()) {
      setError(t("modal.errors.labelRequired"));
      return;
    }
    // `slugify` keeps only Latin letters, digits and `_`, so a label written in
    // a non-Latin script reduces to an empty slug — which the API rejects on
    // `min_length`. Caught here, with the reason, rather than posting it and
    // surfacing a validation error nobody can act on. Only on create: an
    // existing category already has its slug.
    if (!isEdit && !slugify(label)) {
      setError(t("modal.errors.slugEmpty"));
      return;
    }
    try {
      await onSave({
        ...(isEdit ? {} : { slug: slugify(label) }),
        label: label.trim(),
        color,
        semantics,
      });
      onClose();
    } catch (err) {
      const msg = getApiErrorMessage(err, t("modal.errors.saveFailed"));
      // Surface category_slug_exists distinctly so the operator picks a new label.
      if (/category_slug_exists/i.test(msg)) {
        setError(t("modal.errors.slugExists"));
      } else {
        setError(msg);
      }
    }
  };

  // Mounted only while open (`{showCategoryModal && <CategoryModal …>}`), so
  // `open` is constant and closing is delegated to the caller — which keeps
  // Radix's Escape handling and backdrop click going through the same path as
  // the Cancel button.
  return (
    <Dialog open onOpenChange={(next) => { if (!next) onClose(); }}>
      {/* No descriptive paragraph in this dialog, so opt out explicitly —
          Radix warns otherwise, and a wrong `aria-describedby` is worse
          than none. */}
      <DialogContent className="max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="text-xl">
            {isEdit ? t("modal.editTitle") : t("modal.createTitle")}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label
                htmlFor="category-label"
                className="block text-sm text-muted-foreground mb-1"
              >
                {t("modal.labelField")}
              </label>
              {/* The placeholder is Latin in every locale on purpose: the
                  slug below keeps only Latin letters and digits, so a
                  translated example would promise something the derivation
                  can't deliver. */}
              <input
                id="category-label"
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t("modal.labelPlaceholder")}
                autoFocus
                className="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary-500"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {t("modal.labelHint")}
              </p>
            </div>

            {/* The slug as its own read-only field rather than a caption under
                the label. Both are one word for buckets like `needs_revision`,
                so a caption left people unsure which of the two they had just
                typed — a field they cannot type into answers that by itself.
                Read-only rather than disabled: still focusable, announced, and
                copyable, which matters because a status's category is stored
                as this string. */}
            <div>
              <label
                htmlFor="category-slug"
                className="block text-sm text-muted-foreground mb-1"
              >
                {t("modal.slugField")}
              </label>
              <input
                id="category-slug"
                type="text"
                readOnly
                aria-readonly="true"
                aria-describedby="category-slug-hint"
                value={isEdit ? category!.slug : slugify(label)}
                placeholder={t("modal.slugPlaceholder")}
                className="w-full px-4 py-2 bg-muted/50 border border-dashed border-border rounded-lg font-mono text-sm text-muted-foreground placeholder-muted-foreground/60 focus:outline-none cursor-default"
              />
              <p id="category-slug-hint" className="mt-1 text-xs text-muted-foreground">
                {isEdit
                  ? t("modal.slugHintExisting")
                  : t("modal.slugHintNew")}
              </p>
            </div>

            <div>
              <label className="block text-sm text-muted-foreground mb-1">
                {t("modal.semanticsField")}
              </label>
              <div className="grid grid-cols-2 gap-2">
                {SEMANTICS_VALUES.map((value) => {
                  const hint = t(`semantics.${value}.hint`);
                  return (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setSemantics(value)}
                      title={hint}
                      aria-pressed={semantics === value}
                      className={`p-2 rounded-lg border text-left transition ${
                        semantics === value
                          ? "border-primary-500 bg-primary-900/20"
                          : "border-border hover:border-foreground/30"
                      }`}
                    >
                      <div className="text-foreground text-sm font-medium">
                        {t(`semantics.${value}.label`)}
                      </div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        {hint}
                      </div>
                    </button>
                  );
                })}
              </div>
              <p className="text-muted-foreground text-xs mt-1">
                {t("modal.semanticsHint")}
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
      </DialogContent>
    </Dialog>
  );
}
