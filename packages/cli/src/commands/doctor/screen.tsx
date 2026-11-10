/**
 * Ink screen for `gaia doctor`: the shared run screen, then the report.
 * @module commands/doctor/screen
 */

import { Box, Text } from "ink";
import type React from "react";
import { RunScreen } from "../../ui/components/RunScreen.js";
import type { CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import { DOCTOR_REPORT_KEY, doctorReportLines } from "./report.js";

export const DoctorScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const report = state.data[DOCTOR_REPORT_KEY];
  return (
    <RunScreen
      store={store}
      result={
        report && (
          <Box>
            <Text>{doctorReportLines(report).join("\n")}</Text>
          </Box>
        )
      }
    />
  );
};
