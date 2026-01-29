"use client";

import { Suspense, useState, useEffect } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { FolderKanban, Loader2, AlertCircle, Globe, ArrowLeft } from "lucide-react";
import { publicProjectApi, PublicProject } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { AppShell } from "@/components/layout/AppShell";
import { useQueryClient } from "@tanstack/react-query";
import {
  STATUS_COLORS,
  STATUS_LABELS,
  TAB_CONFIG,
  OverviewTab,
  BacklogTab,
  BoardTab,
  StoriesTab,
  BugsTab,
  GoalsTab,
  ReleasesTab,
  TimelineTab,
  RoadmapTab,
  SprintsTab,
} from "../../../components/public-project-page";

function PublicProjectContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const publicSlug = params.publicSlug as string;
  const queryClient = useQueryClient();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();

  const [project, setProject] = useState<PublicProject | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("overview");

  // Handle token from OAuth redirect
  useEffect(() => {
    const token = searchParams.get("token");
    if (token) {
      // Save token to localStorage
      localStorage.setItem("token", token);
      // Invalidate the user query to refresh auth state
      queryClient.invalidateQueries({ queryKey: ["currentUser"] });
      // Remove token from URL for cleanliness and security
      const url = new URL(window.location.href);
      url.searchParams.delete("token");
      window.history.replaceState({}, "", url.pathname);
    }
  }, [searchParams, queryClient]);

  useEffect(() => {
    const loadProject = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await publicProjectApi.getByPublicSlug(publicSlug);
        setProject(data);
      } catch {
        setError("Project not found or is not public.");
      } finally {
        setIsLoading(false);
      }
    };

    if (publicSlug) {
      loadProject();
    }
  }, [publicSlug]);

  // Loading state content
  const loadingContent = (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center">
      <div className="text-center">
        <Loader2 className="h-12 w-12 animate-spin text-primary-500 mx-auto mb-4" />
        <p className="text-slate-400">Loading project...</p>
      </div>
    </div>
  );

  // Error state content
  const errorContent = (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="text-center max-w-md">
        <AlertCircle className="h-16 w-16 text-red-500 mx-auto mb-4" />
        <h1 className="text-2xl font-bold text-white mb-2">Project Not Found</h1>
        <p className="text-slate-400 mb-6">
          {error || "The project you're looking for doesn't exist or is not publicly accessible."}
        </p>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition font-medium"
        >
          <ArrowLeft className="h-4 w-4" />
          Go Home
        </Link>
      </div>
    </div>
  );

  // Handle loading states
  if (isLoading || authLoading) {
    if (isAuthenticated && user) {
      return (
        <AppShell user={user} logout={logout}>
          {loadingContent}
        </AppShell>
      );
    }
    return loadingContent;
  }

  // Handle error states
  if (error || !project) {
    if (isAuthenticated && user) {
      return (
        <AppShell user={user} logout={logout}>
          {errorContent}
        </AppShell>
      );
    }
    return errorContent;
  }

  const statusStyle = STATUS_COLORS[project.status] || STATUS_COLORS.active;
  const enabledTabs = TAB_CONFIG.filter((tab) => project.public_tabs.includes(tab.id));

  const renderTabContent = () => {
    switch (activeTab) {
      case "overview":
        return <OverviewTab project={project} />;
      case "backlog":
        return <BacklogTab publicSlug={publicSlug} />;
      case "board":
        return <BoardTab publicSlug={publicSlug} />;
      case "stories":
        return <StoriesTab publicSlug={publicSlug} />;
      case "bugs":
        return <BugsTab publicSlug={publicSlug} />;
      case "goals":
        return <GoalsTab publicSlug={publicSlug} />;
      case "releases":
        return <ReleasesTab publicSlug={publicSlug} />;
      case "timeline":
        return <TimelineTab publicSlug={publicSlug} />;
      case "roadmap":
        return <RoadmapTab publicSlug={publicSlug} isAuthenticated={isAuthenticated} />;
      case "sprints":
        return <SprintsTab publicSlug={publicSlug} />;
      default:
        return <OverviewTab project={project} />;
    }
  };

  // Main page content
  const pageContent = (
    <div className={isAuthenticated ? "" : "min-h-screen bg-slate-900"}>
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-800/50">
        <div className="max-w-5xl mx-auto px-4 py-6">
          <div className="flex items-center gap-2 text-slate-400 text-sm mb-4">
            <Globe className="h-4 w-4" />
            <span>Public Project</span>
          </div>
          <div className="flex items-start gap-4">
            <div
              className="p-3 rounded-xl flex-shrink-0"
              style={{ backgroundColor: project.color + "20" }}
            >
              <FolderKanban
                className="h-8 w-8"
                style={{ color: project.color }}
              />
            </div>
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-bold text-white mb-2">{project.name}</h1>
              <div className="flex items-center gap-3 flex-wrap">
                <span
                  className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium ${statusStyle.bg} ${statusStyle.text}`}
                >
                  <span className={`w-2 h-2 rounded-full ${statusStyle.dot}`} />
                  {STATUS_LABELS[project.status]}
                </span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Tabs */}
      {enabledTabs.length > 1 && (
        <div className="border-b border-slate-700 bg-slate-800/30">
          <div className="max-w-5xl mx-auto px-4">
            <div className="flex gap-1 overflow-x-auto py-2">
              {enabledTabs.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition ${
                      isActive
                        ? "bg-primary-600 text-white"
                        : "text-slate-400 hover:text-white hover:bg-slate-700"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    {tab.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <main className="max-w-5xl mx-auto px-4 py-8">
        {renderTabContent()}

        {/* Footer - only show for non-authenticated users */}
        {!isAuthenticated && (
          <div className="text-center text-slate-500 text-sm mt-12">
            <p>
              Powered by{" "}
              <Link href="/" className="text-primary-400 hover:text-primary-300 transition">
                Aexy
              </Link>
            </p>
          </div>
        )}
      </main>
    </div>
  );

  // Return with or without AppShell based on authentication
  if (isAuthenticated && user) {
    return (
      <AppShell user={user} logout={logout}>
        {pageContent}
      </AppShell>
    );
  }

  return pageContent;
}

export default function PublicProjectPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-900 flex items-center justify-center">
          <div className="text-center">
            <Loader2 className="h-12 w-12 animate-spin text-primary-500 mx-auto mb-4" />
            <p className="text-slate-400">Loading project...</p>
          </div>
        </div>
      }
    >
      <PublicProjectContent />
    </Suspense>
  );
}
