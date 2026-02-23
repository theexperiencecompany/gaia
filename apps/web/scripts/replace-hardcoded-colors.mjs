#!/usr/bin/env node

/**
 * Automated Color Replacement Script
 * 
 * This script replaces hardcoded zinc/black/white colors with semantic tokens.
 * Based on the light mode support migration mapping.
 * 
 * Usage:
 *   node scripts/replace-hardcoded-colors.mjs --dry-run    # Preview changes
 *   node scripts/replace-hardcoded-colors.mjs              # Apply changes
 *   node scripts/replace-hardcoded-colors.mjs --verbose    # Show all replacements
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Configuration
const SRC_DIR = path.join(__dirname, '../src');
const DRY_RUN = process.argv.includes('--dry-run');
const VERBOSE = process.argv.includes('--verbose');

// Patterns to exclude from replacement (these are intentional)
const EXCLUDE_PATTERNS = [
  /color-primary-bg/,  // Main background color - intentionally different
];

// Color replacement mappings
// Format: { pattern: RegExp, replacement: string, description: string }

const TEXT_COLOR_REPLACEMENTS = [
  // Text colors - zinc to foreground
  { pattern: /\btext-zinc-50\b/g, replacement: 'text-foreground-50', desc: 'lightest text' },
  { pattern: /\btext-zinc-100\b/g, replacement: 'text-foreground-100', desc: 'very light text' },
  { pattern: /\btext-zinc-200\b/g, replacement: 'text-foreground-200', desc: 'light text' },
  { pattern: /\btext-zinc-300\b/g, replacement: 'text-foreground-300', desc: 'light-medium text' },
  { pattern: /\btext-zinc-400\b/g, replacement: 'text-foreground-400', desc: 'muted text' },
  { pattern: /\btext-zinc-500\b/g, replacement: 'text-foreground-500', desc: 'placeholder text' },
  { pattern: /\btext-zinc-600\b/g, replacement: 'text-foreground-600', desc: 'medium text' },
  { pattern: /\btext-zinc-700\b/g, replacement: 'text-foreground-700', desc: 'medium-dark text' },
  { pattern: /\btext-zinc-800\b/g, replacement: 'text-foreground-800', desc: 'dark text' },
  { pattern: /\btext-zinc-900\b/g, replacement: 'text-foreground-900', desc: 'darkest text' },
  { pattern: /\btext-zinc-950\b/g, replacement: 'text-foreground-900', desc: 'near-black text' },
];

const BG_COLOR_REPLACEMENTS = [
  // Background colors - zinc to surface
  { pattern: /\bbg-zinc-50\b/g, replacement: 'bg-surface-50', desc: 'lightest bg' },
  { pattern: /\bbg-zinc-100\b/g, replacement: 'bg-surface-100', desc: 'very light bg' },
  { pattern: /\bbg-zinc-200\b/g, replacement: 'bg-surface-200', desc: 'light bg' },
  { pattern: /\bbg-zinc-300\b/g, replacement: 'bg-surface-300', desc: 'light-medium bg' },
  { pattern: /\bbg-zinc-400\b/g, replacement: 'bg-surface-400', desc: 'medium-light bg' },
  { pattern: /\bbg-zinc-500\b/g, replacement: 'bg-surface-500', desc: 'medium bg' },
  { pattern: /\bbg-zinc-600\b/g, replacement: 'bg-surface-600', desc: 'medium-dark bg' },
  { pattern: /\bbg-zinc-700\b/g, replacement: 'bg-surface-700', desc: 'dark bg' },
  { pattern: /\bbg-zinc-800\b/g, replacement: 'bg-surface-200', desc: 'very dark bg' },
  { pattern: /\bbg-zinc-900\b/g, replacement: 'bg-surface-100', desc: 'near-black bg' },
  { pattern: /\bbg-zinc-950\b/g, replacement: 'bg-surface-50', desc: 'darkest bg' },
];

const BORDER_COLOR_REPLACEMENTS = [
  // Border colors - zinc to border-surface
  { pattern: /\bborder-zinc-300\b/g, replacement: 'border-border-surface-300', desc: 'light border' },
  { pattern: /\bborder-zinc-400\b/g, replacement: 'border-border-surface-400', desc: 'medium-light border' },
  { pattern: /\bborder-zinc-500\b/g, replacement: 'border-border-surface-500', desc: 'medium border' },
  { pattern: /\bborder-zinc-600\b/g, replacement: 'border-border-surface-600', desc: 'medium-dark border' },
  { pattern: /\bborder-zinc-700\b/g, replacement: 'border-border-surface-700', desc: 'dark border' },
  { pattern: /\bborder-zinc-800\b/g, replacement: 'border-border-surface-800', desc: 'very dark border' },
  { pattern: /\bborder-zinc-900\b/g, replacement: 'border-border-surface-900', desc: 'darkest border' },
];

const HOVER_BG_REPLACEMENTS = [
  // Hover backgrounds
  { pattern: /\bhover:bg-zinc-50\b/g, replacement: 'hover:bg-surface-50', desc: 'hover lightest' },
  { pattern: /\bhover:bg-zinc-100\b/g, replacement: 'hover:bg-surface-100', desc: 'hover very light' },
  { pattern: /\bhover:bg-zinc-200\b/g, replacement: 'hover:bg-surface-200', desc: 'hover light' },
  { pattern: /\bhover:bg-zinc-300\b/g, replacement: 'hover:bg-surface-300', desc: 'hover medium-light' },
  { pattern: /\bhover:bg-zinc-400\b/g, replacement: 'hover:bg-surface-400', desc: 'hover medium' },
  { pattern: /\bhover:bg-zinc-500\b/g, replacement: 'hover:bg-surface-500', desc: 'hover medium-dark' },
  { pattern: /\bhover:bg-zinc-600\b/g, replacement: 'hover:bg-surface-600', desc: 'hover dark' },
  { pattern: /\bhover:bg-zinc-700\b/g, replacement: 'hover:bg-surface-300', desc: 'hover very dark' },
  { pattern: /\bhover:bg-zinc-800\b/g, replacement: 'hover:bg-surface-200', desc: 'hover near-black' },
  { pattern: /\bhover:bg-zinc-900\b/g, replacement: 'hover:bg-surface-100', desc: 'hover darkest' },
];

const HOVER_TEXT_REPLACEMENTS = [
  // Hover text colors
  { pattern: /\bhover:text-zinc-50\b/g, replacement: 'hover:text-foreground-50', desc: 'hover lightest text' },
  { pattern: /\bhover:text-zinc-100\b/g, replacement: 'hover:text-foreground-100', desc: 'hover very light text' },
  { pattern: /\bhover:text-zinc-200\b/g, replacement: 'hover:text-foreground-200', desc: 'hover light text' },
  { pattern: /\bhover:text-zinc-300\b/g, replacement: 'hover:text-foreground-300', desc: 'hover medium text' },
  { pattern: /\bhover:text-zinc-400\b/g, replacement: 'hover:text-foreground-400', desc: 'hover muted text' },
  { pattern: /\bhover:text-zinc-500\b/g, replacement: 'hover:text-foreground-500', desc: 'hover placeholder' },
  { pattern: /\bhover:text-zinc-900\b/g, replacement: 'hover:text-foreground-900', desc: 'hover dark text' },
];

const RING_COLOR_REPLACEMENTS = [
  // Ring colors
  { pattern: /\bring-zinc-300\b/g, replacement: 'ring-border-surface-300', desc: 'light ring' },
  { pattern: /\bring-zinc-400\b/g, replacement: 'ring-border-surface-400', desc: 'medium ring' },
  { pattern: /\bring-zinc-500\b/g, replacement: 'ring-border-surface-500', desc: 'dark ring' },
  { pattern: /\bring-zinc-600\b/g, replacement: 'ring-border-surface-600', desc: 'darker ring' },
  { pattern: /\bring-zinc-700\b/g, replacement: 'ring-border-surface-700', desc: 'very dark ring' },
  { pattern: /\bring-zinc-800\b/g, replacement: 'ring-border-surface-800', desc: 'near-black ring' },
];

const DIVIDE_COLOR_REPLACEMENTS = [
  // Divide colors
  { pattern: /\bdivide-zinc-700\b/g, replacement: 'divide-border-surface-700', desc: 'dark divider' },
  { pattern: /\bdivide-zinc-800\b/g, replacement: 'divide-border-surface-800', desc: 'very dark divider' },
];

const PLACEHOLDER_REPLACEMENTS = [
  // Placeholder colors
  { pattern: /\bplaceholder-zinc-400\b/g, replacement: 'placeholder-foreground-400', desc: 'placeholder' },
  { pattern: /\bplaceholder-zinc-500\b/g, replacement: 'placeholder-foreground-500', desc: 'placeholder' },
  { pattern: /\bplaceholder:text-zinc-400\b/g, replacement: 'placeholder:text-foreground-400', desc: 'placeholder' },
  { pattern: /\bplaceholder:text-zinc-500\b/g, replacement: 'placeholder:text-foreground-500', desc: 'placeholder' },
];

const OPACITY_BG_REPLACEMENTS = [
  // Background with opacity - common patterns
  { pattern: /\bbg-zinc-800\/(\d+)\b/g, replacement: 'bg-surface-200/$1', desc: 'bg with opacity' },
  { pattern: /\bbg-zinc-900\/(\d+)\b/g, replacement: 'bg-surface-100/$1', desc: 'bg with opacity' },
  { pattern: /\bbg-zinc-700\/(\d+)\b/g, replacement: 'bg-surface-300/$1', desc: 'bg with opacity' },
  { pattern: /\bbg-zinc-600\/(\d+)\b/g, replacement: 'bg-surface-400/$1', desc: 'bg with opacity' },
];

const FOCUS_REPLACEMENTS = [
  // Focus states
  { pattern: /\bfocus:bg-zinc-800\b/g, replacement: 'focus:bg-surface-200', desc: 'focus bg' },
  { pattern: /\bfocus:bg-zinc-700\b/g, replacement: 'focus:bg-surface-300', desc: 'focus bg' },
  { pattern: /\bfocus:border-zinc-500\b/g, replacement: 'focus:border-border-surface-500', desc: 'focus border' },
  { pattern: /\bfocus:ring-zinc-500\b/g, replacement: 'focus:ring-border-surface-500', desc: 'focus ring' },
];

const GROUP_HOVER_REPLACEMENTS = [
  // Group hover states
  { pattern: /\bgroup-hover:text-zinc-100\b/g, replacement: 'group-hover:text-foreground-100', desc: 'group hover text' },
  { pattern: /\bgroup-hover:text-zinc-200\b/g, replacement: 'group-hover:text-foreground-200', desc: 'group hover text' },
  { pattern: /\bgroup-hover:text-zinc-300\b/g, replacement: 'group-hover:text-foreground-300', desc: 'group hover text' },
  { pattern: /\bgroup-hover:bg-zinc-800\b/g, replacement: 'group-hover:bg-surface-200', desc: 'group hover bg' },
];

// Combine all replacements
const ALL_REPLACEMENTS = [
  ...TEXT_COLOR_REPLACEMENTS,
  ...BG_COLOR_REPLACEMENTS,
  ...BORDER_COLOR_REPLACEMENTS,
  ...HOVER_BG_REPLACEMENTS,
  ...HOVER_TEXT_REPLACEMENTS,
  ...RING_COLOR_REPLACEMENTS,
  ...DIVIDE_COLOR_REPLACEMENTS,
  ...PLACEHOLDER_REPLACEMENTS,
  ...OPACITY_BG_REPLACEMENTS,
  ...FOCUS_REPLACEMENTS,
  ...GROUP_HOVER_REPLACEMENTS,
];

// File extensions to process
const EXTENSIONS = ['.tsx', '.ts', '.jsx', '.js'];

// Directories to skip
const SKIP_DIRS = ['node_modules', '.next', 'dist', '.git', 'scripts'];

// Stats tracking
const stats = {
  filesScanned: 0,
  filesModified: 0,
  totalReplacements: 0,
  replacementsByType: {},
  modifiedFiles: [],
};

/**
 * Recursively get all files in a directory
 */
function getAllFiles(dir, files = []) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.includes(entry.name)) {
        getAllFiles(fullPath, files);
      }
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name);
      if (EXTENSIONS.includes(ext)) {
        files.push(fullPath);
      }
    }
  }
  
  return files;
}

/**
 * Process a single file
 */
function processFile(filePath) {
  stats.filesScanned++;
  
  let content = fs.readFileSync(filePath, 'utf-8');
  let originalContent = content;
  let fileReplacements = [];
  
  for (const { pattern, replacement, desc } of ALL_REPLACEMENTS) {
    const matches = content.match(pattern);
    if (matches) {
      const count = matches.length;
      content = content.replace(pattern, replacement);
      
      fileReplacements.push({
        from: pattern.source.replace(/\\b/g, ''),
        to: replacement,
        count,
        desc,
      });
      
      stats.totalReplacements += count;
      
      const key = `${pattern.source} → ${replacement}`;
      stats.replacementsByType[key] = (stats.replacementsByType[key] || 0) + count;
    }
  }
  
  if (content !== originalContent) {
    stats.filesModified++;
    stats.modifiedFiles.push({
      path: path.relative(SRC_DIR, filePath),
      replacements: fileReplacements,
    });
    
    if (!DRY_RUN) {
      fs.writeFileSync(filePath, content, 'utf-8');
    }
    
    return true;
  }
  
  return false;
}

/**
 * Main execution
 */
function main() {
  console.log('🎨 Color Replacement Script');
  console.log('===========================\n');
  
  if (DRY_RUN) {
    console.log('🔍 DRY RUN MODE - No files will be modified\n');
  }
  
  console.log(`📁 Scanning: ${SRC_DIR}\n`);
  
  const files = getAllFiles(SRC_DIR);
  
  for (const file of files) {
    processFile(file);
  }
  
  // Print results
  console.log('\n📊 Results');
  console.log('==========\n');
  console.log(`Files scanned: ${stats.filesScanned}`);
  console.log(`Files ${DRY_RUN ? 'to be modified' : 'modified'}: ${stats.filesModified}`);
  console.log(`Total replacements: ${stats.totalReplacements}\n`);
  
  if (stats.filesModified > 0) {
    console.log('📝 Modified Files:');
    console.log('------------------');
    
    for (const file of stats.modifiedFiles) {
      console.log(`\n  ${file.path}`);
      if (VERBOSE) {
        for (const r of file.replacements) {
          console.log(`    • ${r.from} → ${r.to} (${r.count}x)`);
        }
      } else {
        const totalInFile = file.replacements.reduce((sum, r) => sum + r.count, 0);
        console.log(`    ${totalInFile} replacement(s)`);
      }
    }
    
    if (VERBOSE) {
      console.log('\n\n📈 Replacement Summary:');
      console.log('-----------------------');
      const sorted = Object.entries(stats.replacementsByType)
        .sort((a, b) => b[1] - a[1]);
      for (const [key, count] of sorted) {
        console.log(`  ${count}x: ${key}`);
      }
    }
  }
  
  if (DRY_RUN && stats.filesModified > 0) {
    console.log('\n\n💡 To apply these changes, run without --dry-run flag');
  }
  
  if (!DRY_RUN && stats.filesModified > 0) {
    console.log('\n\n✅ Changes applied successfully!');
    console.log('   Run the color audit to verify: npm run color-audit');
  }
}

main();
