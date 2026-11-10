import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createServer } from 'node:http';
import { cp, lstat, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { test } from 'node:test';
import { buildResources } from '../scripts/build-resources.mjs';
import { identity, SCRIPTS, validateManifest } from '../src/protocol.mjs';
import { readSnapshot, resolveContext } from '../src/resources.mjs';
import { installSkill } from '../src/skill.mjs';

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
  await installSkill(target);
  assert.deepEqual(await readdir(target), ['SKILL.md']);
  await symlink(target, path.join(root, 'linked'));
  await assert.rejects(installSkill(path.join(root, 'linked')), /symlink/);
});

test('CLI resolves workflow files and reuses a verified cached bundle', async t => {
  const f = await fixture(t);
  const { stdout, stderr } = await exec(process.execPath, [cli, 'context', 'resolve', '--mode', 'ued', '--feed', f.options.feed, '--cache-dir', f.options.cacheDir]);
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

test('pinned execution preserves args, cwd, progress and device-gate exit code without network', async t => {
  const f = await fixture(t);
  const { resourceRoot } = await resolveContext(f.options);
  const count = f.counts.get('/latest.json');
  const workingDirectory = await realpath(f.directory);
  await assert.rejects(exec(process.execPath, [cli, 'run', 'preflight', '--mode', 'download', '--resource-root', resourceRoot, '--', '--report', 'path with spaces/environment.json'], { cwd: f.directory }), error => {
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
  await assert.rejects(exec(process.execPath, [cli, 'run', 'preflight', '--resource-root', first.resourceRoot]), error => {
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
  const results = await Promise.all(Array.from({ length: 4 }, () => resolveContext(f.options)));
  assert.equal(new Set(results.map(result => result.resourceRoot)).size, 1);
  await readSnapshot(results[0].resourceRoot);
});

test('all existing script CLIs can be invoked through verified resources', async t => {
  const f = await fixture(t);
  await cp(fileURLToPath(new URL('../resources/overseas-app-research/scripts/preflight.py', import.meta.url)), path.join(f.source, 'scripts/preflight.py'));
  await buildResources(f.source, f.output);
  const { resourceRoot } = await resolveContext(f.options);
  for (const script of SCRIPTS) {
    const { stdout } = await exec(process.execPath, [cli, 'run', script, '--resource-root', resourceRoot, '--', '--help']);
    assert.match(stdout, /usage:/);
  }
});
