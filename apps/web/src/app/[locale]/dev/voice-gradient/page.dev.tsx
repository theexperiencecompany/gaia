"use client";

import { Button, ButtonGroup } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { ArrowUp01Icon, CallEnd02Icon, Mic02Icon, MicOff02Icon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import type {
  ChatBubbleBotProps,
  ChatBubbleUserProps,
  SetImageDataType,
} from "@/types/features/chatBubbleTypes";
import { useVoiceSpectrum } from "./useVoiceSpectrum";
import { VoiceGradient, type VoiceMode } from "./VoiceGradient";

/** Mock conversation rendered through the REAL ChatBubble{User,Bot} components
 *  so the visual is pixel-identical to /c. Disabling actions keeps the dev
 *  demo isolated from action handlers that need stores we don't populate. */
/* BaseMessageData has many fields typed as `T | undefined` but TS treats
 * them as required because the schema uses literal `undefined` placeholders.
 * Cast through unknown for the dev mock — these are static fixtures, the
 * runtime shape is what the bubble components actually read. */
const MOCK_USER = [
  { message_id: "u1", text: "Hey GAIA, what's on my plate today?" },
  { message_id: "u2", text: "Nice. Anything urgent in mail?" },
  {
    message_id: "u3",
    text: "Draft the Maya reply — keep it tight and professional.",
  },
  {
    message_id: "u4",
    text: "Also, remind me to follow up with the platform team tomorrow morning.",
  },
] as unknown as ChatBubbleUserProps[];

const MOCK_BOT_TEXTS: string[] = [
  "You have three meetings scheduled — a stand-up at 10, design review at 1, and a sync with the platform team at 4. I drafted notes for the design review based on yesterday's threads.",
  "Two threads need a reply today: the legal review from Maya and a contract change from the AcmeCo team. Want me to draft responses?",
  "Drafted. *Tone: professional, concise, with a clear acknowledgement of the timeline.* Ready for your review whenever.",
  'Reminder set for tomorrow at 9:00 — "Follow up with platform team". I\'ll surface it in the morning.',
];

export default function VoiceGradientDemoPage() {
  const [mode, setMode] = useState<VoiceMode>("gaia");
  const source = "hybrid" as const;
  const voice = useVoiceSpectrum({ source });

  const autoStartedRef = useRef(false);
  useEffect(() => {
    if (autoStartedRef.current) return;
    autoStartedRef.current = true;
    voice.start();
  }, [voice.start]);

  // No-op image setters — the dev demo doesn't open the generated-image sheet.
  const [, setImageData] = useState<SetImageDataType>({
    src: "",
    prompt: "",
    improvedPrompt: "",
  });
  const [, setOpenImage] = useState(false);
  const noopSetImage = useCallback(setImageData, [setImageData]);
  const noopSetOpen = useCallback(setOpenImage, [setOpenImage]);

  const botProps = (idx: number, text: string): ChatBubbleBotProps =>
    ({
      message_id: `b${idx}`,
      text,
      setImageData: noopSetImage,
      setOpenImage: noopSetOpen,
      isLastMessage: idx === MOCK_BOT_TEXTS.length - 1,
    }) as unknown as ChatBubbleBotProps;

  return (
    <div className="relative h-[100dvh] w-full overflow-hidden bg-black">
      <VoiceGradient mode={mode} spectrum={voice.spectrum} />

      <div className="relative z-10 flex h-full min-h-0 flex-col">
        {/* Top mode-switch chip */}
        <div className="flex justify-center pt-6">
          <ButtonGroup variant="flat" radius="full" size="sm">
            <Button
              className={
                mode === "user"
                  ? "bg-white text-black"
                  : "bg-zinc-800/70 text-zinc-300"
              }
              onPress={() => setMode("user")}
            >
              You're speaking
            </Button>
            <Button
              className={
                mode === "gaia"
                  ? "bg-[#00bbff] text-black"
                  : "bg-zinc-800/70 text-zinc-300"
              }
              onPress={() => setMode("gaia")}
            >
              GAIA speaking
            </Button>
          </ButtonGroup>
        </div>

        {/* Chat list — exact dimensions of /c */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="conversation_history mx-auto flex w-full max-w-(--breakpoint-lg) flex-col gap-4 p-2 sm:p-4">
            <ChatBubbleUser {...MOCK_USER[0]} disableActions />
            <ChatBubbleBot {...botProps(0, MOCK_BOT_TEXTS[0])} disableActions />
            <ChatBubbleUser {...MOCK_USER[1]} disableActions />
            <ChatBubbleBot {...botProps(1, MOCK_BOT_TEXTS[1])} disableActions />
            <ChatBubbleUser {...MOCK_USER[2]} disableActions />
            <ChatBubbleBot {...botProps(2, MOCK_BOT_TEXTS[2])} disableActions />
            <ChatBubbleUser {...MOCK_USER[3]} disableActions />
            <ChatBubbleBot {...botProps(3, MOCK_BOT_TEXTS[3])} disableActions />
          </div>
        </div>

        {/* Bottom call controls — no status caption */}
        <div className="flex items-center justify-center gap-3 pb-8">
          <ButtonGroup variant="flat" radius="full">
            <Button
              isIconOnly
              className="bg-zinc-800/80 text-white backdrop-blur"
              onPress={voice.toggleMute}
              aria-label={voice.isMuted ? "Unmute" : "Mute"}
            >
              {voice.isMuted ? (
                <MicOff02Icon className="h-5 w-5" />
              ) : (
                <Mic02Icon className="h-5 w-5" />
              )}
            </Button>
            <Dropdown placement="top">
              <DropdownTrigger>
                <Button
                  isIconOnly
                  className="bg-zinc-800/80 text-white backdrop-blur"
                  aria-label="Select microphone"
                >
                  <ArrowUp01Icon className="h-4 w-4" />
                </Button>
              </DropdownTrigger>
              <DropdownMenu
                aria-label="Audio input devices"
                selectionMode="single"
                selectedKeys={voice.deviceId ? [voice.deviceId] : []}
                onAction={(key) => voice.selectDevice(String(key))}
              >
                {voice.devices.length > 0 ? (
                  voice.devices.map((d) => (
                    <DropdownItem key={d.deviceId}>
                      {d.label || "Unnamed device"}
                    </DropdownItem>
                  ))
                ) : (
                  <DropdownItem key="__none" isReadOnly>
                    No devices detected
                  </DropdownItem>
                )}
              </DropdownMenu>
            </Dropdown>
          </ButtonGroup>

          <Button
            isIconOnly
            radius="full"
            color="danger"
            onPress={voice.stop}
            aria-label="Disconnect"
          >
            <CallEnd02Icon className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
