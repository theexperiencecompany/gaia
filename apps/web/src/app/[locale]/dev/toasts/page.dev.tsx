"use client";

import { Button } from "@heroui/button";
import { toast } from "@/lib/toast";

const LONG_MESSAGE =
  "This is a deliberately long toast message that exceeds fifty characters so it wraps into the description panel instead of the pill.";

interface Trigger {
  label: string;
  run: () => void;
}

interface Group {
  title: string;
  triggers: Trigger[];
}

const GROUPS: Group[] = [
  {
    title: "Variants",
    triggers: [
      {
        label: "success",
        run: () => toast.success("Workflow created successfully!"),
      },
      { label: "error", run: () => toast.error("Something went wrong.") },
      {
        label: "warning",
        run: () => toast.warning("Heads up — quota almost reached."),
      },
      { label: "info", run: () => toast.info("New version available.") },
    ],
  },
  {
    title: "With description",
    triggers: [
      {
        label: "success + description",
        run: () =>
          toast.success("Connected to GitHub", {
            description: "Repos and issues are now syncing in the background.",
          }),
      },
      {
        label: "error + description",
        run: () =>
          toast.error("Connection failed", {
            description:
              "The provider returned 403. Reconnect the integration.",
          }),
      },
      { label: "long message (wraps)", run: () => toast.info(LONG_MESSAGE) },
    ],
  },
  {
    title: "With action (+ dismiss)",
    triggers: [
      {
        label: "action button",
        run: () =>
          toast.success("Workflow created", {
            action: {
              label: "View",
              onClick: () => toast.info("Pretend we navigated."),
            },
          }),
      },
      {
        label: "action + description",
        run: () =>
          toast.error("Upload failed", {
            description: "3 of 5 files could not be processed.",
            action: { label: "Retry", onClick: () => toast.info("Retrying…") },
          }),
      },
    ],
  },
  {
    title: "Sticky / loading",
    triggers: [
      {
        label: "sticky (duration: Infinity)",
        run: () =>
          toast.info("This stays until dismissed.", { duration: Infinity }),
      },
      {
        label: "loading → success",
        run: () => {
          const id = toast.loading("Connecting to Gmail…");
          setTimeout(() => toast.success("Connected to Gmail", { id }), 1500);
        },
      },
      {
        label: "loading → error",
        run: () => {
          const id = toast.loading("Saving workflow…");
          setTimeout(
            () => toast.error("Save failed — try again", { id }),
            1500,
          );
        },
      },
    ],
  },
  {
    title: "Edge cases",
    triggers: [
      {
        label: "dismissible: false",
        run: () =>
          toast.success("No dismiss button here", { dismissible: false }),
      },
      {
        label: "stack 4 at once",
        run: () => {
          toast.success("First");
          toast.error("Second");
          toast.warning("Third");
          toast.info("Fourth");
        },
      },
      { label: "clear all", run: () => toast.clear() },
    ],
  },
];

export default function ToastPlaygroundPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="font-medium text-2xl text-white">Toast playground</h1>
      <p className="mt-1 text-sm text-zinc-400">
        Dev-only. Trigger every toast pattern used across the app and verify the
        default dismiss button, action + dismiss, and width.
      </p>

      <div className="mt-8 flex flex-col gap-8">
        {GROUPS.map((group) => (
          <section key={group.title}>
            <h2 className="mb-3 font-medium text-sm text-zinc-300">
              {group.title}
            </h2>
            <div className="flex flex-wrap gap-2">
              {group.triggers.map((t) => (
                <Button
                  key={t.label}
                  size="sm"
                  radius="full"
                  variant="flat"
                  onPress={t.run}
                >
                  {t.label}
                </Button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
