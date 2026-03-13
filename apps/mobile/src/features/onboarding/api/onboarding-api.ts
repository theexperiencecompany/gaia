import { apiService } from "@/lib/api";
import type { OnboardingStatus } from "../types";

export const getOnboardingStatus = () =>
  apiService.get<OnboardingStatus>("/onboarding/status");

export const updateOnboardingPhase = (phase: string, completed: boolean) =>
  apiService.post("/onboarding/phase", { phase, completed });
