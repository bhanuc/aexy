"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { ArrowLeft, FolderKanban, Shield, Users, ChevronDown, Check, X, Crown, RefreshCw, UserMinus, Plus, Mail, UserPlus, AlertCircle, CheckCircle } from "lucide-react";
import { useWorkspace, useWorkspaceMembers } from "@/hooks/useWorkspace";
import { useProject, useProjectMembers } from "@/hooks/useProjects";
import { useRoles } from "@/hooks/useRoles";
import { useAuth } from "@/hooks/useAuth";
import { useSubscription } from "@/hooks/useSubscription";
import { UpgradeModal } from "@/components/PremiumGate";
import { ProjectInviteResult } from "@/lib/api";
import { useTranslations } from "next-intl";
import { ProjectSettingsPage } from "@/components/settings/ProjectSettingsPage";

function getRoleBadgeColor(roleName: string | null) {
  if (!roleName) return "bg-muted text-muted-foreground";

  const name = roleName.toLowerCase();
  if (name.includes("admin") || name.includes("owner")) {
    return "bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400";
  }
  if (name.includes("manager") || name.includes("lead")) {
    return "bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400";
  }
  if (name.includes("developer") || name.includes("dev")) {
    return "bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400";
  }
  if (name.includes("viewer") || name.includes("read")) {
    return "bg-muted text-foreground";
  }
  return "bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400";
}

export default function ProjectPermissionsPage() {
  const t = useTranslations("settingsProjects");
  const tc = useTranslations("common");
  const params = useParams();
  const projectId = params.projectId as string;

  const { user } = useAuth();
  const { currentWorkspaceId, currentWorkspaceLoading } = useWorkspace();
  const { members: workspaceMembers } = useWorkspaceMembers(currentWorkspaceId);
  const { project, isLoading: projectLoading } = useProject(currentWorkspaceId, projectId);
  const { roles } = useRoles(currentWorkspaceId);
  const { canUseTeamFeatures } = useSubscription(currentWorkspaceId);

  const {
    members,
    isLoading: membersLoading,
    addMember,
    updateMember,
    removeMember,
    inviteMembers,
    isAdding,
    isUpdating,
    isInviting,
  } = useProjectMembers(currentWorkspaceId, projectId);

  const [showAddMember, setShowAddMember] = useState(false);
  const [addMode, setAddMode] = useState<"workspace" | "email">("workspace");
  const [selectedDeveloperId, setSelectedDeveloperId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [inviteResult, setInviteResult] = useState<ProjectInviteResult | null>(null);
  const [editingMemberId, setEditingMemberId] = useState<string | null>(null);
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);

  const currentMember = workspaceMembers.find((m) => m.developer_id === user?.id);
  const isAdmin = currentMember?.role === "owner" || currentMember?.role === "admin";

  const availableMembers = workspaceMembers.filter(
    (wm) => !members.some((pm) => pm.developer_id === wm.developer_id)
  );

  const handleAddMember = async () => {
    if (!selectedDeveloperId) return;

    try {
      await addMember({
        developer_id: selectedDeveloperId,
        role_id: selectedRoleId || undefined,
      });
      setSelectedDeveloperId("");
      setSelectedRoleId("");
      setShowAddMember(false);
    } catch (error) {
      console.error("Failed to add member:", error);
    }
  };

  const handleInviteByEmail = async () => {
    if (!emailInput.trim()) return;

    const emails = emailInput
      .split(/[,\n]/)
      .map((e) => e.trim().toLowerCase())
      .filter((e) => e && e.includes("@"));

    if (emails.length === 0) return;

    try {
      const result = await inviteMembers({
        emails,
        role_id: selectedRoleId || undefined,
      });
      setInviteResult(result);
      setEmailInput("");
      if (result.invited.length > 0 && result.failed.length === 0) {
        setTimeout(() => {
          setInviteResult(null);
          setShowAddMember(false);
          setSelectedRoleId("");
        }, 3000);
      }
    } catch (error) {
      console.error("Failed to invite members:", error);
    }
  };

  const handleRemoveMember = async (developerId: string) => {
    if (confirm(t("permissions.confirmRemoveMember"))) {
      try {
        await removeMember(developerId);
      } catch (error) {
        console.error("Failed to remove member:", error);
      }
    }
  };

  const handleRoleChange = async (developerId: string, roleId: string | null) => {
    if (!canUseTeamFeatures) {
      setShowUpgradeModal(true);
      return;
    }
    try {
      await updateMember({
        developerId,
        data: { role_id: roleId || null },
      });
      setEditingMemberId(null);
      setEditingRoleId(null);
    } catch (error) {
      console.error("Failed to update role:", error);
    }
  };

  const isLoading = currentWorkspaceLoading || projectLoading || membersLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500 mx-auto mb-4"></div>
          <p className="text-foreground">{t("permissions.loading")}</p>
        </div>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <FolderKanban className="h-16 w-16 text-muted-foreground mx-auto mb-4" />
          <h3 className="text-xl font-medium text-foreground mb-2">
            {t("notFoundTitle")}
          </h3>
          <p className="text-muted-foreground mb-6">
            {t("permissions.notFoundDescription")}
          </p>
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
    <ProjectSettingsPage
      projectId={projectId}
      description={t("permissions.subtitle")}
    >

      <div>

        {/* Members Section */}
        <div className="bg-card rounded-xl">
          <div className="p-4 border-b border-border">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <h2 className="text-lg font-medium text-foreground flex items-center gap-2">
                <Users className="h-5 w-5 text-muted-foreground" />
                {t("permissions.membersHeading")}
              </h2>
              <span className="text-sm text-muted-foreground">{members.length} members</span>
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              {t("permissions.membersSubtitle")}
            </p>
          </div>

          {/* Members List */}
          <div className="divide-y divide-border/50">
            {members.map((member) => (
              <div
                key={member.id}
                className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-accent/30"
              >
                <div className="flex items-center gap-3">
                  {member.developer_avatar_url ? (
                    <Image
                      src={member.developer_avatar_url}
                      alt={member.developer_name || "Member"}
                      width={40}
                      height={40}
                      className="rounded-full"
                    />
                  ) : (
                    <div className="w-10 h-10 bg-muted rounded-full flex items-center justify-center">
                      <Users className="h-5 w-5 text-muted-foreground" />
                    </div>
                  )}
                  <div>
                    <span className="text-foreground font-medium">
                      {member.developer_name || member.developer_email || "Unknown"}
                    </span>
                    {member.developer_email && member.developer_name && (
                      <p className="text-sm text-muted-foreground">{member.developer_email}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {isAdmin ? (
                    editingMemberId === member.developer_id ? (
                      <div className="flex items-center gap-2">
                        <select
                          value={editingRoleId || ""}
                          onChange={(e) => setEditingRoleId(e.target.value || null)}
                          className="px-3 py-1.5 text-sm rounded bg-muted text-foreground border border-border focus:outline-none focus:border-primary-500"
                        >
                          <option value="">{t("permissions.useOrgRoleInherited")}</option>
                          {roles.map((role) => (
                            <option key={role.id} value={role.id}>
                              {role.name}
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={() => handleRoleChange(member.developer_id, editingRoleId)}
                          disabled={isUpdating}
                          className="p-1.5 text-green-400 hover:bg-accent rounded transition"
                          title={tc("save")}
                        >
                          <Check className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            setEditingMemberId(null);
                            setEditingRoleId(null);
                          }}
                          className="p-1.5 text-muted-foreground hover:bg-accent rounded transition"
                          title={tc("cancel")}
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => {
                          if (!canUseTeamFeatures) {
                            setShowUpgradeModal(true);
                            return;
                          }
                          setEditingMemberId(member.developer_id);
                          setEditingRoleId(member.role_id);
                        }}
                        className={`px-3 py-1.5 text-sm rounded flex items-center gap-2 ${getRoleBadgeColor(
                          member.role_name
                        )} hover:opacity-80 transition`}
                      >
                        {member.role_name || "Org role"}
                        {canUseTeamFeatures ? (
                          <ChevronDown className="h-3 w-3" />
                        ) : (
                          <Crown className="h-3 w-3 text-amber-500" />
                        )}
                      </button>
                    )
                  ) : (
                    <span
                      className={`px-3 py-1.5 rounded text-sm ${getRoleBadgeColor(
                        member.role_name
                      )}`}
                    >
                      {member.role_name || "Member"}
                    </span>
                  )}
                  {isAdmin && (
                    <button
                      onClick={() => handleRemoveMember(member.developer_id)}
                      className="p-1.5 text-muted-foreground hover:text-red-400 hover:bg-accent rounded transition"
                      title={t("permissions.removeFromProject")}
                    >
                      <UserMinus className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
            {members.length === 0 && (
              <div className="p-8 text-center text-muted-foreground">
                {t("permissions.noMembers")}
              </div>
            )}
          </div>

          {/* Add Member */}
          {isAdmin && (
            <div className="p-4 border-t border-border">
              {showAddMember ? (
                <div className="space-y-4">
                  {/* Mode Tabs */}
                  <div className="flex gap-2 p-1 bg-muted/50 rounded-lg">
                    <button
                      onClick={() => {
                        setAddMode("workspace");
                        setInviteResult(null);
                      }}
                      className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition flex items-center justify-center gap-2 ${
                        addMode === "workspace"
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <UserPlus className="h-4 w-4" />
                      {t("permissions.addFromWorkspace")}
                    </button>
                    <button
                      onClick={() => {
                        setAddMode("email");
                        setInviteResult(null);
                      }}
                      className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition flex items-center justify-center gap-2 ${
                        addMode === "email"
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <Mail className="h-4 w-4" />
                      {t("permissions.inviteByEmail")}
                    </button>
                  </div>

                  {addMode === "workspace" ? (
                    <>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs text-muted-foreground mb-1">{t("permissions.memberLabel")}</label>
                          <select
                            value={selectedDeveloperId}
                            onChange={(e) => setSelectedDeveloperId(e.target.value)}
                            className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground text-sm focus:outline-none focus:border-primary-500"
                          >
                            <option value="">{t("permissions.selectMember")}</option>
                            {availableMembers.map((wm) => (
                              <option key={wm.developer_id} value={wm.developer_id}>
                                {wm.developer_name || wm.developer_email || "Unknown"}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs text-muted-foreground mb-1">
                            {t("permissions.projectRoleOptional")}
                          </label>
                          <select
                            value={selectedRoleId}
                            onChange={(e) => setSelectedRoleId(e.target.value)}
                            className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground text-sm focus:outline-none focus:border-primary-500"
                          >
                            <option value="">{t("permissions.useOrganizationRole")}</option>
                            {roles.map((role) => (
                              <option key={role.id} value={role.id}>
                                {role.name}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={handleAddMember}
                          disabled={!selectedDeveloperId || isAdding}
                          className="flex-1 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                          {isAdding ? (
                            <>
                              <RefreshCw className="h-4 w-4 animate-spin" />
                              {t("permissions.adding")}
                            </>
                          ) : (
                            <>
                              <Plus className="h-4 w-4" />
                              {t("permissions.addMember")}
                            </>
                          )}
                        </button>
                        <button
                          onClick={() => {
                            setShowAddMember(false);
                            setSelectedDeveloperId("");
                            setSelectedRoleId("");
                          }}
                          className="px-4 py-2 bg-muted hover:bg-accent text-foreground rounded-lg text-sm transition"
                        >
                          {tc("cancel")}
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="space-y-3">
                        <div>
                          <label className="block text-xs text-muted-foreground mb-1">
                            {t("permissions.emailsLabel")}
                          </label>
                          <textarea
                            value={emailInput}
                            onChange={(e) => setEmailInput(e.target.value)}
                            placeholder="user@example.com, another@example.com"
                            rows={3}
                            className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground text-sm focus:outline-none focus:border-primary-500 placeholder:text-muted-foreground resize-none"
                          />
                          <p className="text-xs text-muted-foreground mt-1">
                            {t("permissions.guestNote")}
                          </p>
                        </div>
                        <div>
                          <label className="block text-xs text-muted-foreground mb-1">
                            {t("permissions.projectRoleOptional")}
                          </label>
                          <select
                            value={selectedRoleId}
                            onChange={(e) => setSelectedRoleId(e.target.value)}
                            className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground text-sm focus:outline-none focus:border-primary-500"
                          >
                            <option value="">{t("permissions.useDefaultRole")}</option>
                            {roles.map((role) => (
                              <option key={role.id} value={role.id}>
                                {role.name}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>

                      {/* Invite Result */}
                      {inviteResult && (
                        <div className="space-y-2">
                          {inviteResult.invited.length > 0 && (
                            <div className="flex items-start gap-2 p-3 bg-green-50 dark:bg-green-900/20 border border-green-800/50 rounded-lg">
                              <CheckCircle className="h-4 w-4 text-green-400 mt-0.5 shrink-0" />
                              <div>
                                <p className="text-sm text-green-400 font-medium">
                                  Successfully invited {inviteResult.invited.length} member(s)
                                </p>
                                <p className="text-xs text-green-400/70 mt-1">
                                  {inviteResult.invited.join(", ")}
                                </p>
                              </div>
                            </div>
                          )}
                          {inviteResult.already_members.length > 0 && (
                            <div className="flex items-start gap-2 p-3 bg-muted/50 border border-border rounded-lg">
                              <Users className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                              <div>
                                <p className="text-sm text-foreground">
                                  Already members: {inviteResult.already_members.length}
                                </p>
                                <p className="text-xs text-muted-foreground mt-1">
                                  {inviteResult.already_members.join(", ")}
                                </p>
                              </div>
                            </div>
                          )}
                          {inviteResult.failed.length > 0 && (
                            <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-800/50 rounded-lg">
                              <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
                              <div>
                                <p className="text-sm text-red-400 font-medium">
                                  Failed to invite {inviteResult.failed.length} user(s)
                                </p>
                                <ul className="text-xs text-red-400/70 mt-1 space-y-1">
                                  {inviteResult.failed.map((f, i) => (
                                    <li key={i}>
                                      {f.email}: {f.reason}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      <div className="flex items-center gap-2">
                        <button
                          onClick={handleInviteByEmail}
                          disabled={!emailInput.trim() || isInviting}
                          className="flex-1 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                          {isInviting ? (
                            <>
                              <RefreshCw className="h-4 w-4 animate-spin" />
                              {t("permissions.inviting")}
                            </>
                          ) : (
                            <>
                              <Mail className="h-4 w-4" />
                              {t("permissions.sendInvites")}
                            </>
                          )}
                        </button>
                        <button
                          onClick={() => {
                            setShowAddMember(false);
                            setEmailInput("");
                            setSelectedRoleId("");
                            setInviteResult(null);
                          }}
                          className="px-4 py-2 bg-muted hover:bg-accent text-foreground rounded-lg text-sm transition"
                        >
                          {tc("cancel")}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <button
                  onClick={() => setShowAddMember(true)}
                  className="w-full px-4 py-2 border border-dashed border-border hover:border-border text-muted-foreground hover:text-foreground rounded-lg text-sm transition flex items-center justify-center gap-2"
                >
                  <Plus className="h-4 w-4" />
                  {t("permissions.addMember")}
                </button>
              )}
            </div>
          )}
        </div>

        {/* Roles Info */}
        <div className="bg-card rounded-xl p-6 mt-6">
          <h2 className="text-lg font-medium text-foreground mb-4 flex items-center gap-2">
            <Shield className="h-5 w-5 text-muted-foreground" />
            {t("permissions.aboutRoles")}
          </h2>
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>
              Project-specific roles allow you to grant different permissions within this
              project than a member has at the organization level.
            </p>
            <p>
              <strong className="text-foreground">{t("permissions.inheritanceLabel")}</strong> If no project role is
              assigned, the member uses their organization role permissions.
            </p>
            <p>
              <strong className="text-foreground">{t("permissions.overrideLabel")}</strong> When a project role is
              assigned, it completely replaces the organization role for this project only.
            </p>
          </div>
          <div className="mt-4 pt-4 border-t border-border">
            <Link
              href="/settings/organization/roles"
              className="text-sm text-primary-400 hover:text-primary-300 transition"
            >
              {t("permissions.manageOrgRoles")}
            </Link>
          </div>
        </div>
      </div>

      {/* Premium Upgrade Modal */}
      {showUpgradeModal && (
        <UpgradeModal feature="team_features" onClose={() => setShowUpgradeModal(false)} />
      )}
    </ProjectSettingsPage>
  );
}
