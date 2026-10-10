"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  useDisclosure,
} from "@heroui/modal";
import { Select, SelectItem } from "@heroui/select";
import { PlusSignIcon } from "@icons";
import type { AddOptions } from "@shared/bridge-core/config-builders";
import { useState } from "react";

// Folder access is a one-switch toggle on the card (the built-in filesystem
// server); this modal is only for the user's own MCP servers.
type ServerType = "stdio" | "url";

const SERVER_TYPES: { key: ServerType; label: string; hint: string }[] = [
  {
    key: "stdio",
    label: "Command (stdio)",
    hint: "Run a local MCP server process, e.g. an npx/uvx package.",
  },
  {
    key: "url",
    label: "Local URL",
    hint: "Point at an MCP server already running on a localhost port.",
  },
];

const NAME_PLACEHOLDER: Record<ServerType, string> = {
  stdio: "Everything server",
  url: "Local API",
};

/** Split a textarea into trimmed, non-empty lines (env/header entries). */
function lines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

interface AddServerModalProps {
  /** Sends CLI-equivalent flags to the main process; resolves true on success. */
  onAdd: (opts: AddOptions) => Promise<boolean>;
  isBusy: boolean;
}

export function AddServerModal({ onAdd, isBusy }: AddServerModalProps) {
  const { isOpen, onOpen, onOpenChange, onClose } = useDisclosure();
  const [type, setType] = useState<ServerType>("stdio");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [url, setUrl] = useState("");
  const [pairs, setPairs] = useState("");

  const reset = () => {
    setType("stdio");
    setName("");
    setCommand("");
    setUrl("");
    setPairs("");
  };

  const submit = async () => {
    const opts: AddOptions =
      type === "stdio"
        ? {
            type,
            name: name.trim(),
            command: command.trim(),
            env: lines(pairs),
          }
        : { type, name: name.trim(), url: url.trim(), header: lines(pairs) };
    if (await onAdd(opts)) {
      reset();
      onClose();
    }
  };

  const activeHint = SERVER_TYPES.find((t) => t.key === type)?.hint;

  return (
    <>
      <Button
        size="sm"
        variant="flat"
        startContent={<PlusSignIcon className="size-4" />}
        onPress={onOpen}
      >
        Add server
      </Button>
      <Modal isOpen={isOpen} onOpenChange={onOpenChange} placement="center">
        <ModalContent>
          {() => (
            <>
              <ModalHeader>Add an MCP server</ModalHeader>
              <ModalBody className="gap-3">
                <Select
                  label="Type"
                  description={activeHint}
                  selectedKeys={[type]}
                  onChange={(e) => setType(e.target.value as ServerType)}
                  disallowEmptySelection
                >
                  {SERVER_TYPES.map((option) => (
                    <SelectItem key={option.key}>{option.label}</SelectItem>
                  ))}
                </Select>

                <Input
                  label="Name"
                  value={name}
                  onValueChange={setName}
                  placeholder={NAME_PLACEHOLDER[type]}
                  isRequired
                />

                {type === "stdio" ? (
                  <>
                    <Input
                      label="Command"
                      value={command}
                      onValueChange={setCommand}
                      placeholder="npx -y @modelcontextprotocol/server-everything"
                    />
                    <Textarea
                      label="Environment (optional)"
                      value={pairs}
                      onValueChange={setPairs}
                      placeholder={"KEY=value\nAPI_TOKEN=..."}
                      minRows={2}
                    />
                  </>
                ) : (
                  <>
                    <Input
                      label="URL"
                      value={url}
                      onValueChange={setUrl}
                      placeholder="http://localhost:3000/mcp"
                    />
                    <Textarea
                      label="Headers (optional)"
                      value={pairs}
                      onValueChange={setPairs}
                      placeholder={"Authorization: Bearer ..."}
                      minRows={2}
                    />
                  </>
                )}
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={onClose}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  onPress={submit}
                  isLoading={isBusy}
                  isDisabled={name.trim().length === 0}
                >
                  Add
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </>
  );
}
