import { DemoFinalCard } from "../DemoFinalCards";
import { SlackDemoBase } from "../SlackDemoBase";

const phase1Content = (
  <>
    <p className="mb-3 text-sm text-zinc-300">
      Good morning. Here&apos;s today&apos;s standup:
    </p>
    <div className="w-fit outline-1 outline-zinc-800 rounded-2xl">
      <DemoFinalCard type="workflow" />
    </div>
  </>
);

export function SoftwareDevSlackDemo() {
  return (
    <SlackDemoBase
      channel="engineering-general"
      phase1Content={phase1Content}
      phase2Time="9:04 AM"
      phase2Question="what's the current status of the payments integration?"
      phase3Time="9:04 AM"
      phase3Response="The payments integration (ENG-380) is 80% done. feat/payments-stripe was merged last Thursday. Remaining: webhook handling (ENG-391, in review by Alex) and error states (ENG-394, not started). Estimated ship: next Monday."
    />
  );
}
