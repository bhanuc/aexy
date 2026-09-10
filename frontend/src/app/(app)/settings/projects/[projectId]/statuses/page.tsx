"use client";

import { getApiErrorMessage } from "@/lib/utils";
import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { AlertCircle, ArrowLeft, Clock, FolderKanban, Layers, Plus, RefreshCw } from "lucide-react";
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors, DragEndEvent } from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";

import { useAuth } from "@/hooks/useAuth";
import { useWorkspace, useWorkspaceMembers } from "@/hooks/useWorkspace";
import { useProject } from "@/hooks/useProjects";
import { useTaskStatuses, useStatusCategories } from "@/hooks/useTaskConfig";
import { TaskStatusConfig, WorkspaceStatusCategory } from "@/lib/api";
import { SortableStatusItem } from "@/components/settings/SortableStatusItem";
import { StatusModal } from "@/components/settings/StatusModal";
import { DeleteStatusModal } from "@/components/settings/DeleteStatusModal";
import { CategoryModal } from "@/components/settings/CategoryModal";
import { SortableCategoryItem } from "@/components/settings/SortableCategoryItem";
import { useTranslations } from "next-intl";
import { ProjectSettingsPage } from "@/components/settings/ProjectSettingsPage";

export default function ProjectStatusesPage() {
  const t = useTranslations("settingsProjects");
  // The status and category sections are the same concepts workspace task
  // settings defines, so they read those messages rather than a second copy.
  const tt = useTranslations("settingsTaskConfig");
  const params = useParams();
  const projectId = params.projectId as string;

  const { user } = useAuth();
  const { currentWorkspaceId, currentWorkspaceLoading } = useWorkspace();
  const { members: workspaceMembers } = useWorkspaceMembers(currentWorkspaceId);
  const { project, isLoading: projectLoading } = useProject(currentWorkspaceId, projectId);

  const {
    statuses,
    isLoading: statusesLoading,
    createStatus,
    updateStatus,
    deleteStatus,
    reorderStatuses,
    cloneFromWorkspace,
    isUsingWorkspaceFallback,
    isCloning,
    isCreating,
    isUpdating,
    isDeleting,
  } = useTaskStatuses(currentWorkspaceId, projectId);

  const {
    categories: statusCategories,
    isLoading: categoriesLoading,
    createCategory,
    updateCategory,
    deleteCategory,
    isCreating: isCreatingCategory,
    isUpdating: isUpdatingCategory,
    isUsingWorkspaceFallback: categoriesInherited,
  } = useStatusCategories(currentWorkspaceId, projectId);

  const [showStatusModal, setShowStatusModal] = useState(false);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState<WorkspaceStatusCategory | null>(null);
  const [editingStatus, setEditingStatus] = useState<TaskStatusConfig | null>(null);
  const [deletingStatus, setDeletingStatus] = useState<TaskStatusConfig | null>(null);

  const currentMember = workspaceMembers.find((m) => m.developer_id === user?.id);
  const isAdmin = currentMember?.role === "owner" || currentMember?.role === "admin";
  const readOnly = isUsingWorkspaceFallback;

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = statuses.findIndex((s) => s.id === active.id);
    const newIndex = statuses.findIndex((s) => s.id === over.id);
    const newOrder = arrayMove(statuses, oldIndex, newIndex);
    await reorderStatuses(newOrder.map((s) => s.id));
  };

  const handleSaveStatus = async (data: {
    name: string;
    category: string;
    color: string;
    icon?: string;
    is_default?: boolean;
  }) => {
    if (editingStatus) {
      await updateStatus({ statusId: editingStatus.id, data });
      toast.success(tt("statuses.updated"));
    } else {
      await createStatus(data);
      toast.success(tt("statuses.created"));
    }
    setEditingStatus(null);
  };

  const handleSaveCategory = async (data: {
    slug?: string;
    label: string;
    color: string;
    semantics: "open" | "active" | "done" | "cancelled";
  }) => {
    if (editingCategory) {
      await updateCategory({
        categoryId: editingCategory.id,
        data: {
          label: data.label,
          color: data.color,
          semantics: data.semantics,
        },
      });
      toast.success(tt("categories.updated"));
    } else {
      await createCategory({
        slug: data.slug!,
        label: data.label,
        color: data.color,
        semantics: data.semantics,
      });
      toast.success(tt("categories.created"));
    }
    setEditingCategory(null);
  };

  const handleDeleteCategory = async (cat: WorkspaceStatusCategory) => {
    const inUse = statuses.some((s) => s.category === cat.slug);
    if (inUse) {
      toast.error(
        tt("categories.inUse", { label: cat.label }),
      );
      return;
    }
    if (!confirm(tt("categories.confirmDelete", { label: cat.label }))) return;
    try {
      await deleteCategory(cat.id);
      toast.success(tt("categories.deleted"));
    } catch (err) {
      const msg = getApiErrorMessage(err, "Failed to delete");
      toast.error(/category_in_use/i.test(msg)
        ? tt("categories.inUseServer")
        : msg);
    }
  };

  const handleConfirmDelete = async (migrateTo: string | null) => {
    if (!deletingStatus) return;
    try {
      await deleteStatus({
        statusId: deletingStatus.id,
        migrateTo: migrateTo ?? undefined,
      });
      toast.success(tt("statuses.deleted"));
      setDeletingStatus(null);
    } catch (err) {
      const message = getApiErrorMessage(err, "Failed to delete status");
      toast.error(message);
    }
  };

  if (currentWorkspaceLoading || projectLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-5 w-64 bg-accent rounded" />
        <div className="h-10 w-72 bg-accent rounded-lg" />
        <div className="h-48 w-full bg-accent rounded-xl" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <FolderKanban className="h-16 w-16 text-muted-foreground mx-auto mb-4" />
          <h3 className="text-xl font-medium text-foreground mb-2">
            {t("notFoundTitle")}
          </h3>
          <Link
            href="/settings/projects"
            className="inline-flex items-center gap-2 px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition font-medium"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("notFoundCta")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <ProjectSettingsPage projectId={projectId} description={t("statuses.subtitle")}>

      <div>

        {/* Categories section — the buckets statuses can belong to. Ships
            with six canonical buckets (backlog, todo, in_progress,
            in_review, done, cancelled) seeded per workspace; admins can
            rename, recolor, or add more. Burndown/velocity branches on
            semantics so renaming a slug is safe. */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
            <div className="flex items-start gap-3">
              <Layers className="h-5 w-5 text-muted-foreground mt-0.5" />
              <div>
                <h2 className="text-lg font-medium text-foreground">
                  {t("categoriesHeading")}
                </h2>
                <p className="text-muted-foreground text-sm">
                  Buckets that statuses belong to. Each carries a semantics
                  flag (Open / Active / Done / Cancelled) used for burndown.
                </p>
              </div>
            </div>
            {isAdmin && (
              <button
                onClick={() => {
                  setEditingCategory(null);
                  setShowCategoryModal(true);
                }}
                className="flex items-center gap-2 px-3 py-1.5 bg-muted hover:bg-accent text-foreground rounded-lg transition text-sm"
              >
                <Plus className="h-4 w-4" />
                {tt("categories.add")}
              </button>
            )}
          </div>

          {/* Inherited categories are workspace rows, not this project's.
              Editing one here would change every other project too, and
              adding one forks the whole set into the project — say both
              out loud rather than letting the list imply otherwise. */}
          {categoriesInherited && (
            <div className="mb-4 flex items-start gap-3 rounded-lg border border-border bg-muted/40 p-3">
              <AlertCircle className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
              <p className="text-sm text-muted-foreground">
                These categories are inherited from the workspace. Adding one
                copies the full set into this project first, so nothing here
                disappears — after that the project keeps its own buckets and
                workspace changes no longer reach it. To rename or recolor a
                shared bucket for every project, use Status Categories in{" "}
                <Link
                  href="/settings/task-config"
                  className="text-primary-400 hover:text-primary-300 underline"
                >
                  workspace task settings
                </Link>
                .
              </p>
            </div>
          )}

          {categoriesLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-14 bg-card rounded-lg animate-pulse" />
              ))}
            </div>
          ) : statusCategories.length > 0 ? (
            <div className="space-y-2">
              {statusCategories.map((cat) => (
                <SortableCategoryItem
                  key={cat.id}
                  category={cat}
                  isAdmin={isAdmin && !categoriesInherited}
                  onEdit={(c) => {
                    setEditingCategory(c);
                    setShowCategoryModal(true);
                  }}
                  onDelete={handleDeleteCategory}
                />
              ))}
            </div>
          ) : (
            <div className="bg-card rounded-xl p-8 text-center text-sm text-muted-foreground">
              No categories yet — they&apos;ll seed automatically when you save your first status.
            </div>
          )}
        </div>

        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <div>
            <h2 className="text-lg font-medium text-foreground">
              {tt("statuses.heading")}
            </h2>
            <p className="text-muted-foreground text-sm">
              {readOnly
                ? t("statusesSubtitleInherited")
                : t("statusesSubtitleOwn")}
            </p>
          </div>
          {isAdmin && !readOnly && (
            <button
              onClick={() => {
                setEditingStatus(null);
                setShowStatusModal(true);
              }}
              className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition text-sm"
            >
              <Plus className="h-4 w-4" />
              {tt("statuses.add")}
            </button>
          )}
        </div>

        {/* Fallback CTA */}
        {readOnly && isAdmin && (
          <div className="mb-4 flex items-start gap-3 rounded-lg border border-primary-500/30 bg-primary-500/5 p-4">
            <AlertCircle className="h-5 w-5 text-primary-400 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-sm font-medium text-foreground">
                {t("usingWorkspaceDefaults")}
              </h4>
              <p className="mt-1 text-sm text-muted-foreground">
                Customizing here forks the workspace statuses into a
                project-scoped copy. Other projects keep using the workspace
                defaults; future workspace edits won&apos;t reach this project.
              </p>
            </div>
            <button
              onClick={async () => {
                try {
                  await cloneFromWorkspace();
                  toast.success(tt("statuses.copied"));
                } catch (err) {
                  console.error(err);
                  toast.error(tt("statuses.copyFailed"));
                }
              }}
              disabled={isCloning}
              className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-md text-sm whitespace-nowrap flex items-center gap-2"
            >
              {isCloning ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  {tt("statuses.forkCopying")}
                </>
              ) : (
                "Customize for this project"
              )}
            </button>
          </div>
        )}

        {/* Status list */}
        {statusesLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 bg-card rounded-lg animate-pulse" />
            ))}
          </div>
        ) : statuses.length > 0 ? (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={statuses.map((s) => s.id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-2">
                {statuses.map((status) => (
                  <SortableStatusItem
                    key={status.id}
                    status={status}
                    isAdmin={isAdmin}
                    onEdit={(s) => {
                      setEditingStatus(s);
                      setShowStatusModal(true);
                    }}
                    onDelete={(statusId) => {
                      const target = statuses.find((s) => s.id === statusId) ?? null;
                      setDeletingStatus(target);
                    }}
                    readOnly={readOnly}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        ) : (
          <div className="bg-card rounded-xl p-12 text-center">
            <Clock className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-medium text-foreground mb-2">
              {t("statusesEmptyTitle")}
            </h3>
            <p className="text-muted-foreground">
              {t("statusesEmptyDescription")}
            </p>
          </div>
        )}
      </div>

      {showStatusModal && (
        <StatusModal
          status={editingStatus}
          categories={statusCategories}
          onClose={() => {
            setShowStatusModal(false);
            setEditingStatus(null);
          }}
          onSave={handleSaveStatus}
          isSaving={isCreating || isUpdating}
        />
      )}

      {showCategoryModal && (
        <CategoryModal
          category={editingCategory}
          onClose={() => {
            setShowCategoryModal(false);
            setEditingCategory(null);
          }}
          onSave={handleSaveCategory}
          isSaving={isCreatingCategory || isUpdatingCategory}
        />
      )}

      {deletingStatus && currentWorkspaceId && (
        <DeleteStatusModal
          workspaceId={currentWorkspaceId}
          status={deletingStatus}
          candidates={statuses}
          onClose={() => setDeletingStatus(null)}
          onConfirm={handleConfirmDelete}
          isDeleting={isDeleting}
        />
      )}
    </ProjectSettingsPage>
  );
}
