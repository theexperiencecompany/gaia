"use client";

import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/modal";
import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { usageApi } from "../api/usageApi";

interface UsageCatalogModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function UsageCatalogModal({ isOpen, onClose }: UsageCatalogModalProps) {
  const { data } = useQuery({
    queryKey: ["usageCatalog"],
    queryFn: () => usageApi.getUsageCatalog(),
    staleTime: 10 * 60 * 1000,
  });

  const actionRows = [
    {
      key: "chat",
      label: "Typical message",
      credits: data?.chat_message_estimate ?? "7–80",
    },
    ...(data?.action_costs ?? []).map((a) => ({
      key: a.key,
      label: a.title,
      credits: a.credits.toLocaleString(),
    })),
  ];

  const planRows = data
    ? (["free", "pro", "max"] as const).map((key) => ({
        key,
        label: key === "max" ? "Max" : key === "pro" ? "Pro" : "Free",
        credits: data.plan_credits[key].toLocaleString(),
      }))
    : [];

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
          <span className="text-lg font-medium text-white">
            What uses credits
          </span>
          <span className="text-sm font-normal text-zinc-500">
            A credit is our unit of AI compute. 10,000 credits = $1.
          </span>
        </ModalHeader>
        <ModalBody className="gap-5 pb-6">
          <p className="text-sm text-zinc-400">
            Everything the assistant does — every message and action — draws
            from one shared balance. Most things cost a little; a few cost more.
          </p>

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium text-zinc-300">Credit cost</h3>
            <Table aria-label="Credit cost" removeWrapper>
              <TableHeader>
                <TableColumn>Action</TableColumn>
                <TableColumn align="end">Credits</TableColumn>
              </TableHeader>
              <TableBody items={actionRows}>
                {(row) => (
                  <TableRow key={row.key}>
                    <TableCell>{row.label}</TableCell>
                    <TableCell>{row.credits}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium text-zinc-300">
              Monthly credits by plan
            </h3>
            <Table aria-label="Monthly credits by plan" removeWrapper>
              <TableHeader>
                <TableColumn>Plan</TableColumn>
                <TableColumn align="end">Credits / month</TableColumn>
              </TableHeader>
              <TableBody items={planRows}>
                {(row) => (
                  <TableRow key={row.key}>
                    <TableCell>{row.label}</TableCell>
                    <TableCell>{row.credits}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </section>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
