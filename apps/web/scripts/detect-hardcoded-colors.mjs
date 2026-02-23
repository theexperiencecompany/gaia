#!/usr/bin/env node
/**
 * Color Detection Script
 * 
 * Scans the codebase for remaining hardcoded color classes that should have been
 * migrated to semantic color tokens for light mode support.
 * 
 * Usage: node scripts/detect-hardcoded-colors.mjs [--fix] [--verbose]
 * 
 * Requirements: 7.4 - THE System SHALL ensure no hardcoded colors remain after migration
 */

import { readFileSync, readdirSync, statSync, writeFileSync } from 'fs';
import { join, relative, extname } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Configuration
const CONFIG = {
  // Directories to scan (relative to apps/web)
  scanDirs: ['src'],
  
  // File extensions to scan
  extensions: ['.tsx', '.ts', '.jsx', '.js', '.css'],
  
  // Directories to exclude
  excludeDirs: ['node_modules', '.next', 'dist', 'build', '.git'],
  
  // Files to exclude (theme configuration files that need hex values)
  excludeFiles: ['tailwind.config.ts', 'tailwind.config.js', 'hero.ts'],
  
  // Files with legitimate hex color usage (canvas/SVG drawing, icon colors, etc.)
  allowedHexFiles: [
    'MemoryGraph.tsx',      // Canvas drawing for graph visualization
    'WeatherCard.tsx',      // Icon fill colors for weather icons
    'ProjectFieldChip.tsx', // Fallback colors for project icons
  ],
};

// Patterns to detect hardcoded colors
const HARDCODED_PATTERNS = {
  // Zinc background classes
  zincBg: {
    pattern: /\bbg-zinc-\d{2,3}(?:\/\d+)?\b/g,
    description: 'Hardcoded zinc background',
    severity: 'error',
    suggestion: 'Use bg-surface-* instead',
  },
  
  // Zinc text classes
  zincText: {
    pattern: /\btext-zinc-\d{2,3}\b/g,
    description: 'Hardcoded zinc text',
    severity: 'error',
    suggestion: 'Use text-foreground-* instead',
  },
  
  // Zinc border classes
  zincBorder: {
    pattern: /\bborder-zinc-\d{2,3}(?:\/\d+)?\b/g,
    description: 'Hardcoded zinc border',
    severity: 'error',
    suggestion: 'Use border-surface-* instead',
  },
  
  // Black background (except intentional cases)
  blackBg: {
    pattern: /\bbg-black(?:\/\d+)?\b/g,
    description: 'Hardcoded black background',
    severity: 'warning',
    suggestion: 'Use bg-surface-50 instead (unless intentional)',
  },
  
  // White background (except intentional cases)
  whiteBg: {
    pattern: /\bbg-white(?:\/\d+)?\b/g,
    description: 'Hardcoded white background',
    severity: 'warning',
    suggestion: 'Use bg-surface-950 instead (unless intentional)',
  },
  
  // Black text
  blackText: {
    pattern: /\btext-black\b/g,
    description: 'Hardcoded black text',
    severity: 'warning',
    suggestion: 'Use text-foreground-900 instead (unless intentional)',
  },
  
  // White text
  whiteText: {
    pattern: /\btext-white\b/g,
    description: 'Hardcoded white text',
    severity: 'warning',
    suggestion: 'Use text-foreground-50 instead (unless intentional)',
  },
  
  // Zinc ring classes
  zincRing: {
    pattern: /\bring-zinc-\d{2,3}\b/g,
    description: 'Hardcoded zinc ring',
    severity: 'error',
    suggestion: 'Use ring-surface-* instead',
  },
  
  // Zinc divide classes
  zincDivide: {
    pattern: /\bdivide-zinc-\d{2,3}\b/g,
    description: 'Hardcoded zinc divide',
    severity: 'error',
    suggestion: 'Use divide-surface-* instead',
  },
  
  // Zinc placeholder classes
  zincPlaceholder: {
    pattern: /\bplaceholder-zinc-\d{2,3}\b/g,
    description: 'Hardcoded zinc placeholder',
    severity: 'error',
    suggestion: 'Use placeholder-foreground-* instead',
  },
  
  // Zinc gradient classes
  zincGradient: {
    pattern: /\b(?:from|to|via)-zinc-\d{2,3}\b/g,
    description: 'Hardcoded zinc gradient',
    severity: 'error',
    suggestion: 'Use from/to/via-surface-* instead',
  },
  
  // CSS hex colors (common dark theme colors)
  cssHexDark: {
    pattern: /#(?:18181b|27272a|3f3f46|52525b|71717a|a1a1aa|d4d4d8|e4e4e7|f4f4f5|fafafa)\b/gi,
    description: 'Hardcoded hex color (zinc palette)',
    severity: 'error',
    suggestion: 'Use hsl(var(--surface-*)) instead',
  },
  
  // CSS hex black/white
  cssHexBW: {
    pattern: /#(?:000000|000|ffffff|fff)\b/gi,
    description: 'Hardcoded hex black/white',
    severity: 'warning',
    suggestion: 'Use hsl(var(--surface-50)) or hsl(var(--surface-950)) instead',
  },
};

// Allowed patterns (exceptions that should not be flagged)
const ALLOWED_PATTERNS = [
  // Comments
  /\/\/.*$/gm,
  /\/\*[\s\S]*?\*\//g,
  
  // String literals that are documentation
  /'[^']*zinc[^']*'/g,
  /"[^"]*zinc[^"]*"/g,
  
  // Tailwind config files
  /tailwind\.config/,
  
  // CSS variable definitions (these are intentional)
  /--[\w-]+:\s*\d+\s+[\d.]+%\s+[\d.]+%/g,
];

// Results storage
const results = {
  errors: [],
  warnings: [],
  totalFiles: 0,
  scannedFiles: 0,
  summary: {},
};

/**
 * Check if a path should be excluded
 */
function shouldExclude(filePath) {
  const pathParts = filePath.split('/');
  
  // Check excluded directories
  for (const dir of CONFIG.excludeDirs) {
    if (pathParts.includes(dir)) return true;
  }
  
  // Check excluded files
  for (const file of CONFIG.excludeFiles) {
    if (filePath.endsWith(file)) return true;
  }
  
  return false;
}

/**
 * Get all files to scan recursively
 */
function getFilesToScan(dir) {
  const files = [];
  
  try {
    const entries = readdirSync(dir);
    
    for (const entry of entries) {
      const fullPath = join(dir, entry);
      
      if (shouldExclude(fullPath)) continue;
      
      const stat = statSync(fullPath);
      
      if (stat.isDirectory()) {
        files.push(...getFilesToScan(fullPath));
      } else if (stat.isFile()) {
        const ext = extname(entry);
        if (CONFIG.extensions.includes(ext)) {
          files.push(fullPath);
        }
      }
    }
  } catch (error) {
    console.error(`Error reading directory ${dir}:`, error.message);
  }
  
  return files;
}

/**
 * Check if a match is within an allowed context
 */
function isAllowedContext(content, match, matchIndex) {
  // Check if match is in a comment
  const lineStart = content.lastIndexOf('\n', matchIndex) + 1;
  const lineEnd = content.indexOf('\n', matchIndex);
  const line = content.slice(lineStart, lineEnd === -1 ? undefined : lineEnd);
  
  // Skip if in a single-line comment
  if (line.includes('//') && line.indexOf('//') < line.indexOf(match)) {
    return true;
  }
  
  // Skip if in a multi-line comment
  const beforeMatch = content.slice(0, matchIndex);
  const lastCommentStart = beforeMatch.lastIndexOf('/*');
  const lastCommentEnd = beforeMatch.lastIndexOf('*/');
  if (lastCommentStart > lastCommentEnd) {
    return true;
  }
  
  // Skip if it's a CSS variable definition in the theme file
  if (content.includes('@layer base') && line.includes('--')) {
    return true;
  }
  
  return false;
}

/**
 * Scan a single file for hardcoded colors
 */
function scanFile(filePath) {
  const content = readFileSync(filePath, 'utf-8');
  const relativePath = relative(process.cwd(), filePath);
  const fileResults = [];
  
  // Check if this file is allowed to have hex colors
  const fileName = filePath.split('/').pop();
  const isAllowedHexFile = CONFIG.allowedHexFiles?.some(f => fileName === f);
  
  for (const [patternName, config] of Object.entries(HARDCODED_PATTERNS)) {
    // Skip hex color checks for files with legitimate hex usage
    if (isAllowedHexFile && (patternName === 'cssHexDark' || patternName === 'cssHexBW')) {
      continue;
    }
    
    const { pattern, description, severity, suggestion } = config;
    
    // Reset regex lastIndex
    pattern.lastIndex = 0;
    
    let match;
    while ((match = pattern.exec(content)) !== null) {
      const matchIndex = match.index;
      
      // Skip if in allowed context
      if (isAllowedContext(content, match[0], matchIndex)) {
        continue;
      }
      
      // Calculate line number
      const lines = content.slice(0, matchIndex).split('\n');
      const lineNumber = lines.length;
      const column = lines[lines.length - 1].length + 1;
      
      // Get context (the line containing the match)
      const lineStart = content.lastIndexOf('\n', matchIndex) + 1;
      const lineEnd = content.indexOf('\n', matchIndex);
      const context = content.slice(lineStart, lineEnd === -1 ? undefined : lineEnd).trim();
      
      const result = {
        file: relativePath,
        line: lineNumber,
        column,
        match: match[0],
        pattern: patternName,
        description,
        severity,
        suggestion,
        context,
      };
      
      fileResults.push(result);
      
      if (severity === 'error') {
        results.errors.push(result);
      } else {
        results.warnings.push(result);
      }
      
      // Track summary
      if (!results.summary[patternName]) {
        results.summary[patternName] = 0;
      }
      results.summary[patternName]++;
    }
  }
  
  return fileResults;
}

/**
 * Format results for console output
 */
function formatResults(verbose = false) {
  const output = [];
  
  output.push('\n' + '='.repeat(80));
  output.push('HARDCODED COLOR DETECTION REPORT');
  output.push('='.repeat(80) + '\n');
  
  output.push(`Files scanned: ${results.scannedFiles}`);
  output.push(`Total errors: ${results.errors.length}`);
  output.push(`Total warnings: ${results.warnings.length}`);
  output.push('');
  
  // Summary by pattern
  output.push('Summary by Pattern:');
  output.push('-'.repeat(40));
  for (const [pattern, count] of Object.entries(results.summary)) {
    const config = HARDCODED_PATTERNS[pattern];
    const icon = config.severity === 'error' ? '❌' : '⚠️';
    output.push(`  ${icon} ${pattern}: ${count} occurrences`);
  }
  output.push('');
  
  // Detailed results
  if (verbose || results.errors.length + results.warnings.length <= 50) {
    if (results.errors.length > 0) {
      output.push('ERRORS (must fix):');
      output.push('-'.repeat(40));
      for (const error of results.errors) {
        output.push(`  ❌ ${error.file}:${error.line}:${error.column}`);
        output.push(`     Match: ${error.match}`);
        output.push(`     ${error.description}`);
        output.push(`     Suggestion: ${error.suggestion}`);
        if (verbose) {
          output.push(`     Context: ${error.context}`);
        }
        output.push('');
      }
    }
    
    if (results.warnings.length > 0) {
      output.push('WARNINGS (review needed):');
      output.push('-'.repeat(40));
      for (const warning of results.warnings) {
        output.push(`  ⚠️  ${warning.file}:${warning.line}:${warning.column}`);
        output.push(`     Match: ${warning.match}`);
        output.push(`     ${warning.description}`);
        output.push(`     Suggestion: ${warning.suggestion}`);
        if (verbose) {
          output.push(`     Context: ${warning.context}`);
        }
        output.push('');
      }
    }
  } else {
    output.push('(Use --verbose to see all details)');
    output.push('');
  }
  
  // Final status
  output.push('='.repeat(80));
  if (results.errors.length === 0 && results.warnings.length === 0) {
    output.push('✅ SUCCESS: No hardcoded colors detected!');
  } else if (results.errors.length === 0) {
    output.push('⚠️  PASS WITH WARNINGS: No errors, but some warnings to review.');
  } else {
    output.push('❌ FAILED: Hardcoded colors detected that need migration.');
  }
  output.push('='.repeat(80) + '\n');
  
  return output.join('\n');
}

/**
 * Generate JSON report
 */
function generateJsonReport() {
  return JSON.stringify({
    timestamp: new Date().toISOString(),
    summary: {
      filesScanned: results.scannedFiles,
      totalErrors: results.errors.length,
      totalWarnings: results.warnings.length,
      byPattern: results.summary,
    },
    errors: results.errors,
    warnings: results.warnings,
  }, null, 2);
}

/**
 * Main function
 */
function main() {
  const args = process.argv.slice(2);
  const verbose = args.includes('--verbose') || args.includes('-v');
  const jsonOutput = args.includes('--json');
  const saveReport = args.includes('--save');
  
  console.log('🔍 Scanning for hardcoded colors...\n');
  
  // Get the web app root directory
  const webAppRoot = join(__dirname, '..');
  
  // Collect all files to scan
  const filesToScan = [];
  for (const dir of CONFIG.scanDirs) {
    const fullDir = join(webAppRoot, dir);
    filesToScan.push(...getFilesToScan(fullDir));
  }
  
  results.totalFiles = filesToScan.length;
  
  // Scan each file
  for (const file of filesToScan) {
    scanFile(file);
    results.scannedFiles++;
  }
  
  // Output results
  if (jsonOutput) {
    console.log(generateJsonReport());
  } else {
    console.log(formatResults(verbose));
  }
  
  // Save report if requested
  if (saveReport) {
    const reportPath = join(webAppRoot, 'color-audit-report.json');
    writeFileSync(reportPath, generateJsonReport());
    console.log(`📄 Report saved to: ${reportPath}\n`);
  }
  
  // Exit with error code if errors found
  if (results.errors.length > 0) {
    process.exit(1);
  }
  
  process.exit(0);
}

main();
