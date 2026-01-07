import { apiService } from "@/lib/api";
import { API_ORIGIN } from "@/lib/constants";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import type {
  IntegrationsConfigResponse,
  IntegrationsStatusResponse,
  IntegrationWithStatus,
} from "../types";

WebBrowser.maybeCompleteAuthSession();

const INTEGRATION_LOGOS: Record<string, string> = {
  google_calendar:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/512px-Google_Calendar_icon_%282020%29.svg.png",
  google_docs:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Google_Docs_logo_%282020%29.svg/512px-Google_Docs_logo_%282020%29.svg.png",
  gmail:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/512px-Gmail_icon_%282020%29.svg.png",
  notion:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/512px-Notion-logo.svg.png",
  twitter:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/Logo_of_Twitter.svg/512px-Logo_of_Twitter.svg.png",
  googlesheets:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Google_Sheets_logo_%282020%29.svg/512px-Google_Sheets_logo_%282014-2020%29.svg.png",
  linkedin:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/LinkedIn_logo_initials.png/512px-LinkedIn_logo_initials.png",
  github:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/GitHub_Invertocat_Logo.svg/512px-GitHub_Invertocat_Logo.svg.png",
  reddit:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b4/Reddit_logo.svg/512px-Reddit_logo.svg.png",
  airtable:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/Airtable_Logo.svg/512px-Airtable_Logo.svg.png",
  linear:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Linear_logo.svg/512px-Linear_logo.svg.png",
  slack:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d5/Slack_icon_2019.svg/512px-Slack_icon_2019.svg.png",
  hubspot:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/HubSpot_Logo.svg/512px-HubSpot_Logo.svg.png",
  googletasks:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Google_Tasks_2021.svg/512px-Google_Tasks_2021.svg.png",
  todoist:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/Todoist_logo.svg/512px-Todoist_logo.svg.png",
  googlemeet:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9b/Google_Meet_icon_%282020%29.svg/512px-Google_Meet_icon_%282020%29.svg.png",
  google_maps:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/Google_Maps_icon_%282020%29.svg/512px-Google_Maps_icon_%282020%29.svg.png",
  asana:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/Asana_logo.svg/512px-Asana_logo.svg.png",
  trello:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7a/Trello-logo-blue.svg/512px-Trello-logo-blue.svg.png",
  instagram:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Instagram_logo_2016.svg/512px-Instagram_logo_2016.svg.png",
  clickup:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/ClickUp_Logo.svg/512px-ClickUp_Logo.svg.png",
};

function getIntegrationLogo(id: string): string {
  return (
    INTEGRATION_LOGOS[id] ||
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/512px-No_image_available.svg.png"
  );
}

function normalizeIntegration(
  integration: IntegrationsConfigResponse["integrations"][0],
  connected: boolean = false,
): IntegrationWithStatus {
  return {
    ...integration,
    connected,
    logo: getIntegrationLogo(integration.id),
  };
}

export async function fetchIntegrationsConfig(): Promise<
  IntegrationWithStatus[]
> {
  try {
    const [configResponse, statusResponse] = await Promise.all([
      apiService.get<IntegrationsConfigResponse>("/integrations/config"),
      fetchIntegrationsStatus(),
    ]);

    const statusMap = new Map(
      statusResponse.map((s) => [s.integrationId, s.connected]),
    );

    return configResponse.integrations.map((integration) =>
      normalizeIntegration(integration, statusMap.get(integration.id) ?? false),
    );
  } catch (error) {
    console.error("Error fetching integrations config:", error);
    return [];
  }
}

export async function fetchIntegrationsStatus(): Promise<
  IntegrationsStatusResponse["integrations"]
> {
  try {
    const response = await apiService.get<IntegrationsStatusResponse>(
      "/integrations/status",
    );
    return response.integrations;
  } catch (error) {
    console.error("Error fetching integrations status:", error);
    return [];
  }
}

export interface ConnectIntegrationResult {
  success: boolean;
  cancelled?: boolean;
  error?: string;
}

export async function connectIntegration(
  integrationId: string,
): Promise<ConnectIntegrationResult> {
  try {
    const redirectUri = Linking.createURL("integrations/callback");
    const authUrl = `${API_ORIGIN}/api/v1/integrations/login/${integrationId}?redirect_path=${encodeURIComponent(redirectUri)}`;

    console.log("Opening integration auth URL:", authUrl);

    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUri);

    if (result.type === "success") {
      return { success: true };
    } else if (result.type === "cancel") {
      return { success: false, cancelled: true };
    } else {
      return { success: false, error: "Authentication failed" };
    }
  } catch (error) {
    console.error("Error connecting integration:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Connection failed",
    };
  }
}

export async function disconnectIntegration(
  integrationId: string,
): Promise<boolean> {
  try {
    await apiService.post(`/integrations/${integrationId}/disconnect`, {});
    return true;
  } catch (error) {
    console.error("Error disconnecting integration:", error);
    return false;
  }
}

export const integrationsApi = {
  fetchIntegrationsConfig,
  fetchIntegrationsStatus,
  connectIntegration,
  disconnectIntegration,
};
