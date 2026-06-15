"use client";

import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/modal";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { useQuery } from "@tanstack/react-query";
import { usageApi } from "../api/usageApi";

interface UsageCatalogModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const fmt = (n: number) => (n > 0 ? n.toLocaleString() : "—");

export function UsageCatalogModal({ isOpen, onClose }: UsageCatalogModalProps) {
  const { data } = useQuery({
    queryKey: ["usageCatalog"],
    queryFn: () => usageApi.getUsageCatalog(),
    staleTime: 10 * 60 * 1000,
  });

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="2xl"
      backdrop="blur"
      scrollBehavior="inside"
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <span className="font-medium text-white">What uses credits</span>
          <span className="text-sm font-normal text-zinc-500">
            A credit is our unit of AI compute. 10,000 credits = $1.
          </span>
        </ModalHeader>
        <ModalBody className="pb-6">
          {/* Per-action cost */}
          <p className="text-xs font-medium tracking-wide text-zinc-500 uppercase">
            Cost per action
          </p>
          <div className="rounded-2xl bg-zinc-900 p-1">
            <Row
              label="Chat message"
              value={`${data?.chat_message_estimate ?? "7–80"} credits`}
            />
            {data?.action_costs.map((a) => (
              <Row
                key={a.key}
                label={a.title}
                value={`${a.credits.toLocaleString()} credits`}
              />
            ))}
          </div>

          {/* Per-plan feature limits */}
          <p className="mt-2 text-xs font-medium tracking-wide text-zinc-500 uppercase">
            Monthly limits by plan
          </p>
          <div className="rounded-2xl bg-zinc-900 p-1">
            <div className="flex items-center px-3 py-2 text-xs text-zinc-500">
              <span className="flex-1">Feature</span>
              <span className="w-20 text-right">Free</span>
              <span className="w-20 text-right">Pro</span>
              <span className="w-20 text-right">Max</span>
            </div>
            <ScrollShadow className="max-h-[40vh]">
              {data?.features.map((f) => (
                <div
                  key={f.key}
                  className="flex items-center px-3 py-2 text-sm hover:bg-white/5"
                >
                  <span className="flex-1 text-zinc-300">{f.title}</span>
                  <span className="w-20 text-right text-zinc-500">
                    {fmt(f.free.month)}
                  </span>
                  <span className="w-20 text-right text-zinc-400">
                    {fmt(f.pro.month)}
                  </span>
                  <span className="w-20 text-right text-zinc-400">
                    {fmt(f.max.month)}
                  </span>
                </div>
              ))}
            </ScrollShadow>
          </div>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 text-sm">
      <span className="text-zinc-300">{label}</span>
      <span className="text-zinc-500">{value}</span>
    </div>
  );
}
