"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Camera01Icon,
  Logout02Icon,
  PencilEdit02Icon,
  UserCircle02Icon,
} from "@icons";
import Image from "next/image";
import type React from "react";
import { useRef, useState } from "react";
import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import {
  SettingsPage,
  SettingsRow,
  SettingsSection,
} from "@/features/settings/components/ui";
import { toast } from "@/lib/toast";
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

      const response = await authApi.updateName(editedName);

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
    <SettingsPage>
      <SettingsSection title="Profile">
        {/* Avatar */}
        <SettingsRow label="Photo" stacked>
          <div className="group relative w-fit">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading}
              className="relative h-14 w-14 cursor-pointer overflow-hidden rounded-full bg-zinc-800 transition-all duration-200 hover:ring-2 hover:ring-primary hover:ring-offset-2 hover:ring-offset-zinc-900"
            >
              {user?.profilePicture ? (
                <Image
                  width={56}
                  height={56}
                  src={user.profilePicture}
                  alt={user?.name || "Profile"}
                  className="h-full w-full object-cover"
                />
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
        </SettingsRow>

        {/* Name */}
        <SettingsRow label="Name" stacked>
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
              type="button"
              onClick={() => setIsEditing(true)}
              className="group flex w-full items-center justify-between rounded-xl bg-zinc-800 px-3 py-2.5 text-sm text-white transition-colors duration-200 hover:bg-zinc-700"
            >
              <span>{user?.name || "Loading..."}</span>
              <PencilEdit02Icon className="h-4 w-4 text-zinc-400 transition-colors duration-200 group-hover:text-white" />
            </button>
          )}
        </SettingsRow>

        {/* Email */}
        <SettingsRow label="Email">
          <span className="text-sm text-zinc-400">{user?.email}</span>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Account">
        <SettingsRow
          label="Sign out"
          description="Sign out of your account on this device"
        >
          <Button
            variant="flat"
            color="danger"
            size="sm"
            onPress={() => setModalAction("logout")}
            startContent={<Logout02Icon className="h-4 w-4" />}
          >
            Sign out
          </Button>
        </SettingsRow>
      </SettingsSection>
    </SettingsPage>
  );
}
