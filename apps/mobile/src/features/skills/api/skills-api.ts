import type { Schema } from "@gaia/shared/api/generated";
import { apiService } from "@/lib/api";

export type Skill = Schema<"Skill">;

export interface SkillsResponse {
  skills: Skill[];
  total: number;
}

export type DiscoverSkillsResponse = Schema<"DiscoverSkillsResponse">;

export type DiscoveredSkill = Schema<"DiscoveredSkillInfo">;

export async function discoverSkills(): Promise<DiscoveredSkill[]> {
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
