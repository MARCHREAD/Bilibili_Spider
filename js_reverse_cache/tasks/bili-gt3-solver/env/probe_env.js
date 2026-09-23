#!/usr/bin/env node
/** Report the browser-detection surface of the env-patch sandbox (why geetest says IE). */
import vm from 'vm';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PROFILE = process.env.ENV_PROFILE
  || 'C:\\Users\\20240\\.dsh\\skills\\spider-king\\references\\profiles\\env-patch';
const ENV_DIR = path.join(ENV_PROFILE, 'env');
const modules = (process.argv[2] || 'bom/navigator.js,bom/location.js,dom/document.js').split(',');

const ctx = vm.createContext(Object.create(null), { name: 'probe', codeGeneration: { strings: true, wasm: false } });
vm.runInContext(`(function(){ const c=Object.create(null); for (const l of ['log','error','warn','info','debug']) c[l]=function(){};
  Object.assign(globalThis,{console:c,setTimeout:()=>0,setInterval:()=>0,clearTimeout(){},clearInterval(){},atob:(s)=>s,btoa:(s)=>s,XMLHttpRequest:function(){}});
  globalThis.window=globalThis; globalThis.self=globalThis; globalThis.global=globalThis; })();`, ctx);
vm.runInContext(fs.readFileSync(path.join(ENV_DIR, 'core', 'ProxyMonitor.js'), 'utf-8'), ctx);
for (const m of modules) {
  const p = path.join(ENV_DIR, m.trim());
  if (fs.existsSync(p)) vm.runInContext(fs.readFileSync(p, 'utf-8'), ctx);
}

const report = JSON.parse(vm.runInContext(`JSON.stringify((function () {
  const n = globalThis.navigator || {};
  const d = globalThis.document || {};
  const w = globalThis;
  const ua = String(n.userAgent || '');
  return {
    ua,
    appVersion: String(n.appVersion || '').slice(0, 120),
    appName: n.appName, platform: n.platform, vendor: n.vendor,
    ieSignals: {
      uaMSIE: /MSIE|Trident/i.test(ua),
      attachEvent: typeof w.attachEvent,
      documentAll: typeof d.all,
      documentMode: d.documentMode,
      ActiveXObject: typeof w.ActiveXObject,
      execCommand: typeof d.execCommand,
      createEventObject: typeof d.createEventObject,
    },
    modern: {
      addEventListener: typeof w.addEventListener,
      documentAddEventListener: typeof d.addEventListener,
      Event: typeof w.Event,
      MouseEvent: typeof w.MouseEvent,
      requestAnimationFrame: typeof w.requestAnimationFrame,
      Promise: typeof w.Promise,
    },
  };
})())`, ctx));
console.log(JSON.stringify(report, null, 2));
