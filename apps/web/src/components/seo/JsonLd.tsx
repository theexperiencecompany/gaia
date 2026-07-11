import { useId } from "react";
import type { Thing, WithContext } from "schema-dts";

interface JsonLdProps {
  data: WithContext<Thing> | WithContext<Thing>[];
}

function serializeSchema(schema: WithContext<Thing>): string | null {
  const seen = new WeakSet();
  try {
    return JSON.stringify(schema, (_key, value) => {
      if (value instanceof Promise || typeof value === "function") {
        return undefined;
      }
      if (typeof value === "object" && value !== null) {
        if (seen.has(value)) return undefined;
        seen.add(value);
      }
      return value;
    });
  } catch {
    return null;
  }
}

/**
 * Renders JSON-LD structured data for SEO
 * Automatically stringifies and safely injects the schema
 */
export default function JsonLd({ data }: JsonLdProps) {
  const schemaArray = Array.isArray(data) ? data : [data];
  const baseId = useId();

  return (
    <>
      {schemaArray.map((schema, index) => {
        const json = serializeSchema(schema);
        if (!json) return null;
        return (
          <script
            // biome-ignore lint/suspicious/noArrayIndexKey: mapping json ld is fine
            key={`jsonld-${baseId}-${index}`}
            type="application/ld+json"
            dangerouslySetInnerHTML={{ __html: json }}
          />
        );
      })}
    </>
  );
}
