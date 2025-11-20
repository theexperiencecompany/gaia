"use client";

import { Card } from "@heroui/card";
import { Checkbox } from "@heroui/checkbox";
import {
  Mail,
  Calendar,
  Workflow,
  MessageSquare,
  Sparkles,
} from "lucide-react";

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
    icon: <Mail size={16} />,
    completed: true,
  },
  {
    id: "calendar",
    label: "Create a calendar event",
    icon: <Calendar size={16} />,
    completed: false,
  },
  {
    id: "workflow",
    label: "Create a workflow",
    icon: <Workflow size={16} />,
    completed: false,
  },
  {
    id: "chat",
    label: "Start a conversation",
    icon: <MessageSquare size={16} />,
    completed: false,
  },
  {
    id: "explore",
    label: "Explore AI features",
    icon: <Sparkles size={16} />,
    completed: false,
  },
];

export default function OnboardingStepsCard() {
  return (
    <div className="flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-4 shadow-xl backdrop-blur-sm">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-zinc-100">Getting Started</h3>
        <span className="text-xs text-zinc-500">0/5</span>
      </div>

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
                className="m-0! border-dotted!"
                classNames={{
                  wrapper: ` ${step.completed ? "" : "border-zinc-500 border-dashed! border-1 before:border-0! bg-zinc-800 "}`,
                }}
                radius="full"
              >
                <span className="text-sm text-zinc-300">{step.label}</span>
              </Checkbox>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
