#!/usr/bin/env node
/**
 * Brute-force the fullpage string table to find which index holds the IE class
 * names, so the emitting call site can be located in the source.
 *
 * usage: node env/find_ie.js [--max 4000] [--asset fullpage|click]
 */
import vm from 'vm';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PROFILE = process.env.ENV_PROFILE
  || 'C:\\Users\\20240\\.dsh\\skills\\spider-king\\references\\profiles\\env-patch';
const ENV_DIR = path.join(ENV_PROFILE, 'env');
const TASK = path.resolve(__dirname, '..');

const argv = process.argv.slice(2);
let max = 4500;
let asset = 'fullpage';
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--max') max = parseInt(argv[++i], 10);
  else if (argv[i] === '--asset') asset = argv[++i];
}
const NAMED = { fullpage: 'fullpage.9.2.0-guwyxh.js', click: 'click.3.1.2.js', geetest: 'geetest.6.0.9.js' };
const assetPath = path.join(TASK, 'cache', NAMED[asset] || asset);

const TIMEOUT = 60000;
const ctx = vm.createContext(Object.create(null), { name: 'find-ie', codeGeneration: { strings: true, wasm: false } });
vm.runInContext(String.raw`
(function () {
  const c = Object.create(null);
  for (const l of ['log','error','warn','info','debug','trace','dir','table']) c[l] = function () {};
  for (const l of ['group','groupCollapsed','groupEnd','time','timeEnd','timeLog','count','countReset','assert','clear']) c[l] = function () {};
  Object.assign(globalThis, {
    console: c, setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {},
    atob: (s) => s, btoa: (s) => s, XMLHttpRequest: function () {},
  });
  globalThis.window = globalThis; globalThis.self = globalThis; globalThis.global = globalThis;
  globalThis.__gt3Typeof__ = function (v) { return typeof v; };
})();
`, ctx, { timeout: TIMEOUT });

vm.runInContext(fs.readFileSync(path.join(ENV_DIR, 'core', 'ProxyMonitor.js'), 'utf-8'), ctx, { timeout: TIMEOUT });
for (const m of ['bom/navigator.js', 'bom/location.js', 'dom/document.js']) {
  const p = path.join(ENV_DIR, m);
  if (fs.existsSync(p)) vm.runInContext(fs.readFileSync(p, 'utf-8'), ctx, { timeout: TIMEOUT });
}

try {
  let code = fs.readFileSync(assetPath, 'utf-8');
  if (path.basename(assetPath).includes('loader')) code = `(function (o) {\n${code}\n})(globalThis.__gt3Typeof__);`;
  vm.runInContext(code, ctx, { timeout: TIMEOUT, filename: path.basename(assetPath) });
} catch (e) {
  console.error('[warn] asset threw: ' + (e && e.name) + ' ' + String(e && e.message).slice(0, 120));
}

const out = JSON.parse(vm.runInContext(`JSON.stringify((function () {
  const res = { decoders: [], found: [], sample: [] };
  const cand = [];
  try { if (globalThis.Vwtrj && typeof globalThis.Vwtrj.$_CV === 'function') cand.push(['Vwtrj.$_CV', globalThis.Vwtrj.$_CV]); } catch (_) {}
  for (const [name] of cand) res.decoders.push(name);
  const MAX = ${max};
  for (const [name, fn] of cand) {
    for (let i = 0; i < MAX; i++) {
      let s;
      try { s = String(fn.call(globalThis.Vwtrj, i)); } catch (_) { continue; }
      if (!s) continue;
      if (i < 40) res.sample.push([i, s.slice(0, 20)]);
      if (/geetest_ie|geetest_radar_click|geetest_holder|geetest_wind|documentMode|execCommand|attachEvent|ActiveXObject|compatMode/i.test(s)
          || /^_?ie$/i.test(s) || /geetest_/i.test(s) || /\bie\b/i.test(s)) {
        res.found.push([i, s.slice(0, 48)]);
      }
    }
  }
  return res;
})())`, ctx, { timeout: TIMEOUT }));

console.log(JSON.stringify(out, null, 2));
