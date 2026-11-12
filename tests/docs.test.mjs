import assert from 'node:assert/strict';
import { access, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
const references = path.join(root, 'resources/global-app-analysis/references');
const skill = await readFile(path.join(root, 'skills/global-app-analysis/SKILL.md'), 'utf8');
const rules = await readFile(path.join(references, 'rules.md'), 'utf8');
const completion = await readFile(path.join(references, 'completion.md'), 'utf8');

function slug(heading) {
  return heading.trim().toLowerCase()
    .replace(/[`*_~]/g, '')
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .trim()
    .replace(/\s+/g, '-');
}

async function markdownFiles(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name === '__pycache__' || entry.name.startsWith('.')) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await markdownFiles(absolute));
    else if (entry.name.endsWith('.md')) files.push(absolute);
  }
  return files;
}

test('local Markdown links resolve and anchors exist', async () => {
  const files = [
    path.join(root, 'README.md'),
    ...await markdownFiles(path.join(root, 'skills')),
    ...await markdownFiles(path.join(root, 'resources/global-app-analysis')),
  ];
  for (const file of files) {
    const text = await readFile(file, 'utf8');
    for (const match of text.matchAll(/\[[^\]]*\]\(([^)\s]+)\)/g)) {
      const target = match[1];
      if (/^(?:https?:|mailto:)/.test(target)) continue;
      const [name, anchor] = target.split('#', 2);
      const destination = name ? path.resolve(path.dirname(file), name) : file;
      if (!destination.endsWith('.md')) continue;
      const content = await readFile(destination, 'utf8').catch(() => {
        throw new Error(`${path.relative(root, file)} links to missing file ${target}`);
      });
      if (anchor) {
        const headings = [...content.matchAll(/^#{1,6}\s+(.*)$/gm)].map(match => slug(match[1]));
        assert.ok(headings.includes(anchor.toLowerCase()),
          `${path.relative(root, file)} links to missing anchor ${target}`);
      }
    }
  }
});

test('entry gates and the detailed checklist agree on the process', () => {
  for (const token of ['mustRead', 'preflight', 'verify', 'completion.md', '审查', '10.4', '重新读取']) {
    assert.ok(skill.includes(token), `SKILL.md is missing gate: ${token}`);
    assert.ok(rules.includes(token), `rules.md is missing gate: ${token}`);
  }
});

test('every file named in the entry gate table exists in the resource snapshot', async () => {
  const table = skill.split('## 强制门槛')[1].split('## 不可协商')[0];
  for (const match of table.matchAll(/`([a-z-]+\.md)(?:#[^`]*)?`/g)) {
    const filename = path.join(references, match[1]);
    await access(filename).catch(() => {
      throw new Error(`SKILL.md gate table names a missing file: ${match[1]}`);
    });
  }
});

test('completion requires reading the current file, not a delivery receipt', () => {
  assert.match(completion, /10\.4/);
  assert.match(completion, /不是完成信号/);
  assert.match(completion, /重新读取/);
  assert.match(skill, /不是完成信号/);
  assert.match(skill, /重新读取/);
});

test('the skill no longer depends on review/delivery checker artifacts', async () => {
  const files = [
    skill,
    ...await markdownFiles(path.join(root, 'resources/global-app-analysis')),
  ];
  for (const file of files) {
    const text = typeof file === 'string' ? file : await readFile(file, 'utf8');
    for (const token of ['check_delivery', 'delivery-record', 'review-record', 'task-checks', '--partial']) {
      assert.ok(!text.includes(token), `${path.relative(root, file)} still mentions ${token}`);
    }
  }
});
