import { resolve } from 'node:path';
import { defineConfig, externalizeDepsPlugin } from 'electron-vite';

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      lib: {
        entry: resolve(__dirname, 'src/main/index.ts'),
        formats: ['es'],
      },
      rollupOptions: {
        output: {
          entryFileNames: '[name].mjs',
        },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'src/preload/index.ts'),
        },
      },
    },
  },
  renderer: {
    // We don't use electron-vite for renderer since we use Next.js
    // This is a placeholder config
    build: {
      rollupOptions: {
        input: {},
      },
    },
  },
});
