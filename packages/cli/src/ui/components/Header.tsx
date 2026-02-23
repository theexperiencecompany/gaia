import { Box } from "ink";
import BigText from "ink-big-text";
import Gradient from "ink-gradient";
import type React from "react";
import { THEME_COLOR } from "../constants.js";

/**
 * Header component displaying the GAIA logo with gradient styling.
 * Uses ink-big-text with 3D font for large ASCII art text.
 */
export const Header: React.FC = () => {
  return (
    <Box flexDirection="column" marginTop={1} marginBottom={1}>
      <Gradient colors={[THEME_COLOR, "#b0eaff", THEME_COLOR]}>
        <BigText text="GAIA" font="3d" />
      </Gradient>
    </Box>
  );
};
