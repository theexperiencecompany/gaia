interface ShinyTextProps {
  text: string;
  disabled?: boolean;
  speed?: number;
  className?: string;
  heading?: string;
}

const ShinyText = ({
  text,
  disabled = false,
  speed = 5,
  className = "",
  heading,
}: ShinyTextProps) => {
  const animationDuration = `${speed}s`;

  return (
    <div className={className}>
      <div
        className={`inline-block bg-clip-text text-zinc-800 ${disabled ? "" : "animate-shine"} `}
        style={{
          backgroundImage:
            "linear-gradient(120deg, rgba(255, 255, 255, 0) 40%, rgba(255, 255, 255, 0.8) 50%, rgba(255, 255, 255, 0) 60%)",
          backgroundSize: "200% 100%",
          WebkitBackgroundClip: "text",
          animationDuration,
        }}
      >
        {heading && <span className="font-medium">{heading} </span>}
        {text}
      </div>
    </div>
  );
};

export default ShinyText;
