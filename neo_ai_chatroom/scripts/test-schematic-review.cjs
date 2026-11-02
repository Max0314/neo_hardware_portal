const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/utils/schematicReview.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } });
const context = vm.createContext({ exports: {} });
vm.runInContext(compiled.outputText, context);
const { mergeSchematicReviewJson, buildSchematicContinuationPrompt, collectAiChecksFromAggregated } = context.exports;

const check = description => ({ check_name: 'IC引脚连接完整性', status: 'WARNING', description });
const first = {
  summary: '初次评审', overall_status: 'WARNING', complete: false,
  interfaces: [
    { interface_name: 'U5', checks: [check('U5 缺少连接')] },
    { interface_name: 'U2V', checks: [check('U2V 缺少连接')] },
  ],
};

test('model interface_name keeps same-named checks from different interfaces', () => {
  const merged = mergeSchematicReviewJson([first]);
  assert.equal(merged.interfaces.length, 2);
  const checks = collectAiChecksFromAggregated({ mergedReview: merged });
  assert.equal(checks.length, 2);
  assert.equal(checks[0].title, 'U5 · IC引脚连接完整性');
  assert.equal(checks[1].title, 'U2V · IC引脚连接完整性');
  assert.match(buildSchematicContinuationPrompt([first], 2), /已覆盖的接口类型包括：U5、U2V/);
});

test('continuations update only the same interface and preserve legacy names', () => {
  const merged = mergeSchematicReviewJson([first, { interfaces: [
    { type: 'U5', checks: [check('U5 已核对')] },
    { name: 'USB', checks: [{ check_name: 'VBUS', status: 'PASS', description: '正常' }] },
    { type: ' ', name: '', interface_name: 'GND', checks: [{ check_name: '连通性', status: 'PASS' }] },
  ] }]);
  assert.equal(merged.interfaces.length, 4);
  const byName = Object.fromEntries(merged.interfaces.map(item => [item.type, item.checks]));
  assert.equal(byName.U5.length, 1);
  assert.equal(byName.U5[0].description, 'U5 已核对');
  assert.equal(byName.U2V[0].description, 'U2V 缺少连接');
  assert.equal(byName.USB[0].check_name, 'VBUS');
  assert.equal(byName.GND[0].check_name, '连通性');
});

test('unmerged legacy history renders model-provided interface names', () => {
  const checks = collectAiChecksFromAggregated({ aiReview: first });
  assert.equal(checks[0].title, 'U5 · IC引脚连接完整性');
  assert.equal(checks[1].title, 'U2V · IC引脚连接完整性');
});
