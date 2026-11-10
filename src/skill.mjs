import { lstat, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { homedir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { VERSION } from './protocol.mjs';

async function stat(filename) {
  try { return await lstat(filename); }
  catch (error) { if (error.code === 'ENOENT') return undefined; throw error; }
}

async function writeSkill(target, existingOnly) {
  const skillPath = path.join(target, 'SKILL.md');
  for (const filename of [target, skillPath]) {
    if ((await stat(filename))?.isSymbolicLink()) {
      if (existingOnly) return { skillPath, status: 'skipped', reason: 'symlink' };
      throw new Error(`Refusing to replace a symlinked skill: ${filename}`);
    }
  }
  if (existingOnly && !(await stat(skillPath))) return { skillPath, status: 'skipped', reason: 'not-installed' };
  if (!existingOnly) await mkdir(target, { recursive: true });
  const lock = path.join(target, '.global-app-skill-lock');
  const deadline = Date.now() + 5000;
  for (;;) {
    try { await mkdir(lock); break; }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      if (Date.now() >= deadline) throw new Error(`Skill update is locked: ${lock}; retry after the other updater finishes`);
      await delay(50);
    }
  }
  try {
    let previous;
    try { previous = await readFile(skillPath, 'utf8'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (existingOnly && !previous?.includes('global-app-skill@latest context resolve')) {
      return { skillPath, status: 'skipped', reason: 'not-managed' };
    }
    const installedVersion = previous?.match(/^<!-- global-app-skill-version: (\d+\.\d+\.\d+) -->$/m)?.[1];
    if (installedVersion) {
      const installed = installedVersion.split('.').map(Number), bundled = VERSION.split('.').map(Number);
      for (let i = 0; i < 3; i++) {
        if (installed[i] < bundled[i]) break;
        if (installed[i] > bundled[i]) return { skillPath, status: 'skipped', reason: 'newer-installed', installedVersion };
      }
    }
    const bundled = await readFile(new URL('../skills/overseas-app-research/SKILL.md', import.meta.url), 'utf8');
    const quotedDirectory = "'" + target.replaceAll("'", "'\\''") + "'";
    const content = bundled.replaceAll('SKILL_DIRECTORY', quotedDirectory).trimEnd() + `\n\n<!-- global-app-skill-version: ${VERSION} -->\n`;
    if (previous === content) return { skillPath, status: 'unchanged' };
    const temporary = path.join(target, `.SKILL-${randomUUID()}.tmp`);
    try {
      await writeFile(temporary, content, { flag: 'wx' });
      await rename(temporary, skillPath);
    } finally { await rm(temporary, { force: true }); }
    return { skillPath, status: previous === undefined ? 'installed' : 'updated' };
  } finally { await rm(lock, { recursive: true, force: true }); }
}

export async function installSkill(directory) {
  return { ok: true, ...await writeSkill(path.resolve(directory || path.join(homedir(), '.agents/skills/overseas-app-research')), false) };
}

export async function syncInstalledSkills({ directory, directories = [
  path.join(homedir(), '.agents/skills/overseas-app-research'),
  path.join(process.env.CODEX_HOME || path.join(homedir(), '.codex'), 'skills/overseas-app-research'),
] } = {}) {
  const targets = [...new Set((directory ? [directory] : directories).map(target => path.resolve(target)))];
  const installations = [];
  for (const target of targets) {
    try { installations.push(await writeSkill(target, true)); }
    catch (error) { installations.push({ skillPath: path.join(target, 'SKILL.md'), status: 'failed', error: error.message }); }
  }
  return { ok: !installations.some(entry => entry.status === 'failed'), installations };
}
