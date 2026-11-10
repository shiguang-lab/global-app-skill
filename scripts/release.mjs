import { execFile } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify, parseArgs } from 'node:util';
import { buildResources } from './build-resources.mjs';
import { RELEASE_TAG, sha256, validateManifest, VERSION } from '../src/protocol.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const exec = promisify(execFile);

export function releasePlan(tag, version = VERSION) {
  if (!RELEASE_TAG.test(tag)) throw new Error('Release tag must be vX.Y.Z or resources-vX.Y.Z');
  const publishNpm = tag.startsWith('v');
  if (publishNpm && tag !== `v${version}`) throw new Error('CLI tag must match package.json version');
  return { tag, version, publishNpm };
}

export async function verifyRelease(directory, compareDirectory) {
  const manifest = validateManifest(JSON.parse(await readFile(path.join(directory, 'latest.json'), 'utf8')));
  const names = ['latest.json', manifest.bundle, 'global-app-skill.tgz'];
  const checksums = await readFile(path.join(directory, 'SHA256SUMS'), 'utf8');
  const expected = [];
  for (const name of names) expected.push(`${sha256(await readFile(path.join(directory, name)))}  ${name}`);
  if (checksums !== expected.join('\n') + '\n') throw new Error('Release asset checksum mismatch');
  if (compareDirectory && checksums !== await readFile(path.join(compareDirectory, 'SHA256SUMS'), 'utf8')) {
    throw new Error('Existing GitHub Release differs from this tag build');
  }
  return manifest;
}

export async function prepareRelease(tag, directory = path.join(root, 'dist/release')) {
  const plan = releasePlan(tag);
  await rm(directory, { recursive: true, force: true });
  await mkdir(directory, { recursive: true });
  const manifest = await buildResources(path.join(root, 'resources/overseas-app-research'), directory, { releaseTag: tag });
  const temporary = await mkdtemp(path.join(tmpdir(), 'global-app-skill-pack-'));
  try {
    const packed = JSON.parse((await exec('npm', ['pack', '--json', '--pack-destination', temporary], { cwd: root })).stdout)[0];
    if (packed.version !== plan.version) throw new Error('Packed CLI does not match release version');
    await copyFile(path.join(temporary, packed.filename), path.join(directory, 'global-app-skill.tgz'));
  } finally { await rm(temporary, { recursive: true, force: true }); }
  const checksums = [];
  for (const name of ['latest.json', manifest.bundle, 'global-app-skill.tgz']) {
    checksums.push(`${sha256(await readFile(path.join(directory, name)))}  ${name}`);
  }
  await writeFile(path.join(directory, 'SHA256SUMS'), checksums.join('\n') + '\n');
  await buildResources(path.join(root, 'resources/overseas-app-research'), directory, { check: true, releaseTag: tag });
  await verifyRelease(directory);
  return { ...plan, directory, resourceHash: manifest.resourceHash };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { values } = parseArgs({ options: { tag: { type: 'string' }, verify: { type: 'string' }, compare: { type: 'string' } } });
  if (values.verify) console.log(JSON.stringify(await verifyRelease(values.verify, values.compare)));
  else console.log(JSON.stringify(await prepareRelease(values.tag || process.env.RELEASE_TAG || `v${VERSION}`)));
}
