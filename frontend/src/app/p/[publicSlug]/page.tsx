"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  FolderKanban,
  Users,
  Layers,
  Calendar,
  Loader2,
  AlertCircle,
  Globe,
  ArrowLeft,
} from "lucide-react";
import { publicProjectApi, PublicProject, ProjectStatus } from "@/lib/api";

const STATUS_COLORS: Record<ProjectStatus, { bg: string; text: string; dot: string }> = {
  active: { bg: "bg-green-500/10", text: "text-green-400", dot: "bg-green-500" },
  on_hold: { bg: "bg-amber-500/10", text: "text-amber-400", dot: "bg-amber-500" },
  completed: { bg: "bg-blue-500/10", text: "text-blue-400", dot: "bg-blue-500" },
  archived: { bg: "bg-slate-500/10", text: "text-slate-400", dot: "bg-slate-500" },
};

const STATUS_LABELS: Record<ProjectStatus, string> = {
  active: "Active",
  on_hold: "On Hold",
  completed: "Completed",
  archived: "Archived",
};

export default function PublicProjectPage() {
  const params = useParams();
  const publicSlug = params.publicSlug as string;

  const [project, setProject] = useState<PublicProject | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadProject = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await publicProjectApi.getByPublicSlug(publicSlug);
        setProject(data);
      } catch (err) {
        setError("Project not found or is not public.");
      } finally {
        setIsLoading(false);
      }
    };

    if (publicSlug) {
      loadProject();
    }
  }, [publicSlug]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-12 w-12 animate-spin text-primary-500 mx-auto mb-4" />
          <p className="text-slate-400">Loading project...</p>
        </div>
      </div>
    );
  }

  if (error || !project) {
    return (
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
  }

  const statusStyle = STATUS_COLORS[project.status] || STATUS_COLORS.active;

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-800/50">
        <div className="max-w-4xl mx-auto px-4 py-6">
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

      <main className="max-w-4xl mx-auto px-4 py-8">
        {/* Description */}
        {project.description && (
          <div className="bg-slate-800 rounded-xl p-6 mb-6">
            <h2 className="text-lg font-medium text-white mb-3">About</h2>
            <p className="text-slate-300 whitespace-pre-wrap">{project.description}</p>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div className="bg-slate-800 rounded-xl p-6">
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 bg-blue-500/10 rounded-lg">
                <Users className="h-5 w-5 text-blue-400" />
              </div>
              <span className="text-slate-400 text-sm">Members</span>
            </div>
            <p className="text-2xl font-bold text-white">{project.member_count}</p>
          </div>

          <div className="bg-slate-800 rounded-xl p-6">
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 bg-purple-500/10 rounded-lg">
                <Layers className="h-5 w-5 text-purple-400" />
              </div>
              <span className="text-slate-400 text-sm">Teams</span>
            </div>
            <p className="text-2xl font-bold text-white">{project.team_count}</p>
          </div>

          <div className="bg-slate-800 rounded-xl p-6">
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 bg-green-500/10 rounded-lg">
                <Calendar className="h-5 w-5 text-green-400" />
              </div>
              <span className="text-slate-400 text-sm">Created</span>
            </div>
            <p className="text-2xl font-bold text-white">
              {new Date(project.created_at).toLocaleDateString("en-US", {
                month: "short",
                year: "numeric",
              })}
            </p>
          </div>
        </div>

        {/* Project Info */}
        <div className="bg-slate-800 rounded-xl p-6">
          <h2 className="text-lg font-medium text-white mb-4">Project Details</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-400">Project Slug</dt>
              <dd className="text-white font-mono">{project.slug}</dd>
            </div>
            {project.public_slug && (
              <div className="flex justify-between">
                <dt className="text-slate-400">Public URL</dt>
                <dd className="text-primary-400 font-mono">
                  /p/{project.public_slug}
                </dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-slate-400">Status</dt>
              <dd className={`flex items-center gap-1.5 ${statusStyle.text}`}>
                <span className={`w-2 h-2 rounded-full ${statusStyle.dot}`} />
                {STATUS_LABELS[project.status]}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-400">Created</dt>
              <dd className="text-white">
                {new Date(project.created_at).toLocaleDateString("en-US", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </dd>
            </div>
          </dl>
        </div>

        {/* Footer */}
        <div className="text-center text-slate-500 text-sm mt-8">
          <p>
            Powered by{" "}
            <Link href="/" className="text-primary-400 hover:text-primary-300 transition">
              Aexy
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
