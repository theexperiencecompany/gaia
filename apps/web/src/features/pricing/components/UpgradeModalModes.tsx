"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { ModalBody } from "@heroui/modal";
import { Tab, Tabs } from "@heroui/tabs";
import type { ReactNode } from "react";
import { RaisedButton } from "@/components/ui/raised-button";

import type { Plan } from "../api/pricingApi";
import type { PaywallCopy } from "../constants";
import {
  type CheckoutPhase,
  isCheckoutSettled,
} from "../stores/checkoutOverlayStore";
import { CheckoutConfirming } from "./CheckoutConfirming";
import { PlanFeature } from "./PlanFeature";
import { PricingCards } from "./PricingCards";

interface UpgradeModalPlanPickerProps {
  offerMessage: string | null | undefined;
  discountBanner: ReactNode;
  plans: Plan[];
}

/** Voluntary mode: the full plan picker (monthly/yearly tabs + cards). */
export function UpgradeModalPlanPicker({
  offerMessage,
  discountBanner,
  plans,
}: UpgradeModalPlanPickerProps) {
  return (
    <div className="flex flex-col items-center gap-5 py-8 overflow-y-auto">
      <div className="flex flex-col items-center gap-1.5 text-center">
        <h2 className="font-serif text-5xl font-normal tracking-tight">
          Level Up
        </h2>
        <p className="text-sm font-light text-zinc-400">
          {offerMessage ??
            "You've been doing this manually. Let GAIA handle it."}
        </p>
      </div>

      {discountBanner}

      <div className="w-full flex flex-col items-center px-5">
        <Tabs aria-label="Billing period" radius="lg">
          <Tab key="monthly" title="Monthly">
            <p className="mt-3 mb-4 text-center text-xs text-zinc-600">
              Secure payment · Cancel anytime
            </p>
            <PricingCards durationIsMonth initialPlans={plans} hideEnterprise />
          </Tab>
          <Tab
            key="yearly"
            title={
              <div className="flex items-center gap-2">
                Yearly
                <Chip color="primary" size="sm" variant="shadow">
                  <span className="text-xs font-medium">2 months free</span>
                </Chip>
              </div>
            }
          >
            <p className="mt-3 mb-4 text-center text-xs text-zinc-600">
              Secure payment · Cancel anytime
            </p>
            <PricingCards initialPlans={plans} hideEnterprise />
          </Tab>
        </Tabs>
      </div>
    </div>
  );
}

interface UpgradeModalOfferProps {
  offerMessage: string | null | undefined;
  discountBanner: ReactNode;
  copy: PaywallCopy;
  proPlan: Plan | undefined;
  isConfirming: boolean;
  checkoutPhase: CheckoutPhase;
  onSubscribe: () => void;
  onLogout: () => void;
}

/** Enforcement mode: a compact wall around a single monthly Pro CTA. */
export function UpgradeModalOffer({
  offerMessage,
  discountBanner,
  copy,
  proPlan,
  isConfirming,
  checkoutPhase,
  onSubscribe,
  onLogout,
}: UpgradeModalOfferProps) {
  return (
    <ModalBody>
      <div className="mb-2 flex flex-col items-center gap-1.5 text-center">
        <h2 className="font-serif text-4xl font-normal tracking-tight">
          {copy.heading}
        </h2>
        <p className="text-sm font-light text-zinc-400">
          {offerMessage ?? copy.body}
        </p>
      </div>

      {discountBanner}

      {proPlan && (
        <div className="rounded-2xl bg-zinc-800/50 p-5">
          <div className="flex flex-col gap-2">
            {proPlan.features.map((feature) => (
              <div
                key={feature}
                className="flex items-start gap-2 text-sm font-light"
              >
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-primary" />
                <PlanFeature feature={feature} />
              </div>
            ))}
          </div>
        </div>
      )}

      {isConfirming ? (
        <CheckoutConfirming isLate={checkoutPhase === "timeout"} />
      ) : (
        <RaisedButton
          className="w-full text-black!"
          color="#00bbff"
          onClick={onSubscribe}
          disabled={!isCheckoutSettled(checkoutPhase)}
        >
          {isCheckoutSettled(checkoutPhase)
            ? copy.subscribeCta
            : "Opening checkout..."}
        </RaisedButton>
      )}

      <Button
        variant="light"
        size="sm"
        className="mx-auto mt-1 h-auto min-w-0 p-0 text-xs text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300 data-[hover=true]:underline"
        onPress={() => onLogout()}
      >
        Log out
      </Button>
    </ModalBody>
  );
}
