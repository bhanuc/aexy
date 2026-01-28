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
  LayoutGrid,
  Bug,
  Target,
  Rocket,
  Map,
  BookOpen,
  Clock,
  AlertTriangle,
} from "lucide-react";
import {
  publicProjectApi,
  PublicProject,
  PublicTaskItem,
  PublicStoryItem,
  PublicBugItem,
  PublicGoalItem,
  PublicReleaseItem,
  PublicRoadmapItem,
  PublicSprintItem,
  PublicBoardData,
  ProjectStatus,
} from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { AppShell } from "@/components/layout/AppShell";

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

const TAB_CONFIG = [
  { id: "overview", label: "Overview", icon: FolderKanban },
  { id: "backlog", label: "Backlog", icon: Layers },
  { id: "board", label: "Board", icon: LayoutGrid },
  { id: "stories", label: "Stories", icon: BookOpen },
  { id: "bugs", label: "Bugs", icon: Bug },
  { id: "goals", label: "Goals", icon: Target },
  { id: "releases", label: "Releases", icon: Rocket },
  { id: "roadmap", label: "Roadmap", icon: Map },
  { id: "sprints", label: "Sprints", icon: Calendar },
];

const PRIORITY_COLORS: Record<string, string> = {
  critical: "text-red-400 bg-red-900/30",
  high: "text-orange-400 bg-orange-900/30",
  medium: "text-yellow-400 bg-yellow-900/30",
  low: "text-slate-400 bg-slate-700",
};

const TASK_STATUS_COLORS: Record<string, string> = {
  todo: "bg-slate-600",
  in_progress: "bg-blue-500",
  review: "bg-purple-500",
  done: "bg-green-500",
  blocked: "bg-red-500",
};

// Tab Content Components
function OverviewTab({ project }: { project: PublicProject }) {
  return (
    <div className="space-y-6">
      {project.description && (
        <div className="bg-slate-800 rounded-xl p-6">
          <h2 className="text-lg font-medium text-white mb-3">About</h2>
          <p className="text-slate-300 whitespace-pre-wrap">{project.description}</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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
    </div>
  );
}

function BacklogTab({ publicSlug }: { publicSlug: string }) {
  const [tasks, setTasks] = useState<PublicTaskItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getBacklog(publicSlug).then(setTasks).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (tasks.length === 0) return <EmptyState message="No backlog items" />;

  return (
    <div className="space-y-3">
      {tasks.map((task) => (
        <div key={task.id} className="bg-slate-800 rounded-lg p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <h3 className="text-white font-medium">{task.title}</h3>
              {task.description && (
                <p className="text-slate-400 text-sm mt-1 line-clamp-2">{task.description}</p>
              )}
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${PRIORITY_COLORS[task.priority] || PRIORITY_COLORS.medium}`}>
                  {task.priority}
                </span>
                <span className="flex items-center gap-1 text-xs text-slate-500">
                  <span className={`w-2 h-2 rounded-full ${TASK_STATUS_COLORS[task.status] || TASK_STATUS_COLORS.todo}`} />
                  {task.status.replace("_", " ")}
                </span>
                {task.story_points && (
                  <span className="text-xs text-slate-500">{task.story_points} pts</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function BoardTab({ publicSlug }: { publicSlug: string }) {
  const [board, setBoard] = useState<PublicBoardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getBoard(publicSlug).then(setBoard).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (!board) return <EmptyState message="No board data" />;

  const columns = [
    { id: "todo", label: "To Do", color: "border-slate-500" },
    { id: "in_progress", label: "In Progress", color: "border-blue-500" },
    { id: "review", label: "Review", color: "border-purple-500" },
    { id: "done", label: "Done", color: "border-green-500" },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      {columns.map((column) => {
        const tasks = board[column.id as keyof PublicBoardData] || [];
        return (
          <div key={column.id} className={`bg-slate-800/50 rounded-lg p-3 border-t-2 ${column.color}`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-slate-300">{column.label}</h3>
              <span className="text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded-full">
                {tasks.length}
              </span>
            </div>
            <div className="space-y-2">
              {tasks.slice(0, 10).map((task) => (
                <div key={task.id} className="bg-slate-800 rounded-lg p-3">
                  <h4 className="text-sm text-white font-medium line-clamp-2">{task.title}</h4>
                  <div className="flex items-center gap-2 mt-2">
                    <span className={`px-1.5 py-0.5 rounded text-xs ${PRIORITY_COLORS[task.priority] || PRIORITY_COLORS.medium}`}>
                      {task.priority}
                    </span>
                    {task.story_points && (
                      <span className="text-xs text-slate-500">{task.story_points} pts</span>
                    )}
                  </div>
                </div>
              ))}
              {tasks.length > 10 && (
                <p className="text-xs text-slate-500 text-center py-2">+{tasks.length - 10} more</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StoriesTab({ publicSlug }: { publicSlug: string }) {
  const [stories, setStories] = useState<PublicStoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getStories(publicSlug).then(setStories).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (stories.length === 0) return <EmptyState message="No user stories" />;

  return (
    <div className="space-y-3">
      {stories.map((story) => (
        <div key={story.id} className="bg-slate-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <span className="text-xs font-mono text-slate-500 bg-slate-700 px-2 py-1 rounded">{story.key}</span>
            <div className="flex-1 min-w-0">
              <h3 className="text-white font-medium">{story.title}</h3>
              <p className="text-slate-400 text-sm mt-1">
                As a <span className="text-slate-300">{story.as_a}</span>, I want{" "}
                <span className="text-slate-300">{story.i_want}</span>
                {story.so_that && (
                  <>, so that <span className="text-slate-300">{story.so_that}</span></>
                )}
              </p>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${PRIORITY_COLORS[story.priority] || PRIORITY_COLORS.medium}`}>
                  {story.priority}
                </span>
                <span className="text-xs text-slate-500">{story.status.replace("_", " ")}</span>
                {story.story_points && (
                  <span className="text-xs text-slate-500">{story.story_points} pts</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function BugsTab({ publicSlug }: { publicSlug: string }) {
  const [bugs, setBugs] = useState<PublicBugItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getBugs(publicSlug).then(setBugs).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (bugs.length === 0) return <EmptyState message="No bugs reported" />;

  const severityColors: Record<string, string> = {
    blocker: "text-red-400 bg-red-900/30",
    critical: "text-red-400 bg-red-900/30",
    major: "text-orange-400 bg-orange-900/30",
    minor: "text-yellow-400 bg-yellow-900/30",
    trivial: "text-slate-400 bg-slate-700",
  };

  return (
    <div className="space-y-3">
      {bugs.map((bug) => (
        <div key={bug.id} className="bg-slate-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <span className="text-xs font-mono text-slate-500 bg-slate-700 px-2 py-1 rounded">{bug.key}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="text-white font-medium">{bug.title}</h3>
                {bug.is_regression && (
                  <span className="text-xs text-red-400 bg-red-900/30 px-1.5 py-0.5 rounded flex items-center gap-1">
                    <AlertTriangle className="h-3 w-3" />
                    Regression
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${severityColors[bug.severity] || severityColors.minor}`}>
                  {bug.severity}
                </span>
                <span className="text-xs text-slate-500">{bug.bug_type}</span>
                <span className="text-xs text-slate-500">{bug.status.replace("_", " ")}</span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function GoalsTab({ publicSlug }: { publicSlug: string }) {
  const [goals, setGoals] = useState<PublicGoalItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getGoals(publicSlug).then(setGoals).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (goals.length === 0) return <EmptyState message="No goals defined" />;

  return (
    <div className="space-y-3">
      {goals.map((goal) => (
        <div key={goal.id} className="bg-slate-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <span className="text-xs font-mono text-slate-500 bg-slate-700 px-2 py-1 rounded">{goal.key}</span>
            <div className="flex-1 min-w-0">
              <h3 className="text-white font-medium">{goal.title}</h3>
              {goal.description && (
                <p className="text-slate-400 text-sm mt-1 line-clamp-2">{goal.description}</p>
              )}
              <div className="mt-3">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-slate-400">Progress</span>
                  <span className="text-slate-300">{Math.round(goal.progress_percentage)}%</span>
                </div>
                <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary-500 rounded-full transition-all"
                    style={{ width: `${goal.progress_percentage}%` }}
                  />
                </div>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-xs text-slate-500">{goal.goal_type}</span>
                <span className="text-xs text-slate-500">{goal.status}</span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReleasesTab({ publicSlug }: { publicSlug: string }) {
  const [releases, setReleases] = useState<PublicReleaseItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getReleases(publicSlug).then(setReleases).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (releases.length === 0) return <EmptyState message="No releases" />;

  const statusColors: Record<string, string> = {
    planning: "text-slate-400 bg-slate-700",
    in_progress: "text-blue-400 bg-blue-900/30",
    code_freeze: "text-purple-400 bg-purple-900/30",
    testing: "text-yellow-400 bg-yellow-900/30",
    released: "text-green-400 bg-green-900/30",
    cancelled: "text-red-400 bg-red-900/30",
  };

  return (
    <div className="space-y-3">
      {releases.map((release) => (
        <div key={release.id} className="bg-slate-800 rounded-lg p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="text-white font-medium">{release.name}</h3>
                {release.version && (
                  <span className="text-xs font-mono text-slate-500 bg-slate-700 px-1.5 py-0.5 rounded">
                    v{release.version}
                  </span>
                )}
              </div>
              {release.description && (
                <p className="text-slate-400 text-sm mt-1 line-clamp-2">{release.description}</p>
              )}
              <div className="flex items-center gap-3 mt-2">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColors[release.status] || statusColors.planning}`}>
                  {release.status.replace("_", " ")}
                </span>
                {release.target_date && (
                  <span className="flex items-center gap-1 text-xs text-slate-500">
                    <Clock className="h-3 w-3" />
                    {new Date(release.target_date).toLocaleDateString()}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

const SPRINT_STATUS_COLORS: Record<string, string> = {
  planning: "bg-blue-500",
  active: "bg-green-500",
  review: "bg-amber-500",
  retrospective: "bg-purple-500",
  completed: "bg-slate-500",
};

function RoadmapTab({ publicSlug }: { publicSlug: string }) {
  const [sprints, setSprints] = useState<PublicRoadmapItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getRoadmap(publicSlug).then(setSprints).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (sprints.length === 0) return <EmptyState message="No sprints in the roadmap" />;

  // Calculate timeline range
  const now = new Date();
  const allDates = sprints.flatMap(s => [new Date(s.start_date), new Date(s.end_date)]);
  const minDate = new Date(Math.min(...allDates.map(d => d.getTime()), now.getTime()));
  const maxDate = new Date(Math.max(...allDates.map(d => d.getTime()), now.getTime()));

  // Add some padding
  minDate.setDate(minDate.getDate() - 7);
  maxDate.setDate(maxDate.getDate() + 14);

  const totalDays = (maxDate.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24);
  const todayOffset = ((now.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24) / totalDays) * 100;

  return (
    <div className="space-y-4">
      {/* Timeline header */}
      <div className="bg-slate-800 rounded-lg p-4">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
          <span>{minDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
          <span>Today</span>
          <span>{maxDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
        </div>
        <div className="relative h-2 bg-slate-700 rounded-full">
          {/* Today marker */}
          <div
            className="absolute top-0 w-0.5 h-4 -mt-1 bg-primary-500 z-10"
            style={{ left: `${todayOffset}%` }}
          />
        </div>
      </div>

      {/* Sprint bars */}
      <div className="space-y-3">
        {sprints.map((sprint) => {
          const startDate = new Date(sprint.start_date);
          const endDate = new Date(sprint.end_date);
          const startOffset = ((startDate.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24) / totalDays) * 100;
          const width = ((endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24) / totalDays) * 100;
          const completionRate = sprint.tasks_count > 0
            ? Math.round((sprint.completed_count / sprint.tasks_count) * 100)
            : 0;

          return (
            <div key={sprint.id} className="bg-slate-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className={`w-3 h-3 rounded-full ${SPRINT_STATUS_COLORS[sprint.status] || SPRINT_STATUS_COLORS.planning}`} />
                  <h3 className="text-white font-medium">{sprint.name}</h3>
                  <span className="text-xs text-slate-500 capitalize">{sprint.status}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span>{sprint.tasks_count} tasks</span>
                  <span>{sprint.total_points} pts</span>
                </div>
              </div>

              {sprint.goal && (
                <p className="text-slate-400 text-sm mb-3">{sprint.goal}</p>
              )}

              {/* Timeline bar */}
              <div className="relative h-8 bg-slate-700/50 rounded-lg overflow-hidden">
                <div
                  className={`absolute h-full rounded-lg ${SPRINT_STATUS_COLORS[sprint.status] || SPRINT_STATUS_COLORS.planning} ${sprint.status === "completed" ? "opacity-60" : ""}`}
                  style={{ left: `${Math.max(0, startOffset)}%`, width: `${Math.min(100 - startOffset, width)}%` }}
                >
                  {/* Progress inside */}
                  <div
                    className="absolute inset-y-0 left-0 bg-white/20 rounded-l-lg"
                    style={{ width: `${completionRate}%` }}
                  />
                  <div className="relative h-full flex items-center px-2">
                    <span className="text-xs text-white font-medium truncate">{completionRate}% complete</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between mt-2 text-xs text-slate-500">
                <span>{startDate.toLocaleDateString()}</span>
                <span>{endDate.toLocaleDateString()}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-4 pt-4">
        {Object.entries(SPRINT_STATUS_COLORS).map(([status, color]) => (
          <div key={status} className="flex items-center gap-1.5">
            <div className={`w-3 h-3 rounded ${color}`} />
            <span className="text-xs text-slate-400 capitalize">{status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SprintsTab({ publicSlug }: { publicSlug: string }) {
  const [sprints, setSprints] = useState<PublicSprintItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getSprints(publicSlug).then(setSprints).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (sprints.length === 0) return <EmptyState message="No sprints" />;

  return (
    <div className="space-y-3">
      {sprints.map((sprint) => {
        const completionRate = sprint.tasks_count > 0
          ? Math.round((sprint.completed_count / sprint.tasks_count) * 100)
          : 0;

        return (
          <div key={sprint.id} className="bg-slate-800 rounded-lg p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <div className={`w-3 h-3 rounded-full ${SPRINT_STATUS_COLORS[sprint.status] || SPRINT_STATUS_COLORS.planning}`} />
                  <h3 className="text-white font-medium">{sprint.name}</h3>
                </div>
                {sprint.goal && (
                  <p className="text-slate-400 text-sm mt-1 line-clamp-2">{sprint.goal}</p>
                )}
                <div className="mt-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-slate-400">
                      {sprint.completed_count}/{sprint.tasks_count} tasks
                    </span>
                    <span className="text-slate-300">{completionRate}%</span>
                  </div>
                  <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-500 rounded-full transition-all"
                      style={{ width: `${completionRate}%` }}
                    />
                  </div>
                </div>
                <div className="flex items-center gap-3 mt-2 flex-wrap">
                  <span className="text-xs text-slate-500 capitalize">{sprint.status}</span>
                  <span className="flex items-center gap-1 text-xs text-slate-500">
                    <Calendar className="h-3 w-3" />
                    {new Date(sprint.start_date).toLocaleDateString()} - {new Date(sprint.end_date).toLocaleDateString()}
                  </span>
                  <span className="text-xs text-slate-500">{sprint.total_points} pts</span>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-center py-12">
      <p className="text-slate-500">{message}</p>
    </div>
  );
}

export default function PublicProjectPage() {
  const params = useParams();
  const publicSlug = params.publicSlug as string;
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();

  const [project, setProject] = useState<PublicProject | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("overview");

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
      case "roadmap":
        return <RoadmapTab publicSlug={publicSlug} />;
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
