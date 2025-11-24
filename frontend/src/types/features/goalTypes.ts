// Legacy goal types - Use API types instead for new code
import type { Goal as ApiGoal } from "@/types/api/goalsApiTypes";

// For backward compatibility, export a GoalData type that extends the API Goal
export interface GoalData extends ApiGoal {
  created_at: string; // This component expects Date objects
}

export interface EdgeType extends Record<string, unknown> {
  id: string;
  source: string;
  target: string;
}

export interface NodeType {
  id: string;
  position?: { x: number; y: number };
  data: NodeData;
}

export interface NodeData extends Record<string, unknown> {
  id: string;
  goalId?: string;
  title?: string;
  label?: string;
  details?: string[];
  estimatedTime?: string[];
  resources?: string[];
  isComplete?: boolean;
  type?: string;
  subtask_id?: string;
}
