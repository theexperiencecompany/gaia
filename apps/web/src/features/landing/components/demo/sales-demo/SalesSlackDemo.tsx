import { SlackDemoBase } from "../SlackDemoBase";

const phase1Content = (
  <p className="text-sm text-zinc-300">
    Good morning. Today&apos;s priority: Acme Corp trial expires Friday.
    Follow-up email drafted and ready to send.
  </p>
);

export function SalesSlackDemo() {
  return (
    <SlackDemoBase
      channel="sales-team"
      phase1Content={phase1Content}
      phase1Time="8:00 AM"
      phase2Time="9:14 AM"
      phase2Question="where does the TechFlow deal stand?"
      phase3Time="9:14 AM"
      phase3Response="TechFlow ($67K) is in Proposal Sent stage, day 8. Last contact March 2nd (you sent pricing). Their CFO approved budget last week per LinkedIn. Suggested next step: schedule a sign-off call with the CFO this week. Want me to draft the ask?"
    />
  );
}
