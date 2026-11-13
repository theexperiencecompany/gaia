import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

interface VoiceModeState {
  voiceModeActive: boolean;
  voiceSessionId: string | null;
  discoveredConversationId: string | null;
  enterVoiceMode: (existingConversationId?: string) => void;
  exitVoiceMode: () => void;
  setDiscoveredConversationId: (id: string | null) => void;
}

const useVoiceModeStore = create<VoiceModeState>()(
  devtools(
    (set) => ({
      voiceModeActive: false,
      voiceSessionId: null,
      discoveredConversationId: null,

      enterVoiceMode: (existingConversationId?: string) => {
        // voiceSessionId is a per-session UI key (forces a fresh gradient canvas), not the
        // conversation id — that's backend-owned: a new chat gets it over the LiveKit
        // `conversation-id` topic, an existing chat reads it from the URL param.
        const newSessionId = crypto.randomUUID();
        set(
          {
            voiceModeActive: true,
            voiceSessionId: newSessionId,
            discoveredConversationId: existingConversationId ?? null,
          },
          false,
          "enterVoiceMode",
        );
      },

      exitVoiceMode: () =>
        set(
          {
            voiceModeActive: false,
            voiceSessionId: null,
            discoveredConversationId: null,
          },
          false,
          "exitVoiceMode",
        ),

      setDiscoveredConversationId: (id) =>
        set({ discoveredConversationId: id }, false, "setDiscoveredConvoId"),
    }),
    { name: "voiceModeStore" },
  ),
);

export const useVoiceModeActive = (): boolean =>
  useVoiceModeStore((s) => s.voiceModeActive);

export const useVoiceSessionId = (): string | null =>
  useVoiceModeStore((s) => s.voiceSessionId);

export const useDiscoveredConversationId = (): string | null =>
  useVoiceModeStore((s) => s.discoveredConversationId);

export const useVoiceModeActions = () =>
  useVoiceModeStore(
    useShallow((s) => ({
      enterVoiceMode: s.enterVoiceMode,
      exitVoiceMode: s.exitVoiceMode,
      setDiscoveredConversationId: s.setDiscoveredConversationId,
    })),
  );
