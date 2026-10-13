// The same shimmer the chat loading text uses (LoadingIndicator.tsx) — a bright
// sweep over dim-white, so "what it's doing right now" reads identically.
export function ShimmerText({ text }: { text: string }) {
  return (
    <span className="animate-shine loading-shine-text bg-size-[200%_100%] bg-clip-text text-transparent">
      {text}
    </span>
  );
}
