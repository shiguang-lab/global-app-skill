import { lstat, mkdir, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { homedir } from 'node:os';
import path from 'node:path';
import { sha256 } from './protocol.mjs';

export const SKILL_ROOTS = ['.agents/skills', '.codex/skills', '.claude/skills', '.cursor/skills', '.gemini/skills', '.kiro/skills'];
const skillName = 'overseas-app-research';

function stateRoot({ home = homedir(), env = process.env, stateDirectory } = {}) {
  return path.resolve(stateDirectory || path.join(env.XDG_STATE_HOME || path.join(home, '.local/state'), 'global-app-skill'));
}

async function exists(filename) {
  try { await lstat(filename); return true; }
  catch (error) { if (['ENOENT', 'ENOTDIR'].includes(error.code)) return false; throw error; }
}

export async function rememberInstallation(directory, options = {}) {
  directory = path.resolve(directory);
  const registry = path.join(stateRoot(options), 'installations');
  await mkdir(registry, { recursive: true });
  // Independent records avoid lost registrations when installs run concurrently.
  const target = path.join(registry, `${sha256(directory)}.json`);
  const temporary = path.join(registry, `.${randomUUID()}.tmp`);
  try {
    await writeFile(temporary, JSON.stringify({ directory }) + '\n', { flag: 'wx' });
    await rename(temporary, target);
  } finally { await rm(temporary, { force: true }); }
}

async function registeredDirectories(options) {
  const registry = path.join(stateRoot(options), 'installations');
  let names;
  try { names = await readdir(registry); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  return Promise.all(names.filter(name => name.endsWith('.json')).sort().map(async name => {
    const { directory } = JSON.parse(await readFile(path.join(registry, name), 'utf8'));
    if (typeof directory !== 'string' || !path.isAbsolute(directory) || name !== `${sha256(directory)}.json`) {
      throw new Error(`Invalid skill installation record: ${path.join(registry, name)}`);
    }
    return directory;
  }));
}

async function projectDirectories(cwd) {
  const directories = [];
  for (let directory = path.resolve(cwd); ; directory = path.dirname(directory)) {
    directories.push(directory);
    if (await exists(path.join(directory, '.git'))) return directories;
    if (path.dirname(directory) === directory) return [path.resolve(cwd)];
  }
}

export async function discoverSkillDirectories(options = {}) {
  const { home = homedir(), env = process.env, cwd = process.cwd() } = options;
  const bases = [path.resolve(home), ...await projectDirectories(cwd)];
  const candidates = bases.flatMap(base => SKILL_ROOTS.map(root => path.join(base, root, skillName)));
  if (env.CODEX_HOME) candidates.push(path.resolve(env.CODEX_HOME, 'skills', skillName));
  candidates.push(...await registeredDirectories(options));
  const unique = [...new Set(candidates)];
  const present = await Promise.all(unique.map(directory => exists(path.join(directory, 'SKILL.md'))));
  return unique.filter((directory, index) => present[index]);
}
