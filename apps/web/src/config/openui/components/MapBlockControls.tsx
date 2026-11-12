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
        variant="default-soft"
        onPress={handleZoomIn}
        aria-label="Zoom in"
        className="bg-zinc-800/90 text-zinc-200 backdrop-blur-md data-[hover=true]:bg-zinc-700"
      >
        <PlusSignIcon className="size-3.5" />
      </GaiaButton>
      <GaiaButton
        isIconOnly
        size="sm"
        variant="default-soft"
        onPress={handleZoomOut}
        aria-label="Zoom out"
        className="bg-zinc-800/90 text-zinc-200 backdrop-blur-md data-[hover=true]:bg-zinc-700"
      >
        <MinusSignIcon className="size-3.5" />
      </GaiaButton>
      <GaiaButton
        isIconOnly
        size="sm"
        variant="default-soft"
        onPress={handleReset}
        aria-label="Reset view"
        className="bg-zinc-800/90 text-zinc-200 backdrop-blur-md data-[hover=true]:bg-zinc-700"
      >
        <RefreshIcon className="size-3.5" />
      </GaiaButton>
    </div>
  );
}
