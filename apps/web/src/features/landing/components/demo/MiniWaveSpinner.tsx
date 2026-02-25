export default function MiniWaveSpinner() {
  const delays = [0, 0.12, 0.24, 0.12, 0.24, 0.36, 0.24, 0.36, 0.48];
  return (
    <div className="grid shrink-0 grid-cols-3 gap-0.5">
      {delays.map((d, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: static list
          key={i}
          className="h-1.5 w-1.5"
          style={{
            backgroundColor: "#00bbff",
            animation: "waveDiagTLAnimation 0.7s ease-out infinite",
            animationDelay: `${d}s`,
          }}
        />
      ))}
    </div>
  );
}
