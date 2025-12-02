import { useId } from "react";
import type { Thing, WithContext } from "schema-dts";

interface JsonLdProps {
  data: WithContext<Thing> | WithContext<Thing>[];
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
      {schemaArray.map((schema, index) => (
        <script
          // biome-ignore lint/suspicious/noArrayIndexKey: mapping json ld is fine
          key={`jsonld-${baseId}-${index}`}
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: setting json ld schema is fine
          dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
        />
      ))}
    </>
  );
}
