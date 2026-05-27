export interface DemoProject {
  id: string;
  name: string;
  color: string;
}

export interface DemoSubTask {
  id: string;
  title: string;
  completed: boolean;
}

export interface DemoWorkflowStep {
  id: string;
  title: string;
  description: string;
  category: string;
}

export interface DemoTodo {
  id: string;
  title: string;
  description?: string;
  priority: "high" | "medium" | "low" | "none";
  labels: string[];
  project_id: string;
  due_date?: string;
  completed: boolean;
  subtasks: DemoSubTask[];
  workflow_categories: string[];
  workflow_steps: DemoWorkflowStep[];
  created_at: string;
}
