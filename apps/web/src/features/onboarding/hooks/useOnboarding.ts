import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { useFetchIntegrationStatus } from "@/features/integrations";
import {
  ANALYTICS_EVENTS,
  trackEvent,
  trackOnboardingComplete,
  trackOnboardingStep,
} from "@/lib/analytics";
import { apiService } from "@/lib/api";
import { toast } from "@/lib/toast";
import { batchSyncConversations } from "@/services/syncService";

import { FIELD_NAMES, professionOptions, questions } from "../constants";
import type { Message, OnboardingState } from "../types";

const ONBOARDING_STORAGE_KEY = "gaia-onboarding-state";

export const useOnboarding = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useUser();
  const { setUser } = useUserActions();
  const [isInitialized, setIsInitialized] = useState(false);
  const onboardingStartTracked = useRef(false);
  const processingStarted = useRef(false);
  const pendingDataRef = useRef<{
    responses: Record<string, string>;
  } | null>(null);

  const { refetch: refetchIntegrationStatus } = useFetchIntegrationStatus({
    refetchOnMount: "always",
  });

  const [onboardingState, setOnboardingState] = useState<OnboardingState>(
    () => {
      if (typeof window !== "undefined") {
        try {
          const saved = sessionStorage.getItem(ONBOARDING_STORAGE_KEY);
          if (saved) {
            const parsed = JSON.parse(saved) as OnboardingState & {
              isProcessingPhase?: boolean;
            };
            if (parsed.messages && Array.isArray(parsed.messages)) {
              return { ...parsed, isProcessingPhase: false };
            }
          }
        } catch (error) {
          console.error("Failed to restore onboarding state:", error);
        }
      }

      return {
        messages: [],
        currentQuestionIndex: 0,
        currentInputs: {
          text: "",
          selectedProfession: null,
        },
        userResponses: {},
        isProcessing: false,
        isProcessingPhase: false,
        hasGmail: false,
        hasAnsweredCurrentQuestion: false,
      };
    },
  );

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    if (!onboardingStartTracked.current) {
      trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED, {
        has_saved_state: onboardingState.messages.length > 0,
      });
      onboardingStartTracked.current = true;
    }
  }, []);

  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      onboardingState.messages.length > 0 &&
      !onboardingState.isProcessingPhase
    ) {
      try {
        sessionStorage.setItem(
          ONBOARDING_STORAGE_KEY,
          JSON.stringify(onboardingState),
        );
      } catch (error) {
        console.error("Failed to save onboarding state:", error);
      }
    }
  }, [onboardingState]);

  const _submitOnboardingToBackend = useCallback(
    async (responses: Record<string, string>) => {
      try {
        const onboardingData = {
          name: responses[FIELD_NAMES.NAME]?.trim() || "",
          profession: responses[FIELD_NAMES.PROFESSION] || "",
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          company_url: responses[FIELD_NAMES.COMPANY_URL] || undefined,
        };

        const response = await authApi.completeOnboarding(onboardingData);

        if (response?.success && response.user) {
          setUser({
            userId: response.user.user_id,
            name: response.user.name,
            email: response.user.email,
            profilePicture: response.user.picture,
            timezone: response.user.timezone,
            onboarding: response.user.onboarding,
            selected_model: response.user.selected_model,
          });

          try {
            await batchSyncConversations();
          } catch {
            // non-blocking
          }

          trackOnboardingComplete({
            profession: responses[FIELD_NAMES.PROFESSION],
            totalSteps: questions.length + 1,
          });
        }
      } catch (error: unknown) {
        const err = error as { response?: { status?: number } };
        if (err?.response?.status === 409) {
          // Already onboarded — proceed anyway
        } else {
          console.error("Onboarding submission failed:", error);
        }
      }
    },
    [setUser],
  );

  // When isProcessingPhase becomes true, submit to backend
  useEffect(() => {
    if (
      onboardingState.isProcessingPhase &&
      pendingDataRef.current &&
      !processingStarted.current
    ) {
      processingStarted.current = true;
      const { responses } = pendingDataRef.current;
      pendingDataRef.current = null;
      void _submitOnboardingToBackend(responses);
    }
  }, [onboardingState.isProcessingPhase, _submitOnboardingToBackend]);

  useEffect(() => {
    scrollToBottom();
  }, [onboardingState.messages]);

  useEffect(() => {
    if (
      !onboardingState.isProcessing &&
      !onboardingState.hasAnsweredCurrentQuestion &&
      !onboardingState.isProcessingPhase
    ) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 500);
    }
  }, [
    onboardingState.isProcessing,
    onboardingState.hasAnsweredCurrentQuestion,
    onboardingState.isProcessingPhase,
  ]);

  const getDisplayText = useCallback(
    (fieldName: string, value: string): string => {
      switch (fieldName) {
        case FIELD_NAMES.PROFESSION:
          return (
            professionOptions.find((p) => p.value === value)?.label || value
          );
        default:
          return value;
      }
    },
    [],
  );

  const submitResponse = useCallback(
    (responseText: string, rawValue?: string) => {
      if (
        onboardingState.isProcessing ||
        onboardingState.currentQuestionIndex >= questions.length
      )
        return;

      const currentQuestion = questions[onboardingState.currentQuestionIndex];

      trackOnboardingStep(
        onboardingState.currentQuestionIndex + 1,
        currentQuestion.fieldName,
        {
          response_value: rawValue ?? responseText,
          question_id: currentQuestion.id,
        },
      );

      const isLastQuestion =
        onboardingState.currentQuestionIndex === questions.length - 1;
      const isGmailQuestion = currentQuestion.fieldName === FIELD_NAMES.GMAIL;
      const gmailConnected = isGmailQuestion && rawValue === "connected";

      if (isLastQuestion) {
        // Store pending data before state update
        const newResponses = {
          ...onboardingState.userResponses,
          [currentQuestion.fieldName]:
            rawValue !== undefined ? rawValue : responseText,
        };
        pendingDataRef.current = {
          responses: newResponses,
        };

        const userMessage: Message = {
          id: `user-${Date.now()}`,
          type: "user",
          content: responseText,
        };

        const processingMsg: Message = {
          id: "processing",
          type: "bot",
          content:
            "Give me a moment. I'm going through your inbox and setting things up.",
        };

        // Clear session storage before entering processing phase
        if (typeof window !== "undefined") {
          sessionStorage.removeItem(ONBOARDING_STORAGE_KEY);
        }

        setOnboardingState((prev) => ({
          ...prev,
          messages: [...prev.messages, userMessage, processingMsg],
          userResponses: newResponses,
          currentInputs: { text: "", selectedProfession: null },
          isProcessing: false,
          isProcessingPhase: true,
          hasGmail: gmailConnected,
          hasAnsweredCurrentQuestion: true,
          currentQuestionIndex: questions.length,
        }));

        return;
      }

      setOnboardingState((prev) => {
        const userMessage: Message = {
          id: `user-${Date.now()}`,
          type: "user",
          content: responseText,
        };

        const newResponses = {
          ...prev.userResponses,
          [currentQuestion.fieldName]:
            rawValue !== undefined ? rawValue : responseText,
        };

        const nextIndex = prev.currentQuestionIndex + 1;
        const nextQuestion = questions[nextIndex];

        let botContent = nextQuestion.question;
        if (prev.currentQuestionIndex === 0) {
          const firstName = (rawValue ?? responseText).split(" ")[0];
          botContent = `Nice to meet you, ${firstName}!<NEW_MESSAGE_BREAK>${nextQuestion.question}`;
        }

        const botMessage: Message = {
          id: nextQuestion.id,
          type: "bot",
          content: botContent,
        };

        return {
          ...prev,
          messages: [...prev.messages, userMessage, botMessage],
          currentQuestionIndex: nextIndex,
          userResponses: newResponses,
          currentInputs: { text: "", selectedProfession: null },
          isProcessing: false,
          hasAnsweredCurrentQuestion: false,
        };
      });
    },
    [
      onboardingState.isProcessing,
      onboardingState.currentQuestionIndex,
      onboardingState.userResponses,
    ],
  );

  // Handle OAuth success/error from URL parameters
  useEffect(() => {
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthError = searchParams.get("oauth_error");

    if (oauthSuccess === "true") {
      toast.success("Gmail connected!");
      refetchIntegrationStatus();
      const url = new URL(window.location.href);
      url.searchParams.delete("oauth_success");
      window.history.replaceState({}, "", url.toString());
      // Advance past the Gmail step now that OAuth succeeded
      submitResponse("Connected", "connected");
    } else if (oauthError) {
      switch (oauthError) {
        case "cancelled":
          toast.error("Connection cancelled. You can try again anytime.");
          break;
        default:
          toast.error("Connection failed. Please try again.");
      }
      const url = new URL(window.location.href);
      url.searchParams.delete("oauth_error");
      window.history.replaceState({}, "", url.toString());
    }
  }, [searchParams, refetchIntegrationStatus, submitResponse]);

  // Called when Gmail OAuth succeeds
  const handleGmailConnect = useCallback(() => {
    const gmailIndex = questions.findIndex(
      (q) => q.fieldName === FIELD_NAMES.GMAIL,
    );
    if (onboardingState.currentQuestionIndex !== gmailIndex) return;
    if (onboardingState.hasAnsweredCurrentQuestion) return;
    submitResponse("Connected", "connected");
  }, [
    onboardingState.currentQuestionIndex,
    onboardingState.hasAnsweredCurrentQuestion,
    submitResponse,
  ]);

  // Called when user skips Gmail
  const handleGmailSkip = useCallback(() => {
    submitResponse("Skip for now", "skipped");
  }, [submitResponse]);

  const handleChipSelect = useCallback(
    (questionId: string, chipValue: string) => {
      if (
        onboardingState.isProcessing ||
        onboardingState.hasAnsweredCurrentQuestion
      )
        return;

      const currentQuestion = questions[onboardingState.currentQuestionIndex];

      if (currentQuestion.id !== questionId) return;

      const selectedChip = currentQuestion.chipOptions?.find(
        (option) => option.value === chipValue,
      );
      if (selectedChip) {
        if (chipValue === "skip") {
          trackEvent(ANALYTICS_EVENTS.ONBOARDING_SKIPPED, {
            step: onboardingState.currentQuestionIndex,
            question_id: questionId,
          });
          submitResponse("Skipped", "");
        } else {
          submitResponse(selectedChip.label, chipValue);
        }
      }
    },
    [
      onboardingState.isProcessing,
      onboardingState.currentQuestionIndex,
      onboardingState.hasAnsweredCurrentQuestion,
      submitResponse,
    ],
  );

  const handleProfessionSelect = useCallback(
    (professionKey: React.Key | null) => {
      if (
        onboardingState.isProcessing ||
        !professionKey ||
        typeof professionKey !== "string" ||
        !professionKey.trim()
      )
        return;

      const professionLabel = getDisplayText("profession", professionKey);
      submitResponse(professionLabel, professionKey);
    },
    [onboardingState.isProcessing, submitResponse, getDisplayText],
  );

  const handleProfessionInputChange = useCallback(
    (value: string) => {
      if (!onboardingState.isProcessing) {
        setOnboardingState((prev) => ({
          ...prev,
          currentInputs: {
            ...prev.currentInputs,
            selectedProfession: value,
          },
        }));
      }
    },
    [onboardingState.isProcessing],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      if (!onboardingState.isProcessing) {
        setOnboardingState((prev) => ({
          ...prev,
          currentInputs: {
            ...prev.currentInputs,
            text: value,
          },
        }));
      }
    },
    [onboardingState.isProcessing],
  );

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();

      if (onboardingState.currentQuestionIndex >= questions.length) return;

      const currentQuestion = questions[onboardingState.currentQuestionIndex];

      if (currentQuestion.fieldName === FIELD_NAMES.PROFESSION) return;
      if (currentQuestion.fieldName === FIELD_NAMES.GMAIL) return;

      const text = onboardingState.currentInputs.text.trim();
      if (text || currentQuestion.optional) {
        submitResponse(text || "", text || undefined);
      }
    },
    [
      onboardingState.currentQuestionIndex,
      onboardingState.currentInputs.text,
      submitResponse,
    ],
  );

  // Skip optional field (company_url)
  const handleSkip = useCallback(() => {
    submitResponse("Skip", "");
  }, [submitResponse]);

  // Called by processing component when intelligence is complete
  const handleConversationReady = useCallback(
    async (conversationId: string) => {
      try {
        await apiService.post("/onboarding/phase", {
          phase: "getting_started",
        });
      } catch {
        // non-blocking
      }

      setTimeout(() => {
        router.push(`/c/${conversationId}`);
      }, 500);
    },
    [router],
  );

  // Initialize — also handle resume if backend is already processing
  useEffect(() => {
    if (isInitialized || onboardingState.messages.length > 0) return;

    // If onboarding was already submitted and backend is processing, resume into processing phase
    if (
      user.onboarding?.completed &&
      user.onboarding.phase &&
      user.onboarding.phase !== "completed" &&
      user.onboarding.phase !== "getting_started"
    ) {
      const processingMsg: Message = {
        id: "processing",
        type: "bot",
        content:
          "Give me a moment. I'm going through your inbox and setting things up.",
      };

      setOnboardingState((prev) => ({
        ...prev,
        messages: [processingMsg],
        currentQuestionIndex: questions.length,
        isProcessingPhase: true,
        hasGmail: false, // Will be resolved by backend
      }));
      processingStarted.current = true;
      setIsInitialized(true);
      return;
    }

    const firstQuestion = questions[0];
    const userName = user.name || "";

    setOnboardingState((prev) => ({
      ...prev,
      messages: [
        {
          id: firstQuestion.id,
          type: "bot",
          content: firstQuestion.question,
        },
      ],
      currentInputs: {
        ...prev.currentInputs,
        text: firstQuestion.fieldName === FIELD_NAMES.NAME ? userName : "",
      },
    }));

    setIsInitialized(true);
  }, [
    isInitialized,
    onboardingState.messages.length,
    user.name,
    user.onboarding,
  ]);

  const handleRestart = useCallback(() => {
    if (typeof window !== "undefined") {
      sessionStorage.removeItem(ONBOARDING_STORAGE_KEY);
    }

    processingStarted.current = false;
    pendingDataRef.current = null;

    const firstQuestion = questions[0];
    const userName = user.name || "";

    setOnboardingState({
      messages: [
        {
          id: firstQuestion.id,
          type: "bot",
          content: firstQuestion.question,
        },
      ],
      currentQuestionIndex: 0,
      currentInputs: {
        text: firstQuestion.fieldName === FIELD_NAMES.NAME ? userName : "",
        selectedProfession: null,
      },
      userResponses: {},
      isProcessing: false,
      isProcessingPhase: false,
      hasGmail: false,
      hasAnsweredCurrentQuestion: false,
    });

    setIsInitialized(true);
  }, [user.name]);

  return {
    onboardingState,
    messagesEndRef,
    inputRef,
    handleChipSelect,
    handleProfessionSelect,
    handleProfessionInputChange,
    handleInputChange,
    handleSubmit,
    handleSkip,
    handleGmailConnect,
    handleGmailSkip,
    handleConversationReady,
    handleRestart,
  };
};
