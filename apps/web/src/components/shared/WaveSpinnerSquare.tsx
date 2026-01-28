export function WaveSpinnerSquare() {
  return (
    <div className="flex items-center justify-center w-fit">
      <style jsx global>{`
        @keyframes waveDiagTLAnimation {
          0%, 100% {
            opacity: 1;
          }
          50% {
            opacity: 0;
          }
        }
      `}</style>

      <div className="relative flex items-center justify-center">
        <div className="relative grid grid-cols-3 gap-0.5">
          {[...Array(9)].map((_, idx) => {
            const delays = [0, 0.12, 0.24, 0.12, 0.24, 0.36, 0.24, 0.36, 0.48];

            return (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: static array for spinner
                key={idx}
                className="w-1.5 h-1.5 transition-all"
                style={{
                  backgroundColor: "#00bbff",
                  animation: "waveDiagTLAnimation 0.7s ease-out infinite",
                  animationDelay: `${delays[idx]}s`,
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
