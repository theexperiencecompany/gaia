import { ArrowUp02Icon } from "@icons";
import { SlackDemoBase } from "../SlackDemoBase";

const phase1Content = (
  <p className="text-sm text-zinc-300">
    Good morning. Portfolio health: 4/6 clients on track · ByteScale 3 days
    behind · Momentum scope creep risk · 2 proposals due this week
  </p>
);

const phase3Response = (
  <>
    DataFlow SEO campaign (Month 2 of 6): 48 target keywords — 31 ranking on
    page 1 (
    <ArrowUp02Icon
      width={12}
      height={12}
      className="inline-block align-middle text-emerald-400"
    />{" "}
    from 19 last month). Organic traffic: +34% MoM. Monthly report is due Monday
    — want me to draft it from Google Analytics and Sheets data?
  </>
);

export function AgencySlackDemo() {
  return (
    <SlackDemoBase
      channel="agency-ops"
      phase1Content={phase1Content}
      phase2Time="9:31 AM"
      phase2Question="what's the status on the DataFlow SEO campaign?"
      phase3Time="9:31 AM"
      phase3Response={phase3Response}
    />
  );
}
