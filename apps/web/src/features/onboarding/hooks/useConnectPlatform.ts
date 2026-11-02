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
 *
 * Opening the app is not the link: that lands when the user taps Start (or
 * sends the text) there. The stage waits for it, polling the linked accounts,
 * and only then submits onboarding, so the first conversation is composed
 * knowing the link exists. The user can skip or pick another app meanwhile.
 */

"use client";

import { QueryObserver, useQuery, useQueryClient } from "@tanstack/react-query";
import { type Dispatch, useCallback, useEffect, useState } from "react";
import type { PhoneLinkTarget } from "@/components/shared/PhoneLinkModal";
import { BOT_AUTH_COMMAND, type BotPlatform } from "@/config/botPlatforms";
import { useBotLinks } from "@/features/bots/hooks/useBotLinks";
import { api } from "@/lib/api/typed";
import { toast } from "@/lib/toast";
import {
  fetchPlatformLinks,
  type LinkCodeResponse,
  mintLinkCode,
} from "../api/onboardingApi";
import { PLATFORM_LINK_POLL_MS } from "../constants";
import type { Action } from "../state/types";

interface UseConnectPlatformReturn {
  connect: (platform: BotPlatform) => void;
  skip: () => void;
  /** The platform whose link the stage is waiting on, once its app is open. */
  awaitingPlatform: BotPlatform | null;
  chooseAnother: () => void;
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
const PLATFORM_LINKS_QUERY_KEY = ["onboarding", "platform-links"] as const;

export function useConnectPlatform(
  dispatch: Dispatch<Action>,
  preferencesPersisted: boolean,
  onConfirmed: () => void,
): UseConnectPlatformReturn {
  const [phoneModalOpen, setPhoneModalOpen] = useState(false);
  const [phoneTarget, setPhoneTarget] = useState<PhoneLinkTarget | null>(null);
  const [isSubmittingPhone, setIsSubmittingPhone] = useState(false);
  const [awaitingPlatform, setAwaitingPlatform] = useState<BotPlatform | null>(
    null,
  );

  // Minted on stage entry, not per click (window.open in a click handler must
  // be synchronous); a code outliving its TTL gets the bot's "link expired"
  // reply. Gated on the answers being stored, or the opener comes back anonymous.
  const { data, error } = useQuery({
    queryKey: LINK_CODE_QUERY_KEY,
    queryFn: mintLinkCode,
    enabled: preferencesPersisted,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  const linkCode: LinkCodeResponse | null = data ?? null;
  const botLinks = useBotLinks();

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
      const url = linkCode?.links[platform] ?? botLinks?.[platform];
      if (url) window.open(url, "_blank", "noopener,noreferrer");
      setAwaitingPlatform(platform);
    },
    [botLinks, linkCode],
  );

  // Subscribed, not derived in render: the link landing is an outside event
  // that submits onboarding once. Focus refetch catches the common case at
  // once — the user taps Start, then switches back to this tab.
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!awaitingPlatform) return;
    const observer = new QueryObserver(queryClient, {
      queryKey: PLATFORM_LINKS_QUERY_KEY,
      queryFn: fetchPlatformLinks,
      refetchInterval: PLATFORM_LINK_POLL_MS,
      refetchOnWindowFocus: true,
      staleTime: 0,
    });
    let confirmed = false;
    return observer.subscribe(({ data }) => {
      if (confirmed || !data?.platform_links[awaitingPlatform]?.platformUserId)
        return;
      confirmed = true;
      dispatch({ type: "platformConnected", platform: awaitingPlatform });
      onConfirmed();
    });
  }, [awaitingPlatform, queryClient, dispatch, onConfirmed]);

  const chooseAnother = useCallback(() => setAwaitingPlatform(null), []);

  const submitPhone = useCallback(
    (phone: string) => {
      setIsSubmittingPhone(true);
      api
        .post("/api/v1/platform-links/{platform}/connect", {
          path: { platform: "imessage" },
          body: { phone },
          silent: true,
        })
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
              : (data.action_link ?? undefined),
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

  // Waiting starts once the modal is dismissed: the user has to read the
  // number they are supposed to text first.
  const closePhoneModal = useCallback(() => {
    const registered = phoneTarget !== null;
    setPhoneModalOpen(false);
    setPhoneTarget(null);
    if (registered) setAwaitingPlatform("imessage");
  }, [phoneTarget]);

  // Skipping just advances the wizard: the web no longer stages the composed
  // opener as the user's own turn (completion seeds GAIA's "Getting started"
  // conversation server-side); bot surfaces still send `code.first_message` as the first turn.
  const skip = useCallback(() => {
    dispatch({ type: "skipPlatforms" });
    onConfirmed();
  }, [dispatch, onConfirmed]);

  return {
    connect,
    skip,
    awaitingPlatform,
    chooseAnother,
    phoneModalOpen,
    phoneTarget,
    isSubmittingPhone,
    submitPhone,
    closePhoneModal,
  };
}
