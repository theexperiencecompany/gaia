export const BotChatDemo = ({ platform = "telegram", messages = [] }) => {
  const [visibleCount, setVisibleCount] = useState(0);
  const [typing, setTyping] = useState(false);
  const containerRef = useRef(null);
  const startedRef = useRef(false);

  const themes = {
    telegram: {
      bg: "#17212b",
      header: "#232e3c",
      userBubble: "#2b5278",
      botBubble: "#182533",
      accent: "#2196F3",
      muted: "#8ba4bf",
      name: "GAIA Bot",
      status: "online",
      statusColor: "#64b5f6",
      input: "Message",
    },
    discord: {
      bg: "#313338",
      header: "#2b2d31",
      userBubble: "#383a40",
      botBubble: "#2b2d31",
      accent: "#5865F2",
      muted: "#949ba4",
      name: "GAIA",
      status: "APP",
      statusColor: "#ffffff",
      input: "Message @GAIA",
    },
    whatsapp: {
      bg: "#0b141a",
      header: "#202c33",
      userBubble: "#005c4b",
      botBubble: "#202c33",
      accent: "#00a884",
      muted: "#8696a0",
      name: "GAIA",
      status: "online",
      statusColor: "#8696a0",
      input: "Type a message",
    },
    slack: {
      bg: "#1a1d21",
      header: "#222529",
      userBubble: "#26292e",
      botBubble: "#26292e",
      accent: "#36C5F0",
      muted: "#ababad",
      name: "GAIA",
      status: "APP",
      statusColor: "#ffffff",
      input: "Message GAIA",
    },
  };
  const t = themes[platform] || themes.telegram;

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !startedRef.current) {
          startedRef.current = true;
          let i = 0;
          const showNext = () => {
            if (i >= messages.length) return;
            const next = messages[i];
            const reveal = () => {
              setTyping(false);
              i += 1;
              setVisibleCount(i);
              setTimeout(showNext, 900);
            };
            if (next.from === "gaia") {
              setTyping(true);
              setTimeout(reveal, 1100);
            } else {
              reveal();
            }
          };
          setTimeout(showNext, 400);
        }
      },
      { threshold: 0.4 },
    );
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [messages]);

  const bubbleBase = {
    maxWidth: "78%",
    borderRadius: 16,
    padding: "8px 12px",
    fontSize: 13,
    lineHeight: 1.5,
    color: "#ffffff",
    whiteSpace: "pre-line",
    transition: "opacity 0.3s ease, transform 0.3s ease",
  };

  return (
    <div
      ref={containerRef}
      className="not-prose my-6 flex flex-col overflow-hidden rounded-2xl"
      style={{ background: t.bg, minHeight: 320 }}
    >
      <div
        className="flex shrink-0 items-center gap-3 px-4 py-3"
        style={{
          background: t.header,
          borderBottom: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{ background: t.accent }}
        >
          <span className="text-sm font-bold text-white">G</span>
        </div>
        <div>
          <p
            className="m-0 text-sm font-semibold leading-none"
            style={{ color: "#ffffff" }}
          >
            {t.name}
          </p>
          <p className="m-0 mt-1 text-[11px]" style={{ color: t.statusColor }}>
            {t.status}
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 px-3 py-4">
        {messages.slice(0, visibleCount).map((msg, idx) =>
          msg.from === "user" ? (
            <div key={idx} className="flex justify-end">
              <div
                style={{
                  ...bubbleBase,
                  background: t.userBubble,
                  borderBottomRightRadius: 4,
                }}
              >
                {msg.text}
              </div>
            </div>
          ) : (
            <div key={idx} className="flex items-end gap-2">
              <div
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
                style={{ background: t.accent }}
              >
                <span className="text-[10px] font-bold text-white">G</span>
              </div>
              <div
                style={{
                  ...bubbleBase,
                  background: t.botBubble,
                  borderBottomLeftRadius: 4,
                }}
              >
                {msg.text}
              </div>
            </div>
          ),
        )}
        {typing && (
          <div className="flex items-end gap-2">
            <div
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
              style={{ background: t.accent }}
            >
              <span className="text-[10px] font-bold text-white">G</span>
            </div>
            <div
              className="flex items-center gap-1"
              style={{
                ...bubbleBase,
                background: t.botBubble,
                borderBottomLeftRadius: 4,
                padding: "12px 14px",
              }}
            >
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: t.muted,
                    display: "inline-block",
                    animation: `botChatDemoPulse 1s ease-in-out ${dot * 0.18}s infinite`,
                  }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <div
        className="flex shrink-0 items-center gap-2 px-3 py-2.5"
        style={{
          background: t.header,
          borderTop: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <div
          className="flex-1 rounded-full px-4 py-2 text-xs"
          style={{ background: t.bg, color: t.muted }}
        >
          {t.input}
        </div>
        <div
          className="flex h-8 w-8 items-center justify-center rounded-full"
          style={{ background: t.accent }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#ffffff"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-label="Send"
          >
            <path d="M22 2L11 13" />
            <path d="M22 2l-7 20-4-9-9-4 20-7z" />
          </svg>
        </div>
      </div>
      <style>{`@keyframes botChatDemoPulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }`}</style>
    </div>
  );
};
