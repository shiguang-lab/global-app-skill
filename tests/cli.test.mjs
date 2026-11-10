import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createServer } from 'node:http';
import { cp, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { gunzipSync, gzipSync } from 'node:zlib';
import { test } from 'node:test';
import { buildResources } from '../scripts/build-resources.mjs';
import { bundleUrl, FEED, identity, sha256, SCRIPTS, validateManifest, VERSION } from '../src/protocol.mjs';
import { readSnapshot, resolveContext } from '../src/resources.mjs';
import { installSkill, syncInstalledSkills } from '../src/skill.mjs';

const cli = fileURLToPath(new URL('../src/cli.mjs', import.meta.url));
const exec = promisify(execFile);

async function fixture(t) {
  const directory = await mkdtemp(path.join(tmpdir(), 'global-app-skill-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const source = path.join(directory, 'source');
  const output = path.join(directory, 'feed');
  await cp(fileURLToPath(new URL('../resources/overseas-app-research/', import.meta.url)), source, {
    recursive: true, filter: name => !name.includes('__pycache__'),
  });
  await writeFile(path.join(source, 'scripts/preflight.py'),
    'import sys, os, json\nprint(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "stages": os.environ["APP_RESEARCH_TOTAL_STAGES"]}))\nprint("fixture-progress", file=sys.stderr)\nsys.exit(4)\n');
  const counts = new Map();
  const server = createServer(async (req, res) => {
    counts.set(req.url, (counts.get(req.url) || 0) + 1);
    try { res.end(await readFile(path.join(output, path.basename(req.url)))); }
    catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const feed = `http://127.0.0.1:${server.address().port}/latest.json`;
  const manifest = await buildResources(source, output);
  return { directory, source, output, counts, manifest,
    options: { mode: 'research', feed, cacheDir: path.join(directory, 'cache') } };
}

test('fresh installation contains only a thin SKILL.md and is repeatable', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'global-app-skill-install-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const target = path.join(root, 'overseas-app-research');
  const result = await installSkill(target);
  assert.deepEqual(await readdir(target), ['SKILL.md']);
  assert.ok((await readFile(result.skillPath, 'utf8')).split('\n').length < 25);
  await Promise.all(Array.from({ length: 4 }, () => installSkill(target)));
  assert.deepEqual(await readdir(target), ['SKILL.md']);
  await symlink(target, path.join(root, 'linked'));
  await assert.rejects(installSkill(path.join(root, 'linked')), /symlink/);
});

test('CLI resolves workflow files and reuses a verified cached bundle', async t => {
  const f = await fixture(t);
  const { stdout, stderr } = await exec(process.execPath, [cli, 'context', 'resolve', '--skill-dir', path.join(f.directory, 'not-installed-skill'), '--mode', 'ued', '--feed', f.options.feed, '--cache-dir', f.options.cacheDir]);
  const first = JSON.parse(stdout);
  assert.equal(first.mode, 'ued');
  assert.equal(first.updated, true);
  assert.match(stderr, /snapshot ready/);
  assert.ok(first.mustRead.some(name => name.endsWith('/ued-workflow.md')));
  for (const filename of first.mustRead) assert.ok((await lstat(filename)).isFile());
  assert.equal((await resolveContext(f.options)).updated, false);
  assert.equal(f.counts.get('/latest.json'), 2);
  assert.equal(f.counts.get(`/${f.manifest.bundle}`), 1);
});

test('GitHub feed changes update resources independently and keep the old task snapshot', async t => {
  const f = await fixture(t);
  const first = await resolveContext(f.options);
  const guide = path.join(f.source, 'references/guide.md');
  await writeFile(guide, (await readFile(guide, 'utf8')) + '\nUpdated fixture workflow\n');
  const secondManifest = await buildResources(f.source, f.output);
  const second = await resolveContext(f.options);
  assert.notEqual(first.resourceRoot, second.resourceRoot);
  assert.equal(second.resourceHash, secondManifest.resourceHash);
  assert.match(await readFile(path.join(second.resourceRoot, 'references/guide.md'), 'utf8'), /Updated fixture/);
  assert.doesNotMatch(await readFile(path.join(first.resourceRoot, 'references/guide.md'), 'utf8'), /Updated fixture/);
  await readSnapshot(first.resourceRoot);
});

test('Release manifests pin archives to their own tag instead of the moving latest alias', async t => {
  const f = await fixture(t);
  const oldManifest = { ...f.manifest, releaseTag: 'resources-v0.1.4' };
  assert.equal(bundleUrl(oldManifest, FEED).href,
    `https://github.com/shiguang-lab/global-app-skill/releases/download/resources-v0.1.4/${oldManifest.bundle}`);
  assert.equal(bundleUrl({ ...oldManifest, releaseTag: 'v0.1.5' }, FEED).href,
    `https://github.com/shiguang-lab/global-app-skill/releases/download/v0.1.5/${oldManifest.bundle}`);
  assert.equal(bundleUrl(oldManifest, f.options.feed).origin, new URL(f.options.feed).origin);
  assert.throws(() => validateManifest({ ...f.manifest, releaseTag: '../main' }), /Invalid resource manifest/);
});

test('pinned execution preserves args, cwd, progress and device-gate exit code without network', async t => {
  const f = await fixture(t);
  const { resourceRoot } = await resolveContext(f.options);
  const count = f.counts.get('/latest.json');
  const workingDirectory = await realpath(f.directory);
  await assert.rejects(exec(process.execPath, [cli, 'run', 'preflight', '--skill-dir', path.join(f.directory, 'not-installed-skill'), '--mode', 'download', '--resource-root', resourceRoot, '--', '--report', 'path with spaces/environment.json'], { cwd: f.directory }), error => {
    assert.equal(error.code, 4);
    const result = JSON.parse(error.stdout);
    assert.deepEqual(result.args, ['--report', 'path with spaces/environment.json']);
    assert.equal(result.cwd, workingDirectory);
    assert.equal(result.stages, '4');
    assert.match(error.stderr, /fixture-progress/);
    return true;
  });
  assert.equal(f.counts.get('/latest.json'), count);
});

test('corrupt pinned scripts cannot execute; resolving repairs corruption', async t => {
  const f = await fixture(t);
  const first = await resolveContext(f.options);
  await writeFile(path.join(first.resourceRoot, 'scripts/preflight.py'), 'print("must not execute")');
  await assert.rejects(exec(process.execPath, [cli, 'run', 'preflight', '--skill-dir', path.join(f.directory, 'not-installed-skill'), '--resource-root', first.resourceRoot]), error => {
    assert.equal(error.code, 1);
    assert.equal(error.stdout, '');
    assert.match(error.stderr, /integrity/);
    return true;
  });
  const repaired = await resolveContext(f.options);
  assert.equal(repaired.updated, true);
  await readSnapshot(first.resourceRoot);
});

test('network and bundle failures never fall back to an old workflow or promote bad resources', async t => {
  const f = await fixture(t);
  const first = await resolveContext(f.options);
  await rm(path.join(f.output, 'latest.json'));
  await assert.rejects(resolveContext(f.options), /HTTP 404/);
  await readSnapshot(first.resourceRoot);
  await writeFile(path.join(f.source, 'references/guide.md'), 'another release');
  const next = await buildResources(f.source, f.output);
  await writeFile(path.join(f.output, next.bundle), 'broken download');
  await assert.rejects(resolveContext(f.options), /integrity/);
  await assert.rejects(lstat(path.join(f.options.cacheDir, 'releases', next.resourceHash)), { code: 'ENOENT' });
  await readSnapshot(first.resourceRoot);
});

test('rejects unsafe manifests, incompatible CLI requirements and symlinked cache scripts', async t => {
  const f = await fixture(t);
  const traversal = structuredClone(f.manifest);
  traversal.files[0].path = 'scripts/../../escape.py';
  traversal.resourceHash = identity(traversal.files);
  traversal.bundle = `${traversal.resourceHash}.json.gz`;
  assert.throws(() => validateManifest(traversal), /file entry/);
  assert.throws(() => validateManifest({ ...f.manifest, minCliVersion: '100.0.0' }), /require CLI/);
  const first = await resolveContext(f.options);
  const script = path.join(first.resourceRoot, 'scripts/preflight.py');
  const original = path.join(f.source, 'scripts/preflight.py');
  await rm(script);
  await symlink(original, script);
  await assert.rejects(readSnapshot(first.resourceRoot), /integrity/);
});

test('parallel first-time resolutions return the same verified snapshot', async t => {
  const f = await fixture(t);
  for (let round = 0; round < 5; round++) {
    const options = { ...f.options, cacheDir: path.join(f.directory, `parallel-cache-${round}`) };
    const results = await Promise.all(Array.from({ length: 4 }, () => resolveContext(options)));
    assert.equal(new Set(results.map(result => result.resourceRoot)).size, 1);
    await readSnapshot(results[0].resourceRoot);
  }
});

test('all existing script CLIs can be invoked through verified resources', async t => {
  const f = await fixture(t);
  await cp(fileURLToPath(new URL('../resources/overseas-app-research/scripts/preflight.py', import.meta.url)), path.join(f.source, 'scripts/preflight.py'));
  await buildResources(f.source, f.output);
  const { resourceRoot } = await resolveContext(f.options);
  for (const script of SCRIPTS) {
    const { stdout } = await exec(process.execPath, [cli, 'run', script, '--skill-dir', path.join(f.directory, 'not-installed-skill'), '--resource-root', resourceRoot, '--', '--help']);
    assert.match(stdout, /usage:/);
  }
});

test('release checks accept equivalent gzip encodings and reject changed source or corrupt archives', async t => {
  const f = await fixture(t);
  const bundlePath = path.join(f.output, f.manifest.bundle);
  const alternate = gzipSync(gunzipSync(await readFile(bundlePath)), { level: 1 });
  assert.notEqual(sha256(alternate), f.manifest.sha256);
  await writeFile(bundlePath, alternate);
  const published = { ...f.manifest, sha256: sha256(alternate), size: alternate.length };
  await writeFile(path.join(f.output, 'latest.json'), JSON.stringify(published));
  assert.equal((await buildResources(f.source, f.output, { check: true })).sha256, published.sha256);
  const guide = path.join(f.source, 'references/guide.md');
  const original = await readFile(guide);
  await writeFile(guide, 'changed source');
  await assert.rejects(buildResources(f.source, f.output, { check: true }), /differ from source/);
  await writeFile(guide, original);
  await writeFile(bundlePath, 'corrupt archive');
  await assert.rejects(buildResources(f.source, f.output, { check: true }), /differ from source/);
});

test('context resolve updates an old custom skill entry even when resources fail', async t => {
  const f = await fixture(t);
  const target = path.join(f.directory, "owner's skill $(false)");
  const { skillPath } = await installSkill(target);
  const oldEntry = '---\nname: overseas-app-research\n---\nnpx -y --prefer-online global-app-skill@latest context resolve --mode MODE\n';
  await writeFile(skillPath, oldEntry);
  const args = [cli, 'context', 'resolve', '--mode', 'research', '--skill-dir', target, '--feed', f.options.feed, '--cache-dir', f.options.cacheDir];
  const { stdout, stderr } = await exec(process.execPath, args);
  const result = JSON.parse(stdout);
  assert.equal(result.skillUpdate.ok, true);
  assert.equal(result.skillUpdate.installations[0].status, 'updated');
  assert.match(stderr, /Updated local entry/);
  const updated = await readFile(skillPath, 'utf8');
  assert.ok(updated.includes(`global-app-skill-version: ${VERSION}`));
  assert.ok(updated.includes("--skill-dir '" + target.replaceAll("'", "'\\''") + "'"));
  assert.deepEqual(await readdir(target), ['SKILL.md']);
  assert.equal(JSON.parse((await exec(process.execPath, args)).stdout).skillUpdate.installations[0].status, 'unchanged');
  const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
  const command = updated.split('\n').find(line => line.startsWith('npx ') && line.includes('context resolve'))
    .replace('npx -y --prefer-online global-app-skill@latest', `${quote(process.execPath)} ${quote(cli)}`)
    .replace('--mode MODE', '--mode research') + ` --feed ${quote(f.options.feed)} --cache-dir ${quote(f.options.cacheDir)}`;
  assert.equal(JSON.parse((await exec('/bin/sh', ['-c', command])).stdout).skillUpdate.installations[0].status, 'unchanged');
  await writeFile(skillPath, oldEntry);
  await rm(path.join(f.output, 'latest.json'));
  await assert.rejects(exec(process.execPath, args), error => {
    assert.equal(JSON.parse(error.stderr.trim().split('\n').at(-1)).skillUpdate.installations[0].status, 'updated');
    return true;
  });
  assert.equal(await readFile(skillPath, 'utf8'), updated);
});

test('entry synchronization preserves unowned, symlinked and newer entries without creating skills', async t => {
  const f = await fixture(t);
  const missing = path.join(f.directory, 'missing');
  assert.equal((await syncInstalledSkills({ directory: missing })).installations[0].reason, 'not-installed');
  await assert.rejects(lstat(missing), { code: 'ENOENT' });
  const standard = path.join(f.directory, '.agents/skills/overseas-app-research');
  const other = path.join(f.directory, '.codex/skills/overseas-app-research');
  await installSkill(standard);
  await writeFile(path.join(standard, 'SKILL.md'), 'global-app-skill@latest context resolve\n');
  await mkdir(other, { recursive: true });
  await writeFile(path.join(other, 'SKILL.md'), 'User-maintained skill');
  const discovered = await syncInstalledSkills({ directories: [standard, other] });
  assert.equal(discovered.installations[0].status, 'updated');
  assert.equal(await readFile(path.join(other, 'SKILL.md'), 'utf8'), 'User-maintained skill');
  const content = await readFile(path.join(standard, 'SKILL.md'), 'utf8');
  await writeFile(path.join(standard, 'SKILL.md'), content.replace(`global-app-skill-version: ${VERSION}`, 'global-app-skill-version: 999.0.0'));
  assert.equal((await syncInstalledSkills({ directory: standard })).installations[0].reason, 'newer-installed');
  const linked = path.join(f.directory, 'linked-skill');
  await symlink(standard, linked);
  assert.equal((await syncInstalledSkills({ directory: linked })).installations[0].reason, 'symlink');
});

test('reports entry update failures independently and preserves pinned script stdout and exit code', async t => {
  const f = await fixture(t);
  const target = path.join(f.directory, 'broken-entry');
  await mkdir(path.join(target, 'SKILL.md'), { recursive: true });
  const context = JSON.parse((await exec(process.execPath, [cli, 'context', 'resolve', '--mode', 'download', '--skill-dir', target,
    '--feed', f.options.feed, '--cache-dir', f.options.cacheDir])).stdout);
  assert.equal(context.ok, true);
  assert.equal(context.skillUpdate.ok, false);
  assert.equal(context.skillUpdate.installations[0].status, 'failed');
  const installed = path.join(f.directory, 'installed');
  await installSkill(installed);
  await writeFile(path.join(installed, 'SKILL.md'), 'global-app-skill@latest context resolve\n');
  await assert.rejects(exec(process.execPath, [cli, 'run', 'preflight', '--mode', 'download', '--skill-dir', installed,
    '--resource-root', context.resourceRoot, '--', '--report', 'example.json']), error => {
    assert.equal(error.code, 4);
    assert.equal(JSON.parse(error.stdout).stages, '4');
    assert.match(error.stderr, /Updated local entry/);
    assert.match(error.stderr, /fixture-progress/);
    return true;
  });
  assert.ok((await readFile(path.join(installed, 'SKILL.md'), 'utf8')).includes(`global-app-skill-version: ${VERSION}`));
});
