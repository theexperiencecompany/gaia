import { apiBaseUrl } from "@/lib/api/client";

export const handleAuthLogin = () => {
  window.location.href = `${apiBaseUrl}/oauth/login/workos`;
};
