// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";

/**
 * A device MCP integration has no icon_url and an id that matches no known
 * category, so getToolCategoryIcon returns null — which used to render a blank
 * space on the integrations page. IntegrationIcon must always render something,
 * and a device integration (category="device") gets its own computer glyph
 * rather than the generic package fallback.
 */
describe("IntegrationIcon", () => {
  it("renders a fallback glyph when there is no category icon and no iconUrl", () => {
    const { container } = render(
      <IntegrationIcon integrationId="device-uuid-no-config" iconUrl={null} />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("renders a glyph for a device integration with no icon_url", () => {
    const { container } = render(
      <IntegrationIcon
        integrationId="device-uuid-no-config"
        iconUrl={null}
        category="device"
      />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("gives a device integration a different glyph than the generic fallback", () => {
    // Same icon-less id; only the category differs. If the device branch is
    // removed, both render the package glyph and this goes red.
    const device = render(
      <IntegrationIcon integrationId="x" iconUrl={null} category="device" />,
    );
    const generic = render(
      <IntegrationIcon integrationId="x" iconUrl={null} />,
    );
    expect(device.container.innerHTML).not.toBe(generic.container.innerHTML);
  });
});
