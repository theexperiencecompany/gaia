// The same shimmer the chat loading text uses (LoadingIndicator.tsx) — a bright
// sweep over dim-white, so "what it's doing right now" reads identically.
export function ShimmerText({ text }: { text: string }) {
  return (
    <span
      className="animate-shine bg-size-[200%_100%] bg-clip-text text-transparent"
      style={{
        backgroundImage:
          "linear-gradient(90deg, rgb(255 255 255 / 0.3) 20%, rgb(255 255 255) 50%, rgb(255 255 255 / 0.3) 80%)",
      }}
    >
      {text}
    </span>
  );
}
