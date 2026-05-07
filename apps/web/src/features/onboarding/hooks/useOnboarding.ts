import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { useFetchIntegrationStatus } from "@/features/integrations/hooks/useIntegrations";
import {
  ANALYTICS_EVENTS,
  trackEvent,
  trackOnboardingComplete,
  trackOnboardingStep,
} from "@/lib/analytics";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";
import { batchSyncConversations } from "@/services/syncService";

import { FIELD_NAMES, professionOptions, questions } from "../constants";
import {
  FOCUS_QUESTION,
  PROCESSING_MSG_FOCUS,
  PROCESSING_MSG_GMAIL,
  PROCESSING_MSG_NO_GMAIL,
} from "../constants/messages";
import type { Message, OnboardingState } from "../types";

const ONBOARDING_STORAGE_KEY = "gaia-onboarding-state";

export const useOnboarding = (skipAutoRedirect?: boolean) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useUser();
  const { setUser, updateUser } = useUserActions();
  const [isInitialized, setIsInitialized] = useState(false);
  const [submissionError, setSubmissionError] = useState(false);
  const onboardingStartTracked = useRef(false);
  const processingStarted = useRef(false);
  const [focusPending, setFocusPending] = useState(false);
  const pendingDataRef = useRef<{
    responses: Record<string, string>;
  } | null>(null);

  const { data: integrationStatus, refetch: refetchIntegrationStatus } =
    useFetchIntegrationStatus({
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

  const submitOnboardingToBackend = useCallback(
    async (responses: Record<string, string>) => {
      setSubmissionError(false);
      try {
        const onboardingData = {
          name: responses[FIELD_NAMES.NAME]?.trim() || "",
          profession: responses[FIELD_NAMES.PROFESSION] || "",
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          focus: responses[FIELD_NAMES.FOCUS] || "",
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
          setSubmissionError(true);
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
      void submitOnboardingToBackend(responses);
    }
  }, [onboardingState.isProcessingPhase, submitOnboardingToBackend]);

  useEffect(() => {
    scrollToBottom();
  }, [onboardingState.messages]);

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
        onboardingState.currentQuestionIndex >= questions.length &&
        !focusPending
      )
        return;

      // Handle the focus answer (submitted after Gmail skip, index is out of bounds)
      if (focusPending) {
        const newResponses = {
          ...onboardingState.userResponses,
          [FIELD_NAMES.FOCUS]: rawValue !== undefined ? rawValue : responseText,
        };
        setFocusPending(false);

        const userMessage: Message = {
          id: `user-${Date.now()}`,
          type: "user",
          content: responseText,
          questionFieldName: FIELD_NAMES.FOCUS,
        };

        const processingMsg: Message = {
          id: "processing",
          type: "bot",
          content: PROCESSING_MSG_FOCUS,
        };

        pendingDataRef.current = { responses: newResponses };

        if (typeof window !== "undefined") {
          sessionStorage.removeItem(ONBOARDING_STORAGE_KEY);
        }

        setOnboardingState((prev) => ({
          ...prev,
          messages: [...prev.messages, userMessage, processingMsg],
          userResponses: newResponses,
          currentInputs: { text: "", selectedProfession: null },
          isProcessingPhase: true,
          hasGmail: false,
          hasAnsweredCurrentQuestion: true,
          currentQuestionIndex: questions.length,
        }));

        return;
      }

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
        const newResponses = {
          ...onboardingState.userResponses,
          [currentQuestion.fieldName]:
            rawValue !== undefined ? rawValue : responseText,
        };

        const userMessage: Message = {
          id: `user-${Date.now()}`,
          type: "user",
          content: responseText,
          questionFieldName: currentQuestion.fieldName,
        };

        // When user skips Gmail, ask the focus question before processing
        if (isGmailQuestion && !gmailConnected && !focusPending) {
          setFocusPending(true);

          const focusQuestion: Message = {
            id: "focus-q",
            type: "bot",
            content: FOCUS_QUESTION,
          };

          setOnboardingState((prev) => ({
            ...prev,
            messages: [...prev.messages, userMessage, focusQuestion],
            userResponses: newResponses,
            currentInputs: { text: "", selectedProfession: null },
            hasAnsweredCurrentQuestion: false,
          }));
          return;
        }

        // Store pending data and enter processing phase
        pendingDataRef.current = { responses: newResponses };

        const processingMsg: Message = {
          id: "processing",
          type: "bot",
          content: gmailConnected
            ? PROCESSING_MSG_GMAIL
            : PROCESSING_MSG_NO_GMAIL,
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
          questionFieldName: currentQuestion.fieldName,
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
          hasAnsweredCurrentQuestion: false,
        };
      });
    },
    [
      onboardingState.currentQuestionIndex,
      onboardingState.userResponses,
      focusPending,
    ],
  );

  // Handle OAuth success/error from URL parameters
  useEffect(() => {
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthError = searchParams.get("oauth_error");

    if (oauthSuccess === "true") {
      toast.success("Gmail connected!");
      refetchIntegrationStatus();
      // Clean all OAuth/integration params from URL
      const url = new URL(window.location.href);
      url.searchParams.delete("oauth_success");
      url.searchParams.delete("integration");
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
      url.searchParams.delete("integration");
      window.history.replaceState({}, "", url.toString());
    }
  }, [searchParams, refetchIntegrationStatus, submitResponse]);

  // Auto-advance Gmail step if already connected (handles page refresh)
  const gmailAutoAdvanced = useRef(false);
  useEffect(() => {
    if (gmailAutoAdvanced.current) return;
    if (onboardingState.isProcessingPhase) return;

    const currentQuestion = questions[onboardingState.currentQuestionIndex];
    if (currentQuestion?.fieldName !== FIELD_NAMES.GMAIL) return;

    const gmailStatus = integrationStatus?.integrations?.find(
      (i: { integrationId: string }) => i.integrationId === "gmail",
    );
    if (gmailStatus?.connected) {
      gmailAutoAdvanced.current = true;
      submitResponse("Connected", "connected");
    }
  }, [
    integrationStatus,
    onboardingState.currentQuestionIndex,
    onboardingState.isProcessingPhase,
    submitResponse,
  ]);

  // Called when user skips Gmail
  const handleGmailSkip = useCallback(() => {
    submitResponse("Continue without Gmail", "skipped");
  }, [submitResponse]);

  const handleSkipSetup = useCallback(async () => {
    if (!onboardingState.userResponses[FIELD_NAMES.NAME]) return;

    const responses = { ...onboardingState.userResponses };
    // Default skipped fields
    if (!responses[FIELD_NAMES.PROFESSION])
      responses[FIELD_NAMES.PROFESSION] = "";
    if (!responses[FIELD_NAMES.GMAIL]) responses[FIELD_NAMES.GMAIL] = "skipped";

    pendingDataRef.current = { responses };

    if (typeof window !== "undefined") {
      sessionStorage.removeItem(ONBOARDING_STORAGE_KEY);
    }

    setOnboardingState((prev) => ({
      ...prev,
      messages: [
        ...prev.messages,
        {
          id: "processing",
          type: "bot" as const,
          content: PROCESSING_MSG_NO_GMAIL,
        },
      ],
      currentQuestionIndex: questions.length,
      isProcessingPhase: true,
      hasAnsweredCurrentQuestion: true,
      hasGmail: false,
    }));
  }, [onboardingState.userResponses]);

  const handleProfessionSelect = useCallback(
    (professionKey: React.Key | null) => {
      if (
        !professionKey ||
        typeof professionKey !== "string" ||
        !professionKey.trim()
      )
        return;

      const professionLabel = getDisplayText("profession", professionKey);
      submitResponse(professionLabel, professionKey);
    },
    [submitResponse, getDisplayText],
  );

  const handleProfessionInputChange = useCallback((value: string) => {
    setOnboardingState((prev) => ({
      ...prev,
      currentInputs: {
        ...prev.currentInputs,
        selectedProfession: value,
      },
    }));
  }, []);

  const handleInputChange = useCallback((value: string) => {
    setOnboardingState((prev) => ({
      ...prev,
      currentInputs: {
        ...prev.currentInputs,
        text: value,
      },
    }));
  }, []);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();

      // Handle focus answer submission (special case after gmail skip)
      if (focusPending) {
        const text = onboardingState.currentInputs.text.trim();
        if (text) {
          submitResponse(text, text);
        }
        return;
      }

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
      focusPending,
      onboardingState.currentQuestionIndex,
      onboardingState.currentInputs.text,
      submitResponse,
    ],
  );

  // Called by processing component when intelligence is complete
  const handleConversationReady = useCallback(
    async (conversationId: string) => {
      if (skipAutoRedirect) {
        // On /onboarding page: don't update phase or redirect — stay embedded
        return;
      }

      // Navigate first so the user is on the chat page before the phase
      // POST lands. If the user reloads during this window, the resume
      // logic in the init effect can otherwise mis-route them — by the
      // time the phase update sets `getting_started`, they're already on
      // /c/{conversationId} and the onboarding page is no longer the
      // active route.
      router.push(`/c/${conversationId}`);

      void apiService
        .post("/onboarding/phase", { phase: "getting_started" })
        .catch(() => {
          // non-blocking — phase tracking is bookkeeping, not critical
        });
    },
    [router, skipAutoRedirect],
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
        content: PROCESSING_MSG_GMAIL,
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

  const handleRetrySubmission = useCallback(() => {
    processingStarted.current = false;
    pendingDataRef.current = { responses: onboardingState.userResponses };
    setSubmissionError(false);

    // Re-trigger the submission effect
    const { responses } = pendingDataRef.current;
    pendingDataRef.current = null;
    processingStarted.current = true;
    void submitOnboardingToBackend(responses);
  }, [onboardingState.userResponses, submitOnboardingToBackend]);

  const [isRestarting, setIsRestarting] = useState(false);

  const handleRestart = useCallback(async (): Promise<void> => {
    if (isRestarting) return;
    setIsRestarting(true);

    // ── Optimistic local reset ──────────────────────────────────────────
    // The UI snaps to question 1 immediately so the user isn't waiting on
    // a network roundtrip. The backend reset runs in the background; the
    // restart button stays in its loading state until it resolves so the
    // user has feedback. If the backend call fails we surface a toast —
    // there's no clean rollback path (the user wanted to start over) and
    // `complete_onboarding` now overwrites stale state as a safety net.
    if (typeof window !== "undefined") {
      sessionStorage.removeItem(ONBOARDING_STORAGE_KEY);
    }

    processingStarted.current = false;
    pendingDataRef.current = null;
    gmailAutoAdvanced.current = false;
    onboardingStartTracked.current = false;

    // Clear backend-derived user.onboarding before resetting local state so
    // the init effect's resume-detection path can't race in between.
    updateUser({ onboarding: undefined });

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
      isProcessingPhase: false,
      hasGmail: false,
      hasAnsweredCurrentQuestion: false,
    });

    setIsInitialized(true);

    try {
      await apiService.post("/onboarding/reset", {}, { silent: true });
    } catch (error) {
      console.error("Failed to reset onboarding on server:", error);
      toast.error(
        "We reset locally, but the server reset didn't fully complete.",
      );
    } finally {
      setIsRestarting(false);
    }
  }, [isRestarting, user.name, updateUser]);

  return {
    onboardingState,
    submissionError,
    isFocusPending: focusPending,
    isRestarting,
    messagesEndRef,
    inputRef,
    handleProfessionSelect,
    handleProfessionInputChange,
    handleInputChange,
    handleSubmit,
    handleGmailSkip,
    handleSkipSetup,
    handleConversationReady,
    handleRetrySubmission,
    handleRestart,
  };
};
