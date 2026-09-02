"use client";

import { Kbd } from "@heroui/kbd";
import { Link } from "@heroui/link";
import {
  Button,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/react";
import { Spinner } from "@heroui/spinner";
import { KeyIcon, RedoIcon } from "@icons";
import { useCallback, useState } from "react";
import { useModalKeyboardSubmit } from "@/hooks/ui/useModalKeyboardSubmit";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { toast } from "@/lib/toast";
import { type CliConnectState, useCliConnect } from "../hooks/useCliConnect";
import type { CliConnectPhase } from "../types";

interface CliConnectModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** The integration being connected, or `null` when nothing is selected. */
  integrationId: string | null;
  integrationName: string;
}

function subtitleFor(phase: CliConnectPhase | null, name: string): string {
  switch (phase) {
    case "awaiting_approval":
      return "Approve this login to continue";
    case "needs_token":
      return `Paste a token to finish connecting ${name}`;
    case "connected":
      return `${name} is connected`;
    case "failed":
      return `${name} couldn't be connected`;
    default:
      return `Setting up ${name}`;
  }
}

/** The tool's own output, shown exactly as it was written. */
function OutputBlock({ text }: { text: string }) {
  return (
    <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-zinc-800 p-3 font-mono text-xs text-zinc-300">
      {text}
    </pre>
  );
}

interface CliConnectBodyProps {
  state: CliConnectState;
  integrationName: string;
  token: string;
  onTokenChange: (token: string) => void;
}

function CliConnectBody({
  state,
  integrationName,
  token,
  onTokenChange,
}: CliConnectBodyProps) {
  if (state.phase === "failed") {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-danger">
          {state.error ?? "Connection failed"}
        </p>
        {state.instructions && <OutputBlock text={state.instructions} />}
      </div>
    );
  }

  if (state.phase === "needs_token") {
    return (
      <div className="flex flex-col gap-2">
        <Input
          label={state.tokenLabel ?? "Access token"}
          placeholder="Paste your token"
          value={token}
          onValueChange={onTokenChange}
          type="password"
          isRequired
          autoFocus
          startContent={<KeyIcon width={16} height={16} />}
        />
        {state.tokenHelpUrl && (
          <Link href={state.tokenHelpUrl} isExternal size="sm">
            Get a token
          </Link>
        )}
      </div>
    );
  }

  if (state.phase === "awaiting_approval") {
    return (
      <div className="flex flex-col gap-3">
        {state.instructions ? (
          <OutputBlock text={state.instructions} />
        ) : (
          <p className="text-sm text-zinc-400">
            {state.message ?? "Starting login…"}
          </p>
        )}
        {state.approvalUrl && (
          <div>
            <Button
              as={Link}
              href={state.approvalUrl}
              isExternal
              variant="flat"
              color="primary"
              size="sm"
            >
              Open approval page
            </Button>
          </div>
        )}
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <Spinner size="sm" />
          Waiting for you to approve
        </div>
      </div>
    );
  }

  if (state.phase === "connected") {
    return (
      <p className="text-sm text-zinc-400">
        {integrationName} is ready to use.
      </p>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm text-zinc-400">
      <Spinner size="sm" />
      Installing {integrationName}…
    </div>
  );
}

/**
 * Connect flow for integrations GAIA drives through a vendor's own tool.
 *
 * The connection advances a step at a time on the backend, so this stays open
 * across the whole run: it shows what the tool is doing, relays the approval
 * text it prints, collects a token when the vendor asks for one, and closes
 * itself the moment the connection is live.
 */
export const CliConnectModal: React.FC<CliConnectModalProps> = ({
  isOpen,
  onClose,
  integrationId,
  integrationName,
}) => {
  const { isMac, modifierKeyName } = usePlatform();
  const [token, setToken] = useState("");

  const handleClose = useCallback(() => {
    setToken("");
    onClose();
  }, [onClose]);

  const handleConnected = useCallback(
    (name: string) => {
      toast.success(`Connected to ${name}`);
      handleClose();
    },
    [handleClose],
  );

  const { state, submitToken, retry } = useCliConnect({
    // Clearing the id while closed is what stops the flow — the hook idles on
    // `null` instead of polling behind a hidden modal.
    integrationId: isOpen ? integrationId : null,
    onConnected: handleConnected,
  });

  const canSubmitToken =
    state.phase === "needs_token" &&
    token.trim().length > 0 &&
    !state.isSubmittingToken;

  const handleSubmitToken = useCallback(() => {
    if (!canSubmitToken) return;
    submitToken(token.trim());
  }, [canSubmitToken, submitToken, token]);

  useModalKeyboardSubmit({
    isOpen,
    loading: state.isSubmittingToken,
    isMac,
    handleSubmit: handleSubmitToken,
  });

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      placement="center"
      size="md"
      className="shadow-none rounded-2xl"
      backdrop="blur"
      isDismissable={!state.isSubmittingToken}
      isKeyboardDismissDisabled={state.isSubmittingToken}
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold">Connect {integrationName}</h2>
          <p className="text-sm font-normal text-zinc-400">
            {subtitleFor(state.phase, integrationName)}
          </p>
        </ModalHeader>

        <ModalBody>
          <CliConnectBody
            state={state}
            integrationName={integrationName}
            token={token}
            onTokenChange={setToken}
          />
        </ModalBody>

        <ModalFooter>
          <Button
            color="default"
            variant="light"
            onPress={handleClose}
            isDisabled={state.isSubmittingToken}
          >
            {state.phase === "failed" ? "Close" : "Cancel"}
          </Button>

          {state.phase === "needs_token" && (
            <Button
              color="primary"
              onPress={handleSubmitToken}
              isLoading={state.isSubmittingToken}
              isDisabled={!canSubmitToken}
              endContent={
                !state.isSubmittingToken && (
                  <Kbd keys={[modifierKeyName, "enter"]} />
                )
              }
            >
              Connect
            </Button>
          )}

          {state.phase === "failed" && (
            <Button
              color="primary"
              onPress={retry}
              startContent={<RedoIcon width={16} height={16} />}
            >
              Try again
            </Button>
          )}
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
