"use client";

import { Button } from "@heroui/button";
import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/modal";
import NumberFlow from "@number-flow/react";
import { useQuery } from "@tanstack/react-query";
import posthog from "posthog-js";
import { useState } from "react";
import { TextMorph } from "torph/react";
import { cn } from "@/lib/utils";
import { usageApi } from "../api/usageApi";

interface TopUpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

// Rough outcome translation so an abstract credit count reads as something real.
function outcomeFor(credits: number): string {
  const messages = Math.round(credits / 15);
  const research = Math.round(credits / 1000);
  return `about ${messages.toLocaleString()} messages or ${research} deep-research runs`;
}

export function TopUpModal({ isOpen, onClose }: TopUpModalProps) {
  const { data: packs } = useQuery({
    queryKey: ["creditPacks"],
    queryFn: () => usageApi.getCreditPacks(),
    staleTime: 5 * 60 * 1000,
  });
  const [selected, setSelected] = useState(1);
  const [loading, setLoading] = useState(false);

  const pack = packs?.[Math.min(selected, (packs?.length ?? 1) - 1)];

  const handleBuy = async () => {
    if (!pack) return;
    setLoading(true);
    posthog.capture("credit_topup_checkout_started", {
      pack_key: pack.key,
      credits: pack.credits,
      price_cents: pack.price_cents,
    });
    try {
      const { payment_link } = await usageApi.purchaseCreditPack(pack.key);
      window.location.href = payment_link;
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg" backdrop="blur">
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <span className="font-medium text-white">Top up credits</span>
          <span className="text-sm font-normal text-zinc-500">
            Purchased credits never reset and stay valid for 12 months.
          </span>
        </ModalHeader>
        <ModalBody className="pb-6">
          <div className="grid grid-cols-3 gap-2">
            {packs?.map((p, i) => (
              <button
                key={p.key}
                type="button"
                onClick={() => setSelected(i)}
                className={cn(
                  "rounded-2xl p-3 text-left transition-colors",
                  i === selected
                    ? "bg-primary/15 ring-1 ring-primary/40"
                    : "bg-zinc-800/60 hover:bg-zinc-800",
                )}
              >
                <p className="text-sm font-medium text-white">
                  {p.credits.toLocaleString()}
                </p>
                <p className="text-xs text-zinc-500">credits</p>
                <p className="mt-2 text-sm text-zinc-300">
                  ${(p.price_cents / 100).toFixed(0)}
                </p>
              </button>
            ))}
          </div>

          <div className="mt-2 rounded-2xl bg-zinc-900 p-4 text-center">
            <div className="flex items-baseline justify-center gap-1.5">
              <NumberFlow
                value={pack?.credits ?? 0}
                className="text-3xl font-semibold text-white"
              />
              <span className="text-sm text-zinc-500">credits</span>
            </div>
            <TextMorph
              as="p"
              className="mt-1 text-xs text-zinc-500"
              ease={{ stiffness: 200, damping: 20 }}
            >
              {outcomeFor(pack?.credits ?? 0)}
            </TextMorph>
          </div>

          <Button
            color="primary"
            className="mt-1 w-full font-medium"
            isLoading={loading}
            onPress={handleBuy}
          >
            {pack
              ? `Buy for $${(pack.price_cents / 100).toFixed(0)}`
              : "Top up"}
          </Button>
          <p className="text-center text-xs text-zinc-600">
            Secure payment. Cancel anytime.
          </p>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
