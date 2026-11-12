// @vitest-environment jsdom
import type { ReferredFriend } from "@shared/api/generated";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { REFERRAL_UI_COPY } from "../referralCopy";
import { FriendsList } from "./FriendsList";

const JOINED = "2026-09-01T00:00:00Z";

function friend(
  first_name: string,
  status: ReferredFriend["status"],
): ReferredFriend {
  return { first_name, status, joined_at: JOINED, paid_at: null };
}

afterEach(cleanup);

describe("FriendsList", () => {
  it("shows a refunded friend as refunded, never on the way", () => {
    render(<FriendsList friends={[friend("Priya", "refunded")]} />);

    const row = screen.getByText("Priya").closest("li");
    expect(row?.textContent).toContain(REFERRAL_UI_COPY.statusRefunded);
    expect(row?.textContent).not.toContain(REFERRAL_UI_COPY.statusPending);
    expect(row?.textContent).not.toContain(REFERRAL_UI_COPY.statusPaid);
  });

  it("keeps a friend who has not paid on the way", () => {
    render(<FriendsList friends={[friend("Sam", "joined")]} />);

    expect(screen.getByText("Sam").closest("li")?.textContent).toContain(
      REFERRAL_UI_COPY.statusPending,
    );
  });
});
