"use client";

import {
  Headphones,
  TrendingUp,
  Calendar,
  UserPlus,
  Users,
  Newspaper,
  Sparkles,
  Bot,
  LucideIcon,
} from "lucide-react";
import { AgentType, getAgentTypeConfig } from "@/lib/api";
import { cn } from "@/lib/utils";

const iconMap: Record<string, LucideIcon> = {
  headphones: Headphones,
  "trending-up": TrendingUp,
  calendar: Calendar,
  "user-plus": UserPlus,
  users: Users,
  newspaper: Newspaper,
  sparkles: Sparkles,
  bot: Bot,
};

interface AgentTypeBadgeProps {
  type: AgentType;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
  className?: string;
}

export function AgentTypeBadge({
  type,
  size = "md",
  showLabel = true,
  className,
}: AgentTypeBadgeProps) {
  const config = getAgentTypeConfig(type);
  const Icon = iconMap[config.icon] || Sparkles;

  const sizeClasses = {
    sm: "text-xs px-2 py-0.5",
    md: "text-sm px-2.5 py-1",
    lg: "text-base px-3 py-1.5",
  };

  const iconSizes = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium",
        sizeClasses[size],
        className
      )}
      style={{
        backgroundColor: `${config.color}20`,
        color: config.color,
      }}
    >
      <Icon className={iconSizes[size]} />
      {showLabel && <span>{config.label}</span>}
    </span>
  );
}

interface AgentTypeIconProps {
  type: AgentType;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
}

export function AgentTypeIcon({ type, size = "md", className }: AgentTypeIconProps) {
  const config = getAgentTypeConfig(type);
  const Icon = iconMap[config.icon] || Sparkles;

  const sizeClasses = {
    sm: "h-4 w-4",
    md: "h-5 w-5",
    lg: "h-6 w-6",
    xl: "h-8 w-8",
  };

  return (
    <Icon
      className={cn(sizeClasses[size], className)}
      style={{ color: config.color }}
    />
  );
}
