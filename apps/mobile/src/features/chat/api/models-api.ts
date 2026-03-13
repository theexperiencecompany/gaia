import { apiService } from "@/lib/api";

export interface ModelInfo {
  model_id: string;
  name: string;
  model_provider?: string;
  provider_model_name?: string;
  description?: string;
  logo_url?: string;
  max_tokens: number;
  supports_streaming: boolean;
  supports_function_calling: boolean;
  available_in_plans: string[];
  lowest_tier: string;
  is_default: boolean;
}

export interface ModelSelectionResponse {
  success: boolean;
  message: string;
  selected_model: ModelInfo;
}

export const fetchAvailableModels = async (): Promise<ModelInfo[]> => {
  return apiService.get<ModelInfo[]>("/chat-models");
};

export const selectModel = async (
  modelId: string,
): Promise<ModelSelectionResponse> => {
  return apiService.put<ModelSelectionResponse>("/chat-models/select", {
    model_id: modelId,
  });
};
