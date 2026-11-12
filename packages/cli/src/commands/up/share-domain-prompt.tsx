/**
 * The share-domain question `gaia up --domain` may ask: a domain for short
 * links or for shared files, or Enter to go without it.
 * @module commands/up/share-domain-prompt
 */

import { TextInput } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { SHARE_DOMAIN_INPUT } from "../../lib/share-domains.js";
import type {
  ShareDomainKind,
  ShareDomainRequest,
} from "../../lib/share-domains.types.js";
import { wrapToWidth } from "../../lib/terminal-text.js";
import { Mark } from "../../ui/components/Mark.js";
import { useCardWidth } from "../../ui/components/use-card-width.js";
import type { CLIStore } from "../../ui/store.js";

const LABELS: Record<ShareDomainKind, string> = {
  link: "Short-link domain",
  usercontent: "Shared-files domain",
};

function hint(request: ShareDomainRequest): string {
  return request.kind === "link"
    ? `Optional. Links you share become https://<domain>/<code> instead of https://${request.appDomain}/l/<code>. Point its DNS here first. Press Enter to skip.`
    : "Optional. Shared HTML and PDF files open in the page instead of as source or a download. Use a domain apart from GAIA's and point its DNS here first. Press Enter to skip.";
}

export const ShareDomainPrompt: React.FC<{
  store: CLIStore;
  request: ShareDomainRequest;
}> = ({ store, request }) => {
  const width = useCardWidth();
  return (
    <Box flexDirection="column" marginTop={1}>
      {request.retry && (
        <Box>
          <Mark kind="fail" />
          <Text>{wrapToWidth(request.retry, width - 4)}</Text>
        </Box>
      )}
      <Text dimColor>{wrapToWidth(hint(request), width)}</Text>
      <Box>
        <Text bold>{LABELS[request.kind]}: </Text>
        <TextInput
          placeholder={`e.g. ${request.kind === "link" ? "go" : "files"}.${request.appDomain}`}
          onSubmit={(value) => store.submitInput(SHARE_DOMAIN_INPUT, value)}
        />
      </Box>
    </Box>
  );
};
