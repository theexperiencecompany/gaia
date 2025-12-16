import { spawn, type ChildProcess } from 'node:child_process';
import { join } from 'node:path';
import { app } from 'electron';
import getPort from 'get-port';

let serverProcess: ChildProcess | null = null;
let serverPort: number = 5174;

/**
 * Check if a port is available (fast check)
 */
async function isPortAvailable(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const net = require('node:net');
    const server = net.createServer();
    
    server.once('error', () => {
      resolve(false);
    });
    
    server.once('listening', () => {
      server.close();
      resolve(true);
    });
    
    server.listen(port, 'localhost');
  });
}

/**
 * Get an available port - try fixed port first for speed
 */
async function findAvailablePort(): Promise<number> {
  const preferredPort = 5174;
  
  // Fast path: try preferred port directly
  if (await isPortAvailable(preferredPort)) {
    return preferredPort;
  }
  
  // Fallback: use get-port for remaining ports
  console.log(`Port ${preferredPort} in use, finding alternative...`);
  return await getPort({ port: [5175, 5176, 5177, 5178, 5179, 5180] });
}

/**
 * Get the URL of the running Next.js server
 */
export function getServerUrl(): string {
  return `http://localhost:${serverPort}`;
}

/**
 * Start the Next.js standalone server
 */
export async function startNextServer(): Promise<void> {
  serverPort = await findAvailablePort();
  
  // Path to the Next.js standalone server
  // In production (packaged app), this is bundled in the app resources
  // In development (mise start), we need to go from apps/desktop/out/main to apps/web/.next/standalone
  const resourcesPath = app.isPackaged
    ? join(process.resourcesPath, 'next-server')
    : join(__dirname, '../../../web/.next/standalone');

  const serverPath = join(resourcesPath, 'apps/web/server.js');

  return new Promise((resolve, reject) => {
    console.log(`Starting Next.js server on port ${serverPort}...`);
    console.log(`Server path: ${serverPath}`);

    serverProcess = spawn('node', [serverPath], {
      env: {
        ...process.env,
        PORT: String(serverPort),
        HOSTNAME: 'localhost',
        NODE_ENV: 'production',
      },
      cwd: resourcesPath,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let resolved = false;

    serverProcess.stdout?.on('data', (data: Buffer) => {
      const message = data.toString();
      console.log('[Next.js]', message);
      
      // Check if server is ready - resolve immediately
      if (!resolved && (message.includes('Ready') || message.includes('started server'))) {
        resolved = true;
        resolve();
      }
    });

    serverProcess.stderr?.on('data', (data: Buffer) => {
      console.error('[Next.js Error]', data.toString());
    });

    serverProcess.on('error', (error) => {
      console.error('Failed to start Next.js server:', error);
      if (!resolved) {
        resolved = true;
        reject(error);
      }
    });

    serverProcess.on('close', (code) => {
      console.log(`Next.js server exited with code ${code}`);
      serverProcess = null;
    });

    // Timeout after 8 seconds - window polling provides additional wait time
    setTimeout(() => {
      if (!resolved && serverProcess) {
        console.warn('Server startup timeout - assuming ready');
        resolved = true;
        resolve();
      }
    }, 8000);
  });
}

/**
 * Stop the Next.js server
 */
export async function stopNextServer(): Promise<void> {
  if (serverProcess) {
    console.log('Stopping Next.js server...');
    serverProcess.kill('SIGTERM');
    serverProcess = null;
  }
}
