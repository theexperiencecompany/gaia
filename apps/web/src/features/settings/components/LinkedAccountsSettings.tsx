"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { DiscordIcon, TelegramIcon } from "@/icons";
import {
  type LinkedAccount,
  linkedAccountsApi,
} from "../api/linkedAccountsApi";
import { SettingsCard } from "./SettingsCard";

const PLATFORM_COLORS: Record<string, string> = {
  discord: "#5865F2",
  slack: "#4A154B",
  telegram: "#0088CC",
};

export function LinkedAccountsSettings() {
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);

  const fetchAccounts = useCallback(async () => {
    try {
      const data = await linkedAccountsApi.getStatus();
      setAccounts(data.accounts);
    } catch (error) {
      console.error("Error fetching linked accounts:", error);
      toast.error("Failed to load linked accounts");
    }
  }, []);

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  // Check for OAuth callback results
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const success = params.get("oauth_success");
    const error = params.get("oauth_error");

    if (success === "true") {
      toast.success("Account linked successfully!");
      window.history.replaceState(
        {},
        "",
        `${window.location.pathname}?section=linked-accounts`,
      );
      // Small delay to ensure DB update completes
      setTimeout(() => {
        fetchAccounts();
      }, 500);
    } else if (error) {
      const errorMessages: Record<string, string> = {
        cancelled: "You cancelled the linking process",
        failed: "Failed to link account. Please try again.",
        invalid_state: "Invalid session. Please try again.",
        user_not_found: "User not found. Please sign in again.",
        token_failed: "Failed to authenticate with the platform.",
        invalid_client: "OAuth configuration error. Please contact support.",
      };
      toast.error(errorMessages[error] || "An error occurred");
      window.history.replaceState(
        {},
        "",
        `${window.location.pathname}?section=linked-accounts`,
      );
    }
  }, [fetchAccounts]);

  const handleConnect = (platform: string) => {
    linkedAccountsApi.linkPlatform(platform);
  };

  const handleUnlink = async (platform: string) => {
    try {
      await linkedAccountsApi.unlinkPlatform(platform);
      await fetchAccounts();
      toast.success("Account unlinked");
    } catch (error) {
      console.error("Error unlinking:", error);
      toast.error("Failed to unlink account");
    }
  };

  return (
    <div className="space-y-6">
      <SettingsCard title="Linked Accounts">
        <p className="text-sm text-zinc-500 mb-4">
          Connect your messaging platform accounts so GAIA can identify you across different apps.
          Your conversations and preferences will be synced regardless of where you chat.
        </p>
        <div className="space-y-3">
          {accounts.map((account) => {
            const color = PLATFORM_COLORS[account.platform];

            return (
              <div
                key={account.platform}
                className="flex items-center justify-between rounded-2xl bg-zinc-800/30 p-3 transition-colors hover:bg-zinc-800/50"
              >
                <div className="flex items-center gap-3">
                  <div
                    className="flex h-9 w-9 items-center justify-center rounded-lg"
                    style={{ backgroundColor: color }}
                  >
                    {account.platform === "discord" && (
                      <DiscordIcon className="h-5 w-5 text-white" />
                    )}
                    {account.platform === "slack" && (
                      <Image
                        src="/images/icons/slack.svg"
                        alt="Slack"
                        width={20}
                        height={20}
                      />
                    )}
                    {account.platform === "telegram" && (
                      <TelegramIcon className="h-5 w-5 text-white bg-[#0088CC]" />
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">
                      {account.name}
                    </span>
                    {account.linked && (
                      <Chip size="sm" variant="flat" color="success">
                        Connected
                      </Chip>
                    )}
                  </div>
                </div>

                <div>
                  {!account.available ? null : account.linked ? (
                    <Button
                      size="sm"
                      variant="flat"
                      color="danger"
                      onPress={() => handleUnlink(account.platform)}
                    >
                      Disconnect
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      color="primary"
                      onPress={() => handleConnect(account.platform)}
                    >
                      Connect
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </SettingsCard>
    </div>
  );
}
