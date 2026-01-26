import React from 'react';
import { Box } from 'ink';
import Gradient from 'ink-gradient';
import BigText from 'ink-big-text';
import { THEME_COLOR } from '../constants.js';

/**
 * Header component displaying the GAIA logo with gradient styling.
 * Uses ink-big-text for ASCII art text and ink-gradient for color effects.
 */
export const Header: React.FC = () => {
    return (
        <Box flexDirection="column" marginTop={1}>
            <Gradient colors={[THEME_COLOR, "#b0eaff", THEME_COLOR]}>
                <BigText text="GAIA" font="3d" />
            </Gradient>
        </Box>
    );
};
