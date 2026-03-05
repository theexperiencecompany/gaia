"use client";

import { Chip } from "@heroui/chip";
import { Modal, ModalContent } from "@heroui/modal";
import { Tab, Tabs } from "@heroui/tabs";

import type { Plan } from "../api/pricingApi";
import { PricingCards } from "./PricingCards";

interface PricingModalProps {
  isOpen: boolean;
  onClose: () => void;
  plans: Plan[];
}

export function PricingModal({ isOpen, onClose, plans }: PricingModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="3xl"
      radius="lg"
      backdrop="blur"
      scrollBehavior="inside"
      classNames={{
        wrapper: "overflow-hidden",
        closeButton:
          "text-zinc-400 hover:text-white hover:bg-zinc-800 top-3 right-3",
      }}
    >
      <ModalContent>
        <div className="flex flex-col items-center gap-5 py-8 overflow-y-auto">
          <div className="flex flex-col items-center gap-1.5 text-center">
            <h2 className="font-serif text-5xl font-normal tracking-tight">
              Level Up
            </h2>
            <p className="text-sm font-light text-zinc-400">
              You've been doing this manually. Let GAIA handle it.
            </p>
          </div>

          {/* Tabs + Cards */}
          <div className="w-full flex flex-col items-center">
            <Tabs aria-label="Billing period" radius="lg">
              <Tab key="monthly" title="Monthly">
                {/* Trust bar */}
                <p className="mt-3 mb-4 text-center text-xs text-zinc-600">
                  Secure payment · Cancel anytime · No credit card for Free
                </p>
                <PricingCards durationIsMonth initialPlans={plans} />
              </Tab>
              <Tab
                key="yearly"
                title={
                  <div className="flex items-center gap-2">
                    Yearly
                    <Chip color="primary" size="sm" variant="shadow">
                      <span className="text-xs font-medium">Save 25%</span>
                    </Chip>
                  </div>
                }
              >
                {/* Trust bar */}
                <p className="mt-3 mb-4 text-center text-xs text-zinc-600">
                  Secure payment · Cancel anytime · No credit card for Free
                </p>
                <PricingCards initialPlans={plans} />
              </Tab>
            </Tabs>
          </div>
        </div>
      </ModalContent>
    </Modal>
  );
}
