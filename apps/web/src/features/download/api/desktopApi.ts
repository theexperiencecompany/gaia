import { api } from "@/lib/api/typed";

export const desktopApi = {
  getLatestRelease: () => api.get("/api/v1/desktop/releases/latest"),
};
