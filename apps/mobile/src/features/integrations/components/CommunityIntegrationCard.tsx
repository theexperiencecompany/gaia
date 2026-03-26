import { Avatar, Button, Card, Chip, PressableFeedback } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator } from "react-native";
import { UserIcon, Wrench01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAddPublicIntegration } from "../hooks/useCommunityIntegrations";
import type { CommunityIntegration } from "../types";

const FALLBACK_LOGO =
  "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/512px-No_image_available.svg.png";

interface CommunityIntegrationCardProps {
  integration: CommunityIntegration;
  onPress?: (integration: CommunityIntegration) => void;
}

export function CommunityIntegrationCard({
  integration,
  onPress,
}: CommunityIntegrationCardProps) {
  const { mutate: addIntegration, isPending } = useAddPublicIntegration();
  const [added, setAdded] = useState(false);

  const logoUri = integration.iconUrl ?? FALLBACK_LOGO;

  const handleAdd = () => {
    addIntegration(
      { slug: integration.slug },
      {
        onSuccess: () => setAdded(true),
      },
    );
  };

  return (
    <PressableFeedback
      onPress={() => onPress?.(integration)}
      className="flex-row items-center px-4 py-3"
    >
      <Card.Body className="flex-row items-center p-0">
        <Avatar
          alt={integration.name}
          size="sm"
          color="default"
          className="w-10 h-10 rounded-xl mr-3"
        >
          <Avatar.Image
            source={{ uri: logoUri }}
            style={{ width: 32, height: 32 }}
          />
          <Avatar.Fallback>
            <Text className="text-xs font-medium">
              {integration.name.charAt(0)}
            </Text>
          </Avatar.Fallback>
        </Avatar>

        <Card
          variant="transparent"
          animation="disable-all"
          className="flex-1 mr-3 p-0"
        >
          <Card.Body className="p-0 gap-0.5">
            <Card.Header className="p-0 flex-row items-center gap-2 mb-0.5">
              <Card.Title className="font-medium text-sm" numberOfLines={1}>
                {integration.name}
              </Card.Title>
              {integration.category ? (
                <Chip variant="secondary" size="sm">
                  <Chip.Label className="text-muted text-[10px]">
                    {integration.category}
                  </Chip.Label>
                </Chip>
              ) : null}
            </Card.Header>

            <Card.Description className="text-xs" numberOfLines={2}>
              {integration.description}
            </Card.Description>

            <Card.Footer className="p-0 flex-row items-center gap-3 mt-1.5">
              <Wrench01Icon size={11} color="#6b6b6b" />
              <Text className="text-muted text-[11px]">
                {integration.toolCount} tools
              </Text>
              <UserIcon size={11} color="#6b6b6b" />
              <Text className="text-muted text-[11px]">
                {integration.cloneCount} added
              </Text>
              {integration.creator?.name ? (
                <Text className="text-muted text-[11px]" numberOfLines={1}>
                  by {integration.creator.name}
                </Text>
              ) : null}
            </Card.Footer>
          </Card.Body>
        </Card>

        <Button
          size="sm"
          variant="tertiary"
          onPress={handleAdd}
          isDisabled={isPending || added}
          className={
            added ? "bg-success/15 px-3 min-w-16" : "bg-muted/10 px-3 min-w-16"
          }
        >
          {isPending ? (
            <ActivityIndicator size="small" color="#8e8e93" />
          ) : (
            <Button.Label
              className={added ? "text-success text-xs" : "text-muted text-xs"}
            >
              {added ? "Added" : "Add"}
            </Button.Label>
          )}
        </Button>
      </Card.Body>
    </PressableFeedback>
  );
}
