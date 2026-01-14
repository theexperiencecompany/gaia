#!/usr/bin/env node
/**
 * Contrast Ratio Testing Script
 * 
 * Tests all color combinations in the semantic color system for WCAG AA compliance.
 * WCAG AA requires:
 * - Normal text: minimum 4.5:1 contrast ratio
 * - Large text (18pt+ or 14pt+ bold): minimum 3:1 contrast ratio
 * - UI components and graphical objects: minimum 3:1 contrast ratio
 * 
 * Requirements: 7.3 - THE System SHALL maintain proper contrast ratios in both themes
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// WCAG AA minimum contrast ratios
const WCAG_AA = {
  normalText: 4.5,
  largeText: 3.0,
  uiComponents: 3.0,
};

// Semantic color definitions (HSL values from design.md)
// Light mode colors
const LIGHT_MODE_COLORS = {
  // Base
  background: { h: 0, s: 0, l: 100 },           // White
  foreground: { h: 240, s: 5.9, l: 10 },        // zinc-950
  
  // Surface scale
  'surface-50': { h: 240, s: 4.8, l: 95.9 },    // zinc-50
  'surface-100': { h: 240, s: 4.8, l: 95.9 },   // zinc-100
  'surface-200': { h: 240, s: 5.9, l: 90 },     // zinc-200
  'surface-300': { h: 240, s: 4.9, l: 83.9 },   // zinc-300
  'surface-400': { h: 240, s: 5, l: 64.9 },     // zinc-400
  'surface-500': { h: 240, s: 3.8, l: 46.1 },   // zinc-500
  'surface-600': { h: 240, s: 5.2, l: 33.9 },   // zinc-600
  'surface-700': { h: 240, s: 5.3, l: 26.1 },   // zinc-700
  'surface-800': { h: 240, s: 3.7, l: 15.9 },   // zinc-800
  'surface-900': { h: 240, s: 5.9, l: 10 },     // zinc-900
  'surface-950': { h: 240, s: 10, l: 3.9 },     // zinc-950
  
  // Text scale
  'foreground-50': { h: 240, s: 4.8, l: 95.9 },
  'foreground-100': { h: 240, s: 4.8, l: 95.9 },
  'foreground-200': { h: 240, s: 5.9, l: 90 },
  'foreground-300': { h: 240, s: 4.9, l: 83.9 },
  'foreground-400': { h: 240, s: 5, l: 64.9 },
  'foreground-500': { h: 240, s: 3.8, l: 46.1 },
  'foreground-600': { h: 240, s: 5.2, l: 33.9 },
  'foreground-700': { h: 240, s: 5.3, l: 26.1 },
  'foreground-800': { h: 240, s: 3.7, l: 15.9 },
  'foreground-900': { h: 240, s: 5.9, l: 10 },
  
  // Brand
  primary: { h: 196, s: 100, l: 50 },           // #00bbff
};

// Dark mode colors (inverted)
const DARK_MODE_COLORS = {
  // Base
  background: { h: 240, s: 10, l: 3.9 },        // zinc-950
  foreground: { h: 240, s: 4.8, l: 95.9 },      // zinc-50
  
  // Surface scale (inverted)
  'surface-50': { h: 240, s: 10, l: 3.9 },      // zinc-950
  'surface-100': { h: 240, s: 5.9, l: 10 },     // zinc-900
  'surface-200': { h: 240, s: 3.7, l: 15.9 },   // zinc-800
  'surface-300': { h: 240, s: 5.3, l: 26.1 },   // zinc-700
  'surface-400': { h: 240, s: 5.2, l: 33.9 },   // zinc-600
  'surface-500': { h: 240, s: 3.8, l: 46.1 },   // zinc-500
  'surface-600': { h: 240, s: 5, l: 64.9 },     // zinc-400
  'surface-700': { h: 240, s: 4.9, l: 83.9 },   // zinc-300
  'surface-800': { h: 240, s: 5.9, l: 90 },     // zinc-200
  'surface-900': { h: 240, s: 4.8, l: 95.9 },   // zinc-100
  'surface-950': { h: 240, s: 4.8, l: 95.9 },   // zinc-50
  
  // Text scale (inverted)
  'foreground-50': { h: 240, s: 10, l: 3.9 },
  'foreground-100': { h: 240, s: 5.9, l: 10 },
  'foreground-200': { h: 240, s: 3.7, l: 15.9 },
  'foreground-300': { h: 240, s: 5.3, l: 26.1 },
  'foreground-400': { h: 240, s: 5.2, l: 33.9 },
  'foreground-500': { h: 240, s: 3.8, l: 46.1 },
  'foreground-600': { h: 240, s: 5, l: 64.9 },
  'foreground-700': { h: 240, s: 4.9, l: 83.9 },
  'foreground-800': { h: 240, s: 5.9, l: 90 },
  'foreground-900': { h: 240, s: 4.8, l: 95.9 },
  
  // Brand
  primary: { h: 196, s: 100, l: 50 },           // #00bbff
};

// Common color combinations to test
const COLOR_COMBINATIONS = [
  // Primary text on backgrounds
  { fg: 'foreground', bg: 'background', type: 'normalText', description: 'Primary text on page background' },
  { fg: 'foreground-400', bg: 'background', type: 'normalText', description: 'Muted text on page background' },
  { fg: 'foreground-500', bg: 'background', type: 'normalText', description: 'Placeholder text on page background' },
  
  // Text on surface levels
  { fg: 'foreground', bg: 'surface-100', type: 'normalText', description: 'Primary text on surface-100' },
  { fg: 'foreground', bg: 'surface-200', type: 'normalText', description: 'Primary text on surface-200' },
  { fg: 'foreground', bg: 'surface-300', type: 'normalText', description: 'Primary text on surface-300' },
  { fg: 'foreground-400', bg: 'surface-200', type: 'normalText', description: 'Muted text on surface-200' },
  { fg: 'foreground-500', bg: 'surface-200', type: 'normalText', description: 'Placeholder on surface-200' },
  
  // Primary color combinations
  { fg: 'primary', bg: 'background', type: 'normalText', description: 'Primary brand on page background' },
  { fg: 'primary', bg: 'surface-200', type: 'normalText', description: 'Primary brand on surface-200' },
  { fg: 'foreground', bg: 'primary', type: 'normalText', description: 'Text on primary background' },
  
  // Card/component backgrounds
  { fg: 'foreground', bg: 'surface-50', type: 'normalText', description: 'Text on card background' },
  { fg: 'foreground-400', bg: 'surface-50', type: 'normalText', description: 'Muted text on card' },
  
  // Border contrast (UI components)
  { fg: 'surface-300', bg: 'background', type: 'uiComponents', description: 'Border on page background' },
  { fg: 'surface-400', bg: 'surface-200', type: 'uiComponents', description: 'Border on surface-200' },
  
  // Interactive elements
  { fg: 'foreground-50', bg: 'surface-700', type: 'normalText', description: 'Light text on dark button' },
  { fg: 'foreground-900', bg: 'surface-200', type: 'normalText', description: 'Dark text on light button' },
];

/**
 * Convert HSL to RGB
 */
function hslToRgb(h, s, l) {
  s /= 100;
  l /= 100;
  
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((h / 60) % 2 - 1));
  const m = l - c / 2;
  
  let r, g, b;
  
  if (h >= 0 && h < 60) {
    [r, g, b] = [c, x, 0];
  } else if (h >= 60 && h < 120) {
    [r, g, b] = [x, c, 0];
  } else if (h >= 120 && h < 180) {
    [r, g, b] = [0, c, x];
  } else if (h >= 180 && h < 240) {
    [r, g, b] = [0, x, c];
  } else if (h >= 240 && h < 300) {
    [r, g, b] = [x, 0, c];
  } else {
    [r, g, b] = [c, 0, x];
  }
  
  return {
    r: Math.round((r + m) * 255),
    g: Math.round((g + m) * 255),
    b: Math.round((b + m) * 255),
  };
}

/**
 * Calculate relative luminance
 * https://www.w3.org/TR/WCAG20/#relativeluminancedef
 */
function getRelativeLuminance(rgb) {
  const [r, g, b] = [rgb.r, rgb.g, rgb.b].map(c => {
    c = c / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Calculate contrast ratio between two colors
 * https://www.w3.org/TR/WCAG20/#contrast-ratiodef
 */
function getContrastRatio(color1, color2) {
  const rgb1 = hslToRgb(color1.h, color1.s, color1.l);
  const rgb2 = hslToRgb(color2.h, color2.s, color2.l);
  
  const l1 = getRelativeLuminance(rgb1);
  const l2 = getRelativeLuminance(rgb2);
  
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Check if contrast ratio meets WCAG AA requirements
 */
function meetsWcagAA(ratio, type) {
  return ratio >= WCAG_AA[type];
}

/**
 * Format contrast ratio for display
 */
function formatRatio(ratio) {
  return ratio.toFixed(2) + ':1';
}

/**
 * Test all color combinations for a theme
 */
function testTheme(themeName, colors) {
  const results = {
    passed: [],
    failed: [],
    warnings: [],
  };
  
  for (const combo of COLOR_COMBINATIONS) {
    const fgColor = colors[combo.fg];
    const bgColor = colors[combo.bg];
    
    if (!fgColor || !bgColor) {
      results.warnings.push({
        ...combo,
        message: `Color not found: ${!fgColor ? combo.fg : combo.bg}`,
      });
      continue;
    }
    
    const ratio = getContrastRatio(fgColor, bgColor);
    const passes = meetsWcagAA(ratio, combo.type);
    const required = WCAG_AA[combo.type];
    
    const result = {
      ...combo,
      ratio,
      required,
      passes,
      theme: themeName,
    };
    
    if (passes) {
      results.passed.push(result);
    } else {
      results.failed.push(result);
    }
  }
  
  return results;
}

/**
 * Format results for console output
 */
function formatResults(lightResults, darkResults) {
  const output = [];
  
  output.push('\n' + '='.repeat(80));
  output.push('WCAG AA CONTRAST RATIO TEST REPORT');
  output.push('='.repeat(80) + '\n');
  
  // Light mode results
  output.push('LIGHT MODE');
  output.push('-'.repeat(40));
  output.push(`✅ Passed: ${lightResults.passed.length}`);
  output.push(`❌ Failed: ${lightResults.failed.length}`);
  output.push(`⚠️  Warnings: ${lightResults.warnings.length}`);
  output.push('');
  
  if (lightResults.failed.length > 0) {
    output.push('Failed combinations:');
    for (const result of lightResults.failed) {
      output.push(`  ❌ ${result.description}`);
      output.push(`     ${result.fg} on ${result.bg}`);
      output.push(`     Ratio: ${formatRatio(result.ratio)} (required: ${result.required}:1)`);
    }
    output.push('');
  }
  
  // Dark mode results
  output.push('DARK MODE');
  output.push('-'.repeat(40));
  output.push(`✅ Passed: ${darkResults.passed.length}`);
  output.push(`❌ Failed: ${darkResults.failed.length}`);
  output.push(`⚠️  Warnings: ${darkResults.warnings.length}`);
  output.push('');
  
  if (darkResults.failed.length > 0) {
    output.push('Failed combinations:');
    for (const result of darkResults.failed) {
      output.push(`  ❌ ${result.description}`);
      output.push(`     ${result.fg} on ${result.bg}`);
      output.push(`     Ratio: ${formatRatio(result.ratio)} (required: ${result.required}:1)`);
    }
    output.push('');
  }
  
  // Summary
  output.push('='.repeat(80));
  const totalPassed = lightResults.passed.length + darkResults.passed.length;
  const totalFailed = lightResults.failed.length + darkResults.failed.length;
  const totalTests = totalPassed + totalFailed;
  
  if (totalFailed === 0) {
    output.push(`✅ ALL TESTS PASSED (${totalPassed}/${totalTests})`);
  } else {
    output.push(`❌ SOME TESTS FAILED (${totalPassed}/${totalTests} passed)`);
  }
  output.push('='.repeat(80) + '\n');
  
  return output.join('\n');
}

/**
 * Generate detailed report
 */
function generateDetailedReport(lightResults, darkResults) {
  const output = [];
  
  output.push('\n' + '='.repeat(80));
  output.push('DETAILED CONTRAST RATIO REPORT');
  output.push('='.repeat(80) + '\n');
  
  // All light mode results
  output.push('LIGHT MODE - ALL COMBINATIONS');
  output.push('-'.repeat(60));
  for (const result of [...lightResults.passed, ...lightResults.failed]) {
    const icon = result.passes ? '✅' : '❌';
    output.push(`${icon} ${result.description}`);
    output.push(`   ${result.fg} on ${result.bg}: ${formatRatio(result.ratio)} (min: ${result.required}:1)`);
  }
  output.push('');
  
  // All dark mode results
  output.push('DARK MODE - ALL COMBINATIONS');
  output.push('-'.repeat(60));
  for (const result of [...darkResults.passed, ...darkResults.failed]) {
    const icon = result.passes ? '✅' : '❌';
    output.push(`${icon} ${result.description}`);
    output.push(`   ${result.fg} on ${result.bg}: ${formatRatio(result.ratio)} (min: ${result.required}:1)`);
  }
  output.push('');
  
  return output.join('\n');
}

/**
 * Main function
 */
function main() {
  const args = process.argv.slice(2);
  const verbose = args.includes('--verbose') || args.includes('-v');
  
  console.log('🎨 Testing contrast ratios for WCAG AA compliance...\n');
  
  // Test both themes
  const lightResults = testTheme('light', LIGHT_MODE_COLORS);
  const darkResults = testTheme('dark', DARK_MODE_COLORS);
  
  // Output results
  console.log(formatResults(lightResults, darkResults));
  
  if (verbose) {
    console.log(generateDetailedReport(lightResults, darkResults));
  }
  
  // Exit with error code if any tests failed
  const totalFailed = lightResults.failed.length + darkResults.failed.length;
  if (totalFailed > 0) {
    process.exit(1);
  }
  
  process.exit(0);
}

main();
