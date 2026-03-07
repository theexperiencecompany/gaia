import { Alert01Icon } from "@icons";
import { SlackDemoBase } from "../SlackDemoBase";

const phase1Content = (
  <p className="text-sm text-zinc-300">
    Sprint 24, Day 6: 14/22 done. 3 blocked.{" "}
    <Alert01Icon
      width={14}
      height={14}
      className="inline-block align-middle text-amber-400"
    />{" "}
    PR #214 needs review · Dev K. out until Thursday
  </p>
);

export default function EMSlackDemo() {
  return (
    <SlackDemoBase
      channel="engineering"
      phase1Content={phase1Content}
      phase2Time="9:22 AM"
      phase2Question="what's the status on the payments integration?"
      phase3Time="9:22 AM"
      phase3Response="Payments integration (ENG-380) is 80% done. feat/payments-stripe merged last Thursday. Remaining: webhook handling (ENG-391, in review by Alex — 3 days) and error states (ENG-394, not started). Estimated ship: Monday if ENG-391 merges today."
    />
  );
}

export { EMSlackDemo };
