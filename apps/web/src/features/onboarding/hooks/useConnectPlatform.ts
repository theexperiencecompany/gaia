/**
 * Platform-connect wiring for the `platformPick` stage — the single seam
 * between a platform button and whatever it takes to reach GAIA there.
 *
 * On entry the hook mints a one-tap linking code. Telegram and WhatsApp then
 * open a deep link that carries it, so the user's first contact links the
 * account and starts a real conversation without anyone typing `/auth`.
 * iMessage cannot use a pre-built link: the number has to be registered with
 * the delivery pool first, so it collects an E.164 number, POSTs it to
 * `/platform-links/imessage/connect`, and builds the `sms:` handoff from the
 * contact number that call returns. Skipping hands the same composed message
 * to the web chat instead.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { type Dispatch, useCallback, useEffect, useState } from "react";
import type { PhoneLinkTarget } from "@/components/shared/PhoneLinkModal";
import { BOT_AUTH_COMMAND, type BotPlatform } from "@/config/botPlatforms";
import { BOT_LINKS } from "@/features/bots/constants";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";
import { type LinkCodeResponse, mintLinkCode } from "../api/onboardingApi";
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

/**
 * The iOS form is `sms:<number>&body=<text>` — the RFC's `?body=` is what
 * Messages ignores, and iMessage is an Apple-only surface.
 */
function buildImessageHandoffLink(
  contactNumber: string,
  handoffText: string,
): string {
  return `sms:${contactNumber}&body=${encodeURIComponent(handoffText)}`;
}

/**
 * One mint per stage entry, shared by every caller. The stage renders this
 * hook twice (picker + composer) and React StrictMode double-invokes effects,
 * so a per-instance effect minted four single-use codes per entry. A query
 * key dedupes all of that: the second subscriber joins the first request, and
 * the cached result survives a StrictMode remount.
 */
const LINK_CODE_QUERY_KEY = ["onboarding", "platform-link-code"] as const;

export function useConnectPlatform(
  dispatch: Dispatch<Action>,
  preferencesPersisted: boolean,
): UseConnectPlatformReturn {
  const [phoneModalOpen, setPhoneModalOpen] = useState(false);
  const [phoneTarget, setPhoneTarget] = useState<PhoneLinkTarget | null>(null);
  const [isSubmittingPhone, setIsSubmittingPhone] = useState(false);

  // Minted on stage entry rather than per click: `window.open` in a click
  // handler must be synchronous or the browser blocks it as a popup. The code
  // outlives the step, and a user who stalls past its TTL gets the bot's
  // "that link expired" reply pointing them back here.
  //
  // Gated on the answers being stored: the server composes `first_message`
  // from the saved profession + needs, so a code minted any earlier carries
  // the anonymous "Hi! Who are you?" opener.
  const { data, error } = useQuery({
    queryKey: LINK_CODE_QUERY_KEY,
    queryFn: mintLinkCode,
    enabled: preferencesPersisted,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  const linkCode: LinkCodeResponse | null = data ?? null;

  useEffect(() => {
    // Degrade to the plain bot links: the user links with /auth instead of
    // one tap. Blocking onboarding on this would be worse.
    if (error) console.error("[onboarding] link code mint failed:", error);
  }, [error]);

  const connect = useCallback(
    (platform: BotPlatform) => {
      if (platform === "imessage") {
        setPhoneTarget(null);
        setPhoneModalOpen(true);
        return;
      }
      const url = linkCode?.links[platform] ?? BOT_LINKS[platform];
      if (url) window.open(url, "_blank", "noopener,noreferrer");
      dispatch({ type: "platformConnected", platform });
    },
    [dispatch, linkCode],
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
          // and the text to send have to stay readable (and copyable) on any
          // device.
          setPhoneTarget({
            contactNumber: data.contact_number,
            command: linkCode?.handoff_text ?? BOT_AUTH_COMMAND,
            actionLink: linkCode
              ? buildImessageHandoffLink(
                  data.contact_number,
                  linkCode.handoff_text,
                )
              : data.action_link,
          });
        })
        .catch((error: unknown) => {
          console.error("[onboarding] iMessage registration failed:", error);
          toast.error("Couldn't register that number. Check it and try again.");
        })
        .finally(() => setIsSubmittingPhone(false));
    },
    [linkCode],
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

  // Skipping just advances the wizard. The web no longer stages the composed
  // opener as the user's own turn: completion seeds GAIA's "Getting started"
  // conversation server-side and the guard lands them in it. The bot surfaces
  // still send `code.first_message` as the user's first turn.
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
