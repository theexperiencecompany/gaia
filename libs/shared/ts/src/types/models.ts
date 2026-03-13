export enum ModelProvider {
  ANTHROPIC = "anthropic",
  OPENAI = "openai",
  GOOGLE = "google",
  META = "meta",
  MISTRAL = "mistral",
  COHERE = "cohere",
  DEEPSEEK = "deepseek",
}

export interface LLMModel {
  id: string;
  name: string;
  provider: ModelProvider;
  contextWindow: number;
  supportsVision: boolean;
  supportsTools: boolean;
  supportsStreaming: boolean;
  costPer1kTokens?: {
    input: number;
    output: number;
  };
  description?: string;
  isDefault?: boolean;
}

export const DEFAULT_MODELS: LLMModel[] = [
  {
    id: "claude-opus-4-5",
    name: "Claude Opus 4.5",
    provider: ModelProvider.ANTHROPIC,
    contextWindow: 200000,
    supportsVision: true,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.015, output: 0.075 },
    description: "Most powerful Claude model for complex tasks",
  },
  {
    id: "claude-sonnet-4-5",
    name: "Claude Sonnet 4.5",
    provider: ModelProvider.ANTHROPIC,
    contextWindow: 200000,
    supportsVision: true,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.003, output: 0.015 },
    description: "Balanced performance and cost",
    isDefault: true,
  },
  {
    id: "claude-haiku-3-5",
    name: "Claude Haiku 3.5",
    provider: ModelProvider.ANTHROPIC,
    contextWindow: 200000,
    supportsVision: true,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.00025, output: 0.00125 },
    description: "Fast and lightweight Claude model",
  },
  {
    id: "gpt-4o",
    name: "GPT-4o",
    provider: ModelProvider.OPENAI,
    contextWindow: 128000,
    supportsVision: true,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.005, output: 0.015 },
    description: "OpenAI's most capable multimodal model",
  },
  {
    id: "gpt-4o-mini",
    name: "GPT-4o Mini",
    provider: ModelProvider.OPENAI,
    contextWindow: 128000,
    supportsVision: true,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.00015, output: 0.0006 },
    description: "Fast and affordable GPT-4o variant",
  },
  {
    id: "gemini-2.0-flash",
    name: "Gemini 2.0 Flash",
    provider: ModelProvider.GOOGLE,
    contextWindow: 1000000,
    supportsVision: true,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.000075, output: 0.0003 },
    description: "Google's fast multimodal model with 1M context",
  },
  {
    id: "gemini-2.5-pro",
    name: "Gemini 2.5 Pro",
    provider: ModelProvider.GOOGLE,
    contextWindow: 1000000,
    supportsVision: true,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.00125, output: 0.005 },
    description: "Google's most capable model with 1M context",
  },
  {
    id: "deepseek-chat",
    name: "DeepSeek Chat",
    provider: ModelProvider.DEEPSEEK,
    contextWindow: 65536,
    supportsVision: false,
    supportsTools: true,
    supportsStreaming: true,
    costPer1kTokens: { input: 0.00014, output: 0.00028 },
    description: "Efficient open-source model from DeepSeek",
  },
];

export const MODEL_ENDPOINTS: Record<string, string> = {
  [ModelProvider.ANTHROPIC]: "https://api.anthropic.com/v1",
  [ModelProvider.OPENAI]: "https://api.openai.com/v1",
  [ModelProvider.GOOGLE]: "https://generativelanguage.googleapis.com/v1",
  [ModelProvider.MISTRAL]: "https://api.mistral.ai/v1",
  [ModelProvider.COHERE]: "https://api.cohere.ai/v1",
  [ModelProvider.DEEPSEEK]: "https://api.deepseek.com/v1",
};

export function getModelById(id: string): LLMModel | undefined {
  return DEFAULT_MODELS.find((model) => model.id === id);
}

export function getModelsByProvider(provider: ModelProvider): LLMModel[] {
  return DEFAULT_MODELS.filter((model) => model.provider === provider);
}
