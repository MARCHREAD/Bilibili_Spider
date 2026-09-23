#!/usr/bin/env node
/**
 * Entry-contract probe for the raw GT3 fullpage asset.
 *
 * Loads the spider env-patch environment + the raw asset into one vm context and
 * reports which globals the asset defines, whether a captcha entry exists, and
 * every JSONP <script> URL captured at the DOM boundary.
 *
 * Reports names/shapes only; never prints target strings.
 *
 * usage:
 *   node env/probe_entry.js [--env a.js,b.js] [--asset path]
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
let envModules = ['bom/navigator.js', 'bom/location.js', 'dom/document.js'];
let assetPath = path.join(TASK, 'cache', 'fullpage.9.2.0-guwyxh.js');
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--env' && argv[i + 1]) envModules = argv[++i].split(',').map((s) => s.trim()).filter(Boolean);
  else if (argv[i] === '--asset' && argv[i + 1]) assetPath = path.resolve(argv[++i]);
}

const TIMEOUT = 60000;
const context = vm.createContext(Object.create(null), {
  name: 'spider-gt3-probe',
  codeGeneration: { strings: true, wasm: false },
});

const bootstrap = String.raw`
(function () {
  'use strict';
  const output = [];
  function safeValue(v) {
    if (v === null || ['undefined','number','boolean'].includes(typeof v)) return v;
    if (typeof v === 'string') return '[String len=' + v.length + ']';
    if (typeof v === 'function') return '[Function]';
    try { if (Array.isArray(v)) return '[Array len=' + v.length + ']'; } catch (_) {}
    return '[Object]';
  }
  const guestConsole = Object.create(null);
  for (const level of ['log','error','warn','info','debug','trace','dir','table']) {
    guestConsole[level] = function () { output.push([level].concat(Array.prototype.map.call(arguments, safeValue))); };
  }
  for (const level of ['group','groupCollapsed','groupEnd','time','timeEnd','timeLog','count','countReset','assert','clear']) {
    guestConsole[level] = function () {};
  }
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
  function atobCompat(input) {
    const text = String(input).replace(/[\t\n\f\r ]/g, '');
    if (text.length % 4 === 1 || /[^A-Za-z0-9+/=]/.test(text)) throw new TypeError('Invalid character');
    let out = '', buf = 0, bits = 0;
    for (const ch of text.replace(/=+$/, '')) {
      buf = (buf << 6) | alphabet.indexOf(ch); bits += 6;
      if (bits >= 8) { bits -= 8; out += String.fromCharCode((buf >> bits) & 255); }
    }
    return out;
  }
  function btoaCompat(input) {
    const text = String(input); let out = '';
    for (let i = 0; i < text.length; i += 3) {
      const a = text.charCodeAt(i), b = text.charCodeAt(i + 1), c = text.charCodeAt(i + 2);
      if (a > 255 || b > 255 || c > 255) throw new TypeError('Invalid character');
      const t = (a << 16) | ((Number.isNaN(b) ? 0 : b) << 8) | (Number.isNaN(c) ? 0 : c);
      out += alphabet[(t >> 18) & 63] + alphabet[(t >> 12) & 63];
      out += Number.isNaN(b) ? '=' : alphabet[(t >> 6) & 63];
      out += Number.isNaN(c) ? '=' : alphabet[t & 63];
    }
    return out;
  }
  class XHRCompat {
    constructor() { this.readyState = 0; }
    open() {} send() {} setRequestHeader() {} getResponseHeader() { return null; }
    getAllResponseHeaders() { return ''; } addEventListener() {} removeEventListener() {} abort() {}
  }
  // real timer queue: never run callbacks synchronously
  const timers = new Map(); let seq = 1;
  Object.assign(globalThis, {
    console: guestConsole,
    setTimeout: function (fn, ms) { const id = seq++; timers.set(id, { fn, ms, args: Array.prototype.slice.call(arguments, 2) }); return id; },
    setInterval: function (fn, ms) { const id = seq++; timers.set(id, { fn, ms, every: true, args: Array.prototype.slice.call(arguments, 2) }); return id; },
    clearTimeout: function (id) { timers.delete(id); },
    clearInterval: function (id) { timers.delete(id); },
    atob: atobCompat, btoa: btoaCompat, XMLHttpRequest: XHRCompat,
    __output__: output, __gt3Requests: [], __gt3Log: [],
  });
  globalThis.window = globalThis;
  globalThis.global = globalThis;
  globalThis.self = globalThis;
  globalThis.__drainTimers__ = function (limit) {
    let ran = 0;
    while (timers.size && ran < (limit || 200)) {
      const [id, t] = timers.entries().next().value;
      timers.delete(id); ran++;
      try { t.fn.apply(null, t.args); } catch (e) { globalThis.__gt3Log.push('timer-error:' + (e && e.message)); }
    }
    return ran;
  };
})();
`;
vm.runInContext(bootstrap, context, { timeout: TIMEOUT });

const notes = [];
const log = (m) => { notes.push(m); };

log(`[probe] env modules: ${envModules.join(', ')}`);
vm.runInContext(fs.readFileSync(path.join(ENV_DIR, 'core', 'ProxyMonitor.js'), 'utf-8'), context, { timeout: TIMEOUT });

for (const mod of envModules) {
  let p;
  if (path.isAbsolute(mod)) p = mod;
  else if (fs.existsSync(path.resolve(process.cwd(), mod))) p = path.resolve(process.cwd(), mod);
  else p = path.join(ENV_DIR, mod);
  if (!fs.existsSync(p)) { log(`[probe] MISSING module ${mod}`); continue; }
  try {
    vm.runInContext(fs.readFileSync(p, 'utf-8'), context, { timeout: TIMEOUT });
    log(`[probe] loaded ${mod}`);
  } catch (e) {
    log(`[probe] module threw: ${mod} (${e && e.name})`);
  }
}

// --- install the DOM-boundary wire capture BEFORE the asset loads ----------
vm.runInContext(String.raw`
(function () {
  'use strict';
  const doc = globalThis.document;
  if (doc && typeof doc.createElement === 'function') {
    const origCreate = doc.createElement.bind(doc);
    doc.createElement = function (tag) {
      const el = origCreate(tag);
      if (String(tag).toLowerCase() === 'script') {
        let src = '';
        try {
          Object.defineProperty(el, 'src', {
            configurable: true,
            get() { return src; },
            set(v) {
              src = String(v);
              try { globalThis.__gt3Requests.push(src); } catch (_) {}
            },
          });
        } catch (_) {}
      }
      return el;
    };
  }
})();
`, context, { timeout: TIMEOUT });

const before = JSON.parse(vm.runInContext('JSON.stringify(Object.getOwnPropertyNames(globalThis))', context));

// --- load the raw asset ---------------------------------------------------
let loaded = false;
try {
  vm.runInContext(fs.readFileSync(assetPath, 'utf-8'), context, {
    timeout: TIMEOUT, filename: path.basename(assetPath), displayErrors: true,
  });
  loaded = true;
} catch (e) {
  log(`[probe] asset threw: ${e && e.name}: ${String(e && e.message).slice(0, 160)}`);
}
log(`[probe] asset loaded: ${loaded}`);

const after = JSON.parse(vm.runInContext('JSON.stringify(Object.getOwnPropertyNames(globalThis))', context));
const added = after.filter((k) => !before.includes(k));

const report = JSON.parse(vm.runInContext(`JSON.stringify({
  addedGlobals: ${JSON.stringify(added)},
  types: Object.fromEntries(${JSON.stringify(added)}.map(k => [k, typeof globalThis[k]])),
  geetest: typeof globalThis.Geetest,
  initGeetest: typeof globalThis.initGeetest,
  GeetestProto: (typeof globalThis.Geetest === 'function' && globalThis.Geetest.prototype)
    ? Object.getOwnPropertyNames(globalThis.Geetest.prototype).slice(0, 40) : [],
  requests: globalThis.__gt3Requests,
  gt3Log: globalThis.__gt3Log,
  timersRan: globalThis.__drainTimers__(50),
  output: globalThis.__output__.slice(0, 20),
})`, context));

console.log(JSON.stringify({ notes, report }, null, 2));
