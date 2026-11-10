import { lstat, mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gunzipSync, gzipSync } from 'node:zlib';
import { identity, sha256, SKILL_NAME, validateManifest, VERSION } from '../src/protocol.mjs';

export async function buildResources(source, output, { check = false, releaseTag = `v${VERSION}` } = {}) {
  const entries = [];
  async function walk(directory) {
    for (const name of (await readdir(directory)).sort()) {
      if (name === '__pycache__' || name.endsWith('.pyc') || name.startsWith('test_')) continue;
      const absolute = path.join(directory, name);
      const stat = await lstat(absolute);
      if (stat.isSymbolicLink()) throw new Error(`Resource symlink is not allowed: ${absolute}`);
      if (stat.isDirectory()) await walk(absolute);
      else if (stat.isFile()) entries.push({ path: path.relative(source, absolute).split(path.sep).join('/'), bytes: await readFile(absolute) });
    }
  }
  for (const name of ['references', 'scripts', 'examples']) await walk(path.join(source, name));
  entries.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  const files = entries.map(file => ({ path: file.path, sha256: sha256(file.bytes), size: file.bytes.length }));
  const resourceHash = identity(files);
  const payload = Buffer.from(JSON.stringify({ files: entries.map(file => ({ path: file.path, content: file.bytes.toString('base64') })) }));
  const bundle = gzipSync(payload, { level: 9 });
  const manifest = validateManifest({ schemaVersion: 1, releaseTag, minCliVersion: '0.1.3', resourceHash,
    bundle: `${resourceHash}.json.gz`, sha256: sha256(bundle), size: bundle.length, files });
  const manifestText = JSON.stringify(manifest, null, 2) + '\n';
  if (check) {
    const published = validateManifest(JSON.parse(await readFile(path.join(output, 'latest.json'), 'utf8')));
    const bytes = await readFile(path.join(output, published.bundle));
    // zlib versions may encode identical source bytes differently. Verify the
    // published archive itself, then compare its full decoded payload to source.
    if (published.resourceHash !== resourceHash || published.releaseTag !== releaseTag || published.minCliVersion !== manifest.minCliVersion ||
        bytes.length !== published.size || sha256(bytes) !== published.sha256 ||
        !gunzipSync(bytes).equals(payload)) {
      throw new Error('Published resources differ from source; run npm run resources:build');
    }
    return published;
  } else {
    await mkdir(output, { recursive: true });
    await writeFile(path.join(output, manifest.bundle), bundle);
    await writeFile(path.join(output, 'latest.json'), manifestText);
  }
  return manifest;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const manifest = await buildResources(path.join(root, 'resources', SKILL_NAME), path.join(root, 'dist/resources'), { check: process.argv.includes('--check') });
  console.log(JSON.stringify({ resourceHash: manifest.resourceHash, files: manifest.files.length, bytes: manifest.size }));
}
