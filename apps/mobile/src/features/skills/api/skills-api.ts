import { apiService } from "@/lib/api";

export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  version?: string;
  author?: string;
  tags?: string[];
}

export interface SkillsResponse {
  skills: Skill[];
  total: number;
}

export interface DiscoverSkillsResponse {
  skills: Skill[];
  total: number;
}

export async function discoverSkills(): Promise<Skill[]> {
  try {
    const response =
      await apiService.get<DiscoverSkillsResponse>("/skills/discover");
    return response.skills;
  } catch (error) {
    console.error("Error discovering skills:", error);
    return [];
  }
}

export async function getSkills(): Promise<Skill[]> {
  try {
    const response = await apiService.get<SkillsResponse>("/skills");
    return response.skills;
  } catch (error) {
    console.error("Error fetching skills:", error);
    return [];
  }
}

export async function enableSkill(id: string): Promise<boolean> {
  try {
    await apiService.post(`/skills/${id}/enable`);
    return true;
  } catch (error) {
    console.error("Error enabling skill:", error);
    return false;
  }
}

export async function disableSkill(id: string): Promise<boolean> {
  try {
    await apiService.post(`/skills/${id}/disable`);
    return true;
  } catch (error) {
    console.error("Error disabling skill:", error);
    return false;
  }
}

export async function deleteSkill(id: string): Promise<boolean> {
  try {
    await apiService.delete(`/skills/${id}`);
    return true;
  } catch (error) {
    console.error("Error deleting skill:", error);
    return false;
  }
}

export const skillsApi = {
  discoverSkills,
  getSkills,
  enableSkill,
  disableSkill,
  deleteSkill,
};
