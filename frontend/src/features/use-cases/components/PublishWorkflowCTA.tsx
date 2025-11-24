import { RaisedButton } from "@/components/ui/raised-button";

export default function PublishWorkflowCTA() {
  return (
    <>
      <div className="mx-auto mt-20 max-w-7xl rounded-4xl bg-zinc-800 p-6 py-20 text-center">
        <div className="mx-auto space-y-1">
          <h3 className="font-serif text-6xl font-normal text-foreground">
            Publish Your Own Workflow
          </h3>
          <p className="text-zinc-400">
            Build and share your automation ideas with the GAIA community
          </p>
          <a
            href={
              (typeof window !== "undefined" &&
              window.location.hostname === "localhost"
                ? "http://localhost:3001"
                : "https://docs.heygaia.io") + "/guides/create-public-workflow"
            }
            target="_blank"
            rel="noopener noreferrer"
          >
            <RaisedButton color="#00bbff" className="mt-5 text-black!">
              Learn How
            </RaisedButton>
          </a>
        </div>
      </div>
    </>
  );
}
