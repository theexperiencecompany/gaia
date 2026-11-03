"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Copy01Icon } from "@icons";
import { copyWithFeedback } from "@/lib/clipboard";
import { toast } from "@/lib/toast";
import { PAYWALL_CONCEPTS } from "./concepts";
import { feedbackMarkdown } from "./feedbackMarkdown";
import { usePaywallLabFeedback } from "./feedbackStore";

/** Overall notes plus the copy-out of every note on the page. */
export function OverallFeedback() {
  const { overall, notes, setOverall, clear } = usePaywallLabFeedback();

  const copyAll = async () => {
    if (
      await copyWithFeedback(feedbackMarkdown(PAYWALL_CONCEPTS, notes, overall))
    )
      toast.success("Feedback copied as markdown");
  };

  return (
    <section
      id="feedback"
      className="flex flex-col gap-4 rounded-2xl bg-zinc-900/60 p-5"
    >
      <div>
        <h2 className="text-xl font-semibold text-zinc-100">Overall notes</h2>
        <p className="mt-1 text-[13px] text-zinc-500">
          Saved in this browser as you type. Copy pastes every note, per
          concept, as markdown.
        </p>
      </div>
      <Textarea
        aria-label="Overall notes"
        placeholder="Which bet, which parts to combine, what's missing"
        minRows={5}
        value={overall}
        onValueChange={setOverall}
      />
      <div className="flex gap-2">
        <Button
          color="primary"
          startContent={<Copy01Icon className="h-4 w-4" />}
          onPress={copyAll}
        >
          Copy all feedback
        </Button>
        <Button variant="light" className="text-zinc-500" onPress={clear}>
          Clear notes
        </Button>
      </div>
    </section>
  );
}
