import { Box, Text, useStdout } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import { CLI_VERSION } from "../../lib/version.js";
import {
  type HeaderOptions,
  terminalColourLevel,
  terminalFacts,
} from "../header/header-lines.js";
import { availableUpdate, probeInstance } from "../header/instance.js";
import { type InstanceStatus, renderHeader } from "../header/render.js";

/**
 * The baked GAIA logo with version, tagline, instance status and update
 * notice; the status line appears once the time-boxed probe answers.
 */
export const Header: React.FC<HeaderOptions> = ({
  size = "small",
  showStatus = true,
  showUpdate = true,
}) => {
  const { stdout } = useStdout();
  const [status, setStatus] = useState<InstanceStatus | null>(null);
  const [update] = useState(() => (showUpdate ? availableUpdate() : null));

  useEffect(() => {
    if (!showStatus) {
      setStatus(null);
      return;
    }
    let current = true;
    probeInstance().then((probed) => {
      if (current) setStatus(probed);
    });
    return () => {
      current = false;
    };
  }, [showStatus]);

  const lines = renderHeader({
    size,
    level: terminalColourLevel(),
    ...terminalFacts(stdout),
    version: CLI_VERSION,
    status: showStatus ? status : null,
    update,
  });

  return (
    <Box marginTop={1} marginBottom={1}>
      <Text>{lines.join("\n")}</Text>
    </Box>
  );
};
