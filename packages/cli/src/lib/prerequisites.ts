/**
 * System prerequisites checking and installation utilities.
 * Verifies required tools (Git, Docker, Mise) are available.
 * @module prerequisites
 */

import { execa } from 'execa';

/**
 * Result of a prerequisite check.
 * - 'success': Tool is installed and working
 * - 'error': Tool exists but failed to run
 * - 'missing': Tool is not installed
 * - 'pending': Check has not been performed yet
 */
export type CheckResult = 'success' | 'error' | 'missing' | 'pending';

/**
 * Checks if Git is installed and accessible.
 * @returns 'success' if Git is available, 'error' otherwise
 */
export async function checkGit(): Promise<CheckResult> {
  try {
    await execa('git', ['--version']);
    return 'success';
  } catch {
    return 'error';
  }
}

/**
 * Checks if Docker is installed and accessible.
 * @returns 'success' if Docker is available, 'error' otherwise
 */
export async function checkDocker(): Promise<CheckResult> {
  try {
    await execa('docker', ['--version']);
    return 'success';
  } catch {
    return 'error';
  }
}

/**
 * Checks if Mise (version manager) is installed.
 * @returns 'success' if Mise is available, 'missing' if not installed
 */
export async function checkMise(): Promise<CheckResult> {
  try {
    await execa('mise', ['--version']);
    return 'success';
  } catch {
    return 'missing';
  }
}

/**
 * Attempts to install Mise using the official install script.
 * @returns True if installation was successful, false otherwise
 */
export async function installMise(): Promise<boolean> {
  try {
    await execa('sh', ['-c', 'curl https://mise.jdx.dev/install.sh | sh']);
    return true;
  } catch {
    return false;
  }
}
/**
 * Checks if a list of ports are available.
 * @param ports - Array of ports to check
 * @returns Object with readiness status and conflicting port if any
 */
export async function checkPorts(ports: number[]): Promise<{ available: boolean; conflict?: number }> {
  try {
    const net = await import('node:net');
    
    // Check one port
    const checkPort = (port: number): Promise<boolean> => {
      return new Promise((resolve) => {
        const server = net.createServer();
        server.once('error', (err: any) => {
          resolve(false);
        });
        server.once('listening', () => {
          server.close(() => resolve(true));
        });
        server.listen(port);
      });
    };

    for (const port of ports) {
      const isFree = await checkPort(port);
      if (!isFree) {
        return { available: false, conflict: port };
      }
    }
    
    return { available: true };
  } catch (e) {
    // If checking fails, log but allow proceeding (could be platform specific)
    console.warn('Port check failed:', e);
    return { available: true };
  }
}
