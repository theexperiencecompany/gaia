"use client";

import { useCallback, useRef, useState } from "react";
import type { Message } from "@/features/onboarding/types";
import type { PersonalizationData } from "@/features/onboarding/types/websocket";

interface PendingStage {
  stage: string;
  results: Record<string, unknown>;
}

interface UseOnboardingRevealReturn {
  revealMessages: Message[];
  progress: number;
  intelligenceConversationId: string | null;
  isRevealComplete: boolean;
  holoCardData: PersonalizationData | null;
  handleProgressEvent: (
    stage: string,
    message: string,
    progress: number,
    results?: Record<string, unknown>,
  ) => void;
  handlePersonalizationComplete: (data: PersonalizationData) => void;
  handleIntelligenceComplete: (conversationId: string) => void;
}

const ORDERED_STAGES = [
  "scanning_inbox",
  "learning_style",
  "finding_profiles",
  "triaging",
  "creating_todos",
  "creating_workflows",
];

let messageCounter = 0;

function generateRevealMessageId(): string {
  messageCounter += 1;
  return `reveal-${messageCounter}-${Date.now()}`;
}

function isStageResultEmpty(
  stage: string,
  results: Record<string, unknown>,
): boolean {
  switch (stage) {
    case "scanning_inbox": {
      const emailCount = results.email_count;
      return typeof emailCount === "number" && emailCount === 0;
    }
    case "learning_style": {
      const styleSummary = results.style_summary;
      return !styleSummary || styleSummary === "";
    }
    case "finding_profiles": {
      const profiles = results.profiles;
      return !Array.isArray(profiles) || profiles.length === 0;
    }
    case "triaging": {
      const importantEmails = results.important_emails;
      return !Array.isArray(importantEmails) || importantEmails.length === 0;
    }
    case "creating_todos": {
      const todos = results.todos;
      return !Array.isArray(todos) || todos.length === 0;
    }
    case "creating_workflows": {
      const workflows = results.workflows;
      return !Array.isArray(workflows) || workflows.length === 0;
    }
    default:
      return false;
  }
}

function buildRevealMessage(
  stage: string,
  results: Record<string, unknown>,
): Message {
  return {
    id: generateRevealMessageId(),
    type: "reveal",
    content: "",
    revealStage: stage,
    revealData: results,
  };
}

function buildHoloCardMessage(
  personalizationData: PersonalizationData,
): Message {
  return {
    id: generateRevealMessageId(),
    type: "reveal",
    content: "",
    revealStage: "holo_card",
    revealData: { personalizationData },
  };
}

export function useOnboardingReveal(): UseOnboardingRevealReturn {
  const [revealMessages, setRevealMessages] = useState<Message[]>([]);
  const [progress, setProgress] = useState<number>(0);
  const [intelligenceConversationId, setIntelligenceConversationId] = useState<
    string | null
  >(null);
  const [isRevealComplete, setIsRevealComplete] = useState<boolean>(false);
  const [holoCardData, setHoloCardData] = useState<PersonalizationData | null>(
    null,
  );

  const pendingStagesRef = useRef<PendingStage[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const intelligenceCompleteRef = useRef<boolean>(false);
  const holoCardDataRef = useRef<PersonalizationData | null>(null);
  const shownStagesRef = useRef<Set<string>>(new Set());

  const stopInterval = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const drainAndFinish = useCallback(() => {
    stopInterval();

    const remaining = pendingStagesRef.current.splice(0);
    const drainedMessages: Message[] = [];

    for (const pending of remaining) {
      if (!shownStagesRef.current.has(pending.stage)) {
        shownStagesRef.current.add(pending.stage);
        drainedMessages.push(
          buildRevealMessage(pending.stage, pending.results),
        );
      }
    }

    const holoData = holoCardDataRef.current;
    const holoMessage = holoData ? buildHoloCardMessage(holoData) : null;

    if (drainedMessages.length > 0 || holoMessage !== null) {
      setRevealMessages((prev) => {
        const next = [...prev, ...drainedMessages];
        if (holoMessage !== null) {
          next.push(holoMessage);
        }
        return next;
      });
    }

    setIsRevealComplete(true);
  }, [stopInterval]);

  const startIntervalIfNeeded = useCallback(() => {
    if (intervalRef.current !== null) {
      return;
    }

    intervalRef.current = setInterval(() => {
      const pending = pendingStagesRef.current;

      if (pending.length > 0) {
        const next = pending.shift();
        if (next !== undefined && !shownStagesRef.current.has(next.stage)) {
          shownStagesRef.current.add(next.stage);
          const message = buildRevealMessage(next.stage, next.results);
          setRevealMessages((prev) => [...prev, message]);
        }
        return;
      }

      if (intelligenceCompleteRef.current) {
        drainAndFinish();
      }
    }, 3500);
  }, [drainAndFinish]);

  const handleProgressEvent = useCallback(
    (
      stage: string,
      _message: string,
      progressValue: number,
      results?: Record<string, unknown>,
    ) => {
      setProgress(progressValue);

      if (!results || !ORDERED_STAGES.includes(stage)) {
        return;
      }

      if (isStageResultEmpty(stage, results)) {
        return;
      }

      if (shownStagesRef.current.has(stage)) {
        return;
      }

      const alreadyQueued = pendingStagesRef.current.some(
        (p) => p.stage === stage,
      );
      if (alreadyQueued) {
        return;
      }

      pendingStagesRef.current.push({ stage, results });

      startIntervalIfNeeded();
    },
    [startIntervalIfNeeded],
  );

  const handlePersonalizationComplete = useCallback(
    (data: PersonalizationData) => {
      holoCardDataRef.current = data;
      setHoloCardData(data);
    },
    [],
  );

  const handleIntelligenceComplete = useCallback(
    (conversationId: string) => {
      intelligenceCompleteRef.current = true;
      setIntelligenceConversationId(conversationId);
      drainAndFinish();
    },
    [drainAndFinish],
  );

  return {
    revealMessages,
    progress,
    intelligenceConversationId,
    isRevealComplete,
    holoCardData,
    handleProgressEvent,
    handlePersonalizationComplete,
    handleIntelligenceComplete,
  };
}
