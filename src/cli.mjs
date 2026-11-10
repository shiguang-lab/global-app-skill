#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { installSkill } from './skill.mjs';
import { resolveContext } from './resources.mjs';
import { runScript } from './run.mjs';
import { validateMode, VERSION } from './protocol.mjs';

const usage = `global-app-skill ${VERSION}
  skill install [--dir ABSOLUTE_SKILL_DIRECTORY]
  context resolve --mode download|research|ued [--cache-dir PATH] [--feed HTTPS_MANIFEST_URL]
  run SCRIPT [--mode download|research|ued] [--resource-root PATH] [--cache-dir PATH] [--feed URL] -- SCRIPT_ARGS
  --version

skill install writes only SKILL.md; default: ~/.agents/skills/overseas-app-research.
run uses a verified pinned snapshot when --resource-root is supplied; otherwise it resolves current resources.
Script stdout/stderr and exit code are preserved. JSON command results go to stdout; progress goes to stderr.
`;

export async function main(argv) {
  const separator = argv.indexOf('--');
  const { values, positionals } = parseArgs({
    args: separator < 0 ? argv : argv.slice(0, separator), allowPositionals: true,
    options: { dir: { type: 'string' }, mode: { type: 'string' }, 'resource-root': { type: 'string' },
      'cache-dir': { type: 'string' }, feed: { type: 'string' }, help: { type: 'boolean' }, version: { type: 'boolean' } },
  });
  if (values.version) { console.log(VERSION); return; }
  if (values.help || positionals.length === 0) { console.log(usage); return; }
  const [command, action] = positionals;
  if (positionals.length !== 2 || (separator >= 0 && command !== 'run')) throw new Error('Invalid command; use --help');
  const allowed = command === 'skill' && action === 'install' ? ['dir'] :
    command === 'context' && action === 'resolve' ? ['mode', 'cache-dir', 'feed'] :
    command === 'run' ? ['mode', 'resource-root', 'cache-dir', 'feed'] : null;
  if (!allowed) throw new Error('Unknown command; use --help');
  for (const key of Object.keys(values)) {
    if (!allowed.includes(key)) throw new Error(`--${key} is not supported by ${command} ${action}`);
  }
  const options = { mode: values.mode || 'research', resourceRoot: values['resource-root'], cacheDir: values['cache-dir'],
    feed: values.feed, progress: message => process.stderr.write(`[global-app-skill] ${message}\n`) };
  if (command !== 'skill') validateMode(command === 'context' ? values.mode : options.mode);
  if (command === 'run') {
    if (options.resourceRoot && (values.feed || values['cache-dir'])) throw new Error('--resource-root cannot be combined with --feed or --cache-dir');
    process.exitCode = await runScript(action, separator < 0 ? [] : argv.slice(separator + 1), options);
    return;
  }
  const output = command === 'skill' ? await installSkill(values.dir) : await resolveContext(options);
  console.log(JSON.stringify(output, null, 2));
}

main(process.argv.slice(2)).catch(error => {
  process.stderr.write(JSON.stringify({ ok: false, error: error.message }) + '\n');
  process.exitCode = 1;
});
