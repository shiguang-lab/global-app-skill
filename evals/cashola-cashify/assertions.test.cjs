const assert = require('node:assert/strict');
const { mkdtempSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const test = require('node:test');
const { firstReview, afterCorrection, loginBlocker } = require('./assertions.cjs');

function review(id, prompt) {
  return [
    { type: 'collabAgentToolCall', status: 'completed', tool: 'spawnAgent', prompt, receiverThreadIds: [id] },
    { type: 'collabAgentToolCall', status: 'completed', tool: 'wait', agentsStates: { [id]: { status: 'completed' } } },
  ];
}

function fixture(t, items) {
  const cwd = mkdtempSync(join(tmpdir(), 'cashify-eval-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  writeFileSync(join(cwd, 'report.html'), '<title>Cashify</title>');
  const notifications = items.map(item => ({ method: 'item/completed', params: { item } }));
  return { cwd, context: { providerResponse: { raw: JSON.stringify({ notifications }), metadata: { codexAppServer: { cwd } } } } };
}

test('three simultaneous reviewers count as one round; the agent claim does not count', t => {
  const group = ['one', 'two', 'three'].map(id => review(id, '首轮证据复核'));
  const { context } = fixture(t, [...group.map(([spawn]) => spawn), ...group.map(([, wait]) => wait)]);
  const result = firstReview('已交付 report.html，做了两轮复核。', context);
  assert.equal(result.pass, false);
  assert.match(result.reason, /1 independently completed/);
  assert.match(firstReview('阶段性报告 report.html', context).reason, /NOT_EXERCISED/);
});

test('a review started before a correction does not verify the corrected graph', t => {
  const first = review('first', '首轮证据审查');
  const [spawn, wait] = review('second', '第二轮复审');
  const edit = { type: 'fileChange', status: 'completed', changes: [{ path: 'loan.mmd' }] };
  const { context } = fixture(t, [...first, spawn, edit, wait]);
  assert.match(afterCorrection('已交付 report.html', context).reason, /^\[FAIL\]/);
  const fixed = fixture(t, [...first, spawn, edit, wait, ...review('third', '修订后第三轮重审')]);
  assert.equal(afterCorrection('已交付 report.html', fixed.context).pass, true);
  assert.equal(firstReview('已交付 report.html', fixed.context).pass, true);
});

test('reading a graph while writing a separate review record is not a flow edit', t => {
  const command = { type: 'commandExecution', exitCode: 0, command: "Path('review.md').write_text(Path('flow.mmd').read_text())" };
  const { context } = fixture(t, [...review('first', '首轮复核'), command]);
  assert.match(afterCorrection('已交付 report.html', context).reason, /^\[NOT_EXERCISED\]/);
});

test('delivery after login requires an actual App-host attempt and a recorded blocker', t => {
  const output = '阶段性报告 report.html，原包停在手机号登录页。';
  const browser = { type: 'commandExecution', exitCode: 0, command: 'node playwright-h5-mock.cjs' };
  const { context } = fixture(t, [browser]);
  assert.match(loginBlocker(output, context).reason, /^\[FAIL\]/);
  const adb = { type: 'commandExecution', exitCode: 1, command: 'adb forward tcp:9222 localabstract:webview_devtools_remote' };
  const attempted = fixture(t, [browser, adb]);
  writeFileSync(join(attempted.cwd, 'review.md'), '## 阻塞\n缺少可调试宿主。下一步取得匹配的运行样本。');
  assert.equal(loginBlocker(output, attempted.context).pass, true);
});
