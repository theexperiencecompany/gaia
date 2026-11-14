import "./pagination.css";
import { ParityButtons } from "./ParityButtons";
import { ParityDisplay } from "./ParityDisplay";
import { ParityFields } from "./ParityFields";
import { ParityOverlays } from "./ParityOverlays";

/**
 * Every HeroUI primitive combination GAIA renders, each under a stable
 * data-parity id, for `mise web:primitive-parity` to compare against v2's
 * computed styles. ?overlay=<id> renders one overlay forced open instead.
 */
export default async function PrimitiveParityPage({
  searchParams,
}: {
  searchParams: Promise<{ overlay?: string }>;
}) {
  const { overlay } = await searchParams;
  if (overlay) return <ParityOverlays overlay={overlay} />;
  return (
    <div className="flex flex-col gap-10 bg-zinc-900 p-8">
      <ParityButtons />
      <ParityFields />
      <ParityDisplay />
    </div>
  );
}
