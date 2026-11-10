import { lstat, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { homedir } from 'node:os';
import path from 'node:path';

export async function installSkill(directory) {
  const target = path.resolve(directory || path.join(homedir(), '.agents/skills/overseas-app-research'));
  const skillPath = path.join(target, 'SKILL.md');
  for (const filename of [target, skillPath]) {
    try {
      if ((await lstat(filename)).isSymbolicLink()) throw new Error(`Refusing to replace a symlinked skill: ${filename}`);
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  const content = await readFile(new URL('../skills/overseas-app-research/SKILL.md', import.meta.url), 'utf8');
  await mkdir(target, { recursive: true });
  const temporary = path.join(target, `.SKILL-${randomUUID()}.tmp`);
  try {
    await writeFile(temporary, content, { flag: 'wx' });
    await rename(temporary, skillPath);
  } finally { await rm(temporary, { force: true }); }
  return { ok: true, skillPath };
}
