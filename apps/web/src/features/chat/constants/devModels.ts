// DEV-ONLY model menu for the chat-header selector (rendered only in development).
// Each `id` MUST match a key of DEV_MODEL_OPTIONS in
// apps/api/app/constants/llm.py — the backend pins the model by that id.

export interface DevModelOption {
  id: string;
  name: string;
  provider: string;
  logo: string;
}

export const DEV_MODEL_OPTIONS: DevModelOption[] = [
  {
    id: "glm-5.2",
    name: "GLM 5.2",
    provider: "Z.AI",
    logo: "/images/icons/zai.png",
  },
  {
    id: "minimax-m3",
    name: "MiniMax M3",
    provider: "MiniMax",
    logo: "/images/icons/minimax.png",
  },
  {
    id: "gemini-3.5-flash",
    name: "Gemini 3.5 Flash",
    provider: "Google",
    logo: "/images/icons/gemini.webp",
  },
  {
    id: "deepseek-v4",
    name: "DeepSeek V4",
    provider: "DeepSeek",
    logo: "/images/icons/deepseek.png",
  },
  {
    id: "gemini-3.1-flash-lite",
    name: "Gemini 3.1 Flash Lite",
    provider: "Google",
    logo: "/images/icons/gemini.webp",
  },
];

export const DEFAULT_DEV_COMMS_MODEL = "glm-5.2";
export const DEFAULT_DEV_EXECUTOR_MODEL = "glm-5.2";
