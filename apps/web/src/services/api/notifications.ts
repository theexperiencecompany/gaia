import type { NotificationPlatform } from "@/features/notification/constants";
import { api } from "@/lib/api/typed";

/**
 * The channel-preference endpoints.
 *
 * Every response shape comes from the schema, so a body that is not the API's
 * (a proxy error page, truncated JSON) fails loudly at parse time instead of
 * surfacing as a TypeError deep in a hook.
 */
export class NotificationsAPI {
  /** Channel preferences (telegram, discord, whatsapp, slack). */
  static getChannelPreferences() {
    return api.get("/api/v1/notifications/preferences/channels");
  }

  static async updateChannelPreference(
    platform: NotificationPlatform,
    enabled: boolean,
  ): Promise<void> {
    await api.put("/api/v1/notifications/preferences/channels", {
      body: { [platform]: enabled },
    });
  }
}
