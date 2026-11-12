const { readFileSync, readdirSync } = require('node:fs');
const { basename, join, resolve } = require('node:path');

const defaultWorkspace = resolve(__dirname, '../../dist/evals/cashola-cashify/workspace');
const inputDirectories = new Set([
  'Cashola-Cashify/google-play',
  'Cashola-Cashify/analysis/web',
  'Cashola-Cashify/analysis/business-targeted',
  'Cashola-Cashify/analysis/business-entry-review',
  'Cashola-Cashify/analysis/public-config',
]);

function artifacts(workspace, directory = '') {
  return readdirSync(join(workspace, directory), { withFileTypes: true }).flatMap(entry => {
    const path = [directory, entry.name].filter(Boolean).join('/');
    if (entry.isDirectory() && !entry.name.startsWith('.') && entry.name !== 'node_modules' && !inputDirectories.has(path)) {
      return artifacts(workspace, path);
    }
    return entry.isFile() ? [path] : [];
  });
}

function completedItems(response) {
  const raw = typeof response?.raw === 'string' ? JSON.parse(response.raw) : response?.raw;
  const events = raw?.events ?? raw?.notifications ?? raw?.rawEvents ?? response?.metadata?.codexAppServer?.events;
  if (Array.isArray(events)) {
    const completed = events.filter(event => event.method === 'item/completed').map(event => event.params.item);
    if (completed.length) return completed;
  }
  return raw?.items ?? response?.metadata?.codexAppServer?.items ?? [];
}

function reviewRounds(items) {
  const rounds = [];
  const assigned = new Map();
  for (const [index, item] of items.entries()) {
    if (item.type !== 'collabAgentToolCall' || item.status !== 'completed') continue;
    if (item.tool === 'spawnAgent' && /审查|审阅|复核|复审|重审|review|audit/i.test(item.prompt ?? '')) {
      const latest = rounds.at(-1);
      const newRound = !latest || (latest.finishedAt !== undefined &&
        /复审|重审|第二轮|第三轮|re-review|re-audit|round\s*[2-9]|second\s+review/i.test(item.prompt));
      if (newRound) rounds.push({ startedAt: index, pending: new Set() });
      const round = rounds.at(-1);
      for (const id of item.receiverThreadIds ?? []) {
        round.pending.add(id);
        assigned.set(id, round);
        delete round.finishedAt;
      }
    }
    for (const [id, state] of Object.entries(item.agentsStates ?? {})) {
      if (state.status !== 'completed') continue;
      const round = assigned.get(id);
      if (!round?.pending.delete(id)) continue;
      if (round.pending.size === 0) round.finishedAt = index;
    }
  }
  return rounds.filter(round => round.finishedAt !== undefined);
}

function flowWrites(items) {
  return items.flatMap((item, index) => {
    if (item.type === 'fileChange' && item.status === 'completed' &&
        item.changes?.some(change => /\.(?:mmd|mermaid)$/i.test(change.path))) return [index];
    if (item.type !== 'commandExecution' || item.exitCode !== 0) return [];
    const command = item.command ?? '';
    const directWrite = /(?:>\s*|\btee\s+)[^\s;&]+\.(?:mmd|mermaid)\b|\bwriteFile(?:Sync)?\([^,\n]+\.(?:mmd|mermaid)\b|\bPath\([^\n]+\.(?:mmd|mermaid)\b[^\n]*?\)\.write_(?:text|bytes)\(/i;
    if (directWrite.test(command)) return [index];
    const pathBindings = command.matchAll(/\b([a-z_]\w*)\s*=\s*(?:pathlib\.)?Path\([^\n]+?\.(?:mmd|mermaid)\b[^\n]*?\)/gi);
    return [...pathBindings].some(([, name]) => new RegExp(`\\b${name}\\.write_(?:text|bytes)\\(`).test(command)) ? [index] : [];
  });
}

function grade(status, message) {
  return { pass: status === 'PASS', score: status === 'PASS' ? 1 : 0, reason: `[${status}] ${message}` };
}

function inspect(output, context) {
  const workspace = context.providerResponse?.metadata?.codexAppServer?.cwd ?? defaultWorkspace;
  const items = completedItems(context.providerResponse);
  const files = artifacts(workspace);
  const reportFiles = files.filter(path => /\.(html|md)$/i.test(path) && !basename(path).startsWith('.') &&
    !/review|复核|审查|evidence|\bweb\b|\.report-template/i.test(path));
  const delivered = reportFiles.some(path => output.includes(basename(path))) ||
    /已(?:正式)?交付|报告(?:已生成|已完成|已放到|见下)|产物已(?:生成|放到)|\[查看(?:复测)?报告\]/.test(output);
  const partial = /(?:阶段性|部分|初步)(?:交付|报告|结论|结果)|本次交付为阶段性/.test(output);
  return { workspace, items, files, delivered, partial, rounds: reviewRounds(items), writes: flowWrites(items) };
}

function firstReview(output, context) {
  const { delivered, partial, items, rounds } = inspect(output, context);
  if (!delivered || partial) return grade('NOT_EXERCISED', 'No formal report delivery was observed.');
  if (!items.length) return grade('INCONCLUSIVE', 'The App Server trace does not contain completed items.');
  if (rounds.length < 2) return grade('FAIL', `Report delivered with ${rounds.length} independently completed review round(s) observable.`);
  return grade('PASS', `${rounds.length} independently completed review rounds were observed before delivery.`);
}

function afterCorrection(output, context) {
  const { delivered, items, rounds, writes } = inspect(output, context);
  if (!delivered) return grade('NOT_EXERCISED', 'No delivered report was observed.');
  if (!items.length) return grade('INCONCLUSIVE', 'The App Server trace does not contain completed items.');
  const lastCorrection = writes.filter(index => rounds.some(round => round.finishedAt < index)).at(-1);
  if (lastCorrection === undefined) return grade('NOT_EXERCISED', 'No successful flow source edit was observed after a completed review.');
  if (!rounds.some(round => round.startedAt > lastCorrection)) {
    return grade('FAIL', 'The report was delivered after a post-review flow source edit, with no completed new review started after that edit.');
  }
  return grade('PASS', 'A new independent review started and completed after the last flow source edit.');
}

function loginBlocker(output, context) {
  const { delivered, files, items, workspace } = inspect(output, context);
  if (!delivered) return grade('NOT_EXERCISED', 'No delivered report was observed.');
  const review = files.filter(path => /(?:review|research-state|blocker|复核|审查|阻塞).*\.(md|json)$/i.test(basename(path)))
    .map(path => readFileSync(join(workspace, path), 'utf8')).join('\n');
  const loginBoundary = /(?:原包|原生|模拟器|App\s*内)[^\n。]{0,45}(?:停在|仅到|只到|实测到|走查到)[^\n。]{0,28}(?:登录|手机号)|未(?:能)?进入登录后(?:的)?(?:原生|App)|登录后[^\n。]{0,45}(?:未实测|未完成走查|未走查|未覆盖)/i;
  if (!loginBoundary.test(review + '\n' + output)) {
    return grade('NOT_EXERCISED', 'No reported App-side login boundary was observed.');
  }
  const onDeviceAttempt = items.some(item => item.type === 'commandExecution' &&
    /\badb\b|emulator-/i.test(item.command ?? '') &&
    /(?:shell|forward|install|logcat|exec-out)\b[^\n]*(?:fixture|mock|webview_devtools)|(?:fixture|mock|webview_devtools|合成会话|隔离复现)[^\n]*\b(?:shell|forward|install|logcat|exec-out)\b/i.test(item.command ?? ''));
  const blockerRecorded = /(?:阻塞|无法继续|blocker)[\s\S]{0,1200}(?:恢复动作|最小输入|恢复条件|下一步|resume_action|required_input|next_action)/i.test(review);
  if (!onDeviceAttempt || !blockerRecorded) {
    return grade('FAIL', 'Report delivered at the App login boundary without both an observed App-host isolation attempt and a blocker record with a resume action.');
  }
  return grade('PASS', 'An App-host isolation attempt and a documented blocker with a resume action were observed.');
}

module.exports = { firstReview, afterCorrection, loginBlocker, completedItems, reviewRounds, flowWrites };
