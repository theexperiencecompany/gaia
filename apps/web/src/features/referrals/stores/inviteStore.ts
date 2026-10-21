import type {
  ReferralInviteStatus,
  ReferralInviteSurface,
} from "@shared/api/generated";
import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { track } from "@/lib/analytics";

/** The "sending" beat before the undo window opens, so the click reads as acknowledged. */
const INVITE_ACK_MS = 600;
/** How long an invite is held client-side, undoable, before it is sent. */
const INVITE_UNDO_MS = 5000;

export type InvitePhase =
  | { phase: "sending" }
  | { phase: "held" }
  | { phase: "committing" }
  | { phase: "done"; status: ReferralInviteStatus };

/** Sends one invite for real; the server's verdict decides the final label. */
export type InviteSender = (
  email: string,
  surface: ReferralInviteSurface,
) => Promise<ReferralInviteStatus>;

type UndoableSurface = Exclude<ReferralInviteSurface, "agent">;

interface InviteStore {
  invites: Record<string, InvitePhase>;
  invite: (email: string, surface: UndoableSurface, send: InviteSender) => void;
  undo: (email: string, surface: UndoableSurface) => void;
}

// Timers live outside state: the card that started a hold can unmount (a
// hover card closes) without dropping or duplicating the send.
const timers = new Map<string, ReturnType<typeof setTimeout>[]>();

function clearTimers(email: string) {
  for (const timer of timers.get(email) ?? []) clearTimeout(timer);
  timers.delete(email);
}

const key = (email: string) => email.trim().toLowerCase();

export const useInviteStore = create<InviteStore>()(
  devtools(
    (set, get) => {
      const setPhase = (email: string, phase: InvitePhase, action: string) =>
        set(
          (state) => ({ invites: { ...state.invites, [email]: phase } }),
          false,
          action,
        );

      const commit = async (
        email: string,
        surface: UndoableSurface,
        send: InviteSender,
      ) => {
        timers.delete(email);
        setPhase(email, { phase: "committing" }, "invite/commit");
        try {
          const status = await send(email, surface);
          setPhase(email, { phase: "done", status }, "invite/done");
        } catch {
          // The API client already toasted and reported the failure; free the button for a retry.
          set(
            (state) => {
              const { [email]: _failed, ...rest } = state.invites;
              return { invites: rest };
            },
            false,
            "invite/rollback",
          );
        }
      };

      return {
        invites: {},
        invite: (rawEmail, surface, send) => {
          const email = key(rawEmail);
          if (get().invites[email]) return;
          setPhase(email, { phase: "sending" }, "invite/sending");
          timers.set(email, [
            setTimeout(
              () => setPhase(email, { phase: "held" }, "invite/held"),
              INVITE_ACK_MS,
            ),
            setTimeout(
              () => void commit(email, surface, send),
              INVITE_ACK_MS + INVITE_UNDO_MS,
            ),
          ]);
        },
        undo: (rawEmail, surface) => {
          const email = key(rawEmail);
          const current = get().invites[email]?.phase;
          if (current !== "sending" && current !== "held") return;
          clearTimers(email);
          set(
            (state) => {
              const { [email]: _undone, ...rest } = state.invites;
              return { invites: rest };
            },
            false,
            "invite/undo",
          );
          track("referral:invite_undone", { surface });
        },
      };
    },
    { name: "referral-invites" },
  ),
);

export const useInvitePhase = (email: string): InvitePhase | undefined =>
  useInviteStore((s) => s.invites[key(email)]);
