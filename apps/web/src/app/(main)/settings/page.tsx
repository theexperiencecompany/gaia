"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { ConfirmAction } from "@/components/shared/ConfirmActionDialog";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import AccountSettings from "@/features/settings/components/AccountSettings";
import LinkedAccountsSettings from "@/features/settings/components/LinkedAccountsSettings";
import MemorySettings from "@/features/settings/components/MemorySettings";
import NotificationSettings from "@/features/settings/components/NotificationSettings";
import PreferencesSettings from "@/features/settings/components/PreferencesSettings";
import ProfileCardSettings from "@/features/settings/components/ProfileCardSettings";
import type { ModalAction } from "@/features/settings/components/SettingsMenu";
import { SubscriptionSettings } from "@/features/settings/components/SubscriptionSettings";
import UsageSettings from "@/features/settings/components/UsageSettings";

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const section = searchParams.get("section");
  const [modalAction, setModalAction] = useState<ModalAction | null>(null);

  // Redirect to /settings?section=account if no section is specified
  useEffect(() => {
    if (!section) {
      router.replace("?section=account");
    }
  }, [section, router]);

  const renderContent = () => {
    switch (section) {
      case "account":
        return <AccountSettings setModalAction={setModalAction} />;
      case "profile":
        return <ProfileCardSettings />;
      case "linked-accounts":
        return <LinkedAccountsSettings />;
      case "subscription":
        return <SubscriptionSettings />;
      case "usage":
        return <UsageSettings />;
      case "preferences":
        return <PreferencesSettings setModalAction={setModalAction} />;
      case "memory":
        return <MemorySettings />;
      case "notifications":
        return <NotificationSettings />;
      default:
        return <ProfileCardSettings />;
    }
  };

  return (
    <>
      <div className="flex h-full w-full flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="flex w-full justify-center p-6">
            <div className="w-full">{renderContent()}</div>
          </div>
        </div>
      </div>

      <ConfirmActionDialog
        action={modalAction as ConfirmAction}
        onOpenChange={(action) => setModalAction(action as ModalAction)}
      />
    </>
  );
}
