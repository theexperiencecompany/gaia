// Goal API Types - These match the backend GoalResponse model and goal_helper output

export interface GoalRoadmap {
  title?: string;
  description?: string;
  nodes?: Array<{
    id: string;
    position?: { x: number; y: number };
    data: {
      id?: string;
      title?: string;
      label?: string;
      details?: string[];
      estimatedTime?: string[];
      resources?: string[];
      isComplete?: boolean;
      type?: string;
      subtask_id?: string;
      goalId?: string;
    };
  }>;
  edges?: Array<{
    id: string;
    source: string;
    target: string;
  }>;
}

export interface Goal {
  id: string;
  title: string;
  description?: string;
  created_at?: string;
  progress?: number;
  user_id?: string;
  todo_project_id?: string;
  todo_id?: string;
  roadmap?: GoalRoadmap;
}

export interface GoalCreate {
  title: string;
  description?: string;
}

export interface GoalUpdate {
  title?: string;
  description?: string;
  status?: string;
  roadmap?: GoalRoadmap;
}
