import { apiauth } from "@/lib/api";

export const handleAuthLogin = () => {
  window.location.href = `${apiauth.getUri()}oauth/login/workos`;
};
