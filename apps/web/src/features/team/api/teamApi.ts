import { apiauth } from "@/lib/api/client";

/**
 * KNOWN BROKEN: no /api/v1/team route exists, so every call here 404s and the
 * blog editor's author picker never populates. It is also why this is the one
 * caller left on raw axios — the path-typed client has no schema path to accept.
 * Resolving it (grow the route, or delete this and the picker) is a product call.
 */

export interface TeamMember {
  id: string;
  name: string;
  role: string;
  avatar?: string;
  linkedin?: string;
  twitter?: string;
}

export const teamApi = {
  getTeamMembers: async (): Promise<TeamMember[]> => {
    const response = await apiauth.get<TeamMember[]>("/team");
    return response.data;
  },
};
