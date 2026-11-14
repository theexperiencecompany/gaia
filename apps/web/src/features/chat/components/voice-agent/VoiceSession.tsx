"use client";

import type { ReactNode } from "react";
import {
  VoiceControlBarContainer,
  VoiceControlBarSlot,
} from "@/features/chat/components/voice-agent/VoiceControlBarContainer";

export interface VoiceSessionProps {
  onEndCall: () => void;
  /** The conversation, given the voice bar to place as its bottom bar. */
  renderConversation: (bottomBar: ReactNode) => ReactNode;
}

/** A live voice session around the conversation; the one entry point into LiveKit's chunk. */
export function VoiceSession({
  onEndCall,
  renderConversation,
}: Readonly<VoiceSessionProps>) {
  return (
    <VoiceControlBarContainer>
      {renderConversation(<VoiceControlBarSlot onEndCall={onEndCall} />)}
    </VoiceControlBarContainer>
  );
}
