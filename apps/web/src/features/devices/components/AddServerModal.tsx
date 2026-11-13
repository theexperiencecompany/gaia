"use client";

import {
  Button,
  Description,
  Input,
  Label,
  ListBox,
  Modal,
  Select,
  TextArea,
  TextField,
  useOverlayState,
} from "@heroui/react";
import { PlusSignIcon } from "@icons";
import type { AddOptions } from "@shared/bridge-core/config-builders";
import { useState } from "react";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";

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
  const { isOpen, open, close, setOpen } = useOverlayState();
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
      close();
    }
  };

  const activeHint = SERVER_TYPES.find((t) => t.key === type)?.hint;

  return (
    <>
      <GaiaButton size="sm" variant="default-soft" onPress={open}>
        <PlusSignIcon className="size-4" />
        Add server
      </GaiaButton>
      <Modal isOpen={isOpen} onOpenChange={setOpen}>
        <Modal.Backdrop>
          <Modal.Container placement="center">
            <Modal.Dialog>
              <Modal.CloseTrigger aria-label="Close" />
              <Modal.Header>
                <Modal.Heading>Add an MCP server</Modal.Heading>
              </Modal.Header>
              <Modal.Body className="gap-3">
                <Select
                  className={fieldVariants({ labelPlacement: "inside" })}
                  selectedKey={type}
                  onSelectionChange={(key) => {
                    if (key != null) setType(key as ServerType);
                  }}
                >
                  <Label>Type</Label>
                  <Select.Trigger>
                    <GaiaSelectValue />
                    <Select.Indicator />
                  </Select.Trigger>
                  <Select.Popover>
                    <ListBox>
                      {SERVER_TYPES.map((option) => (
                        <ListBox.Item
                          key={option.key}
                          id={option.key}
                          textValue={option.label}
                        >
                          {option.label}
                        </ListBox.Item>
                      ))}
                    </ListBox>
                  </Select.Popover>
                  {activeHint ? <Description>{activeHint}</Description> : null}
                </Select>

                <TextField
                  className={fieldVariants({ labelPlacement: "inside" })}
                  value={name}
                  onChange={setName}
                  isRequired
                >
                  <Label>Name</Label>
                  <Input placeholder={NAME_PLACEHOLDER[type]} />
                </TextField>

                {type === "stdio" ? (
                  <>
                    <TextField
                      className={fieldVariants({ labelPlacement: "inside" })}
                      value={command}
                      onChange={setCommand}
                    >
                      <Label>Command</Label>
                      <Input placeholder="npx -y @modelcontextprotocol/server-everything" />
                    </TextField>
                    <TextField
                      className={fieldVariants({ labelPlacement: "inside" })}
                      value={pairs}
                      onChange={setPairs}
                    >
                      <Label>Environment (optional)</Label>
                      <TextArea
                        placeholder={"KEY=value\nAPI_TOKEN=..."}
                        rows={2}
                      />
                    </TextField>
                  </>
                ) : (
                  <>
                    <TextField
                      className={fieldVariants({ labelPlacement: "inside" })}
                      value={url}
                      onChange={setUrl}
                    >
                      <Label>URL</Label>
                      <Input placeholder="http://localhost:3000/mcp" />
                    </TextField>
                    <TextField
                      className={fieldVariants({ labelPlacement: "inside" })}
                      value={pairs}
                      onChange={setPairs}
                    >
                      <Label>Headers (optional)</Label>
                      <TextArea
                        placeholder={"Authorization: Bearer ..."}
                        rows={2}
                      />
                    </TextField>
                  </>
                )}
              </Modal.Body>
              <Modal.Footer>
                <Button variant="ghost" onPress={close}>
                  Cancel
                </Button>
                <Button
                  onPress={submit}
                  isPending={isBusy}
                  isDisabled={name.trim().length === 0}
                  variant="primary"
                >
                  Add
                </Button>
              </Modal.Footer>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </>
  );
}
