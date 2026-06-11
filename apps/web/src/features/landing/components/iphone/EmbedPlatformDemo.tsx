"use client";

import { ChatDemo, type ChatPlatform } from "./ChatDemo";
import { IPhoneMockup } from "./IPhoneMockup";
import { PLATFORMS } from "./platformDemos";
import { useStaggeredMessages } from "./useStaggeredMessages";

interface EmbedPlatformDemoProps {
  platformId: ChatPlatform;
}

export function EmbedPlatformDemo({ platformId }: EmbedPlatformDemoProps) {
  const platform = PLATFORMS.find((p) => p.id === platformId) ?? PLATFORMS[0];
  const messages = useStaggeredMessages(platform.demo.messages, true);

  return (
    <IPhoneMockup
      screenBackground={platform.phone.screenBackground}
      statusBarTone={platform.phone.statusBarTone}
    >
      <div className="flex h-full flex-col">
        <ChatDemo
          platform={platform.id}
          title={platform.demo.title}
          subtitle={platform.demo.subtitle}
          messages={messages}
        />
      </div>
    </IPhoneMockup>
  );
}
