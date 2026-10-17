import { describe, expect, it } from "vitest";
import { releaseHighlights } from "../../src/lib/release-notes.js";

// Shape verbatim from the cli-v0.6.0 GitHub release (release-please).
const BODY = `## [0.6.0](https://github.com/theexperiencecompany/gaia/compare/cli-v0.5.0...cli-v0.6.0) (2026-09-13)


### Features

* **ci:** run CI on the home server with GitHub fallback ([#1131](https://github.com/theexperiencecompany/gaia/issues/1131)) ([f38a9e6](https://github.com/theexperiencecompany/gaia/commit/f38a9e6))
* expose custom and device-hosted MCP servers to the agent from chat ([#1208](https://github.com/theexperiencecompany/gaia/issues/1208)) ([9e97335](https://github.com/theexperiencecompany/gaia/commit/9e97335))


### Bug Fixes

* **desktop:** repair splash, window lifecycle and next-server prepare ([#1222](https://github.com/theexperiencecompany/gaia/issues/1222)) ([b677ec0](https://github.com/theexperiencecompany/gaia/commit/b677ec0))
`;

describe("releaseHighlights", () => {
  it("reads features, then fixes, as plain sentences without scopes or links", () => {
    expect(releaseHighlights(BODY)).toEqual([
      "Run CI on the home server with GitHub fallback",
      "Expose custom and device-hosted MCP servers to the agent from chat",
      "Repair splash, window lifecycle and next-server prepare",
    ]);
  });

  it("stops at five", () => {
    const many = Array.from({ length: 8 }, (_, i) => `* change ${i}`).join(
      "\n",
    );
    expect(releaseHighlights(`### Features\n${many}`)).toHaveLength(5);
  });

  it("has none for a release whose notes list no changes (a beta)", () => {
    expect(
      releaseHighlights(
        "Beta of the GAIA CLI. Install it with: curl -fsSL https://heygaia.io/install.sh | GAIA_CHANNEL=beta sh",
      ),
    ).toEqual([]);
  });
});
