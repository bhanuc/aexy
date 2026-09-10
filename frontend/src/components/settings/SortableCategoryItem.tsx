"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Edit2, MoreVertical, Trash2 } from "lucide-react";

import { WorkspaceStatusCategory } from "@/lib/api";

function semanticsBadgeColor(semantics: string): string {
  switch (semantics) {
    case "open":
      return "bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400";
    case "active":
      return "bg-yellow-50 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400";
    case "done":
      return "bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400";
    case "cancelled":
      return "bg-rose-50 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

export interface SortableCategoryItemProps {
  category: WorkspaceStatusCategory;
  isAdmin: boolean;
  onEdit: (cat: WorkspaceStatusCategory) => void;
  onDelete: (cat: WorkspaceStatusCategory) => void;
}

/**
 * Compact category row for the admin list. No drag handle for now —
 * categories are typically a small fixed set, so reorder isn't a primary
 * affordance. Add it later if users actually want it.
 */
export function SortableCategoryItem({
  category,
  isAdmin,
  onEdit,
  onDelete,
}: SortableCategoryItemProps) {
  const t = useTranslations("taskStatusRow");
  const tc = useTranslations("common");
  const [showMenu, setShowMenu] = useState(false);

  return (
    <div className="bg-card rounded-lg p-3 flex items-center gap-3">
      <div
        className="w-4 h-4 rounded-full flex-shrink-0"
        style={{ backgroundColor: category.color }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-foreground font-medium">{category.label}</span>
          <span
            className={`px-2 py-0.5 rounded text-xs ${semanticsBadgeColor(
              category.semantics,
            )}`}
          >
            {category.semantics}
          </span>
          {category.is_default && (
            <span className="px-2 py-0.5 rounded text-xs bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-400">
              {t("default")}
            </span>
          )}
        </div>
        <p className="text-muted-foreground text-xs">
          slug: <span className="font-mono">{category.slug}</span>
        </p>
      </div>
      {isAdmin && (
        <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="p-2 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition"
            aria-label={`Manage category ${category.label}`}
          >
            <MoreVertical className="h-4 w-4" />
          </button>
          {showMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
              <div className="absolute right-0 top-full mt-1 w-36 bg-muted rounded-lg shadow-xl z-20 py-1">
                <button
                  onClick={() => {
                    onEdit(category);
                    setShowMenu(false);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-foreground hover:bg-accent flex items-center gap-2"
                >
                  <Edit2 className="h-4 w-4" />
                  {tc("edit")}
                </button>
                <button
                  onClick={() => {
                    onDelete(category);
                    setShowMenu(false);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-accent flex items-center gap-2"
                >
                  <Trash2 className="h-4 w-4" />
                  {tc("delete")}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
