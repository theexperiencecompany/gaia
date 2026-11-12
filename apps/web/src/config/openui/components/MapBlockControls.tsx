import { MinusSignIcon, PlusSignIcon, RefreshIcon } from "@icons";
import { GaiaButton } from "@/components/shared/GaiaButton";
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
      <GaiaButton
        isIconOnly
        size="sm"
        variant="tertiary"
        onPress={handleZoomIn}
        aria-label="Zoom in"
        className="backdrop-blur-md"
      >
        <PlusSignIcon className="size-3.5" />
      </GaiaButton>
      <GaiaButton
        isIconOnly
        size="sm"
        variant="tertiary"
        onPress={handleZoomOut}
        aria-label="Zoom out"
        className="backdrop-blur-md"
      >
        <MinusSignIcon className="size-3.5" />
      </GaiaButton>
      <GaiaButton
        isIconOnly
        size="sm"
        variant="tertiary"
        onPress={handleReset}
        aria-label="Reset view"
        className="backdrop-blur-md"
      >
        <RefreshIcon className="size-3.5" />
      </GaiaButton>
    </div>
  );
}
