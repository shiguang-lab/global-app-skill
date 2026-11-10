import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { prepareRelease, releasePlan, verifyRelease } from '../scripts/release.mjs';
import { VERSION } from '../src/protocol.mjs';

test('release tags determine npm publication and must match the CLI version', () => {
  assert.equal(releasePlan(`v${VERSION}`).publishNpm, true);
  assert.equal(releasePlan('resources-v9.8.7').publishNpm, false);
  assert.throws(() => releasePlan('v9.8.7'), /match package/);
  for (const tag of ['main', 'v01.2.3', 'v1.2.3-beta', 'resources-v../main', 'v1.2']) {
    assert.throws(() => releasePlan(tag), /Release tag/);
  }
});

test('builds the complete tag release and detects changed or tampered assets', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'global-app-skill-release-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const directory = path.join(root, 'release');
  const prepared = await prepareRelease(`v${VERSION}`, directory);
  const manifest = await verifyRelease(directory);
  assert.equal(manifest.releaseTag, `v${VERSION}`);
  assert.equal(prepared.resourceHash, manifest.resourceHash);
  assert.deepEqual((await readdir(directory)).sort(), [manifest.bundle, 'SHA256SUMS', 'global-app-skill.tgz', 'latest.json'].sort());
  const remote = path.join(root, 'remote');
  await cp(directory, remote, { recursive: true });
  await verifyRelease(remote, directory);
  await writeFile(path.join(remote, 'global-app-skill.tgz'), 'changed archive');
  await assert.rejects(verifyRelease(remote, directory), /checksum mismatch/);
  const original = await readFile(path.join(directory, 'SHA256SUMS'), 'utf8');
  await writeFile(path.join(directory, 'SHA256SUMS'), original.replace(/^[a-f0-9]/, char => char === 'a' ? 'b' : 'a'));
  await assert.rejects(verifyRelease(directory), /checksum mismatch/);
});
