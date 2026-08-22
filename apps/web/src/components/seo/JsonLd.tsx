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

  return (
    <>
      {schemaArray.map((schema) => {
        const json = serializeSchema(schema);
        if (!json) return null;
        return (
          <script
            key={json}
            type="application/ld+json"
            dangerouslySetInnerHTML={{ __html: json }}
          />
        );
      })}
    </>
  );
}
