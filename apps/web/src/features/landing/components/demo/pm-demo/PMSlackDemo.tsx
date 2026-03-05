import { Alert01Icon } from "@icons";
import { SlackDemoBase } from "../SlackDemoBase";

const phase1Content = (
  <p className="text-sm text-zinc-300">
    Good morning. Sprint 24 status: 14/22 tickets done. 3 blocked. Mobile
    checkout is on track.{" "}
    <Alert01Icon
      width={14}
      height={14}
      className="inline-block align-middle text-amber-400"
    />{" "}
    ENG-445 needs a decision before planning.
  </p>
);

export default function PMSlackDemo() {
  return (
    <SlackDemoBase
      channel="product-team"
      phase1Content={phase1Content}
      phase2Time="9:18 AM"
      phase2Question="what's the current status of the search feature?"
      phase3Time="9:18 AM"
      phase3Response="Search feature (ENG-390) is shipped — v2.3.0, merged Feb 28. Known issue: timeout on >10k results (ENG-412, in progress, assigned to Alex, targeting next sprint). The user-reported timeout bug was fixed yesterday in v2.4.1."
    />
  );
}

export { PMSlackDemo };
