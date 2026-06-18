import { Button } from "@heroui/button";
import * as m from "motion/react-m";

import { useVoiceSession } from "@/features/chat/components/voice-agent/VoiceSessionContext";
import { useAppendToInput } from "@/stores/composerStore";

interface FollowUpActionsProps {
  actions: string[];
  loading: boolean;
}

export default function FollowUpActions({
  actions,
  loading,
}: FollowUpActionsProps) {
  const appendToInput = useAppendToInput();
  const voiceSession = useVoiceSession();

  const handleActionClick = async (action: string) => {
    if (loading) return;

    try {
      if (voiceSession) {
        // No composer in voice mode — send the suggestion to the agent as a
        // new user turn (renders the user bubble + streams/speaks the reply
        // exactly like a spoken message).
        await voiceSession.sendUserTurn(action);
      } else {
        appendToInput(action);
      }
    } catch (error) {
      console.error("Failed to handle follow-up action:", error);
    }
  };

  if (!actions || actions.length === 0) return null;

  return (
    <m.div
      initial="hidden"
      animate="visible"
      variants={{
        visible: {
          transition: {
            staggerChildren: 0.05,
          },
        },
      }}
      className="flex max-w-xl flex-wrap gap-2 pt-3 pb-1"
    >
      {actions.map((action) => (
        <m.div
          key={action}
          variants={{
            hidden: { opacity: 0, y: 10 },
            visible: { opacity: 1, y: 0 },
          }}
        >
          <Button
            className="text-xs text-foreground-500 outline-1 outline-zinc-700 transition-colors outline-dashed hover:bg-zinc-700 hover:text-foreground-700"
            variant="light"
            size="sm"
            onPress={() => handleActionClick(action)}
            isDisabled={loading}
          >
            {action}
          </Button>
        </m.div>
      ))}
    </m.div>
  );
}
