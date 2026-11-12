import { cp, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const input = process.argv[2];
if (!input) throw new Error('Provide the path to the Philippines/Cashola-Cashify archive');

const workspace = fileURLToPath(new URL('../../dist/evals/cashola-cashify/workspace', import.meta.url));
const sources = [
  'google-play/apks',
  'analysis/web',
  'analysis/business-targeted',
  'analysis/business-entry-review',
  'analysis/public-config',
];
await mkdir(resolve(workspace, '..'), { recursive: true });
await mkdir(workspace);
for (const source of sources) {
  await cp(resolve(input, source), resolve(workspace, 'Cashola-Cashify', source), { recursive: true });
}
console.log(workspace);
