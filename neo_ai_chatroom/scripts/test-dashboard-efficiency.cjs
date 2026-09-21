const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const source = fs.readFileSync(path.join(__dirname, '../src/components/dashboard/EfficiencyPanel.tsx'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS } });
const context = vm.createContext({ exports: {}, React, require: name => name.endsWith('.css') ? {} : require(name) });
vm.runInContext(compiled.outputText, context);
const render = props => renderToStaticMarkup(React.createElement(context.exports.EfficiencyPanel, props));
test('saved result counts do not become clicks or invented hours', () => {
  const html = render({ stats: { netlist_compare_count: 12, netlist_analyze_count: 4 }, loading: false });
  assert.match(html, /12 次/);
  assert.match(html, /4 次/);
  assert.match(html, /待标定/);
  assert.match(html, /仍需排除重复任务/);
});
test('failure, loading and real zero are distinct', () => {
  assert.match(render({ stats: null, loading: false }), /读取失败/);
  assert.match(render({ stats: null, loading: true }), /加载中/);
  assert.match(render({ stats: { netlist_compare_count: 0, netlist_analyze_count: 0 }, loading: false }), /0 次/);
});
test('additive top panel leaves original dashboard in place', () => {
  const page = fs.readFileSync(path.join(__dirname, '../src/pages/DashboardPage.tsx'), 'utf8');
  assert.ok(page.indexOf('<EfficiencyPanel') < page.indexOf('<section className="bi-dashboard"'));
  assert.match(page, /<DashboardCharts stats=\{s\}/);
});
