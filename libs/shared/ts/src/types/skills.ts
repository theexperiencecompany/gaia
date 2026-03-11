export type SkillStatus = "enabled" | "disabled" | "available";

export interface SkillTool {
  name: string;
  description: string;
  enabled?: boolean;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  category?: string;
  status: SkillStatus;
  tools?: SkillTool[];
  createdAt?: string;
}

export interface SkillCreate {
  name: string;
  description: string;
  category?: string;
}

export interface DiscoverSkillsResponse {
  skills: Skill[];
  total: number;
}
