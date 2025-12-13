import type React from "react";

import type { Goal as ApiGoal } from "@/types/api/goalsApiTypes";

// Re-export API types for consistency
export type Goal = ApiGoal;

// Extend the API Goal type for chat-specific use cases
export interface GoalNode {
  id: string;
  data: {
    title?: string;
    label?: string;
    isComplete?: boolean;
    type?: string;
    subtask_id?: string;
  };
}

export interface GoalStats {
  total_goals: number;
  goals_with_roadmaps: number;
  total_tasks: number;
  completed_tasks: number;
  overall_completion_rate: number;
  active_goals: Array<{
    id: string;
    title: string;
    progress: number;
  }>;
  active_goals_count: number;
}

export type GoalAction =
  | "create"
  | "list"
  | "get"
  | "delete"
  | "search"
  | "stats"
  | "creating"
  | "fetching"
  | "deleting"
  | "updating_progress"
  | "generating_roadmap"
  | "roadmap_generated"
  | "roadmap_needed"
  | "node_updated"
  | "error";

export interface GoalSectionProps {
  goals?: Goal[];
  stats?: GoalStats;
  action?: GoalAction;
  message?: string;
  goal_id?: string;
  deleted_goal_id?: string;
  error?: string;
}

export interface GoalCardContainerProps {
  variant?: "default" | "create" | "compact";
  children: React.ReactNode;
  onClick?: () => void;
  className?: string;
}

export interface GoalCardHeaderProps {
  title: string;
  variant?: "default" | "create" | "compact";
  icon?: React.ReactNode;
  subtitle?: string;
  progress?: number;
  showExpandToggle?: boolean;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

export interface GoalCardContentProps {
  description?: string;
  progress?: number;
  metadata?: React.ReactNode;
  expandedContent?: React.ReactNode;
  isExpanded?: boolean;
  variant?: "default" | "create" | "compact";
  showProgress?: boolean;
  title?: string; // For create variant
}

export interface GoalCardActionsProps {
  variant?: "default" | "create" | "compact";
  onViewGoal?: () => void;
  onViewTasks?: () => void;
  showViewTasks?: boolean;
  className?: string;
}

export interface GoalCardProps {
  goal: Goal;
  variant?: "default" | "create" | "compact";
  showActions?: boolean;
  showExpandToggle?: boolean;
  isExpanded?: boolean;
  onToggleExpand?: (goalId: string) => void;
  onViewGoal?: (goalId: string) => void;
  onViewTasks?: (projectId: string) => void;
}
