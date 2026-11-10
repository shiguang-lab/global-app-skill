import { lstat, mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { gunzipSync } from 'node:zlib';
import { bundleUrl, FEED, MAX_BYTES, MODES, sha256, validateManifest, validateMode } from './protocol.mjs';

async function download(url, limit) {
  const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new Error(`Cannot download ${url}: HTTP ${response.status}`);
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > limit) {
      throw new Error('Resource download exceeds limit');
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

export async function readSnapshot(resourceRoot) {
  resourceRoot = path.resolve(resourceRoot);
  if (!(await lstat(resourceRoot)).isDirectory()) throw new Error('Resource root must be a real directory');
  const manifestPath = path.join(resourceRoot, 'manifest.json');
  if (!(await lstat(manifestPath)).isFile()) throw new Error('Resource manifest must be a regular file');
  const manifest = validateManifest(JSON.parse(await readFile(manifestPath, 'utf8')));
  if (path.basename(resourceRoot) !== manifest.resourceHash) throw new Error('Resource root does not match its snapshot hash');
  for (const file of manifest.files) {
    let directory = resourceRoot;
    for (const segment of file.path.split('/').slice(0, -1)) {
      directory = path.join(directory, segment);
      if (!(await lstat(directory)).isDirectory()) throw new Error(`Invalid resource directory: ${directory}`);
    }
    const filename = path.join(resourceRoot, file.path);
    const stat = await lstat(filename);
    if (!stat.isFile() || stat.size !== file.size || sha256(await readFile(filename)) !== file.sha256) {
      throw new Error(`Resource integrity check failed: ${file.path}`);
    }
  }
  return manifest;
}

async function validSnapshot(root, resourceHash) {
  try { return (await readSnapshot(root)).resourceHash === resourceHash; }
  catch { return false; }
}

export async function resolveContext({ mode, feed = FEED, cacheDir, progress = () => {} } = {}) {
  validateMode(mode);
  const url = new URL(feed);
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) || url.username || url.password) {
    throw new Error('--feed must be HTTPS (HTTP is allowed only for loopback testing)');
  }
  progress('Checking GitHub resource manifest');
  const manifest = validateManifest(JSON.parse((await download(url, 1024 * 1024)).toString('utf8')));
  const root = path.resolve(cacheDir || process.env.GLOBAL_APP_SKILL_CACHE || path.join(homedir(), '.cache/global-app-skill'));
  const releases = path.join(root, 'releases');
  const resourceRoot = path.join(releases, manifest.resourceHash);
  let updated = false;
  if (!(await validSnapshot(resourceRoot, manifest.resourceHash))) {
    progress(`Downloading and verifying ${manifest.files.length} resource files`);
    const bytes = await download(bundleUrl(manifest, url), MAX_BYTES);
    if (bytes.length !== manifest.size || sha256(bytes) !== manifest.sha256) throw new Error('Resource bundle integrity check failed');
    const bundle = JSON.parse(gunzipSync(bytes, { maxOutputLength: MAX_BYTES * 2 }).toString('utf8'));
    if (!Array.isArray(bundle.files) || bundle.files.length !== manifest.files.length) throw new Error('Invalid resource bundle');
    // Check the complete payload before writing anything into the snapshot.
    const files = bundle.files.map((file, index) => {
      const expected = manifest.files[index];
      if (file.path !== expected.path || typeof file.content !== 'string') throw new Error('Resource bundle file mismatch');
      const content = Buffer.from(file.content, 'base64');
      if (content.length !== expected.size || sha256(content) !== expected.sha256) throw new Error(`Resource bundle integrity check failed: ${file.path}`);
      return { path: expected.path, content };
    });
    await mkdir(releases, { recursive: true });
    const staging = await mkdtemp(path.join(releases, '.prepare-'));
    try {
      for (const file of files) {
        const target = path.join(staging, file.path);
        await mkdir(path.dirname(target), { recursive: true });
        await writeFile(target, file.content, { flag: 'wx' });
      }
      await writeFile(path.join(staging, 'manifest.json'), JSON.stringify(manifest));
      const lock = path.join(releases, `.${manifest.resourceHash}.lock`);
      const deadline = Date.now() + 5000;
      for (;;) {
        try { await mkdir(lock); break; }
        catch (error) {
          if (error.code !== 'EEXIST') throw error;
          if (Date.now() >= deadline) throw new Error(`Snapshot publication is locked: ${lock}; retry after the other updater finishes. Remove a stale lock only when no updater is running.`);
          await delay(50);
        }
      }
      try {
        // Recheck under the lock so a concurrent resolver's completed snapshot
        // cannot be deleted after an earlier ENOENT integrity check.
        if (!(await validSnapshot(resourceRoot, manifest.resourceHash))) {
          await rm(resourceRoot, { recursive: true, force: true });
          await rename(staging, resourceRoot);
        }
      } finally {
        await rm(lock, { recursive: true, force: true });
      }
      updated = true;
    } finally { await rm(staging, { recursive: true, force: true }); }
  }
  await readSnapshot(resourceRoot);
  progress(updated ? 'Resource snapshot ready' : 'Verified cached snapshot is current');
  const mustRead = ['references/cli.md', 'references/guide.md', 'references/orchestration.md', MODES[mode]]
    .map(name => path.join(resourceRoot, name));
  return { ok: true, source: url.origin === 'https://github.com' ? 'github' : 'custom', feed: url.href,
    mode, releaseTag: manifest.releaseTag, resourceHash: manifest.resourceHash, resourceRoot,
    referencePath: path.join(resourceRoot, 'references/guide.md'), mustRead, updated };
}
