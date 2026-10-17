import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import type {
  DependencyCheck,
  DependencyReadiness,
} from "../../lib/dependency-readiness.js";
import { dependencyName, serviceName } from "../../lib/display-names.js";
import type { ContainerStatus } from "../../lib/docker.js";
import type { DockerStatus, ServiceStatus } from "../../lib/healthcheck.js";
import { Header } from "../components/Header.js";
import { Mark } from "../components/Mark.js";
import { ErrorStep } from "../components/shared-steps.js";
import { BOX_BORDER, THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";
import { useCLIState } from "../use-cli-state.js";

const NAME_COLUMN = 22;

/** The keys that leave the screen: q, Esc, or Enter. */
function isQuitKey(input: string, key: { return: boolean; escape: boolean }) {
  return input === "q" || key.return || key.escape;
}

const Row: React.FC<{
  ok: boolean;
  name: string;
  detail?: string;
  problem?: string;
}> = ({ ok, name, detail, problem }) => (
  <Box>
    <Mark kind={ok ? "ok" : "fail"} />
    <Box width={NAME_COLUMN}>
      <Text>{name}</Text>
    </Box>
    {detail && <Text color="gray">{detail}</Text>}
    {problem && <Text color="red">{problem}</Text>}
  </Box>
);

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({
  title,
  children,
}) => (
  <Box flexDirection="column" marginTop={1}>
    <Text bold>{title}</Text>
    {children}
  </Box>
);

const DockerProblem: React.FC<{ docker: DockerStatus }> = ({ docker }) =>
  docker.problem ? (
    <Section title="Docker">
      <Row ok={false} name={docker.problem.summary} />
      <Text color="gray"> {docker.problem.fix}</Text>
    </Section>
  ) : null;

const Containers: React.FC<{ containers: ContainerStatus[] }> = ({
  containers,
}) =>
  containers.length > 0 ? (
    <Section title="Services">
      {containers.map((container) => (
        <Row
          key={container.name}
          ok={container.status === "running"}
          name={serviceName(container.name)}
          detail={container.health ?? container.status}
        />
      ))}
    </Section>
  ) : null;

const Dependencies: React.FC<{ readiness: DependencyReadiness }> = ({
  readiness,
}) => (
  <Section title="Backing services">
    {!readiness.reachable ? (
      <Row ok={false} name="Not checked" problem={readiness.detail} />
    ) : (
      readiness.dependencies.map((dependency: DependencyCheck) => (
        <Box key={dependency.name} flexDirection="column">
          <Row
            ok={dependency.ok}
            name={dependencyName(dependency.name)}
            detail={`${dependency.latency_ms} ms`}
            problem={dependency.error_type ?? undefined}
          />
          {dependency.fix && <Text color="gray"> {dependency.fix}</Text>}
        </Box>
      ))
    )}
  </Section>
);

const DeveloperServices: React.FC<{ services: ServiceStatus[] }> = ({
  services,
}) =>
  services.length > 0 ? (
    <Section title="Local services">
      {[...services]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((service) => (
          <Row
            key={service.name}
            ok={service.status === "up"}
            name={`${service.name} (:${service.port})`}
            detail={service.latency ? `${service.latency} ms` : undefined}
          />
        ))}
    </Section>
  ) : null;

export const StatusScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const readiness = state.data.readiness as DependencyReadiness | undefined;
  const docker = state.data.docker as DockerStatus | undefined;
  const services = state.data.services as ServiceStatus[] | undefined;
  const lastChecked = state.data.checkedAt as string | undefined;
  const showingResults = state.step === "Results";

  useInput((input, key) => {
    if (!showingResults) return;
    if (isQuitKey(input, key)) store.submitInput("exit");
    else if (input === "r" && state.data.refreshable) {
      store.submitInput("refresh");
    }
  });

  return (
    <Box flexDirection="column" width="100%">
      <Header />

      {state.step === "Checking" && (
        <Box marginTop={1}>
          <Spinner
            label={
              services ? "Checking again..." : "Checking GAIA's services..."
            }
          />
        </Box>
      )}

      {showingResults && services && (
        <Box flexDirection="column">
          <Box
            flexDirection="column"
            borderStyle={BOX_BORDER}
            borderColor={THEME_COLOR}
            paddingX={2}
            paddingY={1}
          >
            <Box justifyContent="space-between">
              <Text bold color={THEME_COLOR}>
                GAIA status
              </Text>
              {lastChecked && <Text color="gray">checked {lastChecked}</Text>}
            </Box>
            <Text color="gray">{state.data.install}</Text>
            <Text>{state.status}</Text>

            {docker && <DockerProblem docker={docker} />}
            <DeveloperServices services={services} />
            {docker && <Containers containers={docker.containers} />}
            {readiness && <Dependencies readiness={readiness} />}
          </Box>

          <Box marginTop={1} paddingX={1}>
            <Text color="gray">
              <Text bold>r</Text> refresh · <Text bold>q</Text> quit
            </Text>
          </Box>
        </Box>
      )}

      {state.error && <ErrorStep message={state.error.message} />}
    </Box>
  );
};
