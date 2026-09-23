#!/usr/bin/env node
/**
 * GT3 SDK helper: run the raw geetest assets inside the spider env-patch sandbox
 * and freeze the wire at the DOM boundary.
 *
 * Protocol (JSON lines on stdout / stdin):
 *   out {"type":"ready","assets":[...]}
 *   out {"type":"request","id":N,"kind":"script|script-js|img|xhr","url":"...","params":{...}}
 *   in  {"type":"response","id":N,"kind":"json","body":{...}}        -> JSONP callback
 *   in  {"type":"response","id":N,"kind":"js","body":"<source>"}     -> eval in sandbox
 *   out {"type":"done","requests":[...],"log":[...],"errors":[...]}
 *
 * Live HTTP stays in the caller (Python): the helper never opens a socket.
 *
 * usage:
 *   node env/run.js --gt <gt> --challenge <challenge> [--assets geetest,fullpage]
 *                   [--type slide] [--env a.js,b.js] [--max-rounds 12]
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
const opt = {
  gt: null, challenge: null, type: 'slide', product: 'bind', driver: 'loader', decode: null, dumpCore: false, probeCore: null, probeAllCore: false, synthClicks: null, synthMoves: null, timerCap: 50, verifyFirst: false, probeArgs: null, probeTarget: 'core', dumpInst: false, dumpValues: false, callAwait: null, findMethod: null, callWidget: null, dumpWidget: false, answerFormats: null,
  env: 'bom/navigator.js,bom/location.js,dom/document.js',
  assets: 'loader', drain: 200, maxRounds: 12, lang: 'zh-cn',
};
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--gt') opt.gt = argv[++i];
  else if (a === '--challenge') opt.challenge = argv[++i];
  else if (a === '--type') opt.type = argv[++i];
  else if (a === '--product') opt.product = argv[++i];
  else if (a === '--driver') opt.driver = argv[++i];
  else if (a === '--decode') opt.decode = argv[++i];
  else if (a === '--dump-core') opt.dumpCore = true;
  else if (a === '--probe-core') opt.probeCore = argv[++i];
  else if (a === '--probe-all-core') opt.probeAllCore = true;
  else if (a === '--synth-clicks') opt.synthClicks = argv[++i];
  else if (a === '--synth-moves') opt.synthMoves = argv[++i];
  else if (a === '--verify-first') opt.verifyFirst = true;
  else if (a === '--probe-args') opt.probeArgs = argv[++i];
  else if (a === '--probe-target') opt.probeTarget = argv[++i];
  else if (a === '--dump-inst') opt.dumpInst = true;
  else if (a === '--dump-values') opt.dumpValues = true;
  else if (a === '--call-await') opt.callAwait = argv[++i];
  else if (a === '--find-method') opt.findMethod = argv[++i];
  else if (a === '--call-widget') opt.callWidget = argv[++i];
  else if (a === '--dump-widget') opt.dumpWidget = true;
  else if (a === '--answer-formats') opt.answerFormats = argv[++i];
  else if (a === '--timer-cap') opt.timerCap = parseInt(argv[++i], 10);
  else if (a === '--env') opt.env = argv[++i];
  else if (a === '--assets') opt.assets = argv[++i];
  else if (a === '--drain') opt.drain = parseInt(argv[++i], 10);
  else if (a === '--max-rounds') opt.maxRounds = parseInt(argv[++i], 10);
  else if (a === '--lang') opt.lang = argv[++i];
}
const envModules = opt.env.split(',').map((s) => s.trim()).filter(Boolean);
const NAMED = {
  fullpage: 'fullpage.9.2.0-guwyxh.js',
  slide: 'slide.7.9.3.js',
  geetest: 'geetest.6.0.9.js',
  loader: 'gt_loader_from_bili.js',
};
const assetFiles = opt.assets.split(',').map((s) => s.trim()).filter(Boolean)
  .map((n) => path.join(TASK, 'cache', NAMED[n] || n));

const TIMEOUT = 60000;
const context = vm.createContext(Object.create(null), {
  name: 'spider-gt3-helper',
  codeGeneration: { strings: true, wasm: false },
});

const bootstrap = String.raw`
(function () {
  'use strict';
  const output = [];
  function safe(v) {
    if (v === null || ['undefined','number','boolean'].includes(typeof v)) return v;
    if (typeof v === 'string') return '[String len=' + v.length + ']';
    if (typeof v === 'function') return '[Function]';
    try { if (Array.isArray(v)) return '[Array len=' + v.length + ']'; } catch (_) {}
    return '[Object]';
  }
  const guestConsole = Object.create(null);
  for (const l of ['log','error','warn','info','debug','trace','dir','table']) {
    guestConsole[l] = function () { output.push([l].concat(Array.prototype.map.call(arguments, safe))); };
  }
  for (const l of ['group','groupCollapsed','groupEnd','time','timeEnd','timeLog','count','countReset','assert','clear']) {
    guestConsole[l] = function () {};
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
  const xhrPending = [];
  class XHRCompat {
    constructor() { this.readyState = 0; this.responseText = ''; this.status = 0; this._h = {}; }
    open(m, u) { this._m = m; this._u = String(u); }
    setRequestHeader(k, v) { this._h[k] = v; }
    send(body) {
      this._body = body; this.readyState = 1;
      xhrPending.push(this);
      if (globalThis.__gt3OnXhr) globalThis.__gt3OnXhr(this);
    }
    abort() {}
    getResponseHeader() { return null; }
    getAllResponseHeaders() { return ''; }
    addEventListener(t, fn) { if (t === 'load') this._onload = fn; else if (t === 'error') this._onerror = fn; }
    removeEventListener() {}
    __resolve(text) {
      this.responseText = text; this.response = text; this.status = 200; this.readyState = 4;
      if (this.onreadystatechange) { try { this.onreadystatechange(); } catch (_) {} }
      if (this._onload) { try { this._onload(); } catch (_) {} }
    }
  }
  const timers = new Map(); let seq = 1;
  Object.assign(globalThis, {
    console: guestConsole,
    setTimeout: (fn, ms) => { const id = seq++; timers.set(id, { fn, ms, args: Array.prototype.slice.call(arguments, 2) }); return id; },
    setInterval: (fn, ms) => { const id = seq++; timers.set(id, { fn, ms, every: true, args: Array.prototype.slice.call(arguments, 2) }); return id; },
    clearTimeout: (id) => timers.delete(id),
    clearInterval: (id) => timers.delete(id),
    atob: atobCompat, btoa: btoaCompat, XMLHttpRequest: XHRCompat,
    __output__: output, __gt3Requests: [], __gt3Log: [], __gt3Errors: [], __gt3Timers: timers, __gt3Elements: [],
  });
  globalThis.window = globalThis;
  globalThis.global = globalThis;
  globalThis.self = globalThis;
  // Outer-scope dependency of the loader extracted from bilibili chunk 264:
  // the Babel _typeof helper the loader calls as o(...). Kept under a private
  // name and injected through a loader-only closure, because the product asset
  // also defines its own top-level o table and a global would collide.
  globalThis.__gt3Typeof__ = function (value) {
    return (typeof Symbol === 'function' && typeof Symbol.iterator === 'symbol')
      ? typeof value
      : (value && typeof value === 'object' && typeof value.constructor === 'function'
        && value.constructor === Symbol && value !== Symbol.prototype ? 'symbol' : typeof value);
  };
  globalThis.__pendingTimers__ = () => timers.size;
  globalThis.__pendingDelays__ = () => Array.from(timers.values())
    .map((t) => (t.due === undefined ? (t.ms || 0) : t.due - vnow))
    .sort((a, b) => a - b);
  // Virtual clock. The SDK's script loader arms a long timeout (error 408) next
  // to a 0ms completion timer; draining every timer at once fires the timeout
  // first and fakes a network failure. Only timers due inside a small budget run.
  let vnow = 0;
  globalThis.__virtualNow__ = () => vnow;
  globalThis.__advanceClock__ = (ms) => { vnow += ms; return vnow; };
  globalThis.__drainTimers__ = function (limit, maxDelay) {
    const cap = maxDelay === undefined ? 50 : maxDelay;
    let ran = 0;
    for (;;) {
      if (ran >= (limit || 200)) break;
      let bestId = null, best = null;
      for (const [id, t] of timers) {
        if (t.due === undefined) t.due = vnow + (t.ms || 0);
        if (t.due > vnow + cap) continue;
        if (!best || t.due < best.due || (t.due === best.due && id < bestId)) { best = t; bestId = id; }
      }
      if (!best) break;
      timers.delete(bestId);
      if (best.due > vnow) vnow = best.due;
      ran++;
      try { best.fn.apply(null, best.args); } catch (e) {
        globalThis.__gt3Log.push('timer:' + (e && e.name) + ':' + String(e && e.message).slice(0, 160)
          + '|stack:' + String((e && e.stack) || '').replace(/\n/g, ' << ').slice(0, 420));
      }
    }
    return ran;
  };
  globalThis.__xhrPending__ = xhrPending;
  // Capture the plaintext the SDK encrypts into w: hook JSON.stringify and keep
  // any object whose keys look like a geetest payload. This reveals what the SDK
  // actually declares (type, ep, passtime, userresponse) before encryption.
  globalThis.__gt3Payloads = [];
  (function () {
    const orig = JSON.stringify;
    const WANT = ['ep', 'userresponse', 'passtime', 'aa', 'rp', 'geetest', 'client_type', 'lot_number'];
    JSON.stringify = function (value) {
      let out;
      try { out = orig.apply(JSON, arguments); } catch (e) { throw e; }
      try {
        if (value && typeof value === 'object' && !Array.isArray(value) && globalThis.__gt3Payloads.length < 12) {
          const keys = Object.keys(value);
          if (keys.some((k) => WANT.indexOf(k) >= 0)) {
            globalThis.__gt3Payloads.push({ keys, len: out ? out.length : 0, sample: String(out).slice(0, 900) });
          }
        }
      } catch (_) {}
      return out;
    };
  })();
})();
`;
vm.runInContext(bootstrap, context, { timeout: TIMEOUT });
vm.runInContext(fs.readFileSync(path.join(ENV_DIR, 'core', 'ProxyMonitor.js'), 'utf-8'), context, { timeout: TIMEOUT });

const diag = [];
// an exception thrown inside the SDK's own .then chain would otherwise vanish
process.on('unhandledRejection', (reason) => {
  diag.push('unhandledRejection:' + String((reason && reason.stack) || reason).replace(/\n/g, ' << ').slice(0, 300));
});
process.on('uncaughtException', (err) => {
  diag.push('uncaughtException:' + String((err && err.stack) || err).replace(/\n/g, ' << ').slice(0, 300));
});
for (const mod of envModules) {
  let p;
  if (path.isAbsolute(mod)) p = mod;
  else if (fs.existsSync(path.resolve(process.cwd(), mod))) p = path.resolve(process.cwd(), mod);
  else p = path.join(ENV_DIR, mod);
  if (!fs.existsSync(p)) { diag.push(`missing-module:${mod}`); continue; }
  try { vm.runInContext(fs.readFileSync(p, 'utf-8'), context, { timeout: TIMEOUT }); diag.push(`loaded:${mod}`); }
  catch (e) { diag.push(`module-threw:${mod}:${e && e.name}`); }
}

// --- DOM boundary: containers + wire capture ------------------------------
vm.runInContext(String.raw`
(function () {
  'use strict';
  const doc = globalThis.document;
  if (!doc) { globalThis.__gt3Log.push('no-document'); return; }
  const tagOf = (n) => (n && n.tagName ? String(n.tagName).toLowerCase() : '');
  // minimal but real event API: the SDK feature-detects addEventListener and
  // then calls it on freshly created elements
  function installEventApi(node) {
    if (!node.__ev) node.__ev = {};
    if (typeof node.addEventListener !== 'function') {
      node.addEventListener = function (type, fn) {
        (this.__ev[type] = this.__ev[type] || []).push(fn);
        try {
          const list = (globalThis.__gt3Bindings = globalThis.__gt3Bindings || []);
          if (list.length < 60) list.push({ tag: String(this.tagName || '?'), cls: String(this.className || '').slice(0, 40), type: String(type) });
        } catch (_) {}
      };
    }
    if (typeof node.removeEventListener !== 'function') {
      node.removeEventListener = function (type, fn) {
        if (this.__ev[type]) this.__ev[type] = this.__ev[type].filter((f) => f !== fn);
      };
    }
    if (typeof node.dispatchEvent !== 'function') {
      node.dispatchEvent = function (ev) {
        const type = ev && ev.type;
        const seen = new Set();
        let cur = this;
        while (cur && !seen.has(cur)) {
          seen.add(cur);
          const fns = (cur.__ev && cur.__ev[type]) || [];
          for (const fn of fns.slice()) { try { fn.call(cur, ev); } catch (e) { globalThis.__gt3Log.push('listener-threw:' + e.name); } }
          const inline = cur['on' + type];
          if (typeof inline === 'function') { try { inline.call(cur, ev); } catch (e) { globalThis.__gt3Log.push('handler-threw:' + e.name); } }
          cur = cur.parentNode || null;
        }
        // real events reach document and window after bubbling through ancestors
        for (const top of [globalThis.document, globalThis]) {
          if (!top || seen.has(top)) continue;
          seen.add(top);
          const fns = (top.__ev && top.__ev[type]) || [];
          for (const fn of fns.slice()) { try { fn.call(top, ev); } catch (e) { globalThis.__gt3Log.push('doc-listener-threw:' + e.name); } }
          const inline = top['on' + type];
          if (typeof inline === 'function') { try { inline.call(top, ev); } catch (_) {} }
        }
        return true;
      };
    }
    return node;
  }
  globalThis.__gt3InstallEventApi = installEventApi;
  // force the event API where dom/document.js exposes a non-writable stub
  function forceEventApi(target, label) {
    if (!target) return;
    try { installEventApi(target); } catch (_) {}
    for (const key of ['addEventListener', 'removeEventListener', 'dispatchEvent']) {
      try {
        if (typeof target[key] !== 'function') {
          Object.defineProperty(target, key, {
            configurable: true, writable: true,
            value: installEventApi({ __ev: {} })[key],
          });
          globalThis.__gt3Log.push('forced:' + label + '.' + key);
        }
      } catch (e) { globalThis.__gt3Log.push('force-failed:' + label + '.' + key + ':' + e.name); }
    }
  }
  globalThis.__gt3ForceEventApi = forceEventApi;
  function makeContainer(tag) {
    const c = {
      tagName: tag.toUpperCase(), nodeName: tag.toUpperCase(), nodeType: 1,
      children: [], childNodes: [], style: {}, dataset: {}, attributes: {},
      appendChild(n) { this.children.push(n); this.childNodes.push(n); if (n) n.parentNode = this; return n; },
      insertBefore(n) { this.children.unshift(n); this.childNodes.unshift(n); return n; },
      removeChild(n) { const i = this.children.indexOf(n); if (i >= 0) this.children.splice(i, 1); return n; },
      remove() {}, setAttribute() {}, getAttribute() { return null; },
      getElementsByTagName() { return []; }, querySelector() { return null; },
      getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 }; },
    };
    return installEventApi(c);
  }
  const head = doc.head || makeContainer('head');
  const body = doc.body || makeContainer('body');
  const html = makeContainer('html');
  try { if (!doc.head) Object.defineProperty(doc, 'head', { configurable: true, get: () => head }); } catch (_) {}
  try { if (!doc.body) Object.defineProperty(doc, 'body', { configurable: true, get: () => body }); } catch (_) {}
  globalThis.__gt3Containers = { head, body, html };
  // The product's IE check is literally a CSS-transition feature probe on
  // documentElement.style (any vendor prefix); a plain fake style object fails
  // all four, so the widget was built in its legacy geetest_ie branch. Give
  // every style a realistic CSSStyleDeclaration surface.
  for (const [target, label] of [[doc, 'document'], [globalThis, 'window'], [head, 'head'], [body, 'body'], [html, 'html']]) {
    forceEventApi(target, label);
  }
  const CSS_PROPS = ['transition', 'webkitTransition', 'mozTransition', 'msTransition', 'transform',
    'webkitTransform', 'animation', 'webkitAnimation', 'flex', 'webkitFlex', 'msFlex', 'grid',
    'boxShadow', 'opacity', 'filter', 'webkitFilter', 'backdropFilter', 'touchAction',
    'willChange', 'userSelect', 'webkitUserSelect', 'pointerEvents'];
  const styleProto = {};
  for (const p of CSS_PROPS) styleProto[p] = '';
  globalThis.__gt3StyleProto = styleProto;
  const patchStyle = (el) => {
    if (!el || !el.style) return el;
    try { if (Object.getPrototypeOf(el.style) !== styleProto) Object.setPrototypeOf(el.style, styleProto); } catch (_) {}
    for (const p of CSS_PROPS) { if (!(p in el.style)) { try { el.style[p] = ''; } catch (_) {} } }
    return el;
  };
  globalThis.__gt3PatchStyle = patchStyle;
  for (const node of [doc.documentElement, head, body, html]) patchStyle(node);
  // document.all is the classic IE tell: with it present the geetest product takes
  // its legacy branch (geetest_ie widget, no click listeners, different w shape)
  try {
    if ('all' in doc) Object.defineProperty(doc, 'all', { configurable: true, get: () => undefined });
  } catch (_) {}
  try { if (doc.documentMode !== undefined) Object.defineProperty(doc, 'documentMode', { configurable: true, get: () => undefined }); } catch (_) {}
  if (typeof globalThis.Event !== 'function') {
    globalThis.Event = function Event(type, init) { return Object.assign({ type: String(type) }, init || {}); };
  }
  if (typeof globalThis.MouseEvent !== 'function') {
    globalThis.MouseEvent = function MouseEvent(type, init) { return Object.assign({ type: String(type), bubbles: true, cancelable: true }, init || {}); };
  }
  if (typeof globalThis.requestAnimationFrame !== 'function') {
    globalThis.requestAnimationFrame = function (fn) { return setTimeout(function () { fn(Date.now()); }, 16); };
    globalThis.cancelAnimationFrame = function (id) { clearTimeout(id); };
  }

  const pending = [];
  globalThis.__gt3Pending = pending;

  // capture every script/img src, and never actually load it
  const origCreate = doc.createElement.bind(doc);
  doc.createElement = function (tag) {
    const el = origCreate(tag);
    const t = String(tag).toLowerCase();
    if (t === 'script' || t === 'img' || t === 'link') {
      const prop = t === 'link' ? 'href' : 'src';
      let src = '';
      try {
        Object.defineProperty(el, prop, {
          configurable: true,
          get() { return src; },
          set(v) { src = String(v); pending.push({ el, kind: t, url: src }); },
        });
      } catch (_) {}
    }
    if (!el.appendChild) el.appendChild = function (n) { if (n) n.parentNode = el; return n; };
    if (!el.getBoundingClientRect) el.getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 });
    installEventApi(el);
    try { patchStyle(el); } catch (_) {}
    try { (globalThis.__gt3Elements = globalThis.__gt3Elements || []).push(el); } catch (_) {}
    return el;
  };
  // keep script/img nodes in the container tree: an SDK that walks childNodes to
  // find its own script must still see it. Nothing is actually fetched.
  for (const c of [head, body]) {
    if (c && typeof c.appendChild === 'function') {
      const orig = c.appendChild.bind(c);
      c.appendChild = function (n) { return orig(n); };
    }
  }
  // The loader resolves its append target as getElementsByTagName('head')[0];
  // the stock DOM module returns an empty list, so force a real container.
  const origGetByTag = typeof doc.getElementsByTagName === 'function' ? doc.getElementsByTagName.bind(doc) : null;
  doc.getElementsByTagName = function (tag) {
    const name = String(tag).toLowerCase();
    if (name === 'head') return [head];
    if (name === 'body') return [body];
    if (name === 'html') return [html];
    const r = origGetByTag ? origGetByTag(tag) : [];
    return r && r.length ? r : [];
  };
  try { if (!doc.documentElement) Object.defineProperty(doc, 'documentElement', { configurable: true, get: () => html }); } catch (_) {}
  if (typeof doc.getElementById !== 'function') doc.getElementById = () => null;
  if (typeof doc.querySelector !== 'function') doc.querySelector = () => null;
})();
`, context, { timeout: TIMEOUT });

const loadLog = [];
let assetOk = false;
for (const f of assetFiles) {
  try {
    let code = fs.readFileSync(f, 'utf-8');
    // the extracted loader is a module fragment: bind its outer `o` helper in a
    // private closure so the product asset keeps its own `o` table
    if (path.basename(f).includes('loader')) code = `(function (o) {\n${code}\n})(globalThis.__gt3Typeof__);`;
    vm.runInContext(code, context, { timeout: TIMEOUT, filename: path.basename(f), displayErrors: true });
    assetOk = true; loadLog.push(`ok:${path.basename(f)}`);
  } catch (e) {
    diag.push(`asset-threw:${path.basename(f)}:${e && e.name}`);
    loadLog.push(`threw:${path.basename(f)}`);
  }
}

// --- optional string-table decode (settles what a patched call site needs) --
if (opt.decode) {
  const idx = opt.decode.split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n));
  try {
    const decoded = JSON.parse(vm.runInContext(`JSON.stringify((function () {
      const out = {};
      const decoders = [];
      try { if (globalThis.Vwtrj && typeof globalThis.Vwtrj.$_CV === 'function') decoders.push(['Vwtrj.$_CV', globalThis.Vwtrj.$_CV.bind(globalThis.Vwtrj)]); } catch (_) {}
      for (const [name, fn] of decoders) {
        for (const i of ${JSON.stringify(idx)}) {
          try { out[name + '(' + i + ')'] = String(fn(i)); } catch (e) { out[name + '(' + i + ')'] = 'ERR:' + e.name; }
        }
      }
      return out;
    })())`, context, { timeout: TIMEOUT }));
    console.log(JSON.stringify({ type: 'decode', decoded }, null, 2));
  } catch (e) {
    console.log(JSON.stringify({ type: 'decode', error: String(e && e.message).slice(0, 200) }));
  }
}

// --- instantiate ----------------------------------------------------------
if (assetOk && opt.gt && opt.challenge) {
  const cfg = {
    gt: opt.gt, challenge: opt.challenge, offline: false, new_captcha: true,
    product: opt.product, lang: opt.lang, https: true,
  };
  try {
    const driverCode = opt.driver === 'loader'
      ? String.raw`
      (function () {
        'use strict';
        try {
          if (typeof globalThis.initGeetest !== 'function') { globalThis.__gt3Errors.push('no-initGeetest-global'); return; }
          globalThis.initGeetest(__CFG__, function (inst) {
            globalThis.__gt3Log.push('initGeetest-callback');
            globalThis.__gt3Instance = inst;
            // bilibili's own wrapper calls verify() on ready; do it from the
            // driver instead, so a throw inside verify() cannot surface as the
            // product's "user callback threw" (604) report
            if (typeof inst.onReady === 'function') inst.onReady(function () { globalThis.__gt3Log.push('onReady'); });
            if (typeof inst.onError === 'function') inst.onError(function (e) {
              let detail;
              try { detail = JSON.stringify(e); } catch (_) { detail = String(e); }
              globalThis.__gt3Errors.push('onError:' + (e && (e.code || e.msg)) + '|detail:' + String(detail).slice(0, 400));
            });
            if (typeof inst.onClose === 'function') inst.onClose(function () { globalThis.__gt3Log.push('onClose'); });
            if (typeof inst.appendTo === 'function') {
              try { inst.appendTo(globalThis.document.body); globalThis.__gt3Log.push('appendTo'); } catch (e) { globalThis.__gt3Log.push('appendTo-threw:' + e.name); }
            }
          });
        } catch (e) {
          globalThis.__gt3Errors.push('init:' + (e && e.name) + ':' + String(e && e.message).slice(0, 180));
        }
      })();
      `
      : String.raw`
      (function () {
        'use strict';
        try {
          if (typeof globalThis.Geetest !== 'function') { globalThis.__gt3Errors.push('no-Geetest-global'); return; }
          const inst = new globalThis.Geetest(__CFG__);
          globalThis.__gt3Instance = inst;
          if (typeof inst.onReady === 'function') inst.onReady(function () { globalThis.__gt3Log.push('onReady'); });
          if (typeof inst.onError === 'function') inst.onError(function (e) { globalThis.__gt3Errors.push('onError:' + (e && (e.code || e.msg))); });
          if (typeof inst.onClose === 'function') inst.onClose(function () { globalThis.__gt3Log.push('onClose'); });
          if (typeof inst.appendTo === 'function') {
            try { inst.appendTo(globalThis.document.body); globalThis.__gt3Log.push('appendTo'); } catch (e) { globalThis.__gt3Log.push('appendTo-threw:' + e.name); }
          }
        } catch (e) {
          globalThis.__gt3Errors.push('construct:' + (e && e.name) + ':' + String(e && e.message).slice(0, 180)
            + '|stack:' + String((e && e.stack) || '').slice(0, 400));
        }
      })();
      `;
    vm.runInContext(driverCode.replace('__CFG__', JSON.stringify(cfg)), context, { timeout: TIMEOUT });
  } catch (e) {
    diag.push(`drive-threw:${e && e.name}`);
  }
}

// --- JSONL driving loop ---------------------------------------------------
const out = (obj) => process.stdout.write(JSON.stringify(obj) + '\n');
const stdinLines = [];
let stdinBuf = '';
let waiter = null;
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  stdinBuf += chunk;
  let idx;
  while ((idx = stdinBuf.indexOf('\n')) >= 0) {
    const line = stdinBuf.slice(0, idx); stdinBuf = stdinBuf.slice(idx + 1);
    if (!line.trim()) continue;
    try { stdinLines.push(JSON.parse(line)); } catch (_) {}
    if (waiter) { const w = waiter; waiter = null; w(); }
  }
});
function nextLine() {
  if (stdinLines.length) return Promise.resolve(stdinLines.shift());
  return new Promise((resolve) => {
    waiter = () => resolve(stdinLines.shift());
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function snapshotPending() {
  const list = JSON.parse(vm.runInContext('JSON.stringify(globalThis.__gt3Pending.map(p => ({kind: p.kind, url: p.url})))', context));
  return list;
}

async function main() {
  out({ type: 'ready', assets: assetFiles.map((f) => path.basename(f)), loadLog, diag, gt: opt.gt, challenge: opt.challenge });

  const seen = new Set();
  let sent = 0;
  let probed = false;
  let clicked = false;
  let commitDone = false;
  let clickIdx = 0;
  let verifyDone = false;
  let instDumped = false;
  let valuesDumped = false;
  let awaited = false;
  let foundMethod = false;
  let widgetReported = false;
  let widgetDumped = false;
  let fmtIdx = 0;
  let submitPoints = null;
  let submitFormat = null;   // set when the driver builds the answer itself (word mode)
  const submitFormats = (opt.answerFormats || opt.answerFormat || 'raw').split(',').map((s) => s.trim()).filter(Boolean);
  let moveIdx = 0;
  let movePoints = null;   // built lazily: mousePath is defined further down
  const clickPoints = opt.synthClicks
    ? opt.synthClicks.split(';').map((s) => s.split(',').map((n) => parseInt(n, 10)))
    : [];
  let probeNames = null;
  let probeIdx = 0;
  const probeObjLiteral = () => (opt.probeTarget === 'inst' ? 'globalThis.__gt3Instance' : 'globalThis.__gt3Core');
  const collectMethodNames = () => JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const core = ${probeObjLiteral()};
    if (!core) return [];
    const set = new Set();
    let o = core;
    while (o && o !== Object.prototype) {
      for (const k of Object.getOwnPropertyNames(o)) set.add(k);
      o = Object.getPrototypeOf(o);
    }
    return Array.from(set);
  })())`, context));
  // Real Chrome only needs the single image layer to receive the click; spraying
  // every element confuses the product. Dispatch only on elements that actually
  // registered listeners, and let the caller space them out in wall-clock time.
  const dispatchPoint = (x, y) => JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const xs = ${x}, ys = ${y};
    const els = globalThis.__gt3Elements || [];
    let targets = els.filter((el) => el && el.__ev && (el.__ev.mousedown || el.__ev.click || el.__ev.touchstart));
    if (!targets.length) targets = els.slice(-2);
    let fired = 0;
    const log = [];
    for (const el of targets) {
      const base = { clientX: xs, clientY: ys, pageX: xs, pageY: ys, button: 0, bubbles: true, cancelable: true, target: el };
      for (const type of ['mousemove', 'mousedown', 'mouseup', 'click']) {
        try { el.dispatchEvent(Object.assign({ type }, base)); fired++; } catch (e) { log.push(type + ':' + (e && e.name)); }
      }
    }
    return { fired, targets: targets.length, log };
  })())`, context));

  const listenerReport = () => JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const els = globalThis.__gt3Elements || [];
    let n = 0;
    const rows = [];
    els.forEach((el, i) => {
      const ev = el && el.__ev;
      const hasEv = !!(ev && (ev.mousedown || ev.click || ev.touchstart || ev.mouseup));
      if (hasEv) n++;
      const handlers = ['onclick', 'onmousedown', 'onmouseup', 'onmousemove', 'ontouchstart', 'onload'].filter((k) => typeof el[k] === 'function');
      const bg = el.style && el.style.backgroundImage ? String(el.style.backgroundImage).slice(0, 55) : '';
      const src = el.src ? String(el.src).slice(0, 55) : '';
      if (hasEv || handlers.length || bg || src) rows.push({ i, tag: el.tagName, ev: hasEv, handlers, bg, src });
    });
    return {
      elements: els.length, withListeners: n, candidates: rows.slice(-20),
      bindings: (globalThis.__gt3Bindings || []).slice(0, 25),
      docListeners: (function () { const out = {}; for (const k of ['document', 'window']) { const t = k === 'document' ? globalThis.document : globalThis; out[k] = t && t.__ev ? Object.keys(t.__ev) : []; } return out; })(),
      tags: (function () { const t = {}; els.forEach((e) => { t[e.tagName] = (t[e.tagName] || 0) + 1; }); return t; })(),
      divs: els.filter((e) => e.tagName === 'DIV').slice(0, 25).map((e, i) => ({
        i, cls: String(e.className || '').slice(0, 60),
        style: e.style ? Object.keys(e.style).slice(0, 6).join(',') : '',
        kids: e.children ? e.children.length : -1,
      })),
    };
  })())`, context));

  // the product submits on the confirm control, not on the picture
  const dispatchCommit = () => JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const els = globalThis.__gt3Elements || [];
    const clickable = els.filter((el) => el && el.__ev && el.__ev.click);
    let fired = 0;
    for (const el of clickable) {
      const base = { clientX: 1, clientY: 1, pageX: 1, pageY: 1, button: 0, bubbles: true, cancelable: true, target: el };
      for (const type of ['mousedown', 'mouseup', 'click']) {
        try { el.dispatchEvent(Object.assign({ type }, base)); fired++; } catch (_) {}
      }
    }
    return { fired, candidates: clickable.length };
  })())`, context));
  // The product only binds window-level behaviour listeners (mousemove/scroll/
  // focus/blur/...). Feed it a realistic pointer path so the tracked behaviour is
  // not empty -- the real browser's pre-radar w is far longer than an idle one.
  const dispatchMove = (x, y) => JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const ev = { type: 'mousemove', clientX: ${x}, clientY: ${y}, pageX: ${x}, pageY: ${y}, bubbles: false, cancelable: true };
    let fired = 0;
    for (const t of [globalThis, globalThis.document]) {
      if (!t) continue;
      const fns = (t.__ev && t.__ev.mousemove) || [];
      for (const fn of fns.slice()) { try { fn.call(t, ev); fired++; } catch (e) { globalThis.__gt3Log.push('move-threw:' + e.name); } }
      if (typeof t.onmousemove === 'function') { try { t.onmousemove(ev); fired++; } catch (_) {} }
    }
    return { fired, listeners: ((globalThis.__ev && globalThis.__ev.mousemove) || []).length + ((globalThis.document && globalThis.document.__ev && globalThis.document.__ev.mousemove) || []).length };
  })())`, context));

  const mousePath = (n, w0, h0) => {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const t = i / Math.max(1, n - 1);
      pts.push([Math.round(40 + t * (w0 - 120) + Math.sin(t * 7) * 12), Math.round(60 + t * (h0 - 160) + Math.cos(t * 5) * 10)]);
    }
    return pts;
  };

  const probeArgLiteral = () => {
    const pts = clickPoints.length ? clickPoints : [[244, 49], [212, 212]];
    if (!opt.probeArgs || opt.probeArgs === 'none') return 'undefined';
    if (opt.probeArgs === 'array') return JSON.stringify(pts);
    if (opt.probeArgs === 'string') return JSON.stringify(pts.map((p) => p.join(',')).join(';'));
    if (opt.probeArgs === 'numbers') return pts.length ? String(pts[0][0]) : '0';
    return JSON.stringify({
      userresponse: pts.map((p) => p.join(',')).join(','),
      passtime: 3200, imgload: 120, aa: '', rp: '', ep: {},
      geetest_challenge: '', geetest_validate: '', geetest_seccode: '',
    });
  };
  const callOne = (name) => vm.runInContext(`JSON.stringify((function () {
    const core = ${probeObjLiteral()};
    if (!core) return 'no-target';
    const fn = core[${JSON.stringify(name)}];
    if (typeof fn !== 'function') return 'not-a-function';
    try { const r = fn.call(core, ${probeArgLiteral()}); return 'ok:' + typeof r; }
    catch (e) { return 'threw:' + (e && e.name) + ':' + String(e && e.message).slice(0, 90); }
  })())`, context);
  const dumpInstance = () => {
    const dump = JSON.parse(vm.runInContext(`JSON.stringify((function () {
      const out = { inst: null, children: [] };
      const inst = globalThis.__gt3Instance;
      if (!inst) return out;
      const dec = (s) => String(s).replace(/\\\\u([0-9a-fA-F]{4})/g, (m, h) => String.fromCharCode(parseInt(h, 16)));
      const methodsOf = (obj) => {
        const methods = [];
        let p = Object.getPrototypeOf(obj);
        while (p && p !== Object.prototype) {
          for (const k of Object.getOwnPropertyNames(p)) methods.push(dec(k));
          p = Object.getPrototypeOf(p);
        }
        return methods;
      };
      out.inst = { ownKeys: Object.getOwnPropertyNames(inst).map(dec).slice(0, 40), methods: methodsOf(inst).slice(0, 60) };
      for (const k of Object.getOwnPropertyNames(inst)) {
        let v;
        try { v = inst[k]; } catch (_) { continue; }
        if (v && typeof v === 'object') {
          out.children.push({ key: dec(k), methods: methodsOf(v).slice(0, 60), ownKeys: Object.getOwnPropertyNames(v).map(dec).slice(0, 30) });
        }
      }
      return out;
    })())`, context));
    out({ type: 'inst-dump', dump });
  };

  const dumpValues = () => {
    const dump = JSON.parse(vm.runInContext(`JSON.stringify((function () {
      const dec = (s) => String(s).replace(/\\\\u([0-9a-fA-F]{4})/g, (m, h) => String.fromCharCode(parseInt(h, 16)));
      const brief = (v) => {
        if (v === null) return 'null';
        const t = typeof v;
        if (t === 'string') return 'str[' + v.length + ']' + (v.length < 40 ? '=' + v : '');
        if (t === 'number' || t === 'boolean' || t === 'undefined') return String(v);
        if (Array.isArray(v)) return 'arr[' + v.length + ']' + (v.length && v.length < 8 ? '=' + JSON.stringify(v).slice(0, 120) : '');
        if (t === 'object') return 'obj{' + Object.getOwnPropertyNames(v).slice(0, 8).map(dec).join(',') + '}';
        return t;
      };
      const out = { inst: {}, core: {} };
      for (const target of ['inst', 'core']) {
        const obj = target === 'inst' ? globalThis.__gt3Instance : globalThis.__gt3Core;
        if (!obj) { out[target] = 'absent'; continue; }
        for (const k of Object.getOwnPropertyNames(obj)) {
          let v;
          try { v = obj[k]; } catch (_) { continue; }
          out[target][dec(k)] = brief(v);
        }
      }
      return out;
    })())`, context));
    out({ type: 'values', dump });
  };

  const callAwait = (name) => vm.runInContext(`(async function () {
    const inst = globalThis.__gt3Instance;
    if (!inst || typeof inst[${JSON.stringify(name)}] !== 'function') return 'not-a-function';
    try {
      const r = inst[${JSON.stringify(name)}]([[244, 49], [212, 212]], 3260);
      if (r && typeof r.then === 'function') {
        const v = await r;
        let s; try { s = JSON.stringify(v); } catch (_) { s = String(v); }
        return 'resolved:' + String(s).slice(0, 300);
      }
      let s; try { s = JSON.stringify(r); } catch (_) { s = String(r); }
      return 'sync:' + String(s).slice(0, 300);
    } catch (e) { return 'threw:' + (e && e.name) + ':' + String(e && e.message).slice(0, 160); }
  })()`, context);

  const findMethod = (name) => JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const want = ${JSON.stringify(name)};
    const seen = new Set();
    const out = [];
    const walk = (obj, path, depth) => {
      if (!obj || depth > 4 || seen.has(obj)) return;
      seen.add(obj);
      // prototype chain first: product methods live on prototypes
      let proto = Object.getPrototypeOf(obj);
      let level = 0;
      while (proto && proto !== Object.prototype && level < 4) {
        seen.add(proto);
        let pkeys = [];
        try { pkeys = Object.getOwnPropertyNames(proto); } catch (_) { break; }
        if (pkeys.indexOf(want) >= 0) out.push(path + '.<proto' + level + '>[' + want + ']');
        proto = Object.getPrototypeOf(proto);
        level += 1;
      }
      let keys = [];
      try { keys = Object.getOwnPropertyNames(obj); } catch (_) { return; }
      for (const k of keys) {
        let v;
        try { v = obj[k]; } catch (_) { continue; }
        if (typeof v === 'function') {
          if (k === want) out.push(path + '[' + k + ']');
        } else if (v && typeof v === 'object') {
          if (seen.has(v)) continue;
          let n = 0;
          try { n = Object.getOwnPropertyNames(v).length; } catch (_) {}
          if (depth >= 1 && n > 200) continue;
          walk(v, path + '[' + k + ']', depth + 1);
        }
      }
    };
    const roots = [['inst', globalThis.__gt3Instance], ['core', globalThis.__gt3Core], ['window', globalThis]];
    for (const [label, r] of roots) if (r) walk(r, label, 0);
    return out.slice(0, 25);
  })())`, context));

  const callWidget = (name) => vm.runInContext(`(async function () {
    const w = globalThis.__gt3Widget;
    if (!w) return 'no-widget';
    if (typeof w[${JSON.stringify(name)}] !== 'function') {
      const keys = Object.getOwnPropertyNames(w).slice(0, 30);
      let proto = Object.getPrototypeOf(w), pkeys = [];
      while (proto && proto !== Object.prototype) { pkeys = pkeys.concat(Object.getOwnPropertyNames(proto).slice(0, 40)); proto = Object.getPrototypeOf(proto); }
      return 'not-a-function; own=' + keys.join(',') + ' proto=' + pkeys.slice(0, 40).join(',');
    }
    try {
      const r = w[${JSON.stringify(name)}]([[244, 49], [212, 212]], 3260);
      if (r && typeof r.then === 'function') { const v = await r; let s; try { s = JSON.stringify(v); } catch (_) { s = String(v); } return 'resolved:' + String(s).slice(0, 300); }
      let s; try { s = JSON.stringify(r); } catch (_) { s = String(r); }
      return 'sync:' + String(s).slice(0, 300);
    } catch (e) { return 'threw:' + (e && e.name) + ':' + String(e && e.message).slice(0, 160); }
  })()`, context);

  const dumpWidget = () => JSON.parse(vm.runInContext(`JSON.stringify((function () {
    const w = globalThis.__gt3Widget;
    if (!w) return { error: 'no-widget' };
    const methodsOf = (o) => {
      const out = [];
      let p = Object.getPrototypeOf(o), lvl = 0;
      while (p && p !== Object.prototype && lvl < 3) {
        for (const k of Object.getOwnPropertyNames(p)) out.push(k);
        p = Object.getPrototypeOf(p); lvl += 1;
      }
      return out;
    };
    const tracker = w['$_CBIT'];
    let answer = null;
    try {
      answer = tracker && typeof tracker['$_FAA'] === 'function'
        ? String(JSON.stringify(tracker['$_FAA']())).slice(0, 500) : 'n/a';
    } catch (e) { answer = 'threw:' + (e && e.name); }
    return {
      widgetKeys: Object.getOwnPropertyNames(w).slice(0, 60),
      widgetMethods: methodsOf(w).slice(0, 60),
      trackerType: typeof tracker,
      trackerKeys: tracker ? Object.getOwnPropertyNames(tracker).slice(0, 40) : [],
      trackerMethods: tracker ? methodsOf(tracker).slice(0, 60) : [],
      currentAnswer: answer,
      startedAt: w['$_CBDL'] === undefined ? 'absent' : typeof w['$_CBDL'],
    };
  })())`, context));

  const callWidgetSubmit = (name, points, format) => {
    const answer = (() => {
      if (format === 'str') return points;   // pre-built answer string (word mode)
      if (format === 'flat') return points.map((p) => p.join(',')).join(',');
      if (format === 'semi') return points.map((p) => p.join(',')).join(';');
      if (format === 'strarray') return points.map((p) => p.join(','));
      if (format === 'objarray') return points.map((p) => ({ x: p[0], y: p[1] }));
      return points;                       // raw nested array (default)
    })();
    return vm.runInContext(`(async function () {
      const w = globalThis.__gt3Widget;
      if (!w) return 'no-widget';
      const fn = w[${JSON.stringify(name)}];
      if (typeof fn !== 'function') return 'not-a-function';
      const answer = ${JSON.stringify(answer)};
      const started = typeof w['$_CBDL'] === 'number' ? w['$_CBDL'] : Date.now() - 3200;
      const passtime = Math.max(800, Date.now() - started);
      try {
        const r = fn.call(w, answer, passtime);
        if (r && typeof r.then === 'function') { const v = await r; let s; try { s = JSON.stringify(v); } catch (_) { s = String(v); } return 'resolved:' + String(s).slice(0, 200); }
        let s; try { s = JSON.stringify(r); } catch (_) { s = String(r); }
        return 'sync:' + String(s).slice(0, 200) + '|answer=' + JSON.stringify(answer).slice(0, 120) + '|passtime=' + passtime
          + '|PLAIN=' + (function () { try { return JSON.stringify(globalThis.__gt3Plain).slice(0, 2000); } catch (e) { return 'unserializable'; } })();
      } catch (e) { return 'threw:' + (e && e.name) + ':' + String(e && e.message).slice(0, 160); }
    })()`, context);
  };

  const runProbe = () => {
    const names = opt.probeCore.split(',');
    const result = JSON.parse(vm.runInContext(`JSON.stringify((function () {
      const out = [];
      const targets = [['inst', globalThis.__gt3Instance], ['core', globalThis.__gt3Core]];
      for (const name of ${JSON.stringify(names)}) {
        for (const pair of targets) {
          const label = pair[0], obj = pair[1];
          if (!obj) { out.push(label + ':absent'); continue; }
          if (typeof obj[name] !== 'function') { out.push(label + '.' + name + ':not-a-function'); continue; }
          try {
            const r = obj[name]();
            out.push(label + '.' + name + '():ok:' + typeof r);
          } catch (e) {
            out.push(label + '.' + name + '():threw:' + (e && e.name) + ':' + String(e && e.message).slice(0, 100));
          }
        }
      }
      return out;
    })())`, context));
    for (const line of result) out({ type: 'probe', line });
  };

  for (let round = 0; round < opt.maxRounds; round++) {
    try { vm.runInContext(`__drainTimers__(${opt.drain}, ${opt.timerCap})`, context, { timeout: TIMEOUT }); } catch (_) {}

    const pending = snapshotPending();
    const fresh = pending.filter((p) => p.url && !seen.has(p.url));
    // XHR requests are captured separately (they have no src)
    const xhrs = JSON.parse(vm.runInContext('JSON.stringify(globalThis.__xhrPending__.map((x,i) => ({ idx: i, method: x._m, url: x._u, bodyLen: x._body ? String(x._body).length : 0, done: x.readyState === 4 })))', context));
    const freshXhr = xhrs.filter((x) => !x.done && x.url && !seen.has('xhr:' + x.url));

    if (!fresh.length && !freshXhr.length) {
      if (opt.verifyFirst && !verifyDone) {
        verifyDone = true;
        let res;
        try {
          res = JSON.parse(vm.runInContext(`JSON.stringify((function () {
            const inst = globalThis.__gt3Instance;
            if (!inst || typeof inst.verify !== 'function') return 'no-verify';
            try { const r = inst.verify(); return 'ok:' + typeof r; } catch (e) { return 'threw:' + (e && e.name) + ':' + String(e && e.message).slice(0, 120); }
          })())`, context));
        } catch (e) { res = { error: String(e && e.message).slice(0, 120) }; }
        out({ type: 'verify', result: res });
        try { vm.runInContext(`__drainTimers__(200, ${opt.timerCap})`, context, { timeout: TIMEOUT }); } catch (_) {}
        await sleep(400);
        continue;
      }
      if (opt.synthMoves && moveIdx < (movePoints || (movePoints = mousePath(parseInt(opt.synthMoves, 10) || 24, 1200, 800))).length) {
        if (moveIdx === 0) out({ type: 'moves-plan', count: movePoints.length });
        const mv = movePoints[moveIdx++];
        let res;
        try { res = dispatchMove(mv[0], mv[1]); } catch (e) { res = { error: String(e && e.message).slice(0, 100) }; }
        if (moveIdx === 1 || moveIdx === movePoints.length) out({ type: 'move', index: moveIdx, point: mv, result: res });
        await sleep(25);
        continue;
      }
      if (opt.probeAllCore) {
        if (probeNames === null) {
          probeNames = collectMethodNames();
          out({ type: 'probe-plan', count: probeNames.length, names: probeNames });
        }
        if (probeIdx < probeNames.length) {
          const name = probeNames[probeIdx++];
          const before = snapshotPending().length;
          let line;
          try { line = callOne(name); } catch (e) { line = 'call-threw:' + String(e && e.message).slice(0, 90); }
          try { vm.runInContext(__drainTimers__(200, ), context, { timeout: TIMEOUT }); } catch (_) {}
          const gained = snapshotPending().length - before;
          out({ type: 'probe', name, line, newPending: gained });
          if (gained > 0) {
            out({ type: 'probe-trigger', name, line, note: 'stopping sweep: this method started a request' });
            probeIdx = probeNames.length;   // stop sweeping, resume normal driving
          }
          continue;
        }
      }
      if (opt.dumpWidget && !widgetDumped) {
        widgetDumped = true;
        try { out({ type: 'widget-dump', dump: dumpWidget() }); } catch (e) { out({ type: 'error', note: 'widget-dump:' + String(e && e.message).slice(0, 100) }); }
        continue;
      }
      if (opt.callWidget && fmtIdx < submitFormats.length) {
        if (fmtIdx === 0) {
          out({ type: 'need-points' });
          const reply = await nextLine();
          if (reply && reply.type === 'points' && reply.points
              && (typeof reply.points === 'string' || reply.points.length)) {
            submitPoints = reply.points;
            if (typeof reply.points === 'string') submitFormat = reply.format || 'str';
          } else {
            submitPoints = clickPoints.length ? clickPoints : [[244, 49], [212, 212]];
          }
        }
        const fmt = submitFormat || submitFormats[fmtIdx++];
        let res;
        try { res = await callWidgetSubmit(opt.callWidget, submitPoints, fmt); }
        catch (e) { res = 'threw:' + String(e && e.message).slice(0, 120); }
        out({ type: 'call-widget', name: opt.callWidget, points: submitPoints, format: fmt, result: String(res).slice(0, 2000) });
        try { vm.runInContext(`__drainTimers__(200, ${opt.timerCap})`, context, { timeout: TIMEOUT }); } catch (_) {}
        await sleep(1200);
        continue;
      }
      if (opt.callWidget) {
        if (!widgetReported) {
          widgetReported = true;
          let res;
          try { res = await callWidget(opt.callWidget); } catch (e) { res = 'threw:' + String(e && e.message).slice(0, 120); }
          out({ type: 'call-widget', name: opt.callWidget, result: String(res).slice(0, 600) });
          try { vm.runInContext(`__drainTimers__(200, ${opt.timerCap})`, context, { timeout: TIMEOUT }); } catch (_) {}
          await sleep(600);
          continue;
        }
      }
      if (opt.findMethod && !foundMethod) {
        foundMethod = true;
        let paths;
        try { paths = findMethod(opt.findMethod); } catch (e) { paths = ['threw:' + String(e && e.message).slice(0, 100)]; }
        out({ type: 'find-method', name: opt.findMethod, paths });
        continue;
      }
      if (opt.callAwait && !awaited) {
        awaited = true;
        for (const name of opt.callAwait.split(',')) {
          let res;
          try { res = await callAwait(name); } catch (e) { res = 'await-threw:' + String(e && e.message).slice(0, 100); }
          out({ type: 'call-await', name, result: String(res).slice(0, 400) });
          try { vm.runInContext(`__drainTimers__(200, ${opt.timerCap})`, context, { timeout: TIMEOUT }); } catch (_) {}
        }
        continue;
      }
      if (opt.dumpValues && !valuesDumped) {
        valuesDumped = true;
        try { dumpValues(); } catch (e) { out({ type: 'error', note: 'values-failed:' + String(e && e.message).slice(0, 100) }); }
        continue;
      }
      if (opt.dumpInst && !instDumped) {
        instDumped = true;
        try { dumpInstance(); } catch (e) { out({ type: 'error', note: 'inst-dump-failed:' + String(e && e.message).slice(0, 100) }); }
        continue;
      }
      if (opt.probeCore && !probed) {
        probed = true;
        runProbe();
        try { vm.runInContext(__drainTimers__(200, ), context, { timeout: TIMEOUT }); } catch (_) {}
        continue;
      }
      if (opt.synthClicks && clickIdx < clickPoints.length) {
        if (clickIdx === 0) out({ type: 'listeners', ...listenerReport() });
        const pt = clickPoints[clickIdx++];
        let res;
        try { res = dispatchPoint(pt[0], pt[1]); } catch (e) { res = { error: String(e && e.message).slice(0, 120) }; }
        out({ type: 'click', index: clickIdx - 1, point: pt, result: res });
        try { vm.runInContext(__drainTimers__(200, ), context, { timeout: TIMEOUT }); } catch (_) {}
        await sleep(260);                       // human-ish gap between picks
        continue;
      }
      if (opt.synthClicks && !commitDone && clickIdx >= clickPoints.length) {
        commitDone = true;
        let res;
        try { res = dispatchCommit(); } catch (e) { res = { error: String(e && e.message).slice(0, 120) }; }
        out({ type: 'commit', result: res });
        try { vm.runInContext(__drainTimers__(200, ), context, { timeout: TIMEOUT }); } catch (_) {}
        await sleep(500);
        continue;
      }
      break;
    }

    for (const p of fresh) {
      seen.add(p.url);
      const id = ++sent;
      const q = (p.url.split('?')[1] || '');
      const params = {};
      for (const [k, v] of new URLSearchParams(q).entries()) params[k] = v.length > 120 ? `[len=${v.length}]` : v;
      out({ type: 'request', id, kind: p.kind, url: p.url, params });
      const reply = await nextLine();
      if (!reply || reply.type !== 'response') { out({ type: 'error', id, note: 'no-response' }); continue; }
      if (reply.kind === 'noop') continue;
      if (reply.kind === 'link') {
        // stylesheet load: the product appears to wait for CSS before it wires
        // the interactive widget, and real <link> onload is what it listens for
        vm.runInContext(`(function(){
          const entry = globalThis.__gt3Pending.find(x => x.url === ${JSON.stringify(p.url)});
          const el = entry && entry.el;
          if (!el) return;
          try { el.sheet = { cssRules: [], insertRule() {}, deleteRule() {} }; } catch (_) {}
          try { el.readyState = 'complete'; el.complete = true; } catch (_) {}
          try { if (typeof el.dispatchEvent === 'function') el.dispatchEvent({ type: 'load', target: el }); } catch (_) {}
          try { if (typeof el.onload === 'function') el.onload(); } catch (_) {}
          try { if (typeof el.onreadystatechange === 'function') el.onreadystatechange(); } catch (_) {}
        })()`, context, { timeout: TIMEOUT });
        continue;
      }
      if (reply.kind === 'img') {
        // a real image load: the click product needs natural/rendered size and a
        // load event before it will accept clicks on the picture
        vm.runInContext(`(function(){
          const entry = globalThis.__gt3Pending.find(x => x.url === ${JSON.stringify(p.url)});
          const el = entry && entry.el;
          if (!el) return;
          try {
            el.naturalWidth = ${Number(reply.width) || 0};
            el.naturalHeight = ${Number(reply.height) || 0};
            el.width = ${Number(reply.width) || 0};
            el.height = ${Number(reply.height) || 0};
            el.complete = true;
            el.readyState = 'complete';
            if (typeof el.getBoundingClientRect !== 'function' || !el.__rectSet) {
              const w = ${Number(reply.width) || 0}, h = ${Number(reply.height) || 0};
              el.getBoundingClientRect = () => ({ left: 0, top: 0, right: w, bottom: h, width: w, height: h, x: 0, y: 0 });
              el.__rectSet = true;
            }
            if (typeof el.dispatchEvent === 'function') el.dispatchEvent({ type: 'load', target: el });
            if (typeof el.onload === 'function') el.onload();
          } catch (e) { globalThis.__gt3Log.push('img-load-threw:' + (e && e.name)); }
        })()`, context, { timeout: TIMEOUT });
        continue;
      }
      try {
        if (reply.kind === 'js') {          vm.runInContext(String(reply.body), context, { timeout: TIMEOUT, filename: 'remote-asset.js' });
          vm.runInContext(`(function(){
            const entry = globalThis.__gt3Pending.find(p => p.url === ${JSON.stringify(p.url)});
            if (entry && entry.el) {
              const el = entry.el;
              try { if (typeof el.dispatchEvent === 'function') el.dispatchEvent({ type: 'load', target: el }); } catch (_) {}
              try { if (typeof el.onload === 'function') el.onload(); } catch (_) {}
            }
          })()`, context);
        } else {
          const cb = params.callback;
          if (cb) {
            // JSONP: invoke the callback, then satisfy the SDK's load latch.
            // The SDK registers listeners through addEventListener, so the
            // completion signal must go through dispatchEvent, not only onload.
            vm.runInContext(`(function(){
              const url = ${JSON.stringify(p.url)};
              const entry = globalThis.__gt3Pending.find(x => x.url === url);
              const cbName = ${JSON.stringify(cb)};
              const f = globalThis[cbName];
              const diag = { cbName, isFn: typeof f, globals: Object.keys(globalThis).filter(k => k.indexOf('geetest_') === 0).length };
              if (typeof f === 'function') {
                try {
                  const ret = f(${JSON.stringify(reply.body)});
                  diag.ret = typeof ret + ':' + String(ret).slice(0, 60);
                } catch (e) { diag.threw = (e && e.name) + ':' + String(e && e.message).slice(0, 120); }
              }
              if (entry && entry.el) {
                const el = entry.el;
                try { el.readyState = 'complete'; } catch (_) {}
                try { el.complete = true; } catch (_) {}
                try { if (typeof el.dispatchEvent === 'function') el.dispatchEvent({ type: 'load', target: el }); } catch (e) { diag.dispatchThrew = e.name; }
                try { if (typeof el.onload === 'function') el.onload(); } catch (e) { diag.onloadThrew = e.name; }
                try { if (typeof el.onreadystatechange === 'function') el.onreadystatechange(); } catch (_) {}
              }
              try {
                const inst = globalThis.__gt3Instance;
                diag.instKeys = inst ? Object.getOwnPropertyNames(inst).length : -1;
              } catch (_) {}
              globalThis.__gt3Log.push('jsonp-diag:' + JSON.stringify(diag).slice(0, 300));
            })()`, context, { timeout: TIMEOUT });
          }
        }
      } catch (e) {
        out({ type: 'error', id, note: 'apply-response-failed:' + (e && e.name) + ':' + String(e && e.message).slice(0, 140) + '|stack:' + String((e && e.stack) || '').slice(0, 400) });
      }
      // force microtask turns so the SDK's own .then chain is observable here
      try {
        const after = await vm.runInContext(`(async function () {
          for (let i = 0; i < 6; i++) await null;
          return JSON.stringify({
            core: !!globalThis.__gt3Core,
            timers: __pendingTimers__(),
            delays: __pendingDelays__(),
            instKeys: globalThis.__gt3Instance ? Object.getOwnPropertyNames(globalThis.__gt3Instance).length : -1,
          });
        })()`, context);
        out({ type: 'after-response', id, after });
      } catch (e) {
        out({ type: 'after-response', id, error: String(e && e.message).slice(0, 120) });
      }
    }

    for (const x of freshXhr) {
      seen.add('xhr:' + x.url);
      const id = ++sent;
      out({ type: 'request', id, kind: 'xhr', url: x.url, params: {} });
      const reply = await nextLine();
      if (reply && reply.type === 'response') {
        try {
          vm.runInContext(`(function(){ const x = globalThis.__xhrPending__[${x.idx}];
            if (x) x.__resolve(${JSON.stringify(typeof reply.body === 'string' ? reply.body : JSON.stringify(reply.body))}); })()`, context, { timeout: TIMEOUT });
        } catch (e) { out({ type: 'error', id, note: 'xhr-apply-failed:' + (e && e.name) }); }
      }
    }
    await sleep(0);
  }

  if (opt.dumpCore) {
    let dump;
    try {
      dump = JSON.parse(vm.runInContext(`JSON.stringify((function () {
        const out = { hasInstance: !!globalThis.__gt3Instance, keys: [], proto: [], protoDecoded: [], coreKeys: [], coreProtoDecoded: [] };
        const dec = (s) => String(s).replace(/\\\\u([0-9a-fA-F]{4})/g, (m, h) => String.fromCharCode(parseInt(h, 16)));
        try {
          const inst = globalThis.__gt3Instance;
          if (inst) {
            out.keys = Object.getOwnPropertyNames(inst).map(dec).slice(0, 60);
            const core = globalThis.__gt3Core || inst['$_CAJz'];
            out.hasCore = !!core;
            if (core) {
              out.coreKeys = Object.getOwnPropertyNames(core).map(dec).slice(0, 80);
              const proto = Object.getPrototypeOf(core);
              if (proto) out.coreProtoDecoded = Object.getOwnPropertyNames(proto).map(dec).slice(0, 160);
              const proto2 = proto ? Object.getPrototypeOf(proto) : null;
              if (proto2 && proto2 !== Object.prototype) out.coreProto2Decoded = Object.getOwnPropertyNames(proto2).map(dec).slice(0, 80);
            }
          }
        } catch (e) { out.err = (e && e.name) + ':' + String(e && e.message).slice(0, 120); }
        return out;
      })())`, context));
    } catch (e) {
      dump = { err: String(e && e.message).slice(0, 160) };
    }
    out({ type: 'core-dump', dump });
  }

  const final = JSON.parse(vm.runInContext(`JSON.stringify({
    requests: globalThis.__gt3Requests,
    pending: globalThis.__gt3Pending.map(p => ({ kind: p.kind, url: p.url })),
    log: globalThis.__gt3Log,
    errors: globalThis.__gt3Errors,
    pendingTimers: globalThis.__pendingTimers__(),
    payloads: globalThis.__gt3Payloads || [],
    output: globalThis.__output__.slice(0, 30),
  })`, context));
  out({ type: 'done', diag, ...final });
  process.exit(0);
}

main().catch((e) => {
  out({ type: 'fatal', error: String(e && e.message).slice(0, 300) });
  process.exit(1);
});
