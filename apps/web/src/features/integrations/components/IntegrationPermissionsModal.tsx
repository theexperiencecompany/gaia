"use client";

import { Modal } from "@heroui/react";
import type { IntegrationPermissions } from "@/features/integrations/hooks/useIntegrationPermissions";
import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";

import { PermissionModeDecision } from "./PermissionModeDecision";
import { PermissionToolList } from "./PermissionToolList";

interface IntegrationPermissionsModalProps {
  name: string;
  tools: IntegrationToolEntry[];
  permissions: IntegrationPermissions;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Where an integration's approvals are configured: two titled cards, one per
 * decision — when GAIA stops, and which tools it may stop on. No footer,
 * because every change saves on the spot.
 */
export const IntegrationPermissionsModal = ({
  name,
  tools,
  permissions,
  isOpen,
  onOpenChange,
}: IntegrationPermissionsModalProps) => (
  <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
    <Modal.Backdrop>
      <Modal.Container size="lg">
        <Modal.Dialog>
          <Modal.CloseTrigger aria-label="Close" />
          <Modal.Header className="flex-col items-start gap-1 pb-3">
            <Modal.Heading className="text-base font-semibold text-zinc-100">
              {name} permissions
            </Modal.Heading>
            {/* Someone opening this for the first time has no idea GAIA acts on
                its own, which is the fact both cards below depend on. */}
            <span className="text-sm font-normal text-zinc-400">
              GAIA uses {name} on its own. Tell it when to stop and ask you
              first.
            </span>
          </Modal.Header>
          <Modal.Body className="gap-6 pb-6">
            <PermissionModeDecision
              integrationName={name}
              permissions={permissions}
            />
            <PermissionToolList tools={tools} permissions={permissions} />
          </Modal.Body>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  </Modal>
);
