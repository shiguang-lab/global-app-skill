#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { installSkill, syncInstalledSkills } from './skill.mjs';
import { resolveContext } from './resources.mjs';
import { runScript } from './run.mjs';
import { SKILL_NAME, validateMode, VERSION } from './protocol.mjs';

const usage = `global-app-skill ${VERSION}
  skill install [--dir ABSOLUTE_SKILL_DIRECTORY]
  context resolve --mode download|research|ued [--skill-dir PATH] [--cache-dir PATH] [--feed HTTPS_MANIFEST_URL]
  run SCRIPT [--mode download|research|ued] [--skill-dir PATH] [--resource-root PATH] [--cache-dir PATH] [--feed URL] -- SCRIPT_ARGS
  --version

skill install writes only SKILL.md; default: ~/.agents/skills/${SKILL_NAME}.
context resolve and run synchronize existing managed skill entries from this CLI bundle.
Skill locations are discovered from client user/project directories and CLI installation records.
run uses a verified pinned snapshot when --resource-root is supplied; otherwise it resolves current resources.
Script stdout/stderr and exit code are preserved. JSON command results go to stdout; progress goes to stderr.
`;

export async function main(argv) {
  const separator = argv.indexOf('--');
  const { values, positionals } = parseArgs({
    args: separator < 0 ? argv : argv.slice(0, separator), allowPositionals: true,
    options: { dir: { type: 'string' }, 'skill-dir': { type: 'string' }, mode: { type: 'string' }, 'resource-root': { type: 'string' },
      'cache-dir': { type: 'string' }, feed: { type: 'string' }, help: { type: 'boolean' }, version: { type: 'boolean' } },
  });
  if (values.version) { console.log(VERSION); return; }
  if (values.help || positionals.length === 0) { console.log(usage); return; }
  const [command, action] = positionals;
  if (positionals.length !== 2 || (separator >= 0 && command !== 'run')) throw new Error('Invalid command; use --help');
  const allowed = command === 'skill' && action === 'install' ? ['dir'] :
    command === 'context' && action === 'resolve' ? ['mode', 'skill-dir', 'cache-dir', 'feed'] :
    command === 'run' ? ['mode', 'skill-dir', 'resource-root', 'cache-dir', 'feed'] : null;
  if (!allowed) throw new Error('Unknown command; use --help');
  for (const key of Object.keys(values)) {
    if (!allowed.includes(key)) throw new Error(`--${key} is not supported by ${command} ${action}`);
  }
  const options = { mode: values.mode || 'research', resourceRoot: values['resource-root'], cacheDir: values['cache-dir'],
    feed: values.feed, progress: message => process.stderr.write(`[global-app-skill] ${message}\n`) };
  if (command !== 'skill') validateMode(command === 'context' ? values.mode : options.mode);
  if (command === 'run' && options.resourceRoot && (values.feed || values['cache-dir'])) {
    throw new Error('--resource-root cannot be combined with --feed or --cache-dir');
  }
  const skillUpdate = command === 'skill' ? undefined : await syncInstalledSkills({ directory: values['skill-dir'] });
  if (skillUpdate?.error) process.stderr.write(`[global-app-skill] Skill discovery failed: ${skillUpdate.error}\n`);
  for (const entry of skillUpdate?.installations || []) {
    if (entry.status === 'updated') process.stderr.write(`[global-app-skill] Updated local entry: ${entry.skillPath}; reload the skill to use new discovery instructions\n`);
    if (entry.status === 'failed') process.stderr.write(`[global-app-skill] Skill entry update failed: ${entry.skillPath}: ${entry.error}\n`);
  }
  if (command === 'run') {
    process.exitCode = await runScript(action, separator < 0 ? [] : argv.slice(separator + 1), options);
    return;
  }
  let output;
  try { output = command === 'skill' ? await installSkill(values.dir) : { ...await resolveContext(options), skillUpdate }; }
  catch (error) { error.skillUpdate = skillUpdate; throw error; }
  console.log(JSON.stringify(output, null, 2));
}

main(process.argv.slice(2)).catch(error => {
  process.stderr.write(JSON.stringify({ ok: false, error: error.message, ...(error.skillUpdate ? { skillUpdate: error.skillUpdate } : {}) }) + '\n');
  process.exitCode = 1;
});
