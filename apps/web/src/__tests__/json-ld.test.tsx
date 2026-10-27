/** JsonLd keeps every property, including one entity referenced twice, and drops only a true cycle. */
import { renderToStaticMarkup } from "react-dom/server";
import type { Thing, WithContext } from "schema-dts";
import { describe, expect, it } from "vitest";

import JsonLd from "@/components/seo/JsonLd";

function rendered(schema: object): Record<string, unknown> {
  const html = renderToStaticMarkup(
    <JsonLd data={schema as WithContext<Thing>} />,
  );
  const json = html.match(/<script[^>]*>(.*)<\/script>/)?.[1];
  return JSON.parse(json ?? "null") as Record<string, unknown>;
}

describe("JsonLd", () => {
  it("serializes an entity reference used by two properties in both", () => {
    const organization = { "@id": "https://heygaia.io/#organization" };
    const schema = rendered({
      "@context": "https://schema.org",
      "@type": "HowTo",
      publisher: organization,
      author: organization,
    });
    expect(schema.publisher).toEqual(organization);
    expect(schema.author).toEqual(organization);
  });

  it("drops a property that loops back to an enclosing node", () => {
    const schema: Record<string, unknown> = {
      "@context": "https://schema.org",
      "@type": "WebPage",
      name: "Page",
    };
    schema.self = schema;
    expect(rendered(schema)).toEqual({
      "@context": "https://schema.org",
      "@type": "WebPage",
      name: "Page",
    });
  });
});
