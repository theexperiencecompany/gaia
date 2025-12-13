import { apiauth } from "@/lib/api";

export const handleGoogleLogin = () => {
  window.location.href = `${apiauth.getUri()}oauth/login/google`;
};
