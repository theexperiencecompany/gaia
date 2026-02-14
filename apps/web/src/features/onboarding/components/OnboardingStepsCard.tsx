"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Checkbox } from "@heroui/checkbox";

import {
  BubbleChatAddIcon,
  CalendarAdd01Icon,
  MailAdd01Icon,
  WorkflowCircle03Icon,
} from "@icons";
import {
  OnboardingPhase,
  useOnboardingPhaseStore,
} from "@/stores/onboardingStore";

/**
 * OnboardingStepsCard - Getting Started checklist
 *
 * This component handles the THIRD phase of user guidance:
 * 1. Initial Onboarding (name/profession/connections) - /onboarding page
 * 2. Personalization (house, bio) - ContextGatheringLoader component
 * 3. Getting Started (create email, calendar, workflow, chat) - THIS COMPONENT ✓
 *
 * Shows when phase is GETTING_STARTED or COMPLETED.
 */

interface OnboardingStep {
  id: string;
  label: string;
  icon: React.ReactNode;
  completed: boolean;
}

const steps: OnboardingStep[] = [
  {
    id: "email",
    label: "Create an email",
    icon: <MailAdd01Icon size={16} />,
    completed: true,
  },
  {
    id: "calendar",
    label: "Create a calendar event",
    icon: <CalendarAdd01Icon size={16} />,
    completed: false,
  },
  {
    id: "workflow",
    label: "Create a workflow",
    icon: <WorkflowCircle03Icon size={16} />,
    completed: false,
  },
  {
    id: "chat",
    label: "Start a conversation",
    icon: <BubbleChatAddIcon size={16} />,
    completed: false,
  },
];

export default function OnboardingStepsCard() {
  const { phase } = useOnboardingPhaseStore();

  // Only show this card when user is in getting_started or completed phase
  if (
    !phase ||
    (phase !== OnboardingPhase.GETTING_STARTED &&
      phase !== OnboardingPhase.COMPLETED)
  ) {
    console.log(
      "[OnboardingStepsCard] Not showing card. Current phase:",
      phase,
    );
    return null;
  }

  console.log("[OnboardingStepsCard] Showing card for phase:", phase);

  return (
    <div className="flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-2 shadow-xl backdrop-blur-sm overflow-hidden!">
      {/* <div className="flex items-center justify-start">
        <h3 className="text-xs font-semibold text-zinc-100">Getting Started</h3>
        <span className="text-xs text-zinc-500">0/5</span>
      </div> */}

      <Accordion defaultExpandedKeys={["1"]}>
        <AccordionItem
          key="1"
          aria-label="Getting started"
          classNames={{ trigger: "cursor-pointer", content: "overflow-hidden" }}
          title={
            <div className="flex items-center justify-start gap-2 font-normal">
              <h3 className="text-xs font-semibold text-zinc-100">
                First Steps
              </h3>
              <span className="text-xs text-zinc-500">0/5</span>
            </div>
          }
          isCompact
        >
          <div className="space-y-1">
            {steps.map((step, index) => (
              <div key={step.id} className="relative flex w-full items-center">
                {/* Vertical connecting line */}
                {index !== steps.length - 1 && (
                  <div className="absolute top-6 left-[18px] h-[calc(100%+4px)] w-[2px] border-l-1 border-dashed border-zinc-500" />
                )}

                <div className="flex w-full items-center gap-2 rounded-xl hover:bg-zinc-700/50">
                  <Checkbox
                    isSelected={step.completed}
                    lineThrough
                    className="m-0! w-full! border-dotted!"
                    classNames={{
                      wrapper: ` ${step.completed ? "" : "border-zinc-500 border-dashed! border-1 before:border-0! bg-zinc-800 "}`,
                      label: "w-[30vw]",
                    }}
                    radius="full"
                  >
                    <div className="flex w-full items-center justify-between">
                      <span className="text-sm text-zinc-300">
                        {step.label}
                      </span>
                      <span></span>
                      {step.icon}
                    </div>
                  </Checkbox>
                </div>
              </div>
            ))}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
