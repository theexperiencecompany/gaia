import {
  BottomSheetBackdrop,
  type BottomSheetBackdropProps,
  BottomSheetModal,
  BottomSheetView,
} from "@gorhom/bottom-sheet";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import { Pressable, View } from "react-native";
import {
  Camera01Icon,
  File01Icon,
  HugeiconsIcon,
  Image01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
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
  const bottomSheetRef = useRef<BottomSheetModal>(null);
  const { spacing, fontSize, iconSize } = useResponsive();

  const snapPoints = useMemo(() => ["28%"], []);

  useImperativeHandle(ref, () => ({
    open: () => bottomSheetRef.current?.present(),
    close: () => bottomSheetRef.current?.dismiss(),
  }));

  const dismiss = useCallback(() => {
    bottomSheetRef.current?.dismiss();
  }, []);

  const handlePhotoLibrary = useCallback(async () => {
    dismiss();
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
  }, [dismiss, onAttachmentsSelected]);

  const handleCamera = useCallback(async () => {
    dismiss();
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
  }, [dismiss, onAttachmentsSelected]);

  const handleFile = useCallback(async () => {
    dismiss();
    const result = await DocumentPicker.getDocumentAsync({
      multiple: true,
      type: [
        "application/pdf",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/*",
      ],
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
  }, [dismiss, onAttachmentsSelected]);

  const renderBackdrop = useCallback(
    (props: BottomSheetBackdropProps) => (
      <BottomSheetBackdrop
        {...props}
        disappearsOnIndex={-1}
        appearsOnIndex={0}
        opacity={0.4}
      />
    ),
    [],
  );

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
    <BottomSheetModal
      ref={bottomSheetRef}
      snapPoints={snapPoints}
      enableDynamicSizing={false}
      enablePanDownToClose
      backdropComponent={renderBackdrop}
      backgroundStyle={{ backgroundColor: "#1c1c1e" }}
      handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
    >
      <BottomSheetView
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
                gap: spacing.md,
                paddingVertical: spacing.sm + 2,
                paddingHorizontal: spacing.sm,
                borderRadius: 12,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.06)"
                  : "transparent",
              })}
              android_ripple={{ color: "rgba(255,255,255,0.08)" }}
            >
              <View
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 10,
                  backgroundColor: "#27272a",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <HugeiconsIcon
                  icon={option.icon}
                  size={iconSize.md - 2}
                  color="#a1a1aa"
                />
              </View>
              <Text
                style={{
                  fontSize: fontSize.base,
                  color: "#e4e4e7",
                  fontWeight: "400",
                }}
              >
                {option.label}
              </Text>
            </Pressable>
          ))}
        </View>
      </BottomSheetView>
    </BottomSheetModal>
  );
});

AttachmentSheet.displayName = "AttachmentSheet";
