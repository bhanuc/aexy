"use client";

import { useState } from "react";
import { Edit2, GripVertical, MoreVertical, Trash2 } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { StatusCategory, TaskStatusConfig } from "@/lib/api";

function getCategoryBadgeColor(category: StatusCategory) {
  switch (category) {
    case "backlog":
      return "bg-slate-50 text-slate-600 dark:bg-slate-900/40 dark:text-slate-300";
    case "todo":
      return "bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400";
    case "in_progress":
      return "bg-yellow-50 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400";
    case "in_review":
      return "bg-violet-50 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400";
    case "done":
      return "bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400";
    case "cancelled":
      return "bg-rose-50 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

export interface SortableStatusItemProps {
  status: TaskStatusConfig;
  isAdmin: boolean;
  onEdit: (status: TaskStatusConfig) => void;
  onDelete: (statusId: string) => void;
  /** When true the row renders with a "Workspace default" chip and no
      drag/edit/delete affordances. Used in per-project mode before the
      admin has clicked "Customize for this project". */
  readOnly?: boolean;
}

export function SortableStatusItem({
  status,
  isAdmin,
  onEdit,
  onDelete,
  readOnly = false,
}: SortableStatusItemProps) {
  const interactive = isAdmin && !readOnly;
  const [showMenu, setShowMenu] = useState(false);
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: status.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`bg-card rounded-lg p-3 flex items-center gap-3 ${
        readOnly ? "opacity-80" : ""
      }`}
    >
      {interactive && (
        <button
          {...attributes}
          {...listeners}
          aria-label={`Reorder ${status.name}`}
          className="p-1 text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing"
        >
          <GripVertical className="h-4 w-4" />
        </button>
      )}
      <div
        className="w-4 h-4 rounded-full flex-shrink-0"
        style={{ backgroundColor: status.color }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-foreground font-medium">{status.name}</span>
          <span
            className={`px-2 py-0.5 rounded text-xs ${getCategoryBadgeColor(
              status.category,
            )}`}
          >
            {status.category.replace("_", " ")}
          </span>
          {status.is_default && (
            <span className="px-2 py-0.5 rounded text-xs bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-400">
              Default
            </span>
          )}
          {readOnly && (
            <span className="px-2 py-0.5 rounded text-xs bg-muted text-muted-foreground border border-border">
              Workspace default
            </span>
          )}
        </div>
        <p className="text-muted-foreground text-xs">slug: {status.slug}</p>
      </div>
      {interactive && (
        <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="p-2 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition"
          >
            <MoreVertical className="h-4 w-4" />
          </button>
          {showMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
              <div className="absolute right-0 top-full mt-1 w-36 bg-muted rounded-lg shadow-xl z-20 py-1">
                <button
                  onClick={() => {
                    onEdit(status);
                    setShowMenu(false);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-foreground hover:bg-accent flex items-center gap-2"
                >
                  <Edit2 className="h-4 w-4" />
                  Edit
                </button>
                <button
                  onClick={() => {
                    onDelete(status.id);
                    setShowMenu(false);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-accent flex items-center gap-2"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
