import Image from "next/image";
import { RaisedButton } from "@/components/ui/raised-button";

export default function PublishWorkflowCTA() {
  return (
    <div className="mx-auto mt-20 max-w-7xl rounded-4xl bg-background p-6 py-20 text-center relative overflow-hidden outline-surface-300 outline-1">
      <Image
        fill
        src={"/images/wallpapers/blueprint.png"}
        alt="Blueprint image"
        className="object-cover  z-0 opacity-50 blur-[3px]"
      />
      <div className="mx-auto space-y-1">
        <h3 className="font-serif text-6xl font-normal text-foreground relative z-[1]">
          Publish Your Own Workflow
        </h3>
        <p className="text-foreground-600 relative z-[1]">
          Build and share your automation ideas with the GAIA community
        </p>
        <a
          href={`${
            typeof window !== "undefined" &&
            window.location.hostname === "localhost"
              ? "http://localhost:3001"
              : "https://docs.heygaia.io"
          }/guides/create-public-workflow`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <RaisedButton color="#00bbff" className="mt-5 text-black!">
            Learn How
          </RaisedButton>
        </a>
      </div>
    </div>
  );
}
