/**
 * GAIA's side of an onboarding turn: several lines joined with the same break
 * token chat replies use, so a stage's copy renders as chat does (one avatar,
 * a stacked group) rather than as separate messages. Given a `revealKey` the
 * lines are paced out behind a typing indicator instead of landing at once.
 */

import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";

import { OnboardingBotBubble } from "./OnboardingBotBubble";
import { OnboardingPacedBubbles } from "./OnboardingPacedBubbles";

export function OnboardingBotBubbles({
  lines,
  revealKey,
  instant,
}: {
  lines: string[];
  revealKey?: string;
  /** With a `revealKey`: this turn is history, show it at once. */
  instant?: boolean;
}) {
  if (revealKey)
    return (
      <OnboardingPacedBubbles
        lines={lines}
        revealKey={revealKey}
        instant={instant}
      />
    );
  return <OnboardingBotBubble text={lines.join(NEW_MESSAGE_BREAK_TOKEN)} />;
}
