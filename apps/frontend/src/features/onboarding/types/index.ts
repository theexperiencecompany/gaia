import type { UserInfo } from "@/features/auth/api/authApi";

export interface Message {
  id: string;
  type: "bot" | "user";
  content: string;
}

export interface Question {
  id: string;
  question: string;
  placeholder: string;
  fieldName: string;
  chipOptions?: { label: string; value: string }[];
}

export interface OnboardingState {
  messages: Message[];
  currentQuestionIndex: number;
  currentInputs: {
    text: string;
    selectedProfession: string | null;
  };
  userResponses: Record<string, string>;
  isProcessing: boolean;
  isOnboardingComplete: boolean;
  hasAnsweredCurrentQuestion: boolean;
}

export interface ProfessionOption {
  label: string;
  value: string;
}

export interface OnboardingResponse {
  success: boolean;
  message: string;
  user?: UserInfo;
}
