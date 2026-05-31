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

export const useVoiceModeStore = create<VoiceModeState>()(
  devtools(
    (set) => ({
      voiceModeActive: false,
      voiceSessionId: null,
      discoveredConversationId: null,

      enterVoiceMode: (existingConversationId?: string) => {
        const newUUID =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        set(
          {
            voiceModeActive: true,
            voiceSessionId: newUUID,
            // Seed with an existing conversation ID so the first turn is captured
            // under the correct ID. For new conversations, generate a provisional
            // UUID so the token API can pass it to the agent before any speech.
            discoveredConversationId: existingConversationId ?? newUUID,
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
