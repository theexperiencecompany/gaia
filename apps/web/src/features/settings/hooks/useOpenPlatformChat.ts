import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { api } from "@/lib/api/typed";

/** Open a linked bot's DM chat; the server resolves it, creating it before the first message. */
export function useOpenPlatformChat(platform: string) {
  const router = useRouter();
  const [isOpening, setIsOpening] = useState(false);

  const openChat = useCallback(async () => {
    setIsOpening(true);
    try {
      const { conversation_id } = await api.post(
        "/api/v1/platform-links/{platform}/conversation",
        { path: { platform } },
      );
      router.push(`/c/${conversation_id}`);
    } finally {
      setIsOpening(false);
    }
  }, [platform, router]);

  return { openChat, isOpening };
}
