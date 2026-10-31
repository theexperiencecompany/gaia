/**
 * Marketplace tool cards: the page H1 already names the product, so tool labels
 * and descriptions must not repeat it unless it disambiguates. These guard the
 * provider-prefix strip and the attributive-only description rewrite.
 */
import { describe, expect, it } from "vitest";

import {
  displayToolDescription,
  displayToolName,
} from "@/app/[locale]/(landing)/marketplace/[slug]/toolCopy";

describe("displayToolName", () => {
  it("strips the provider prefix the page title already carries", () => {
    expect(displayToolName("AIRTABLE_CREATE_RECORD", "Airtable")).toBe(
      "Create Record",
    );
  });

  it("strips a multi-word prefix", () => {
    expect(
      displayToolName("MICROSOFT_TEAMS_CREATE_MEETING", "Microsoft Teams"),
    ).toBe("Create Meeting");
  });

  it("leaves a name from another product alone", () => {
    expect(displayToolName("GITHUB_CREATE_ISSUE", "Airtable")).toBe(
      "Github Create Issue",
    );
  });

  it("keeps the label when the tool name is only the prefix", () => {
    expect(displayToolName("AIRTABLE", "Airtable")).toBe("Airtable");
  });
});

describe("displayToolDescription", () => {
  it("drops an attributive product name", () => {
    expect(
      displayToolDescription(
        "Creates a new Airtable base with specified tables and fields within a workspace.",
        "Airtable",
      ),
    ).toBe(
      "Creates a new base with specified tables and fields within a workspace.",
    );
  });

  it("keeps the article grammatical", () => {
    expect(
      displayToolDescription(
        "Creates a field in an Airtable base.",
        "Airtable",
      ),
    ).toBe("Creates a field in a base.");
  });

  it("uses the article the following noun needs", () => {
    expect(
      displayToolDescription("Adds a GitHub organization.", "GitHub"),
    ).toBe("Adds an organization.");
    expect(displayToolDescription("Adds a GitHub user.", "GitHub")).toBe(
      "Adds a user.",
    );
  });

  it("leaves a compound product name intact", () => {
    expect(
      displayToolDescription("Adds a GitHub Actions secret.", "GitHub"),
    ).toBe("Adds a GitHub Actions secret.");
  });

  it("drops a preposition left dangling by the name", () => {
    expect(
      displayToolDescription(
        "Updates multiple records in Airtable using PUT.",
        "Airtable",
      ),
    ).toBe("Updates multiple records using PUT.");
    expect(
      displayToolDescription(
        "Adds a reference to an external file to Slack for discovery.",
        "Slack",
      ),
    ).toBe("Adds a reference to an external file for discovery.");
  });

  it("keeps capitalised product compounds", () => {
    expect(
      displayToolDescription("Adds a runner to GitHub Actions.", "GitHub"),
    ).toBe("Adds a runner to GitHub Actions.");
  });

  it("shortens a product API reference", () => {
    expect(displayToolDescription("Uses the Notion API.", "Notion")).toBe(
      "Uses the API.",
    );
  });

  it("capitalises a sentence that started with the product name", () => {
    expect(
      displayToolDescription("Airtable bases are listed here.", "Airtable"),
    ).toBe("Bases are listed here.");
  });

  it("leaves a standalone mention, which carries meaning", () => {
    expect(displayToolDescription("Search in Notion.", "Notion")).toBe(
      "Search in Notion.",
    );
  });
});
