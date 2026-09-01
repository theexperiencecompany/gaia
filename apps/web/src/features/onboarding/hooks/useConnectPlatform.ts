/**
 * Platform-connect wiring for the `platformPick` stage — the single seam
 * between a platform button and whatever it takes to reach GAIA there.
 *
 * Telegram and WhatsApp open their public bot deep link in a new tab.
 * iMessage cannot: the number has to be registered with the delivery pool
 * first, so it collects an E.164 number, POSTs it to
 * `/platform-links/imessage/connect`, and hands the returned contact number
 * back for the user to text. Phase 7 replaces the plain deep links with
 * code-carrying ones by changing this hook and nothing else.
 */

"use client";

import { type Dispatch, useCallback, useState } from "react";
import type { PhoneLinkTarget } from "@/components/shared/PhoneLinkModal";
import { BOT_AUTH_COMMAND, type BotPlatform } from "@/config/botPlatforms";
import { BOT_LINKS } from "@/features/bots/constants";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";
import type { Action } from "../state/types";

interface PlatformConnectResponse {
  auth_url?: string;
  instructions?: string;
  action_link?: string;
  contact_number?: string;
  auth_type: string;
}

interface UseConnectPlatformReturn {
  connect: (platform: BotPlatform) => void;
  skip: () => void;
  phoneModalOpen: boolean;
  phoneTarget: PhoneLinkTarget | null;
  isSubmittingPhone: boolean;
  submitPhone: (phone: string) => void;
  closePhoneModal: () => void;
}

export function useConnectPlatform(
  dispatch: Dispatch<Action>,
): UseConnectPlatformReturn {
  const [phoneModalOpen, setPhoneModalOpen] = useState(false);
  const [phoneTarget, setPhoneTarget] = useState<PhoneLinkTarget | null>(null);
  const [isSubmittingPhone, setIsSubmittingPhone] = useState(false);

  const connect = useCallback(
    (platform: BotPlatform) => {
      if (platform === "imessage") {
        setPhoneTarget(null);
        setPhoneModalOpen(true);
        return;
      }
      const url = BOT_LINKS[platform];
      if (url) window.open(url, "_blank", "noopener,noreferrer");
      dispatch({ type: "platformConnected", platform });
    },
    [dispatch],
  );

  const submitPhone = useCallback(
    (phone: string) => {
      setIsSubmittingPhone(true);
      apiService
        .post<PlatformConnectResponse>(
          "/platform-links/imessage/connect",
          { phone },
          { silent: true },
        )
        .then((data) => {
          if (!data.contact_number) {
            toast.error("iMessage isn't available right now. Try another way.");
            return;
          }
          // An sms: deep link only resolves on Apple devices, so the number
          // and command have to stay readable (and copyable) on any device.
          setPhoneTarget({
            contactNumber: data.contact_number,
            command: BOT_AUTH_COMMAND,
            actionLink: data.action_link,
          });
        })
        .catch((error: unknown) => {
          console.error("[onboarding] iMessage registration failed:", error);
          toast.error("Couldn't register that number. Check it and try again.");
        })
        .finally(() => setIsSubmittingPhone(false));
    },
    [dispatch],
  );

  // The stage only advances once the modal is dismissed: advancing on the
  // successful POST would unmount the modal before the user has read the
  // number they are supposed to text.
  const closePhoneModal = useCallback(() => {
    const registered = phoneTarget !== null;
    setPhoneModalOpen(false);
    setPhoneTarget(null);
    if (registered)
      dispatch({ type: "platformConnected", platform: "imessage" });
  }, [dispatch, phoneTarget]);

  const skip = useCallback(() => {
    dispatch({ type: "skipPlatforms" });
  }, [dispatch]);

  return {
    connect,
    skip,
    phoneModalOpen,
    phoneTarget,
    isSubmittingPhone,
    submitPhone,
    closePhoneModal,
  };
}
