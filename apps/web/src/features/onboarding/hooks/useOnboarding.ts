import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { useFetchIntegrationStatus } from "@/features/integrations";
import {
  ANALYTICS_EVENTS,
  trackEvent,
  trackOnboardingComplete,
  trackOnboardingStep,
} from "@/lib/analytics";
import { batchSyncConversations } from "@/services/syncService";

import { FIELD_NAMES, professionOptions, questions } from "../constants";
import type { Message, OnboardingResponse, OnboardingState } from "../types";

const ONBOARDING_STORAGE_KEY = "gaia-onboarding-state";

export const useOnboarding = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useUser();
  const { setUser } = useUserActions();
  const [isInitialized, setIsInitialized] = useState(false);
  const onboardingStartTracked = useRef(false);

  // Force integration status refresh on this page to show connected state immediately
  const { refetch: refetchIntegrationStatus } = useFetchIntegrationStatus({
    refetchOnMount: "always",
  });

  const [onboardingState, setOnboardingState] = useState<OnboardingState>(
    () => {
      // Try to restore state from sessionStorage
      if (typeof window !== "undefined") {
        try {
          const saved = sessionStorage.getItem(ONBOARDING_STORAGE_KEY);
          if (saved) {
            const parsed = JSON.parse(saved);
            // Validate that saved state has required structure
            if (parsed.messages && Array.isArray(parsed.messages)) {
              return parsed;
            }
          }
        } catch (error) {
          console.error("Failed to restore onboarding state:", error);
        }
      }

      // Default initial state
      return {
        messages: [],
        currentQuestionIndex: 0,
        currentInputs: {
          text: "",
          selectedProfession: null,
        },
        userResponses: {},
        isProcessing: false,
        isOnboardingComplete: false,
        hasAnsweredCurrentQuestion: false,
      };
    },
  );

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Track onboarding start (only once per session)
  useEffect(() => {
    if (!onboardingStartTracked.current) {
      trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED, {
        has_saved_state: onboardingState.messages.length > 0,
      });
      onboardingStartTracked.current = true;
    }
  }, []);

  // Persist state to sessionStorage whenever it changes
  useEffect(() => {
    if (typeof window !== "undefined" && onboardingState.messages.length > 0) {
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

  // Handle OAuth success/error from URL parameters
  useEffect(() => {
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthError = searchParams.get("oauth_error");

    if (oauthSuccess === "true") {
      toast.success("Integration connected successfully!");
      // Refresh integration status to update button states
      refetchIntegrationStatus();
      // Clean up URL parameter
      const url = new URL(window.location.href);
      url.searchParams.delete("oauth_success");
      window.history.replaceState({}, "", url.toString());
    } else if (oauthError) {
      // Handle OAuth errors
      switch (oauthError) {
        case "cancelled":
          toast.error("Connection cancelled. You can try again anytime.");
          break;
        case "failed":
          toast.error("Connection failed. Please try again.");
          break;
        default:
          toast.error("Connection failed. Please try again.");
      }
      // Clean up URL parameter
      const url = new URL(window.location.href);
      url.searchParams.delete("oauth_error");
      window.history.replaceState({}, "", url.toString());
    }
  }, [searchParams, refetchIntegrationStatus]);

  useEffect(() => {
    scrollToBottom();
  }, [onboardingState.messages]);

  // Auto-focus input when a new question appears
  useEffect(() => {
    if (
      !onboardingState.isProcessing &&
      !onboardingState.hasAnsweredCurrentQuestion
    ) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 500);
    }
  }, [
    onboardingState.isProcessing,
    onboardingState.hasAnsweredCurrentQuestion,
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

      // Track step completion
      trackOnboardingStep(
        onboardingState.currentQuestionIndex + 1,
        currentQuestion.fieldName,
        {
          response_value: rawValue ?? responseText,
          question_id: currentQuestion.id,
        },
      );

      // First, add user message and update state
      setOnboardingState((prev) => {
        const newState = { ...prev };
        newState.isProcessing = true;
        newState.hasAnsweredCurrentQuestion = true;

        const userMessage: Message = {
          id: `user-${Date.now()}`,
          type: "user",
          content: responseText,
        };
        newState.messages = [...prev.messages, userMessage];

        const newResponses = {
          ...prev.userResponses,
          [currentQuestion.fieldName]:
            rawValue !== undefined ? rawValue : responseText,
        };
        newState.userResponses = newResponses;

        newState.currentInputs = {
          text: "",
          selectedProfession: null,
        };

        return newState;
      });

      setOnboardingState((prev) => {
        const newState = { ...prev };

        if (prev.currentQuestionIndex < questions.length - 1) {
          const nextQuestionIndex = prev.currentQuestionIndex + 1;
          const nextQuestion = questions[nextQuestionIndex];

          if (prev.currentQuestionIndex === 0) {
            // Combine greeting and next question with NEW_MESSAGE_BREAK
            const combinedMessage: Message = {
              id: nextQuestion.id,
              type: "bot",
              content: `Nice to meet you, ${prev.userResponses.name}! 😊<NEW_MESSAGE_BREAK>${nextQuestion.question}`,
            };
            newState.messages = [...prev.messages, combinedMessage];
          } else {
            // For other questions, just add the question normally
            const botMessage: Message = {
              id: nextQuestion.id,
              type: "bot",
              content: nextQuestion.question,
            };
            newState.messages = [...prev.messages, botMessage];
          }

          newState.currentQuestionIndex = nextQuestionIndex;
          newState.hasAnsweredCurrentQuestion = false;
        } else if (prev.currentQuestionIndex === questions.length - 1) {
          // After profession (last question), move to connections step
          const connectionsMessage: Message = {
            id: "connections",
            type: "bot",
            content: `Great! Now let's connect your accounts to help me assist you better. You can connect Gmail and Google Calendar below, or skip this step for now.`,
          };
          newState.messages = [...prev.messages, connectionsMessage];
          newState.currentQuestionIndex = questions.length; // Step 3 (connections)
          newState.hasAnsweredCurrentQuestion = false;
          newState.isOnboardingComplete = true; // Show completion buttons
        } else {
          // This shouldn't happen in normal flow
          const finalMessage: Message = {
            id: "final",
            type: "bot",
            content: `Thank you, ${prev.userResponses.name}! I'm all set up and ready to assist you. Let's get started!`,
          };
          newState.messages = [...prev.messages, finalMessage];
          newState.isOnboardingComplete = true;
        }

        newState.isProcessing = false;
        return newState;
      });
    },
    [onboardingState.isProcessing, onboardingState.currentQuestionIndex],
  );

  const handleChipSelect = useCallback(
    (questionId: string, chipValue: string) => {
      if (
        onboardingState.isProcessing ||
        onboardingState.hasAnsweredCurrentQuestion
      )
        return;

      const currentQuestion = questions[onboardingState.currentQuestionIndex];

      // Ensure we're selecting from the current question only
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
        } else if (chipValue === "none") {
          submitResponse("No special instructions", "");
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
      const { fieldName } = currentQuestion;

      if (fieldName !== FIELD_NAMES.PROFESSION) {
        if (onboardingState.currentInputs.text.trim()) {
          submitResponse(onboardingState.currentInputs.text.trim());
        }
      }
    },
    [
      onboardingState.currentQuestionIndex,
      onboardingState.currentInputs.text,
      submitResponse,
    ],
  );

  const handleLetsGo = async () => {
    // Prevent multiple submissions
    if (onboardingState.isProcessing) return;

    try {
      // Set loading state
      setOnboardingState((prev) => ({ ...prev, isProcessing: true }));

      // Validate required fields
      const requiredFields = ["name", "profession"];
      const missingFields = requiredFields.filter(
        (field) => !onboardingState.userResponses[field],
      );

      if (missingFields.length > 0) {
        toast.error(
          `Please complete all required fields: ${missingFields.join(", ")}`,
        );
        return;
      }

      // Prepare the onboarding data
      const onboardingData = {
        name: onboardingState.userResponses.name.trim(),
        profession: onboardingState.userResponses.profession,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, // Auto-capture timezone
      };

      // Send onboarding data to backend with retry logic
      let retryCount = 0;
      const maxRetries = 3;
      let response: OnboardingResponse | undefined;

      while (retryCount < maxRetries) {
        try {
          response = await authApi.completeOnboarding(onboardingData);
          break; // Success, exit retry loop
        } catch (error: unknown) {
          retryCount++;
          if (retryCount >= maxRetries) {
            throw error; // Re-throw if max retries reached
          }

          // Wait before retrying (exponential backoff)
          await new Promise((resolve) =>
            setTimeout(resolve, 1000 * retryCount),
          );
        }
      }

      if (response?.success) {
        // Track onboarding completion
        trackOnboardingComplete({
          profession: onboardingState.userResponses.profession,
          totalSteps: questions.length + 1, // questions + connections step
        });

        // Clear saved onboarding state since we're done
        if (typeof window !== "undefined") {
          sessionStorage.removeItem(ONBOARDING_STORAGE_KEY);
        }

        // Sync user store with the updated user data from backend
        if (response.user) {
          setUser({
            userId: response.user.user_id,
            name: response.user.name,
            email: response.user.email,
            profilePicture: response.user.picture,
            timezone: response.user.timezone,
            onboarding: response.user.onboarding,
            selected_model: response.user.selected_model,
          });
        }

        // Fetch conversations to populate sidebar with seeded data
        try {
          await batchSyncConversations();
        } catch (error) {
          console.error("Failed to sync conversations:", error);
          // Don't block navigation if conversation sync fails
        }

        // Navigate to the main chat page
        router.push("/c");
      } else {
        throw new Error("Failed to complete onboarding");
      }
    } catch (error: unknown) {
      console.error("Error completing onboarding:", error);

      // Provide specific error messages
      const errorObj = error as {
        response?: { status?: number };
        message?: string;
        code?: string;
      };

      if (errorObj?.response?.status === 409) {
        router.push("/c");
      } else if (errorObj?.response?.status === 422) {
        toast.error("Please check your input and try again.");
      } else if (
        errorObj?.message?.includes("network") ||
        errorObj?.code === "NETWORK_ERROR"
      ) {
        toast.error(
          "Network error. Please check your connection and try again.",
        );
      } else {
        toast.error("Failed to save your preferences. Please try again.");
      }
    } finally {
      // Clear loading state
      setOnboardingState((prev) => ({ ...prev, isProcessing: false }));
    }
  };

  // Initialize onboarding only once - don't reset on user.name changes
  useEffect(() => {
    // Only initialize if we haven't already and there are no messages
    if (isInitialized || onboardingState.messages.length > 0) return;

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
  }, [isInitialized, onboardingState.messages.length, user.name]);

  const handleRestart = useCallback(() => {
    // Clear sessionStorage
    if (typeof window !== "undefined") {
      sessionStorage.removeItem(ONBOARDING_STORAGE_KEY);
    }

    // Reset state
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
      isOnboardingComplete: false,
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
    handleLetsGo,
    handleRestart,
  };
};
