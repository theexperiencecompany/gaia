import { describe, expect, it } from "vitest";
import type { HoloCardDisplayData } from "@/components/ui/holo-card/types";
import { mergeIncomingCard } from "@/components/ui/holo-card/utils";

// What the API returns before Gmail is connected: a placeholder bio and the
// generic name, plus whatever overlay the user has saved.
const BEFORE_CONNECT: HoloCardDisplayData = {
  house: "bluehaven",
  name: "Dev User",
  personality_phrase: "",
  user_bio: "Connect your Gmail for a more personalized bio",
  account_number: "#1",
  member_since: "2026",
  overlay_color: "rgba(0,0,0,0)",
  overlay_opacity: 40,
  holo_card_id: "card-1",
};

// The same card after ProfileCardSettings refetches on a successful connect —
// a new object with a generated bio and name, overlay untouched.
const AFTER_CONNECT: HoloCardDisplayData = {
  ...BEFORE_CONNECT,
  name: "Aryan",
  personality_phrase: "builds things that build things",
  user_bio: "Ships full-stack systems and argues with linters.",
};

describe("mergeIncomingCard", () => {
  it("adopts every field of a refetched card, not just the overlay", () => {
    const merged = mergeIncomingCard(
      BEFORE_CONNECT,
      AFTER_CONNECT,
      BEFORE_CONNECT,
    );

    // The editor renders the merged copy, so a field left behind here is a
    // field the user keeps seeing stale on the card.
    expect(merged.user_bio).toBe(AFTER_CONNECT.user_bio);
    expect(merged.name).toBe("Aryan");
    expect(merged.personality_phrase).toBe(AFTER_CONNECT.personality_phrase);
  });

  it("keeps an in-progress overlay pick when the refetch carries the same overlay", () => {
    // User dragged the opacity slider and picked a colour; neither has been
    // saved back, so the incoming card still has the old overlay values.
    const beingEdited: HoloCardDisplayData = {
      ...BEFORE_CONNECT,
      overlay_color: "rgb(255,0,0)",
      overlay_opacity: 88,
    };

    const merged = mergeIncomingCard(
      beingEdited,
      AFTER_CONNECT,
      BEFORE_CONNECT,
    );

    expect(merged.overlay_color).toBe("rgb(255,0,0)");
    expect(merged.overlay_opacity).toBe(88);
    // ...while the rest of the refetch still lands.
    expect(merged.user_bio).toBe(AFTER_CONNECT.user_bio);
  });

  it("takes the server overlay when the refetched card genuinely changed it", () => {
    const serverChangedOverlay: HoloCardDisplayData = {
      ...AFTER_CONNECT,
      overlay_color: "rgb(0,0,255)",
      overlay_opacity: 12,
    };
    const beingEdited: HoloCardDisplayData = {
      ...BEFORE_CONNECT,
      overlay_color: "rgb(255,0,0)",
      overlay_opacity: 88,
    };

    const merged = mergeIncomingCard(
      beingEdited,
      serverChangedOverlay,
      BEFORE_CONNECT,
    );

    expect(merged.overlay_color).toBe("rgb(0,0,255)");
    expect(merged.overlay_opacity).toBe(12);
  });
});
