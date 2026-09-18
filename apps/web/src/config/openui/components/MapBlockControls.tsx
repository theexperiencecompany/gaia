import { Button } from "@heroui/react";
import { MinusSignIcon, PlusSignIcon, RefreshIcon } from "@icons";
import { useMap } from "@/components/ui/map";

export function MapBlockControls({
  initialCenter,
  initialZoom,
}: {
  initialCenter: [number, number];
  initialZoom: number;
}) {
  const { map } = useMap();

  const handleZoomIn = () => {
    map?.zoomTo(map.getZoom() + 1, { duration: 250 });
  };
  const handleZoomOut = () => {
    map?.zoomTo(map.getZoom() - 1, { duration: 250 });
  };
  const handleReset = () => {
    map?.flyTo({
      center: initialCenter,
      zoom: initialZoom,
      bearing: 0,
      pitch: 0,
      duration: 400,
    });
  };

  return (
    <div className="absolute top-2 right-2 z-10 flex flex-col gap-1">
      <Button
        isIconOnly
        size="sm"
        variant="flat"
        radius="lg"
        onPress={handleZoomIn}
        aria-label="Zoom in"
        className="text-zinc-200"
      >
        <PlusSignIcon className="size-3.5" />
      </Button>
      <Button
        isIconOnly
        size="sm"
        variant="flat"
        radius="lg"
        onPress={handleZoomOut}
        aria-label="Zoom out"
        className="text-zinc-200"
      >
        <MinusSignIcon className="size-3.5" />
      </Button>
      <Button
        isIconOnly
        size="sm"
        variant="flat"
        radius="lg"
        onPress={handleReset}
        aria-label="Reset view"
        className="text-zinc-200"
      >
        <RefreshIcon className="size-3.5" />
      </Button>
    </div>
  );
}
