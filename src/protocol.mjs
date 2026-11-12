import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

export const VERSION = JSON.parse(readFileSync(new URL('../package.json', import.meta.url))).version;
export const SKILL_NAME = 'global-app-analysis';
export const RELEASE_BASE = 'https://github.com/shiguang-lab/global-app-skill/releases';
export const FEED = `${RELEASE_BASE}/latest/download/latest.json`;
export const RELEASE_TAG = /^(?:v|resources-v)(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/;
export const MAX_BYTES = 16 * 1024 * 1024;
export const RULES_PATH = 'references/rules.md';
export const MODES = {
  download: 'references/download-workflow.md',
  research: 'references/research-workflow.md',
  ued: 'references/ued-workflow.md',
};
export const SCRIPTS = ['preflight', 'download', 'export_device', 'verify', 'attempts', 'inspect_package', 'long_screenshot'];
export const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
export const identity = (files) => sha256(JSON.stringify(files));

export function validateMode(mode) {
  if (!Object.hasOwn(MODES, mode)) throw new Error('--mode must be download, research or ued');
  return mode;
}

export function validateManifest(manifest, { requireRules = true } = {}) {
  const hash = /^[a-f0-9]{64}$/;
  if (manifest?.schemaVersion !== 1 || !RELEASE_TAG.test(manifest.releaseTag) || !hash.test(manifest.resourceHash) ||
      !/^\d+\.\d+\.\d+$/.test(manifest.minCliVersion) ||
      !Array.isArray(manifest.files) || !manifest.files.length || manifest.files.length > 1024 ||
      manifest.bundle !== `${manifest.resourceHash}.json.gz` || !hash.test(manifest.sha256) ||
      !Number.isSafeInteger(manifest.size) || manifest.size <= 0 || manifest.size > MAX_BYTES) {
    throw new Error('Invalid resource manifest');
  }
  const seen = new Set();
  let total = 0;
  for (const file of manifest.files) {
    if (typeof file.path !== 'string' || !/^(references|scripts|examples)\//.test(file.path) ||
        file.path.split('/').some(part => !/^[a-zA-Z0-9_.-]+$/.test(part) || part === '.' || part === '..') ||
        seen.has(file.path) || !hash.test(file.sha256) ||
        !Number.isSafeInteger(file.size) || file.size < 0 || (total += file.size) > MAX_BYTES) {
      throw new Error('Invalid resource file entry');
    }
    seen.add(file.path);
  }
  if (identity(manifest.files) !== manifest.resourceHash) throw new Error('Resource manifest hash mismatch');
  const required = ['references/guide.md', 'references/cli.md', 'references/orchestration.md',
    ...Object.values(MODES), ...SCRIPTS.map(name => `scripts/${name}.py`), 'scripts/apk_utils.py', 'scripts/progress.py'];
  if (requireRules) required.unshift(RULES_PATH, 'references/delivery-record.md', 'scripts/check_delivery.py');
  const missing = required.filter(name => !seen.has(name));
  if (missing.length) throw new Error(`Resource manifest is missing workflow files: ${missing.join(', ')}`);
  const installed = VERSION.split('.').map(Number);
  const minimum = manifest.minCliVersion.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if (installed[i] > minimum[i]) break;
    if (installed[i] < minimum[i]) throw new Error(`Resources require CLI >=${manifest.minCliVersion}; rerun with global-app-skill@latest`);
  }
  return manifest;
}

export function bundleUrl(manifest, feed) {
  const url = new URL(feed);
  if (url.origin === 'https://github.com' && url.pathname.startsWith('/shiguang-lab/global-app-skill/releases/')) {
    // Pin the bundle to the manifest's release, even if "latest" advances
    // between fetching the manifest and fetching its archive.
    return new URL(`${RELEASE_BASE}/download/${manifest.releaseTag}/${manifest.bundle}`);
  }
  return new URL(manifest.bundle, url);
}
