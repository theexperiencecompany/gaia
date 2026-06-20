import { api } from "@/lib/api/client";
import type { DesktopRelease } from "../types";

export const desktopApi = {
  getLatestRelease: async (): Promise<DesktopRelease> => {
    const response = await api.get<DesktopRelease>("/desktop/releases/latest");
    return response.data;
  },
};
