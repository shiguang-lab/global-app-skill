import { execFile, spawn } from 'node:child_process';
import path from 'node:path';
import { promisify } from 'node:util';
import { SCRIPTS } from './protocol.mjs';
import { readSnapshot, resolveContext } from './resources.mjs';

export async function runScript(script, args, options = {}) {
  if (!SCRIPTS.includes(script)) throw new Error(`Unknown script; choose ${SCRIPTS.join(', ')}`);
  const resourceRoot = options.resourceRoot ? path.resolve(options.resourceRoot) : (await resolveContext(options)).resourceRoot;
  // A task that already resolved an earlier snapshot may finish on it.
  await readSnapshot(resourceRoot, { requireReviewWorkflow: !options.resourceRoot });
  await promisify(execFile)('python3', ['-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'])
    .catch(() => { throw new Error('Python >=3.9 must be available as python3'); });
  return new Promise((resolve, reject) => {
    const child = spawn('python3', [path.join(resourceRoot, 'scripts', `${script}.py`), ...args], {
      stdio: 'inherit',
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', APP_RESEARCH_TOTAL_STAGES: options.mode === 'download' ? '4' : '10' },
    });
    child.once('error', reject);
    child.once('exit', (code, signal) => resolve(code ?? (signal === 'SIGINT' ? 130 : 1)));
  });
}
