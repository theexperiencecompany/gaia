import * as DocumentPicker from "expo-document-picker";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  Camera01Icon,
  File01Icon,
  Image01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { AttachmentFile } from "./attachment-preview";

export interface AttachmentSheetRef {
  open: () => void;
  close: () => void;
}

interface AttachmentSheetProps {
  onAttachmentsSelected: (attachments: AttachmentFile[]) => void;
}

function makeLocalId(): string {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const AttachmentSheet = forwardRef<
  AttachmentSheetRef,
  AttachmentSheetProps
>(({ onAttachmentsSelected }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const { spacing, fontSize } = useResponsive();

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const handlePhotoLibrary = useCallback(async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setIsOpen(false);
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: "images",
      allowsMultipleSelection: true,
      quality: 0.8,
      selectionLimit: 5,
    });

    if (result.canceled || result.assets.length === 0) return;

    const attachments: AttachmentFile[] = result.assets.map((asset) => ({
      localId: makeLocalId(),
      uri: asset.uri,
      name: asset.fileName ?? `image_${Date.now()}.jpg`,
      mimeType: asset.mimeType ?? "image/jpeg",
      size: asset.fileSize,
      isUploading: false,
    }));

    onAttachmentsSelected(attachments);
  }, [onAttachmentsSelected]);

  const handleCamera = useCallback(async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setIsOpen(false);
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) return;

    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: "images",
      quality: 0.8,
    });

    if (result.canceled || result.assets.length === 0) return;

    const asset = result.assets[0];
    if (!asset) return;

    const attachment: AttachmentFile = {
      localId: makeLocalId(),
      uri: asset.uri,
      name: asset.fileName ?? `photo_${Date.now()}.jpg`,
      mimeType: asset.mimeType ?? "image/jpeg",
      size: asset.fileSize,
      isUploading: false,
    };

    onAttachmentsSelected([attachment]);
  }, [onAttachmentsSelected]);

  const handleFile = useCallback(async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setIsOpen(false);
    const result = await DocumentPicker.getDocumentAsync({
      multiple: true,
      type: "*/*",
      copyToCacheDirectory: true,
    });

    if (result.canceled || result.assets.length === 0) return;

    const attachments: AttachmentFile[] = result.assets.map((asset) => ({
      localId: makeLocalId(),
      uri: asset.uri,
      name: asset.name,
      mimeType: asset.mimeType ?? "application/octet-stream",
      size: asset.size,
      isUploading: false,
    }));

    onAttachmentsSelected(attachments);
  }, [onAttachmentsSelected]);

  const options = [
    {
      label: "Photo Library",
      icon: Image01Icon,
      onPress: handlePhotoLibrary,
    },
    {
      label: "Camera",
      icon: Camera01Icon,
      onPress: handleCamera,
    },
    {
      label: "File",
      icon: File01Icon,
      onPress: handleFile,
    },
  ];

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["28%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <View
            style={{
              paddingHorizontal: spacing.md,
              paddingTop: spacing.sm,
              paddingBottom: spacing.xl,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: "#ffffff",
                marginBottom: spacing.md,
              }}
            >
              Add Attachment
            </Text>

            <View style={{ gap: spacing.xs }}>
              {options.map((option) => (
                <Pressable
                  key={option.label}
                  onPress={option.onPress}
                  style={({ pressed }) => ({
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 12,
                    padding: 14,
                    borderRadius: 12,
                    backgroundColor: pressed
                      ? "rgba(255,255,255,0.06)"
                      : "transparent",
                  })}
                  android_ripple={{ color: "rgba(255,255,255,0.08)" }}
                >
                  <AppIcon icon={option.icon} size={20} color="#e4e4e7" />
                  <Text
                    style={{
                      fontSize: 16,
                      color: "#e4e4e7",
                      fontWeight: "400",
                    }}
                  >
                    {option.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

AttachmentSheet.displayName = "AttachmentSheet";
