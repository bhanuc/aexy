"use client";

import { useState, useEffect } from "react";
import {
  ChevronUp,
  MessageSquare,
  Plus,
  Filter,
  Lightbulb,
  Zap,
  Link2,
  Bug,
  MoreHorizontal,
  CheckCircle2,
  Clock,
  XCircle,
  Loader2,
  Send,
  Github,
  ArrowRight,
} from "lucide-react";
import {
  publicProjectApi,
  RoadmapRequest,
  RoadmapComment,
  RoadmapCategory,
  RoadmapStatus,
} from "@/lib/api";
import { LoadingSpinner, EmptyState } from "./shared";
import { GoogleIcon } from "@/app/page";

interface RoadmapTabProps {
  publicSlug: string;
  isAuthenticated?: boolean;
}

const CATEGORY_CONFIG: Record<RoadmapCategory, { label: string; icon: typeof Lightbulb; color: string }> = {
  feature: { label: "Feature", icon: Lightbulb, color: "text-blue-400 bg-blue-900/30" },
  improvement: { label: "Improvement", icon: Zap, color: "text-yellow-400 bg-yellow-900/30" },
  integration: { label: "Integration", icon: Link2, color: "text-purple-400 bg-purple-900/30" },
  bug_fix: { label: "Bug Fix", icon: Bug, color: "text-red-400 bg-red-900/30" },
  other: { label: "Other", icon: MoreHorizontal, color: "text-slate-400 bg-slate-700" },
};

const STATUS_CONFIG: Record<RoadmapStatus, { label: string; icon: typeof Clock; color: string }> = {
  under_review: { label: "Under Review", icon: Clock, color: "text-slate-400" },
  planned: { label: "Planned", icon: CheckCircle2, color: "text-blue-400" },
  in_progress: { label: "In Progress", icon: Loader2, color: "text-yellow-400" },
  completed: { label: "Completed", icon: CheckCircle2, color: "text-green-400" },
  declined: { label: "Declined", icon: XCircle, color: "text-red-400" },
};
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getLoginUrls() {
  const redirectUrl = typeof window !== "undefined" ? window.location.href : "";
  const encodedRedirect = encodeURIComponent(redirectUrl);
  return {
    github: `${API_BASE_URL}/auth/github/login?redirect_url=${encodedRedirect}`,
    google: `${API_BASE_URL}/auth/google/login?redirect_url=${encodedRedirect}`,
  };
}
function RequestCard({
  request,
  isAuthenticated,
  onVote,
  onOpenComments,
}: {
  request: RoadmapRequest;
  isAuthenticated: boolean;
  onVote: () => void;
  onOpenComments: () => void;
}) {
  const category = CATEGORY_CONFIG[request.category as RoadmapCategory] || CATEGORY_CONFIG.other;
  const status = STATUS_CONFIG[request.status as RoadmapStatus] || STATUS_CONFIG.under_review;
  const CategoryIcon = category.icon;
  const StatusIcon = status.icon;

  return (
    <div className="bg-slate-800 rounded-lg p-4">
      <div className="flex gap-4">
        {/* Vote button */}
        <button
          onClick={onVote}
          disabled={!isAuthenticated}
          className={`flex flex-col items-center justify-center min-w-[60px] p-2 rounded-lg border transition ${
            request.has_voted
              ? "bg-primary-600/20 border-primary-500 text-primary-400"
              : "bg-slate-700/50 border-slate-600 text-slate-400 hover:border-slate-500"
          } ${!isAuthenticated ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
          title={isAuthenticated ? (request.has_voted ? "Remove vote" : "Upvote") : "Login to vote"}
        >
          <ChevronUp className={`h-5 w-5 ${request.has_voted ? "text-primary-400" : ""}`} />
          <span className="text-sm font-semibold">{request.vote_count}</span>
        </button>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <h3 className="text-white font-medium">{request.title}</h3>
              {request.description && (
                <p className="text-slate-400 text-sm mt-1 line-clamp-2">{request.description}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 mt-3 flex-wrap">
            {/* Category badge */}
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${category.color}`}>
              <CategoryIcon className="h-3 w-3" />
              {category.label}
            </span>

            {/* Status badge */}
            <span className={`inline-flex items-center gap-1 text-xs ${status.color}`}>
              <StatusIcon className={`h-3 w-3 ${request.status === "in_progress" ? "animate-spin" : ""}`} />
              {status.label}
            </span>

            {/* Comments */}
            <button
              onClick={onOpenComments}
              className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition"
            >
              <MessageSquare className="h-3 w-3" />
              {request.comment_count} comments
            </button>

            {/* Submitter */}
            <span className="text-xs text-slate-500">
              by {request.submitted_by.name || "Anonymous"}
            </span>

            {/* Date */}
            <span className="text-xs text-slate-500">
              {new Date(request.created_at).toLocaleDateString()}
            </span>
          </div>

          {/* Admin response */}
          {request.admin_response && (
            <div className="mt-3 p-3 bg-slate-700/50 rounded-lg border-l-2 border-primary-500">
              <p className="text-xs text-primary-400 font-medium mb-1">Official Response</p>
              <p className="text-sm text-slate-300">{request.admin_response}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CommentsModal({
  request,
  publicSlug,
  isAuthenticated,
  onClose,
}: {
  request: RoadmapRequest;
  publicSlug: string;
  isAuthenticated: boolean;
  onClose: () => void;
}) {
  const [comments, setComments] = useState<RoadmapComment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [newComment, setNewComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const loginUrls = getLoginUrls();

  useEffect(() => {
    publicProjectApi
      .getRoadmapComments(publicSlug, request.id)
      .then(setComments)
      .finally(() => setIsLoading(false));
  }, [publicSlug, request.id]);

  const handleSubmitComment = async () => {
    if (!newComment.trim() || !isAuthenticated) return;

    setIsSubmitting(true);
    try {
      const comment = await publicProjectApi.createRoadmapComment(publicSlug, request.id, newComment);
      setComments([...comments, comment]);
      setNewComment("");
    } catch (error) {
      console.error("Failed to submit comment:", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-xl max-w-2xl w-full max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-slate-700">
          <h3 className="text-lg font-medium text-white">{request.title}</h3>
          <p className="text-sm text-slate-400 mt-1">{request.vote_count} votes · {comments.length} comments</p>
        </div>

        {/* Comments list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          ) : comments.length === 0 ? (
            <p className="text-center text-slate-500 py-8">No comments yet. Be the first to comment!</p>
          ) : (
            comments.map((comment) => (
              <div
                key={comment.id}
                className={`p-3 rounded-lg ${comment.is_admin_response ? "bg-primary-900/20 border border-primary-700/50" : "bg-slate-700/50"}`}
              >
                <div className="flex items-center gap-2 mb-2">
                  {comment.author.avatar_url ? (
                    <img src={comment.author.avatar_url} alt="" className="w-6 h-6 rounded-full" />
                  ) : (
                    <div className="w-6 h-6 rounded-full bg-slate-600 flex items-center justify-center text-xs text-slate-300">
                      {(comment.author.name || "A")[0].toUpperCase()}
                    </div>
                  )}
                  <span className="text-sm font-medium text-white">{comment.author.name || "Anonymous"}</span>
                  {comment.is_admin_response && (
                    <span className="text-xs text-primary-400 bg-primary-900/50 px-1.5 py-0.5 rounded">Admin</span>
                  )}
                  <span className="text-xs text-slate-500">{new Date(comment.created_at).toLocaleDateString()}</span>
                </div>
                <p className="text-sm text-slate-300">{comment.content}</p>
              </div>
            ))
          )}
        </div>

        {/* Comment input */}
        <div className="p-4 border-t border-slate-700">
          {isAuthenticated ? (
            <div className="flex gap-2">
              <input
                type="text"
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                placeholder="Add a comment..."
                className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-primary-500"
                onKeyDown={(e) => e.key === "Enter" && handleSubmitComment()}
              />
              <button
                onClick={handleSubmitComment}
                disabled={!newComment.trim() || isSubmitting}
                className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition"
              >
                {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </button>
            </div>
          ) : (
            <div className="flex flex-col sm:flex-row justify-center gap-4">
              <a
                href={loginUrls.google}
                className="group relative overflow-hidden bg-white text-black p-2 rounded-full text-sm font-semibold transition-all hover:scale-105 hover:shadow-[0_0_40px_rgba(255,255,255,0.3)] flex items-center justify-center gap-3"
              >
                <GoogleIcon />
                Continue with Google
                <ArrowRight className="h-5 w-5 group-hover:translate-x-1 transition-transform" />
              </a>
              <a
                href={loginUrls.github}
                className="group bg-white/5 hover:bg-white/10 text-white p-2 rounded-full text-sm font-semibold transition-all border border-white/10 hover:border-white/20 flex items-center justify-center gap-3"
              >
                <Github className="h-5 w-5" />
                Continue with GitHub
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CreateRequestModal({
  publicSlug,
  onClose,
  onCreated,
}: {
  publicSlug: string;
  onClose: () => void;
  onCreated: (request: RoadmapRequest) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<RoadmapCategory>("feature");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!title.trim()) {
      setError("Title is required");
      return;
    }

    setIsSubmitting(true);
    setError("");

    try {
      const request = await publicProjectApi.createRoadmapRequest(publicSlug, {
        title: title.trim(),
        description: description.trim() || undefined,
        category,
      });
      onCreated(request);
      onClose();
    } catch (err) {
      setError("Failed to create request. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-xl max-w-lg w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-slate-700">
          <h3 className="text-lg font-medium text-white">Submit a Request</h3>
          <p className="text-sm text-slate-400 mt-1">Share your idea with the community</p>
        </div>

        <div className="p-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-sm text-red-400">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Title *</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Brief description of your request"
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder:text-slate-500 focus:outline-none focus:border-primary-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Provide more details about your request..."
              rows={3}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder:text-slate-500 focus:outline-none focus:border-primary-500 resize-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Category</label>
            <div className="grid grid-cols-2 gap-2">
              {(Object.entries(CATEGORY_CONFIG) as [RoadmapCategory, typeof CATEGORY_CONFIG.feature][]).map(
                ([key, config]) => {
                  const Icon = config.icon;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setCategory(key)}
                      className={`flex items-center gap-2 p-2 rounded-lg border text-sm transition ${
                        category === key
                          ? "bg-primary-600/20 border-primary-500 text-white"
                          : "bg-slate-700/50 border-slate-600 text-slate-400 hover:border-slate-500"
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                      {config.label}
                    </button>
                  );
                }
              )}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-slate-700 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-slate-400 hover:text-white transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-lg transition"
          >
            {isSubmitting ? "Submitting..." : "Submit Request"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function RoadmapTab({ publicSlug, isAuthenticated = false }: RoadmapTabProps) {
  const [requests, setRequests] = useState<RoadmapRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [sortBy, setSortBy] = useState<"votes" | "newest" | "oldest">("votes");
  const [statusFilter, setStatusFilter] = useState<RoadmapStatus | "">("");
  const [categoryFilter, setCategoryFilter] = useState<RoadmapCategory | "">("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedRequest, setSelectedRequest] = useState<RoadmapRequest | null>(null);
  const loginUrls = getLoginUrls();
  

  const loadRequests = async () => {
    setIsLoading(true);
    try {
      const data = await publicProjectApi.getRoadmapRequests(publicSlug, {
        sortBy,
        status: statusFilter || undefined,
        category: categoryFilter || undefined,
      });
      setRequests(data);
    } catch (error) {
      console.error("Failed to load roadmap requests:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadRequests();
  }, [publicSlug, sortBy, statusFilter, categoryFilter]);

  const handleVote = async (request: RoadmapRequest) => {
    if (!isAuthenticated) return;

    try {
      const result = await publicProjectApi.voteRoadmapRequest(publicSlug, request.id);
      setRequests((prev) =>
        prev.map((r) =>
          r.id === request.id
            ? { ...r, vote_count: result.vote_count, has_voted: result.has_voted }
            : r
        )
      );
    } catch (error) {
      console.error("Failed to vote:", error);
    }
  };

  const handleCreated = (newRequest: RoadmapRequest) => {
    setRequests((prev) => [newRequest, ...prev]);
  };

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Sort */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-primary-500"
          >
            <option value="votes">Most Voted</option>
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
          </select>

          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as RoadmapStatus | "")}
            className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-primary-500"
          >
            <option value="">All Statuses</option>
            {(Object.entries(STATUS_CONFIG) as [RoadmapStatus, typeof STATUS_CONFIG.under_review][]).map(
              ([key, config]) => (
                <option key={key} value={key}>
                  {config.label}
                </option>
              )
            )}
          </select>

          {/* Category filter */}
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value as RoadmapCategory | "")}
            className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-primary-500"
          >
            <option value="">All Categories</option>
            {(Object.entries(CATEGORY_CONFIG) as [RoadmapCategory, typeof CATEGORY_CONFIG.feature][]).map(
              ([key, config]) => (
                <option key={key} value={key}>
                  {config.label}
                </option>
              )
            )}
          </select>
        </div>

        {/* Create button */}
        {isAuthenticated ? (
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition"
          >
            <Plus className="h-4 w-4" />
            Submit Request
          </button>
        ) : (
           <div className="flex flex-col sm:flex-row justify-center gap-4">
              <a
                href={loginUrls.google}
                className="group relative overflow-hidden bg-white text-black p-2 rounded-full text-sm font-semibold transition-all hover:scale-105 hover:shadow-[0_0_40px_rgba(255,255,255,0.3)] flex items-center justify-center gap-3"
              >
                <GoogleIcon />
                Continue with Google
                <ArrowRight className="h-5 w-5 group-hover:translate-x-1 transition-transform" />
              </a>
              <a
                href={loginUrls.github}
                className="group bg-white/5 hover:bg-white/10 text-white p-2 rounded-full text-sm font-semibold transition-all border border-white/10 hover:border-white/20 flex items-center justify-center gap-3"
              >
                <Github className="h-5 w-5" />
                Continue with GitHub
              </a>
            </div>
        )}
      </div>

      {/* Requests list */}
      {requests.length === 0 ? (
        <EmptyState message="No requests yet. Be the first to submit one!" />
      ) : (
        <div className="space-y-3">
          {requests.map((request) => (
            <RequestCard
              key={request.id}
              request={request}
              isAuthenticated={isAuthenticated}
              onVote={() => handleVote(request)}
              onOpenComments={() => setSelectedRequest(request)}
            />
          ))}
        </div>
      )}

      {/* Status legend */}
      <div className="flex items-center justify-center gap-4 pt-4 flex-wrap">
        {(Object.entries(STATUS_CONFIG) as [RoadmapStatus, typeof STATUS_CONFIG.under_review][]).map(
          ([key, config]) => {
            const Icon = config.icon;
            return (
              <div key={key} className={`flex items-center gap-1.5 ${config.color}`}>
                <Icon className="h-3 w-3" />
                <span className="text-xs">{config.label}</span>
              </div>
            );
          }
        )}
      </div>

      {/* Modals */}
      {showCreateModal && (
        <CreateRequestModal
          publicSlug={publicSlug}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleCreated}
        />
      )}

      {selectedRequest && (
        <CommentsModal
          request={selectedRequest}
          publicSlug={publicSlug}
          isAuthenticated={isAuthenticated}
          onClose={() => setSelectedRequest(null)}
        />
      )}
    </div>
  );
}
