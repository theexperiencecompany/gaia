/**
 * The chrome around a bot bubble: the avatar pinned to the lane, and the
 * footer with follow-ups, the timestamp and the actions row. Split out of
 * ChatBubbleBot so the bubble itself stays readable.
 */

import * as m from "motion/react-m";
import Image from "next/image";
import type { RefObject } from "react";

import ChatBubble_Actions from "@/features/chat/components/bubbles/actions/ChatBubble_Actions";
import ChatBubble_Actions_Image from "@/features/chat/components/bubbles/actions/ChatBubble_Actions_Image";
import {
  MESSAGE_BREAK_DURATION_SECONDS,
  MESSAGE_BREAK_EASE_OUT_QUART,
} from "@/features/chat/utils/messageBreakUtils";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";

import FollowUpActions from "./FollowUpActions";

/** The GAIA logo, absolutely pinned to the avatar lane; it fades in with the
 *  last part of the turn (`delaySeconds`). */
export function BotBubbleAvatar({ delaySeconds }: { delaySeconds: number }) {
  return (
    <m.div
      className="absolute bottom-0 left-0 z-5 transition duration-900"
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{
        duration: MESSAGE_BREAK_DURATION_SECONDS,
        ease: MESSAGE_BREAK_EASE_OUT_QUART,
        delay: delaySeconds,
      }}
    >
      <Image
        alt="GAIA Logo"
        src={"/images/logos/logo.webp"}
        width={30}
        height={30}
      />
    </m.div>
  );
}

type FooterProps = Pick<
  ChatBubbleBotProps,
  | "follow_up_actions"
  | "date"
  | "image_data"
  | "message_id"
  | "pinned"
  | "text"
  | "onRetry"
  | "isRetrying"
> & {
  actionsRef: RefObject<HTMLDivElement | null>;
  loading: boolean;
  disableActions: boolean;
};

/** Follow-up chips, the timestamp and the hover-revealed actions row. */
export function BotBubbleFooter({
  actionsRef,
  loading,
  disableActions,
  follow_up_actions,
  date,
  image_data,
  message_id,
  pinned,
  text,
  onRetry,
  isRetrying,
}: FooterProps) {
  const hasFollowUps = !!follow_up_actions && follow_up_actions.length > 0;
  const rowClass = disableActions
    ? "hidden"
    : loading
      ? "opacity-0!"
      : "opacity-100";
  return (
    <div className="ml-10.75 flex flex-col">
      {hasFollowUps && (
        <FollowUpActions actions={follow_up_actions} loading={loading} />
      )}

      <div
        ref={actionsRef}
        className={`flex flex-col transition-all ${rowClass}`}
        style={{
          opacity: disableActions ? 1 : 0,
          visibility: disableActions ? "visible" : "hidden",
        }}
      >
        {date && !disableActions && (
          <span
            className="text-opacity-40 flex flex-col p-1 py-2 text-xs text-nowrap text-zinc-400 select-text"
            suppressHydrationWarning
          >
            {parseDate(date)}
          </span>
        )}

        {!disableActions &&
          (image_data ? (
            <ChatBubble_Actions_Image image_data={image_data} />
          ) : (
            <ChatBubble_Actions
              loading={loading}
              message_id={message_id}
              pinned={pinned}
              text={text}
              messageRole="assistant"
              onRetry={onRetry}
              isRetrying={isRetrying}
            />
          ))}
      </div>
    </div>
  );
}
