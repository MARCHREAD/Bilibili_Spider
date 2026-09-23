#!/usr/bin/env node
/**
 * Decode the four `x in documentElement.style` probes used by the product's IE
 * check C(), then run those exact probes inside the env-patch sandbox.
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

const TIMEOUT = 60000;
const ctx = vm.createContext(Object.create(null), { name: 'probe-ie', codeGeneration: { strings: true, wasm: false } });
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
vm.runInContext(fs.readFileSync(path.join(TASK, 'cache', 'fullpage.9.2.0-guwyxh.js'), 'utf-8'), ctx,
  { timeout: TIMEOUT, filename: 'fullpage.js' });

const report = JSON.parse(vm.runInContext(`JSON.stringify((function () {
  const dec = (i) => { try { return String(globalThis.Vwtrj.$_CV(i)); } catch (e) { return 'ERR'; } };
  const names = [415, 440, 464, 432, 478, 222, 1012, 1080].map((i) => [i, dec(i)]);
  const d = globalThis.document || {};
  const de = d.documentElement || {};
  const style = de.style || {};
  const probes = {};
  for (const [i, name] of names.slice(1, 5)) {
    try { probes[name] = (name in style); } catch (e) { probes[name] = 'threw:' + e.name; }
  }
  const extras = {};
  for (const k of ['behavior', 'msTransform', 'msFlexAlign', 'msGridRows', 'filter', 'position', 'display', 'zzzNotARealProperty']) {
    try { extras[k] = (k in style); } catch (e) { extras[k] = 'threw'; }
  }
  const own = [];
  try { own.push(['style keys', Object.keys(style).length]); } catch (_) {}
  try { own.push(['style ownNames', Object.getOwnPropertyNames(style).length]); } catch (_) {}
  return {
    decoded: names,
    documentElement: typeof de, styleType: typeof style,
    ieProbe: probes,
    extraProbes: extras,
    own,
    documentAll: (function () { try { return typeof d.all; } catch (e) { return 'threw'; } })(),
    documentMode: (function () { try { return d.documentMode; } catch (e) { return 'threw'; } })(),
  };
})())`, ctx, { timeout: TIMEOUT }));

console.log(JSON.stringify(report, null, 2));
