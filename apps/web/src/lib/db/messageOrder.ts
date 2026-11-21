import type { IMessage } from "./chatDb";

/**
 * Where a message stands in its conversation's order. The server's `seq` is
 * the order. Saved messages cached before seq existed keep their place ahead of
 * it until a sync gives them one. Sends and replies the server has not placed
 * yet come last.
 */
const ORDER_RANK = {
  cachedBeforeSeq: 0,
  placed: 1,
  notYetPlaced: 2,
} as const;

const rankOf = (message: IMessage): number => {
  if (message.seq !== undefined) return ORDER_RANK.placed;
  return message.optimistic || message.status !== "sent"
    ? ORDER_RANK.notYetPlaced
    : ORDER_RANK.cachedBeforeSeq;
};

/**
 * The one message order: by server `seq`; a message without one falls back to
 * creation order within its rank, and moves into place when its seq arrives.
 */
export const compareMessageOrder = (a: IMessage, b: IMessage): number => {
  const rankA = rankOf(a);
  const rankB = rankOf(b);
  if (rankA !== rankB) return rankA - rankB;
  if (a.seq !== undefined && b.seq !== undefined) return a.seq - b.seq;
  return a.createdAt.getTime() - b.createdAt.getTime();
};
