import { View } from "react-native";
import { Popover, Button } from "heroui-native";
import { StyledSafeAreaView } from "@/lib/uniwind";

export default function Test() {
  return (
    <StyledSafeAreaView className="flex-1 p-4">
      <Popover>
        <Popover.Trigger asChild>
          <Button>
            <Button.Label>Open Bottom Sheet</Button.Label>
          </Button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Overlay />
          <Popover.Content presentation="bottom-sheet" snapPoints={["90%"]}>
            <Popover.Title>Test Bottom Sheet</Popover.Title>
            <Popover.Description>
              This is a test bottom sheet content.
            </Popover.Description>
            <View className="mt-4">
              <Popover.Close asChild>
                <Button>
                  <Button.Label>Close</Button.Label>
                </Button>
              </Popover.Close>
            </View>
          </Popover.Content>
        </Popover.Portal>
      </Popover>
    </StyledSafeAreaView>
  );
}
