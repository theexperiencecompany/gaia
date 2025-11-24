"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import type React from "react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { LabeledField } from "@/features/settings/components/FormField";
import { SettingsCard } from "@/features/settings/components/SettingsCard";
import { SettingsCardSimple } from "@/features/settings/components/SettingsCardSimple";
import { SettingsOption } from "@/features/settings/components/SettingsOption";
import {
  Camera01Icon,
  Logout02Icon,
  PencilEdit02Icon,
  UserCircle02Icon,
} from "@/icons";

import type { ModalAction } from "./SettingsMenu";

export default function AccountSection({
  setModalAction,
}: {
  setModalAction: React.Dispatch<React.SetStateAction<ModalAction | null>>;
}) {
  const user = useUser();
  const { updateUser } = useUserActions();
  const [isEditing, setIsEditing] = useState(false);
  const [editedName, setEditedName] = useState(user?.name || "");
  const [isLoading, setIsLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSave = async () => {
    try {
      setIsLoading(true);
      toast.loading("Updating name...", { id: "update-name" });

      // Use the consolidated name update endpoint
      const response = await authApi.updateName(editedName);

      // Use partial update to preserve onboarding state
      updateUser({
        name: response.name,
        email: response.email,
        profilePicture: response.picture,
      });

      setIsEditing(false);
    } catch (error) {
      console.error("Profile update error:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleImageChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setIsLoading(true);
      toast.loading("Uploading profile picture...", { id: "update-picture" });

      const formData = new FormData();
      formData.append("picture", file);

      const response = await authApi.updateProfile(formData);

      // Use partial update to preserve onboarding state
      updateUser({
        name: response.name,
        email: response.email,
        profilePicture: response.picture,
      });
    } catch (error) {
      console.error("Profile picture update error:", error);
    } finally {
      setIsLoading(false);
      toast.dismiss("update-picture");
    }
  };

  return (
    <div className="flex w-full grid-cols-4 gap-10 space-y-4">
      <div className="col-span-3 w-full space-y-4">
        <div>
          <h3 className="text-lg font-semibold text-white">Account Settings</h3>
          <p className="text-sm text-zinc-400">Adjust your preferences</p>
        </div>

        <SettingsCard>
          <div className="flex items-start space-x-3">
            {/* Avatar */}
            <div className="group relative">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading}
                className="relative mt-5 h-14 w-14 cursor-pointer overflow-hidden rounded-full bg-zinc-800 transition-all duration-200 hover:ring-2 hover:ring-primary hover:ring-offset-2 hover:ring-offset-zinc-900"
              >
                {user?.profilePicture ? (
                  <>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={user.profilePicture}
                      alt={user?.name || "Profile"}
                      className="h-full w-full object-cover"
                    />
                  </>
                ) : (
                  <div className="flex h-full w-full items-center justify-center">
                    <UserCircle02Icon className="h-8 w-8 text-zinc-400" />
                  </div>
                )}
                <div className="bg-opacity-50 absolute inset-0 flex items-center justify-center bg-black opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                  <Camera01Icon className="h-6 w-6 text-white" />
                </div>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleImageChange}
                className="hidden"
              />
            </div>

            {/* UserCircle02Icon Info */}
            <div className="flex-1 space-y-4">
              {/* Name */}
              <LabeledField label="Name">
                {isEditing ? (
                  <div className="space-y-3">
                    <Input
                      type="text"
                      value={editedName}
                      onChange={(e) => setEditedName(e.target.value)}
                      placeholder="Enter your name"
                    />
                    <div className="flex items-center space-x-3">
                      <Button
                        onPress={handleSave}
                        disabled={isLoading}
                        color="primary"
                        size="sm"
                        fullWidth
                      >
                        {isLoading ? "Saving..." : "Save Changes"}
                      </Button>
                      <Button
                        fullWidth
                        size="sm"
                        onPress={() => {
                          setIsEditing(false);
                          setEditedName(user?.name || "");
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setIsEditing(true)}
                    className="group flex w-full items-center justify-between rounded-xl bg-zinc-800 px-3 py-2.5 text-sm text-white transition-colors duration-200 hover:bg-zinc-700"
                  >
                    <span>{user?.name || "Loading..."}</span>
                    <PencilEdit02Icon className="h-4 w-4 text-zinc-400 transition-colors duration-200 group-hover:text-white" />
                  </button>
                )}
              </LabeledField>

              {/* Email */}
              <LabeledField label="Email">
                <Input value={user.email} readOnly disabled isDisabled />
              </LabeledField>
            </div>
          </div>
        </SettingsCard>

        <SettingsCardSimple>
          <SettingsOption
            icon={<Logout02Icon className="h-5 w-5 text-red-500" />}
            title="Sign Out"
            description="Sign out of your account on this device"
            action={
              <Button
                variant="flat"
                color="danger"
                onPress={() => setModalAction("logout")}
              >
                Sign Out
              </Button>
            }
          />
        </SettingsCardSimple>
      </div>
    </div>
  );
}
