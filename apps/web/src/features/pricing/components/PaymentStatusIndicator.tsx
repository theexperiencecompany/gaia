"use client";

import { Spinner } from "@heroui/spinner";
import React from "react";

import {
  CreditCardIcon,
  SecurityCheckIcon,
  StarsIcon,
  Tick02Icon,
} from "@/icons";

import type { PaymentFlowStates } from "../hooks/usePaymentFlow";

interface PaymentStatusIndicatorProps {
  states: PaymentFlowStates;
  className?: string;
}

export function PaymentStatusIndicator({
  states,
  className = "",
}: PaymentStatusIndicatorProps) {
  const { isInitiating, isProcessing, isVerifying, isComplete, error } = states;

  if (error) {
    return (
      <div className={`flex items-center gap-2 text-red-500 ${className}`}>
        <div className="flex h-4 w-4 items-center justify-center rounded-full bg-red-500/20">
          <div className="h-2 w-2 rounded-full bg-red-500" />
        </div>
        <span className="text-sm font-medium">Payment Failed</span>
      </div>
    );
  }

  if (isComplete) {
    return (
      <div className={`flex items-center gap-2 text-green-500 ${className}`}>
        <div className="flex h-4 w-4 items-center justify-center rounded-full bg-green-500/20">
          <Tick02Icon className="h-2.5 w-2.5" />
        </div>
        <span className="text-sm font-medium">Subscription Active</span>
      </div>
    );
  }

  if (isVerifying) {
    return (
      <div className={`flex items-center gap-2 text-blue-500 ${className}`}>
        <div className="flex h-4 w-4 items-center justify-center rounded-full bg-blue-500/20">
          <Spinner size="sm" className="h-2.5 w-2.5" />
        </div>
        <span className="text-sm font-medium">Activating subscription...</span>
      </div>
    );
  }

  if (isProcessing) {
    return (
      <div className={`flex items-center gap-2 text-purple-500 ${className}`}>
        <div className="flex h-4 w-4 items-center justify-center rounded-full bg-purple-500/20">
          <SecurityCheckIcon className="h-2.5 w-2.5" />
        </div>
        <span className="text-sm font-medium">Processing payment...</span>
      </div>
    );
  }

  if (isInitiating) {
    return (
      <div className={`flex items-center gap-2 text-orange-500 ${className}`}>
        <div className="flex h-4 w-4 items-center justify-center rounded-full bg-orange-500/20">
          <CreditCardIcon className="h-2.5 w-2.5" />
        </div>
        <span className="text-sm font-medium">Preparing payment...</span>
      </div>
    );
  }

  return null;
}

interface PaymentStatusStepsProps {
  states: PaymentFlowStates;
  className?: string;
}

export function PaymentStatusSteps({
  states,
  className = "",
}: PaymentStatusStepsProps) {
  const { isInitiating, isProcessing, isVerifying, isComplete, error } = states;

  const steps = [
    {
      id: "initiate",
      label: "Initiating Payment",
      icon: CreditCardIcon,
      isActive: isInitiating,
      isCompleted: isProcessing || isVerifying || isComplete,
    },
    {
      id: "process",
      label: "Processing Payment",
      icon: SecurityCheckIcon,
      isActive: isProcessing,
      isCompleted: isVerifying || isComplete,
    },
    {
      id: "verify",
      label: "Activating Subscription",
      icon: StarsIcon,
      isActive: isVerifying,
      isCompleted: isComplete,
    },
    {
      id: "complete",
      label: "Complete",
      icon: Tick02Icon,
      isActive: isComplete,
      isCompleted: isComplete,
    },
  ];

  if (error) {
    return (
      <div
        className={`rounded-lg border border-red-200 bg-red-50 p-4 ${className}`}
      >
        <div className="flex items-center gap-2 text-red-600">
          <div className="flex h-5 w-5 items-center justify-center rounded-full bg-red-100">
            <div className="h-2 w-2 rounded-full bg-red-500" />
          </div>
          <span className="font-medium">Payment Failed</span>
        </div>
        <p className="mt-1 ml-7 text-sm text-red-600">{error}</p>
      </div>
    );
  }

  return (
    <div
      className={`rounded-lg border border-surface-700 bg-surface-950 p-4 ${className}`}
    >
      <div className="flex items-center justify-between">
        {steps.map((step, index) => {
          const Icon = step.icon;
          return (
            <React.Fragment key={step.id}>
              <div className="flex flex-col items-center gap-2">
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full transition-colors ${
                    step.isCompleted
                      ? "bg-green-500 text-foreground-50"
                      : step.isActive
                        ? "bg-blue-500 text-foreground-50"
                        : "bg-surface-800 text-foreground-500"
                  }`}
                >
                  {step.isActive && !step.isCompleted ? (
                    <Spinner size="sm" className="h-4 w-4" />
                  ) : (
                    <Icon className="h-4 w-4" />
                  )}
                </div>
                <span
                  className={`text-center text-xs font-medium ${
                    step.isCompleted
                      ? "text-green-600"
                      : step.isActive
                        ? "text-blue-600"
                        : "text-foreground-500"
                  }`}
                >
                  {step.label}
                </span>
              </div>
              {index < steps.length - 1 && (
                <div
                  className={`mx-2 h-0.5 flex-1 ${
                    step.isCompleted ? "bg-green-500" : "bg-surface-200"
                  }`}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
