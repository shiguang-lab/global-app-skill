import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { discoverSkillDirectories, SKILL_ROOTS } from '../src/installations.mjs';
import { installSkill, syncInstalledSkills } from '../src/skill.mjs';
import { VERSION } from '../src/protocol.mjs';

const oldEntry = '---\nname: overseas-app-research\n---\nnpx -y --prefer-online global-app-skill@latest context resolve --mode MODE\n';

async function fixture(t) {
  const root = await mkdtemp(path.join(tmpdir(), 'global-app-skill-discovery-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const options = { home: path.join(root, 'home'), cwd: path.join(root, 'work'), env: {}, stateDirectory: path.join(root, 'state') };
  await mkdir(options.home);
  await mkdir(options.cwd);
  return { root, options };
}

async function oldSkill(directory) {
  await mkdir(directory, { recursive: true });
  await writeFile(path.join(directory, 'SKILL.md'), oldEntry);
  return directory;
}

test('installs the same portable file in different locations and remembers concurrent custom installs', async t => {
  const { root, options } = await fixture(t);
  const targets = [path.join(root, "owner's custom skill"), path.join(root, 'another machine layout/skill')];
  await Promise.all(targets.map(target => installSkill(target, options)));
  const texts = await Promise.all(targets.map(target => readFile(path.join(target, 'SKILL.md'), 'utf8')));
  assert.equal(texts[0], texts[1]);
  for (const target of targets) {
    assert.ok(!texts[0].includes(target));
    assert.deepEqual(await readdir(target), ['SKILL.md']);
    await writeFile(path.join(target, 'SKILL.md'), oldEntry);
  }
  assert.ok(!texts[0].includes('--skill-dir'));
  assert.ok(!texts[0].includes('SKILL_DIRECTORY'));
  assert.deepEqual((await discoverSkillDirectories(options)).sort(), targets.sort());
  const updated = await syncInstalledSkills(options);
  assert.equal(updated.ok, true);
  assert.equal(updated.installations.filter(entry => entry.status === 'updated').length, targets.length);
  for (const target of targets) assert.equal(await readFile(path.join(target, 'SKILL.md'), 'utf8'), texts[0]);
});

test('discovers existing client user/project skills up to the nearest repository root', async t => {
  const { root, options } = await fixture(t);
  const repo = path.join(root, 'repo');
  const nested = path.join(repo, 'packages/ui/src');
  await mkdir(nested, { recursive: true });
  await writeFile(path.join(repo, '.git'), 'gitdir: /fixture/worktree');
  const expected = [];
  for (const directory of SKILL_ROOTS) expected.push(await oldSkill(path.join(options.home, directory, 'overseas-app-research')));
  expected.push(await oldSkill(path.join(repo, '.claude/skills/overseas-app-research')));
  expected.push(await oldSkill(path.join(repo, 'packages/ui/.cursor/skills/overseas-app-research')));
  const codexHome = path.join(root, 'codex-config');
  expected.push(await oldSkill(path.join(codexHome, 'skills/overseas-app-research')));
  const outside = await oldSkill(path.join(root, '.agents/skills/overseas-app-research'));
  const unrelated = await oldSkill(path.join(repo, 'other-project/.gemini/skills/overseas-app-research'));
  const scoped = { ...options, cwd: nested, env: { CODEX_HOME: codexHome } };
  assert.deepEqual((await discoverSkillDirectories(scoped)).sort(), expected.sort());
  const result = await syncInstalledSkills(scoped);
  assert.equal(result.ok, true);
  assert.equal(result.installations.filter(entry => entry.status === 'updated').length, expected.length);
  assert.equal(await readFile(path.join(outside, 'SKILL.md'), 'utf8'), oldEntry);
  assert.equal(await readFile(path.join(unrelated, 'SKILL.md'), 'utf8'), oldEntry);
});

test('a moved standard-directory skill updates without the old machine installation record', async t => {
  const { root, options } = await fixture(t);
  const original = path.join(root, 'machine-a/custom/skill');
  await installSkill(original, options);
  const portable = await readFile(path.join(original, 'SKILL.md'), 'utf8');
  const secondHome = path.join(root, 'machine-b');
  const moved = path.join(secondHome, '.gemini/skills/overseas-app-research');
  await mkdir(path.dirname(moved), { recursive: true });
  await rename(original, moved);
  await writeFile(path.join(moved, 'SKILL.md'), portable.replace(`global-app-skill-version: ${VERSION}`, 'global-app-skill-version: 0.0.1') + '\nold entry\n');
  const secondOptions = { ...options, home: secondHome, stateDirectory: path.join(root, 'new-state') };
  const result = await syncInstalledSkills(secondOptions);
  assert.equal(result.installations.length, 1);
  assert.equal(result.installations[0].skillPath, path.join(moved, 'SKILL.md'));
  assert.equal(result.installations[0].status, 'updated');
  assert.equal(await readFile(path.join(moved, 'SKILL.md'), 'utf8'), portable);
  await assert.rejects(readFile(path.join(original, 'SKILL.md')), { code: 'ENOENT' });
});

test('discovery outside a repository stays local, skips missing registrations, and reports corrupt state', async t => {
  const { root, options } = await fixture(t);
  const local = await oldSkill(path.join(options.cwd, '.kiro/skills/overseas-app-research'));
  await oldSkill(path.join(root, '.cursor/skills/overseas-app-research'));
  const custom = path.join(root, 'removed-skill');
  await installSkill(custom, options);
  await rm(custom, { recursive: true });
  assert.deepEqual(await discoverSkillDirectories(options), [local]);
  const registry = path.join(options.stateDirectory, 'installations');
  await writeFile(path.join(registry, 'broken.json'), '{}');
  const result = await syncInstalledSkills(options);
  assert.equal(result.ok, false);
  assert.match(result.error, /Invalid skill installation record/);
  assert.equal(await readFile(path.join(local, 'SKILL.md'), 'utf8'), oldEntry);
});
