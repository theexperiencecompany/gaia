import { api } from "@/lib/api";

export interface TeamMember {
  id: string;
  name: string;
  role: string;
  avatar?: string;
  linkedin?: string;
  twitter?: string;
}

export interface TeamMemberCreate {
  name: string;
  role: string;
  avatar?: string;
  linkedin?: string;
  twitter?: string;
}

export interface TeamMemberUpdate {
  name?: string;
  role?: string;
  avatar?: string;
  linkedin?: string;
  twitter?: string;
}

export const teamApi = {
  getTeamMembers: async (): Promise<TeamMember[]> => {
    const response = await api.get<TeamMember[]>("/team");
    return response.data;
  },

  getTeamMember: async (id: string): Promise<TeamMember> => {
    const response = await api.get<TeamMember>(`/team/${id}`);
    return response.data;
  },

  createTeamMember: async (member: TeamMemberCreate): Promise<TeamMember> => {
    const response = await api.post<TeamMember>("/team", member);
    return response.data;
  },

  updateTeamMember: async (
    id: string,
    member: TeamMemberUpdate,
  ): Promise<TeamMember> => {
    const response = await api.put<TeamMember>(`/team/${id}`, member);
    return response.data;
  },

  deleteTeamMember: async (id: string): Promise<void> => {
    await api.delete(`/team/${id}`);
  },
};
