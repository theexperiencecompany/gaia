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
      size="2xl"
      backdrop="blur"
      scrollBehavior="inside"
      classNames={{
        wrapper: "overflow-hidden",
        closeButton:
          "text-zinc-400 hover:text-white hover:bg-zinc-800 top-3 right-3",
      }}
    >
      <ModalContent>
        <div className="flex flex-col items-center gap-5 px-4 pt-10 pb-8">
          {/* Header */}
          <div className="flex flex-col items-center gap-1.5 text-center">
            <h2 className="font-serif text-5xl font-normal tracking-tight">
              Level Up
            </h2>
            <p className="text-sm text-zinc-400 font-light">
              Choose the plan that matches your ambition
            </p>
          </div>

          {/* Tabs + Cards */}
          <div className="w-full flex flex-col items-center">
            <Tabs aria-label="Billing period" radius="full">
              <Tab key="monthly" title="Monthly">
                <div className="mt-4">
                  <PricingCards durationIsMonth initialPlans={plans} />
                </div>
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
                <div className="mt-4">
                  <PricingCards initialPlans={plans} />
                </div>
              </Tab>
            </Tabs>
          </div>
        </div>
      </ModalContent>
    </Modal>
  );
}
