#!/usr/bin/env node
/**
 * Dump a product's whole decoded string table to a file, so payload-builder
 * sites can be located offline by the strings they use.
 *
 * usage: node env/dump_strings.js --asset click --max 20000
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
let max = 20000;
let asset = 'click';
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--max') max = parseInt(argv[++i], 10);
  else if (argv[i] === '--asset') asset = argv[++i];
}
const NAMED = { fullpage: 'fullpage.9.2.0-guwyxh.js', click: 'click.3.1.2.js', geetest: 'geetest.6.0.9.js' };
const assetPath = path.join(TASK, 'cache', NAMED[asset] || asset);
const outPath = path.join(TASK, 'cache', `${asset}_strings.tsv`);

const TIMEOUT = 60000;
const ctx = vm.createContext(Object.create(null), { name: 'dump-strings', codeGeneration: { strings: true, wasm: false } });
vm.runInContext(String.raw`
(function () {
  const c = Object.create(null);
  for (const l of ['log','error','warn','info','debug','trace','dir','table']) c[l] = function () {};
  for (const l of ['group','groupCollapsed','groupEnd','time','timeEnd','timeLog','count','countReset','assert','clear']) c[l] = function () {};
  Object.assign(globalThis, { console: c, setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {}, atob: (s) => s, btoa: (s) => s, XMLHttpRequest: function () {} });
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
  vm.runInContext(fs.readFileSync(assetPath, 'utf-8'), ctx, { timeout: TIMEOUT, filename: path.basename(assetPath) });
} catch (e) {
  console.error('[warn] asset threw: ' + (e && e.name));
}

const rows = JSON.parse(vm.runInContext(`JSON.stringify((function () {
  const out = [];
  const cands = [];
  try { if (globalThis.Vwtrj && typeof globalThis.Vwtrj.$_CV === 'function') cands.push(['Vwtrj.$_CV', globalThis.Vwtrj.$_CV, globalThis.Vwtrj]); } catch (_) {}
  try { if (globalThis.YDbxr && typeof globalThis.YDbxr.$_Ct === 'function') cands.push(['YDbxr.$_Ct', globalThis.YDbxr.$_Ct, globalThis.YDbxr]); } catch (_) {}
  // generic: any global object exposing a short \$_XX function that returns strings
  try {
    for (const k of Object.getOwnPropertyNames(globalThis)) {
      let v;
      try { v = globalThis[k]; } catch (_) { continue; }
      if (!v || typeof v !== 'object') continue;
      for (const f of Object.getOwnPropertyNames(v)) {
        if (!/^\\$_\\w{1,3}$/.test(f)) continue;
        let fn;
        try { fn = v[f]; } catch (_) { continue; }
        if (typeof fn !== 'function') continue;
        let ok = false;
        try { ok = typeof fn.call(v, 3) === 'string'; } catch (_) {}
        if (ok) cands.push([k + '.' + f, fn, v]);
      }
    }
  } catch (_) {}
  out.push(['__decoders__', cands.map((c) => c[0]).join('|')]);
  for (const [name, fn, self] of cands) {
    for (let i = 0; i < ${max}; i++) {
      let s;
      try { s = String(fn.call(self, i)); } catch (_) { continue; }
      if (s && s.length && s.length < 80) out.push([i, s, name]);
    }
    break;   // first working decoder wins
  }
  return out;
})())`, ctx, { timeout: TIMEOUT }));

if (rows.length <= 1) {
  const info = JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const out = { globals: [] };
    for (const k of Object.getOwnPropertyNames(globalThis)) {
      let v, t;
      try { v = globalThis[k]; t = typeof v; } catch (_) { continue; }
      if (t === 'object' && v && k.length < 12) out.globals.push([k, Object.getOwnPropertyNames(v).slice(0, 10)]);
      if (t === 'function' && k.length < 12) out.globals.push([k, 'fn']);
    }
    return out;
  })())`, ctx, { timeout: TIMEOUT }));
  console.log(JSON.stringify({ asset, entries: 0, info }, null, 2));
  process.exit(0);
}

const lines = rows.map(([i, s]) => `${i}\t${s}`).join('\n');
fs.writeFileSync(outPath, lines, 'utf-8');
console.log(JSON.stringify({ asset, entries: rows.length, out: outPath }));
