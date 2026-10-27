import type { Thing, WithContext } from "schema-dts";

interface JsonLdProps {
  data: WithContext<Thing> | WithContext<Thing>[];
}

/** The schema as plain JSON data: functions and promises dropped, and a property that loops back to an enclosing node cut. A value shared by two properties is kept in both. */
function toJsonData(value: unknown, ancestors: Set<object>): unknown {
  if (value instanceof Promise || typeof value === "function") return undefined;
  if (typeof value !== "object" || value === null) return value;
  if (ancestors.has(value)) return undefined;
  ancestors.add(value);
  const data = Array.isArray(value)
    ? value.map((item) => toJsonData(item, ancestors))
    : Object.fromEntries(
        Object.entries(value).map(([key, item]) => [
          key,
          toJsonData(item, ancestors),
        ]),
      );
  ancestors.delete(value);
  return data;
}

function serializeSchema(schema: WithContext<Thing>): string {
  return JSON.stringify(toJsonData(schema, new Set()));
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
