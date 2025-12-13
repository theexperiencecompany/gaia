"use client";

import { handleGoogleLogin } from "@/features/auth/hooks/handleGoogleLogin";

// Shared function for login/signup button click
export function handleAuthButtonClick(setLoading: (loading: boolean) => void) {
  setLoading(true);
  handleGoogleLogin();
}
