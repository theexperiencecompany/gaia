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

export default function SlackDemo() {
  return (
    <SlackDemoBase
      channel="engineering-standup"
      phase1Content={phase1Content}
      phase2Time="9:03 AM"
      phase2Question="What's blocking the auth refactor?"
      phase3Time="9:03 AM"
      phase3Response="2 blockers on feat/auth-refactor: Alex's PR needs your review (23 files changed), and Maya is waiting on the API schema decision from Monday's thread. Both are merge-blocking."
    />
  );
}
