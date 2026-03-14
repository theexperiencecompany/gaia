import { apiauth } from "@/lib/api/client";

export const handleAuthLogin = () => {
  window.location.href = `${apiauth.getUri()}oauth/login/workos`;
};
