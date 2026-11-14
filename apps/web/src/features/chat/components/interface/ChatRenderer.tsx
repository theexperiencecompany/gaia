"use client";

import { SCREEN_ITEM_KIND } from "@shared/conversation";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import nextDynamic from "next/dynamic";
import { useParams } from "next/navigation";
import {
  memo,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { MessageScrollerItem } from "@/components/ui/message-scroller";
import { SystemPurpose } from "@/features/chat/api/chatApi";
import CreatedByGAIABanner from "@/features/chat/components/banners/CreatedByGAIABanner";
import { ChatItemBoundary } from "@/features/chat/components/bubbles/bot/ChatItemBoundary";
import SearchedImageDialog from "@/features/chat/components/bubbles/bot/SearchedImageDialog";
import GeneratedImageSheet from "@/features/chat/components/image/GeneratedImageSheet";
import { LoadingIndicator } from "@/features/chat/components/interface/LoadingIndicator";
import MemoryModal from "@/features/chat/components/memory/MemoryModal";
import { useChatRows } from "@/features/chat/hooks/useChatRows";
import { useConversationRow } from "@/features/chat/hooks/useConversationList";
import { useMessageHighlight } from "@/features/chat/hooks/useMessageHighlight";
import { useRetryMessage } from "@/features/chat/hooks/useRetryMessage";
import {
  type LiveConversation,
  useLiveConversation,
} from "@/features/chat/live/liveConversationStore";
import { useActiveLiveLoading } from "@/features/chat/live/useLiveChat";
import { useChatStore } from "@/stores/chatStore";
import type { SetImageDataType } from "@/types/features/chatBubbleTypes";
import { GaiaRow } from "./rows/GaiaRow";
import {
  type ChatRow,
  isUserSide,
  type RowActions,
  type RowLayout,
  rowId,
  rowKind,
  rowShows,
} from "./rows/rows";
import { UserRow } from "./rows/UserRow";

interface ChatRendererProps {
  /**
   * Compact mode for narrow surfaces (assistant popup): no avatars,
   * full-width bubbles, and a translate+blur entrance on each bubble.
   */
  compact?: boolean;
}

type Sends = LiveConversation["sends"];

/** Compact-mode loader: the GAIA orb instead of the wave spinner. */
const GaiaOrbLazy = nextDynamic(() => import("@/components/ui/orb/GaiaOrb"), {
  ssr: false,
});

/**
 * Bubble keys that already played their entrance. Module-level so list
 * remounts (conversation-id swap, optimistic->real id transitions) don't
 * replay it — replaying flashes existing bubbles invisible.
 *
 * FIFO-bounded so a long session can't accumulate keys indefinitely; the
 * cap is far above any realistic conversation, so a visible bubble never gets evicted.
 */
const revealedBubbleKeys = new Set<string>();
const MAX_REVEALED_BUBBLE_KEYS = 2000;

function markBubbleRevealed(bubbleKey: string): void {
  revealedBubbleKeys.add(bubbleKey);
  if (revealedBubbleKeys.size > MAX_REVEALED_BUBBLE_KEYS) {
    const oldest = revealedBubbleKeys.values().next().value;
    if (oldest !== undefined) revealedBubbleKeys.delete(oldest);
  }
}

/** Entrance played only the FIRST time a bubble key appears. */
function CompactReveal({
  bubbleKey,
  children,
}: Readonly<{
  bubbleKey: string;
  children: ReactNode;
}>) {
  const isNew = !revealedBubbleKeys.has(bubbleKey);

  useEffect(() => {
    markBubbleRevealed(bubbleKey);
  }, [bubbleKey]);

  return (
    <m.div
      initial={isNew ? { opacity: 0, y: 12, filter: "blur(8px)" } : false}
      animate={{
        opacity: 1,
        y: 0,
        filter: "blur(0px)",
        // Clear the filter once done — a lingering filter rasterizes the
        // subtree, which leaves white AA halos around clip-path tails on
        // transparent (liquid glass) windows.
        transitionEnd: { filter: "none" },
      }}
      transition={{ duration: 0.35, ease: [0.19, 1, 0.22, 1] }}
    >
      {children}
    </m.div>
  );
}

/** The row's bubble, chosen by what the server's item is. */
function RowBubble({
  row,
  sends,
  actions,
  layout,
}: Readonly<{
  row: ChatRow;
  sends: Sends;
  actions: RowActions;
  layout: RowLayout;
}>) {
  switch (row.kind) {
    case "item": {
      const { item } = row;
      if (
        item.kind === SCREEN_ITEM_KIND.REPLY ||
        item.kind === SCREEN_ITEM_KIND.WORK ||
        item.kind === SCREEN_ITEM_KIND.NOTICE
      )
        return (
          <GaiaRow
            item={item}
            draft={row.draft}
            actions={actions}
            layout={layout}
          />
        );
      return (
        <UserRow
          source={{ kind: "item", item }}
          actions={actions}
          layout={layout}
        />
      );
    }
    case "draft":
      return (
        <GaiaRow
          item={null}
          draft={row.draft}
          actions={actions}
          layout={layout}
        />
      );
    case "pending":
      return (
        <UserRow
          source={{
            kind: "pending",
            send: row.send,
            local: sends[row.send.id],
          }}
          actions={actions}
          layout={layout}
        />
      );
    case "optimistic":
      return (
        <UserRow
          source={{ kind: "optimistic", message: row.message }}
          actions={actions}
          layout={layout}
        />
      );
    default: {
      const unhandled: never = row;
      return unhandled;
    }
  }
}

/** What a row draws from: screenRows wraps these anew each frame, and each keeps its identity while unchanged. */
function rowInputs(row: ChatRow): readonly unknown[] {
  switch (row.kind) {
    case "item":
      return [row.item, row.draft];
    case "draft":
      return [row.draft];
    case "pending":
      return [row.send];
    case "optimistic":
      return [row.message];
    default: {
      const unhandled: never = row;
      return unhandled;
    }
  }
}

interface ChatRowItemProps {
  row: ChatRow;
  sends: Sends;
  actions: RowActions;
  isGroupedWithNext: boolean;
  isGroupedWithPrev: boolean;
  suppressForBusy: boolean;
  compact: boolean;
}

function sameRowItem(a: ChatRowItemProps, b: ChatRowItemProps): boolean {
  const before = rowInputs(a.row);
  const after = rowInputs(b.row);
  return (
    a.row.kind === b.row.kind &&
    before.every((input, at) => Object.is(input, after[at])) &&
    (a.row.kind !== "pending" || a.sends === b.sends) &&
    a.actions === b.actions &&
    a.isGroupedWithNext === b.isGroupedWithNext &&
    a.isGroupedWithPrev === b.isGroupedWithPrev &&
    a.suppressForBusy === b.suppressForBusy &&
    a.compact === b.compact
  );
}

/**
 * One row, memoized on its server item (an unchanged item keeps its identity)
 * and its grouping flags, so a streamed token re-renders only the row it
 * lands in. `compact` mode drops the avatar, goes full-width, suppresses
 * actions and follow-ups, and plays a one-time CompactReveal entrance.
 */
const ChatRowItem = memo(function ChatRowItem({
  row,
  sends,
  actions,
  isGroupedWithNext,
  isGroupedWithPrev,
  suppressForBusy,
  compact,
}: ChatRowItemProps) {
  const id = rowId(row);
  const guarded = (
    <ChatItemBoundary
      item="message"
      messageId={id}
      resetKey={rowInputs(row)[0]}
    >
      <RowBubble
        row={row}
        sends={sends}
        actions={actions}
        layout={{
          isGroupedWithNext,
          isGroupedWithPrev,
          suppressForBusy,
          compact,
        }}
      />
    </ChatItemBoundary>
  );

  return compact ? (
    <CompactReveal bubbleKey={id}>{guarded}</CompactReveal>
  ) : (
    guarded
  );
}, sameRowItem);

export default function ChatRenderer({ compact = false }: ChatRendererProps) {
  const rows = useChatRows();
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const { sends } = useLiveConversation(activeConversationId);
  const [openGeneratedImage, setOpenGeneratedImage] = useState<boolean>(false);
  const [openMemoryModal, setOpenMemoryModal] = useState<boolean>(false);
  // The open conversation's loading row, from its server state (plus voice/upload loading).
  const { isLoading, loadingText, toolInfo } = useActiveLiveLoading();
  const { id: convoIdParam } = useParams<{ id: string }>();
  // While GAIA owes a reply, the newest bubble's follow-ups and action row
  // (they belong to a finished answer) are suppressed; finished turns keep theirs.
  const isConversationBusy = isLoading;
  const { scrollToMessage } = useMessageHighlight();

  const { retryMessage, isRetrying } = useRetryMessage();
  const [imageData, setImageData] = useState<SetImageDataType>({
    src: "",
    prompt: "",
    improvedPrompt: "",
  });

  const conversation = useConversationRow(convoIdParam);

  // `retryMessage` gets a new identity on most renders (unstable
  // `sendMessage` deps), so read it via ref to keep `handleRetry` (and the
  // memoized rows) stable across streaming tokens.
  const retryMessageRef = useRef(retryMessage);
  useEffect(() => {
    retryMessageRef.current = retryMessage;
  });
  const handleRetry = useCallback((itemId: string) => {
    // Use the store's active conversation id, not the route param: a new
    // conversation rewrites the URL via history.replaceState without
    // updating useParams, so retry only worked after reload before this. getState keeps this dep-free.
    const conversationId = useChatStore.getState().activeConversationId;
    if (!conversationId) return;
    retryMessageRef.current(conversationId, itemId);
  }, []);

  // Depend on primitive conversation fields, not the conversation object —
  // the conversation list gets a new reference every streaming token
  // (preview/timestamp updates), which would defeat the memoization downstream.
  const isSystemGenerated = conversation?.is_system_generated ?? false;
  const systemPurpose = conversation?.system_purpose ?? undefined;
  const actions = useMemo<RowActions>(
    () => ({
      setImageData,
      setOpenImage: setOpenGeneratedImage,
      onOpenMemoryModal: () => setOpenMemoryModal(true),
      onRetry: handleRetry,
      isRetrying,
      isConvoSystemGenerated: isSystemGenerated,
      systemPurpose,
    }),
    [isSystemGenerated, systemPurpose, handleRetry, isRetrying],
  );

  // A GAIA row with nothing to draw renders nothing, so it is left out: the
  // grouping below then reads only the rows actually on screen.
  const alwaysShowsGaia =
    isSystemGenerated && systemPurpose === SystemPurpose.EMAIL_PROCESSING;
  const shownRows = useMemo(
    () => rows.filter((row) => rowShows(row, alwaysShowsGaia)),
    [rows, alwaysShowsGaia],
  );

  // Scroll to (and highlight) a deep-linked message once it exists.
  const scrolledToMessageRef = useRef<string | null>(null);
  useEffect(() => {
    const messageId = new URLSearchParams(window.location.search).get(
      "messageId",
    );
    if (
      messageId &&
      shownRows.length > 0 &&
      scrolledToMessageRef.current !== messageId
    ) {
      scrollToMessage(messageId);
      scrolledToMessageRef.current = messageId;
    }
  }, [shownRows, scrollToMessage]);

  return (
    <>
      <title id="chat_title">{`${conversation?.description || "New chat"} | GAIA`}</title>
      <GeneratedImageSheet
        imageData={imageData}
        openImage={openGeneratedImage}
        setOpenImage={setOpenGeneratedImage}
      />
      <MemoryModal
        isOpen={openMemoryModal}
        onClose={() => setOpenMemoryModal(false)}
      />
      <SearchedImageDialog />
      <CreatedByGAIABanner
        show={
          conversation?.is_system_generated === true &&
          conversation.system_purpose !== SystemPurpose.GETTING_STARTED
        }
      />
      {shownRows.map((row, index) => {
        const id = rowId(row);
        const userSide = isUserSide(row);
        // Consecutive bubbles from one side group (iMessage-style): only the
        // LAST shows the avatar/actions/timestamp; others sit tight with no gap.
        const isGroupedWithNext =
          index + 1 < shownRows.length &&
          isUserSide(shownRows[index + 1]) === userSide;
        const isGroupedWithPrev =
          index > 0 && isUserSide(shownRows[index - 1]) === userSide;
        // Only the active turn's bubble (the last one) is suppressed while
        // the conversation is busy — finished turns keep their actions.
        const suppressForBusy =
          index === shownRows.length - 1 && isConversationBusy;

        return (
          // The scroller virtualizes rows (content-visibility) with anchor
          // math it owns. User messages are turn anchors.
          <MessageScrollerItem
            key={id}
            messageId={id}
            scrollAnchor={userSide}
            data-screen-item-id={id}
            data-screen-item-kind={rowKind(row)}
          >
            <ChatRowItem
              row={row}
              sends={sends}
              actions={actions}
              isGroupedWithNext={isGroupedWithNext}
              isGroupedWithPrev={isGroupedWithPrev}
              suppressForBusy={suppressForBusy}
              compact={compact}
            />
          </MessageScrollerItem>
        );
      })}
      {isLoading && (
        <AnimatePresence>
          <LoadingIndicator
            loadingText={loadingText}
            toolInfo={toolInfo}
            noPadding={compact}
            spinner={
              // The orb replaces the wave spinner in the popup; the
              // loading text and tool info render exactly as on web.
              compact ? (
                // Slow continuous rotation + breathing over the shader so
                // the orb reads alive at this small size. Negative margins
                // tuck the text close (canvas is mostly transparent glow padding).
                <m.div
                  className="-my-3 -ml-2.5 -mr-2.5 shrink-0"
                  animate={{ rotate: 360, scale: [1, 1.08, 1] }}
                  transition={{
                    rotate: {
                      duration: 6,
                      ease: "linear",
                      repeat: Number.POSITIVE_INFINITY,
                    },
                    scale: {
                      duration: 1.6,
                      ease: "easeInOut",
                      repeat: Number.POSITIVE_INFINITY,
                    },
                  }}
                >
                  <GaiaOrbLazy state="thinking" className="size-14" />
                </m.div>
              ) : undefined
            }
          />
        </AnimatePresence>
      )}
    </>
  );
}
