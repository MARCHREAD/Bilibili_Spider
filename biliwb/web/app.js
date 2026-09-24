/* bilibili 本地采集工作台 —— 前端逻辑（原生 JS，无依赖） */

const $ = (id) => document.getElementById(id);

/* ---------------------------------------------------------- 接口定义 */

const KINDS = [
  {
    kind: 'search', label: '2.1 综合搜索', targetLabel: '搜索关键词', ph: '例如：原神',
    hint: 'order/duration/日期区间按需求约定；开始日期必须小于结束日期。',
    fields: [
      { k: 'order', label: '排序方式', type: 'select', def: 'totalrank',
        options: { totalrank: '综合排序', click: '最多播放', pubdate: '最新发布', dm: '最多弹幕', stow: '最多收藏' } },
      { k: 'page', label: '起始页码', type: 'number', def: 1 },
      { k: 'pages', label: '抓取页数(≤250)', type: 'number', def: 1 },
      { k: 'page_size', label: '每页数量(≤50)', type: 'number', def: 30 },
      { k: 'duration', label: '时长筛选', type: 'select', def: '0',
        options: { 0: '全部时长', 1: '10分钟以下', 2: '10-30分钟', 3: '30-60分钟', 4: '60分钟以上' } },
      { k: 'pubtime_begin_s', label: '开始日期(10位时间戳，可空)', type: 'text' },
      { k: 'pubtime_end_s', label: '结束日期(10位时间戳，可空)', type: 'text' },
    ],
    summary: [['keyword', '关键词'], ['order_label', '排序'], ['duration_label', '时长'],
              ['total', '结果总数'], ['count', '抓取条数'], ['pages_fetched', '已抓页数'],
              ['page_start', '起始页'], ['page_end', '结束页'],
              ['stop_reason_text', '停止原因']],
    table: { path: 'items', cols: [['bvid', 'BV'], ['title', '标题'], ['author', 'UP'], ['mid', 'UID'],
                                   ['play', '播放'], ['danmaku', '弹幕'], ['duration', '时长'], ['pubdate', '发布', 'ts']] },
  },
  {
    kind: 'video', label: '2.2 视频详情', targetLabel: '视频（BV 号 / 链接）',
    ph: 'BV1BHez6cEEm 或带参数链接',
    hint: '含点赞/投币/收藏/转发、标题、简介、tag、字幕、作者、发布时间、播放量、弹幕量，以及投流/接广判定。',
    fields: [
      { k: 'with_subtitle', label: '取字幕', type: 'checkbox', def: true },
      { k: 'with_subtitle_text', label: '取字幕正文', type: 'checkbox', def: false },
      { k: 'with_tags', label: '取 tag', type: 'checkbox', def: true },
      { k: 'with_pinned_comment', label: '取置顶评论(接广判定)', type: 'checkbox', def: true },
      { k: 'with_page_probe', label: '抓视频页(广告披露旁证)', type: 'checkbox', def: false },
    ],
    summary: [['bvid', 'BV'], ['aid', 'aid'], ['cid', 'cid'], ['title', '标题'],
              ['author.name', '作者'], ['author.mid', '作者 UID'], ['pubdate_str', '发布时间'],
              ['duration_str', '时长'], ['stat.view', '播放'], ['stat.danmaku', '弹幕'],
              ['stat.like', '点赞'], ['stat.coin', '投币'], ['stat.favorite', '收藏'],
              ['stat.share', '转发'], ['stat.reply', '评论'], ['tname', '分区']],
    verdict: true,
    sub: [
      { title: 'tag', path: 'tags', cols: [['tag_id', 'ID'], ['tag_name', '名称'], ['likes', '点赞']] },
      { title: '字幕', path: 'subtitle.subtitles', cols: [['lan', '语言'], ['lan_doc', '名称'], ['ai_status', 'AI']] },
      { title: '分P', path: 'pages', cols: [['page', 'P'], ['cid', 'cid'], ['part', '标题'], ['duration', '时长']] },
    ],
  },
  {
    kind: 'comments', label: '2.3 视频评论', targetLabel: '视频（BV 号 / 链接）', ph: 'BV1BHez6cEEm',
    hint: '主评论为游标分页（内部按页顺序推进）；可带二级评论；含评论者昵称/UID/等级与评论时间。',
    fields: [
      { k: 'page', label: '起始页码', type: 'number', def: 1 },
      { k: 'pages', label: '抓取页数(≤250)', type: 'number', def: 1 },
      { k: 'page_size', label: '每页数量', type: 'number', def: 20 },
      { k: 'sort', label: '排序', type: 'select', def: 'hot', options: { hot: '热度', time: '时间' } },
      { k: 'with_sub', label: '取二级评论', type: 'checkbox', def: true },
      { k: 'sub_pages', label: '二级评论页数', type: 'number', def: 1 },
    ],
    summary: [['bvid', 'BV'], ['all_count', '评论总数'], ['count', '抓取条数'],
              ['pages_fetched', '已抓页数'], ['page_end', '结束页'],
              ['stop_reason_text', '停止原因'], ['is_end', '是否末页'], ['sort', '排序']],
    table: { path: 'items', cols: [['member.uname', '昵称'], ['member.mid', 'UID'], ['member.level', '等级'],
                                   ['message', '内容'], ['like', '点赞'], ['rcount', '回复数'],
                                   ['ctime_str', '时间']] },
  },
  {
    kind: 'danmaku', label: '2.4 视频弹幕', targetLabel: '视频（BV 号 / 链接）', ph: 'BV1BHez6cEEm',
    hint: 'protobuf 分段拉取；含弹幕内容、视频内时间、发送时间、midHash。发送者 uid/昵称/等级受协议限制（仅 midHash 下发）。',
    fields: [
      { k: 'all_segments', label: '取全部分段', type: 'checkbox', def: true },
      { k: 'segment_index', label: '指定分段(0=按全部)', type: 'number', def: 0 },
      { k: 'resolve_senders', label: '尝试还原发送者 uid(候选池碰撞)', type: 'checkbox', def: false },
      { k: 'pool_pages', label: '候选池评论页数(越大命中越多)', type: 'number', def: 5 },
      { k: 'enrich_limit', label: '补昵称/等级的 uid 上限', type: 'number', def: 0 },
    ],
    summary: [['bvid', 'BV'], ['cid', 'cid'], ['segment_total', '协议段数'], ['count', '弹幕条数'],
              ['identity.resolved', 'uid 还原数'], ['identity.unresolved', '未还原'], ['identity.pool_source', '候选池来源']],
    table: { path: 'items', cols: [['video_time', '视频内'], ['content', '弹幕'], ['send_time_str', '发送时间'],
                                   ['uid', 'UID'], ['uname', '昵称'], ['level', '等级'], ['mid_hash', 'midHash'],
                                   ['mode', '模式'], ['color_hex', '颜色']] },
  },
  {
    kind: 'user', label: '2.5 用户资料', targetLabel: 'UID / 主页链接 / 准确用户名', ph: '480959917',
    hint: '含简介、动态数、视频数、关注数、粉丝数、获赞数、播放数、充电人数；关注/粉丝名单受隐私与登录态限制。',
    fields: [
      { k: 'with_followings', label: '取关注名单', type: 'checkbox', def: false },
      { k: 'with_followers', label: '取粉丝名单', type: 'checkbox', def: false },
      { k: 'list_pages', label: '名单页数(≤250)', type: 'number', def: 1 },
      { k: 'with_dynamic_scan', label: '翻页累计动态数(准确但慢)', type: 'checkbox', def: false },
    ],
    summary: [['uid', 'UID'], ['name', '昵称'], ['sign', '简介'], ['level', '等级'],
              ['following', '关注数'], ['follower', '粉丝数'], ['video_count', '视频数'],
              ['dynamic_count', '动态数'], ['dynamic_count_method', '动态数来源'],
              ['likes', '获赞数'], ['play', '播放数'],
              ['charging_count', '充电人数'], ['privacy.following_hidden', '关注列表隐藏'],
              ['privacy.fans_hidden', '粉丝列表隐藏']],
    sub: [
      { title: '关注名单', path: 'followings.items', cols: [['mid', 'UID'], ['uname', '昵称'], ['sign', '签名'], ['special', '特别关注']] },
      { title: '粉丝名单', path: 'followers.items', cols: [['mid', 'UID'], ['uname', '昵称'], ['sign', '签名']] },
    ],
  },
  {
    kind: 'user_videos', label: '2.6 作者视频列表', targetLabel: 'UID / 主页链接 / 准确用户名', ph: '480959917',
    hint: '分页参数 pn/ps/order；未登录时该接口会被 412 风控拦截，登录后可用。',
    fields: [
      { k: 'page', label: '起始页码', type: 'number', def: 1 },
      { k: 'pages', label: '抓取页数(≤250)', type: 'number', def: 1 },
      { k: 'page_size', label: '每页数量(≤50)', type: 'number', def: 30 },
      { k: 'order', label: '排序', type: 'select', def: 'pubdate', options: { pubdate: '最新发布', click: '最多播放', stow: '最多收藏' } },
      { k: 'keyword', label: '关键词过滤', type: 'text' },
    ],
    summary: [['uid', 'UID'], ['total', '投稿总数'], ['count', '抓取条数'],
              ['pages_fetched', '已抓页数'], ['page_start', '起始页'], ['page_end', '结束页'],
              ['stop_reason_text', '停止原因'], ['order', '排序']],
    table: { path: 'items', cols: [['bvid', 'BV'], ['title', '标题'], ['created', '发布', 'ts'], ['length', '时长'],
                                   ['play', '播放'], ['comment', '评论'], ['video_review', '弹幕']] },
  },
  {
    kind: 'stream', label: '2.7 视频流', targetLabel: '视频（BV 号 / 链接）', ph: 'BV1BHez6cEEm',
    hint: '返回 DASH 视频/音频直链与清晰度列表；直链带时效签名，需保持 Referer/UA 一致。',
    fields: [
      { k: 'qn', label: '清晰度 qn(80=1080P)', type: 'number', def: 80 },
      { k: 'fnval', label: 'fnval', type: 'number', def: 4048 },
    ],
    summary: [['bvid', 'BV'], ['cid', 'cid'], ['quality_now_label', '当前清晰度'], ['duration', '时长(ms)']],
    sub: [
      { title: '视频轨', path: 'dash.video', cols: [['quality', '清晰度'], ['codecs', '编码'], ['width', '宽'], ['height', '高'], ['bandwidth', '码率'], ['base_url', '直链']] },
      { title: '音频轨', path: 'dash.audio', cols: [['id', 'ID'], ['codecs', '编码'], ['bandwidth', '码率'], ['base_url', '直链']] },
    ],
  },
  {
    kind: 'dynamics', label: '2.8 用户动态', targetLabel: 'UID / 主页链接 / 准确用户名', ph: '480959917',
    hint: '游标分页：第 2 页起请填写上一页返回的 offset。',
    fields: [
      { k: 'page', label: '起始批次', type: 'number', def: 1 },
      { k: 'pages', label: '抓取批数(≤250)', type: 'number', def: 1 },
      { k: 'offset', label: 'offset(续传游标)', type: 'text' },
    ],
    summary: [['uid', 'UID'], ['total', '动态总数'], ['count', '抓取条数'],
              ['pages_fetched', '已抓批数'], ['stop_reason_text', '停止原因'],
              ['has_more', '还有更多'], ['offset_out', '下一页 offset']],
    table: { path: 'items', cols: [['id', '动态 ID'], ['type', '类型'], ['kind', '内容类型'],
                                   ['text', '正文'], ['author.pub_time_str', '时间']] },
  },
];

const KIND_MAP = Object.fromEntries(KINDS.map((k) => [k.kind, k]));
let current = KINDS[0];
let currentPayload = null;
let currentMeta = null;

/* ---------------------------------------------------------- 工具 */

const get = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);

function fmtTs(v) {
  if (!v) return '';
  const n = Number(v);
  if (!n) return String(v);
  const d = new Date(n * 1000);
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtCount(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return value == null ? '-' : String(value);
  if (n >= 100000000) return `${(n / 100000000).toFixed(n >= 1000000000 ? 0 : 1)}亿`;
  if (n >= 10000) return `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)}万`;
  return String(n);
}

function imageUrl(value) {
  let url = String(value || '');
  if (url.startsWith('//')) url = 'https:' + url;
  if (url.startsWith('http://')) url = 'https://' + url.slice(7);
  return url ? `/api/image?url=${encodeURIComponent(url)}` : '';
}

function cell(value, mode) {
  if (value == null || value === '') return '';
  if (mode === 'ts') return fmtTs(value);
  let text = Array.isArray(value) ? value.join(', ') : String(value);
  if (text.length > 220) text = text.slice(0, 220) + '…';
  return text;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v === false || v == null) continue;
    else if (v === true) node.setAttribute(k, '');
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(c);
  return node;
}

async function api(path, options) {
  let res;
  try { res = await fetch(path, options); }
  catch (error) { return { ok: false, error: `网络请求失败：${error.message}`, meta: { duration_ms: 0, http_calls: 0, trace: [] } }; }
  let body;
  try { body = await res.json(); } catch (e) { body = { ok: false, error: `HTTP ${res.status}` }; }
  return body;
}

function post(path, payload) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
}

/* ---------------------------------------------------------- 账号与并发 */

let ACCOUNTS = [];
let qrTimer = null;
let qrAccountId = null;

async function refreshStatus() {
  const body = await api('/api/status');
  if (!body.ok) return;
  const d = body.data;
  ACCOUNTS = d.accounts || [];
  $('version').textContent = `v${d.version} · ${d.workers.workers} workers`;
  $('version').title = `记录 ${d.store.records} · 任务 ${d.store.jobs} · midHash 字典 ${d.store.midhash_index}`;
  $('account-count').textContent = String(d.account_count || 0);
  $('health-dot').className = 'dot ' + (d.healthy_count ? 'on' : (d.account_count ? 'warn' : 'off'));
  $('session-text').textContent = d.account_count
    ? `账号 ${d.account_count} 个 · 会话健康 ${d.healthy_count} 个`
    : '还没有账号，点右上角「+ 添加账号」';
  renderAccountNav();
  renderAccountPicker();
  renderWorkerHint(d.workers, d.account_count, d.healthy_count);
  const w = $('workers');
  if (document.activeElement !== w) w.value = d.workers.workers;
}

function renderAccountNav() {
  const nav = $('account-nav');
  nav.innerHTML = '';
  if (!ACCOUNTS.length) {
    nav.appendChild(el('div', { class: 'hint', text: '暂无账号' }));
    return;
  }
  ACCOUNTS.forEach((a) => {
    const ok = a.last_status === 'ok';
    // challenge 是"服务端要求人工安全验证"，不是密码/验证码出错 —— 单独说清楚，
    // 否则用户会以为是自己密码填错了而反复重试（越试风控越重）。
    const statusText = {
      ok: '正常', expired: '会话失效', failed: '登录失败',
      challenge: '需人工验证', error: '请求异常',
    }[a.last_status] || a.last_status || '未校验';
    const row = el('div', { class: 'account-row', title:
      `uid=${a.mid || '-'}  状态=${statusText}`
      + (a.has_password ? '\n已保存密码（加密）' : '')
      + (a.has_cookie ? `\n已保存 cookie（加密）` : '')
      + (a.last_error ? `\n最近错误：${a.last_error}` : '') }, [
      el('span', { class: 'dot ' + (ok ? 'on' : 'off') }),
      el('span', { class: 'grow', text: a.uname ? `${a.alias} · ${a.uname}` : a.alias }),
      el('span', { class: 'tag', text: a.login_method || '-' }),
      ...(a.last_status === 'challenge'
        ? [el('span', { class: 'tag warn', text: '需人工验证' })] : []),
    ]);
    const acts = el('span', { class: 'acct-actions' }, [
      el('button', { class: 'mini', text: '校验', title: '校验会话有效性',
        onclick: (e) => { e.stopPropagation(); verifyAccount(a.id); } }),
      el('button', { class: 'mini', text: '扫码', title: '重新扫码登录',
        onclick: (e) => { e.stopPropagation(); openQr(a.id, a.alias); } }),
    ]);
    if (a.has_password) {
      acts.appendChild(el('button', { class: 'mini', text: '密码', title: '用保存的账号密码自动登录（过 GT3）',
        onclick: (e) => { e.stopPropagation(); loginPassword(a.id, a.alias); } }));
    }
    if (a.last_status === 'challenge') {
      // 已经有待处理的二次验证：直接开弹窗填验证码，不必再撞一遍密码登录
      acts.appendChild(el('button', { class: 'mini primary', text: '验证',
        title: '完成二次安全验证（协议发短信，你填验证码）',
        onclick: (e) => { e.stopPropagation(); openRiskModal(a.id, a.alias, null); } }));
    }
    acts.appendChild(el('button', { class: 'mini danger', text: '删', title: '删除本地账号',
      onclick: (e) => { e.stopPropagation(); deleteAccount(a); } }));
    row.appendChild(acts);
    nav.appendChild(row);
  });
}

function renderAccountPicker() {
  const sel = $('job-account');
  const keep = sel.value;
  sel.innerHTML = '';
  sel.appendChild(el('option', { value: '', text: '自动选择健康账号' }));
  ACCOUNTS.forEach((a) => sel.appendChild(el('option', {
    value: String(a.id),
    text: `${a.alias}${a.uname ? ' · ' + a.uname : ''}`
      + (a.last_status === 'ok' ? '' : '（未就绪）'),
  })));
  if (keep && ACCOUNTS.some((a) => String(a.id) === keep)) sel.value = keep;
}

function renderWorkerHint(w, total, healthy) {
  const cap = Math.min(w.workers, Math.max(1, healthy || total || 1));
  $('worker-hint').textContent =
    `队列 ${w.queued} · 运行中 ${w.running} · 并发上限≈${cap}（受可用账号数限制）`;
  $('shard-hint').textContent = healthy > 1
    ? `分片会把目标按 ${healthy} 个健康账号切分并行执行。`
    : '分片需要 ≥2 个健康账号，否则自动退化为单账号串行。';
}

async function verifyAccount(id) {
  const body = await post(`/api/accounts/${id}/verify`);
  if (!body.ok) { alert('校验失败：' + body.error); return; }
  const d = body.data;
  alert([
    `账号：${d.alias || id}`,
    `登录态：${d.ok ? '有效' : '无效'}`,
    `UID：${d.mid || '-'}`,
    `昵称：${d.uname || '-'}`,
    `等级：${d.level ?? '-'}`,
    `SESSDATA：${d.has_sessdata ? '有' : '无'}`,
    d.cookie_refresh_recommended ? '提示：服务端建议刷新 Cookie（建议重新扫码）' : '',
    d.error ? '错误：' + d.error : '',
  ].filter(Boolean).join('\n'));
  refreshStatus();
}

async function verifyAll() {
  const btn = $('btn-verify-all');
  btn.disabled = true; btn.textContent = '校验中…';
  const body = await post('/api/accounts/verify-all');
  btn.disabled = false; btn.textContent = '校验全部账号';
  if (!body.ok) { alert('失败：' + body.error); return; }
  const lines = body.data.map((r) =>
    `${r.alias}：${r.ok ? '有效 ' + (r.uname || '') + ' (uid ' + (r.mid || '-') + ')'
                      : '无效 ' + (r.error || '')}`);
  alert(lines.length ? lines.join('\n') : '没有账号');
  refreshStatus();
}

async function deleteAccount(a) {
  if (!confirm(`删除账号「${a.alias}」？\n本地保存的加密 cookie / 密码会一并删除。`)) return;
  const body = await api(`/api/accounts/${a.id}`, { method: 'DELETE' });
  if (!body.ok) { alert('删除失败：' + body.error); return; }
  refreshStatus();
}

async function loginPassword(id, alias) {
  const acc = (typeof ACCOUNTS !== 'undefined' ? ACCOUNTS : []).find((x) => x.id === id);
  // 防呆：登录态已经健康的账号不需要走密码通道 —— 它要重新过验证码，而且每次
  // 失败都在累积密码类风控（-629 / 二次人工验证），得不偿失。
  if (acc && acc.last_status === 'ok') {
    if (!confirm(`「${alias}」当前登录态是健康的（uid ${acc.mid || '-'}，${acc.uname || ''}）。\n\n`
      + `密码登录会重新过极验验证码，并且失败会累积密码类风控，`
      + `可能把账号推到「需要人工验证」。\n\n`
      + `健康账号通常没必要密码登录。确定仍要继续吗？`)) return;
  }
  if (!confirm(`用保存的账号密码自动登录「${alias}」？\n`
    + `需要过极验 GT3 验证码：单轮约 20~75 秒。\n`
    + `验证码有时效，超时会自动重新取一轮重试。`)) return;
  $('session-text').textContent =
    `正在为「${alias}」预取验证码 → 解算 → 登录（单轮上限 75s，超时自动重取）…`;
  const body = await post(`/api/accounts/${id}/login/password`);
  if (!body.ok) { alert('请求失败：' + body.error); refreshStatus(); return; }
  const d = body.data;
  const capLine = d.captcha
    ? `验证码 score=${d.captcha.score ?? '-'} 单轮耗时 ${d.captcha.seconds ?? '-'}s`
      + (d.token_age != null ? `，预取到提交 ${d.token_age}s` : '')
    : '';
  if (d.ok) {
    alert(`登录成功：${d.account?.uname || ''} (uid ${d.account?.mid || ''})\n${capLine}`
      + (d.attempts_used > 1 ? `\n共用 ${d.attempts_used} 轮验证码` : ''));
  } else if (d.stage === 'challenge') {
    // status!=0：B 站要求二次安全验证。全部在本地弹窗里完成 —— 不跳浏览器、
    // 不需要复制链接：协议过一次人机验证码并发短信，用户只在本弹窗里填验证码。
    console.warn('[login/password] challenge', d);
    await openRiskModal(id, alias, d);
  } else {
    const detail = [
      `登录失败（阶段：${d.stage}）`,
      d.error || d.hint || d.message || '',
      capLine,
      d.attempts_used != null ? `已用验证码轮次：${d.attempts_used}/${d.attempts_allowed ?? '?'}` : '',
      d.captcha_help || '',
    ].filter(Boolean).join('\n');
    console.warn('[login/password]', d);
    alert(detail);
  }
  refreshStatus();
}

/* ------------------------------------------------ 二次安全验证（status=2 短信） */

let riskAccountId = null;

function showRiskCodeStep(msg) {
  $('risk-step-send').classList.add('hidden');
  $('risk-step-code').classList.remove('hidden');
  $('risk-status').textContent = msg || '';
  setTimeout(() => $('risk-code').focus(), 60);
}

async function openRiskModal(id, alias, info) {
  riskAccountId = id;
  $('risk-title').textContent = `二次安全验证 · ${alias || id}`;
  $('risk-desc').textContent = info
    ? `服务端要求额外安全验证（status=${info.status ?? '?'}）：用短信校验该账号绑定的手机号。`
    : '用短信校验该账号绑定的手机号。';
  $('risk-status').textContent = '';
  $('risk-code').value = '';
  $('risk-step-send').classList.remove('hidden');
  $('risk-step-code').classList.add('hidden');

  const st = await api(`/api/accounts/${id}/risk/status`);
  const sd = (st.ok && st.data) || {};
  if (!sd.pending) {
    $('risk-status').textContent = sd.hint || '没有待处理的二次验证，请重新点一次「密码」登录。';
  } else if (sd.captcha_sent) {
    showRiskCodeStep(`短信此前已发送（${sd.sms_type}）。请填写手机收到的验证码；`
      + `没收到就点「重新发送」。`);
  }
  $('risk-modal').classList.remove('hidden');
}

function closeRiskModal() {
  $('risk-modal').classList.add('hidden');
  riskAccountId = null;
}

async function riskSend() {
  if (riskAccountId == null) return;
  $('btn-risk-send').disabled = true;
  $('btn-risk-resend').disabled = true;
  $('risk-status').textContent = '正在过一次人机验证码（约 15~75 秒），随后发送短信…';
  const r = await post(`/api/accounts/${riskAccountId}/risk/sms/send`);
  $('btn-risk-send').disabled = false;
  $('btn-risk-resend').disabled = false;
  if (!r.ok) {
    $('risk-status').textContent = `发送失败：${r.error || ''}`;
    return;
  }
  const d = r.data || {};
  showRiskCodeStep(`短信已发往该账号绑定的手机（验证码类型 ${d.captcha_type || '-'}`
    + (d.solve?.seconds != null ? `，过人机验证码 ${d.solve.seconds}s` : '')
    + (d.solve?.score != null ? `，score=${d.solve.score}` : '')
    + '）。请在下面填写收到的验证码。');
}

async function riskSubmit() {
  if (riskAccountId == null) return;
  const code = ($('risk-code').value || '').trim();
  if (!code) {
    $('risk-status').textContent = '请先填写手机收到的验证码';
    $('risk-code').focus();
    return;
  }
  $('btn-risk-submit').disabled = true;
  $('risk-status').textContent = '正在提交验证码并换取登录态…';
  const r = await post(`/api/accounts/${riskAccountId}/risk/sms/verify`, { code });
  $('btn-risk-submit').disabled = false;
  if (!r.ok) {
    $('risk-status').textContent = `请求失败：${r.error || ''}`;
    return;
  }
  const d = r.data || {};
  if (d.ok) {
    const acc = d.account || {};
    $('risk-status').textContent =
      `验证通过，登录成功：${acc.uname || ''} (uid ${acc.mid || ''})，登录态已加密写入该账号。`;
    setTimeout(() => { closeRiskModal(); refreshStatus(); }, 1200);
  } else {
    $('risk-status').textContent = `验证未通过：${d.error || ''}（验证码可能错了或已过期）`;
    $('risk-code').select();
  }
}

async function applyWorkers() {
  const n = Number($('workers').value || 3);
  const body = await post('/api/workers', { workers: n });
  if (!body.ok) { alert('失败：' + body.error); return; }
  refreshStatus();
}

/* ---------------------------------------------------------- 二维码（绑定账号） */

async function openQr(accountId, alias) {
  if (!accountId) { openAccountModal(); return; }
  qrAccountId = accountId;
  $('qr-title').textContent = `扫码登录 · ${alias || accountId}`;
  $('qr-modal').classList.remove('hidden');
  $('qr-holder').textContent = '正在申请二维码…';
  $('qr-state').textContent = '';
  const body = await post(`/api/accounts/${accountId}/login/qr`);
  if (!body.ok) { $('qr-holder').textContent = '申请失败：' + body.error; return; }
  $('qr-holder').innerHTML = '';
  $('qr-holder').appendChild(el('img', { src: body.data.svg, alt: '登录二维码' }));
  pollQr(body.data.qrcode_key);
}

async function pollQr(key) {
  clearTimeout(qrTimer);
  const body = await api(`/api/accounts/${qrAccountId}/login/qr/poll?qrcode_key=`
    + encodeURIComponent(key));
  if (!body.ok) { $('qr-state').textContent = '轮询失败：' + body.error; return; }
  const d = body.data;
  $('qr-state').textContent = d.state + (d.logged_in ? '' : '（等待中…）');
  if (d.logged_in) {
    const s = d.session || {};
    $('qr-state').textContent = `登录成功：${s.uname || ''} (uid ${s.mid || ''})`;
    refreshStatus();
    setTimeout(closeQr, 1200);
    return;
  }
  if (d.state_code === 86038) return;   // 已失效，停止轮询
  qrTimer = setTimeout(() => pollQr(key), 2000);
}

function closeQr() {
  clearTimeout(qrTimer);
  $('qr-modal').classList.add('hidden');
}

/* ---------------------------------------------------------- 添加账号 */

function openAccountModal() {
  $('acc-alias').value = '';
  $('acc-method').value = 'qr';
  renderAccFields();
  $('account-modal').classList.remove('hidden');
}

function renderAccFields() {
  const method = $('acc-method').value;
  const box = $('acc-fields');
  box.innerHTML = '';
  const addInput = (id, label, type = 'text', ph = '') => {
    const input = el('input', { id, type, placeholder: ph });
    box.appendChild(el('div', { class: 'field' },
      [el('label', { for: id, text: label }), input]));
  };
  if (method === 'password') {
    addInput('acc-user', 'bilibili 账号（手机号 / 邮箱 / 用户名）');
    addInput('acc-pass', '密码', 'password');
    $('acc-hint').textContent =
      '密码用 Windows DPAPI 加密后存本地（只有同机同用户能解），不会明文落盘。'
      + '自动登录需过极验 GT3，约 30~60 秒且非 100% 成功 —— 日常建议靠 cookie 复用。';
  } else if (method === 'cookie') {
    const ta = el('textarea', { id: 'acc-cookie', rows: '3',
      placeholder: 'SESSDATA=...; bili_jct=...; DedeUserID=...' });
    box.appendChild(el('div', { class: 'field' }, [el('label', { text: 'Cookie' }), ta]));
    $('acc-hint').textContent = 'Cookie 同样加密存储；导入后会立即校验一次。';
  } else {
    $('acc-hint').textContent = '创建后会自动弹出二维码，用手机 bilibili 扫码即可（不过验证码）。';
  }
}

async function createAccount() {
  const alias = $('acc-alias').value.trim();
  const method = $('acc-method').value;
  if (!alias) { alert('请填写别名'); return; }
  const payload = { alias, login_method: method };
  if (method === 'password') {
    payload.username = ($('acc-user')?.value || '').trim();
    payload.password = $('acc-pass')?.value || '';
    if (!payload.username || !payload.password) { alert('请填写账号与密码'); return; }
  } else if (method === 'cookie') {
    payload.cookie = ($('acc-cookie')?.value || '').trim();
    if (!payload.cookie) { alert('请粘贴 Cookie'); return; }
  }
  const body = await post('/api/accounts', payload);
  if (!body.ok) { alert('创建失败：' + body.error); return; }
  $('account-modal').classList.add('hidden');
  await refreshStatus();
  const created = body.data;
  if (method === 'qr') openQr(created.id, created.alias);
  else if (method === 'cookie') verifyAccount(created.id);
  else loginPassword(created.id, created.alias);
}

/* ---------------------------------------------------------- 表单 */

function renderNav() {
  const nav = $('kind-nav');
  nav.innerHTML = '';
  KINDS.forEach((k) => {
    nav.appendChild(el('button', {
      text: k.label,
      class: k.kind === current.kind ? 'active' : '',
      onclick: () => { current = k; renderNav(); renderForm(); },
    }));
  });
}

function renderForm() {
  $('panel-title').textContent = current.label.replace(/^2\.\d\s*/, '');
  $('panel-hint').textContent = current.hint;
  $('target').placeholder = current.ph || '目标';
  currentPayload = null;
  currentMeta = null;
  $('result-status').textContent = '等待开始采集';
  $('btn-export-current').classList.add('hidden');
  $('btn-toggle-json').classList.add('hidden');
  $('result').className = 'result empty-state';
  $('result').innerHTML = '<div class="empty-graphic" aria-hidden="true"><span></span><span></span><span></span></div>'
    + '<strong>采集结果将在这里呈现</strong><p>填写目标后开始采集</p>';

  const box = $('fields');
  box.innerHTML = '';
  (current.fields || []).forEach((f) => {
    const id = 'f_' + f.k;
    let input;
    if (f.type === 'select') {
      input = el('select', { id });
      Object.entries(f.options).forEach(([v, label]) =>
        input.appendChild(el('option', { value: v, text: label })));
      input.value = String(f.def);
    } else if (f.type === 'checkbox') {
      input = el('input', { id, type: 'checkbox' });
      input.checked = !!f.def;
    } else {
      input = el('input', { id, type: f.type === 'number' ? 'number' : 'text' });
      if (f.def !== undefined) input.value = f.def;
    }
    box.appendChild(el('div', { class: 'field' }, [el('label', { for: id, text: f.label }), input]));
  });
}

function collectOptions() {
  const out = {};
  (current.fields || []).forEach((f) => {
    const node = $('f_' + f.k);
    if (!node) return;
    if (f.type === 'checkbox') { out[f.k] = node.checked; return; }
    const v = node.value;
    if (v === '' || v == null) return;
    out[f.k] = f.type === 'number' ? Number(v) : v;
  });
  return out;
}

/* ---------------------------------------------------------- 结果渲染 */

function renderSummary(payload, spec) {
  const box = el('div', { class: 'summary' });
  (spec || []).forEach(([path, label]) => {
    const v = get(payload, path);
    if (v === undefined || v === null || v === '') return;
    const value = typeof v === 'boolean' ? (v ? '是' : '否') : String(v);
    box.appendChild(el('div', {}, [el('b', { text: label + '：' }), el('span', { text: value })]));
  });
  return box;
}

function renderTable(payload, tbl) {
  const rows = get(payload, tbl.path) || [];
  if (!rows.length) return el('p', { class: 'hint', text: `（${tbl.path} 为空）` });
  const wrap = el('div', { class: 'scroll' });
  const table = el('table');
  const thead = el('tr');
  tbl.cols.forEach(([, label]) => thead.appendChild(el('th', { text: label })));
  table.appendChild(el('thead', {}, [thead]));
  const tbody = el('tbody');
  rows.slice(0, 500).forEach((row) => {
    const tr = el('tr');
    tbl.cols.forEach(([path, , mode]) => {
      let v = get(row, path);
      tr.appendChild(el('td', { text: cell(v, mode) }));
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  if (rows.length > 500) wrap.appendChild(el('p', { class: 'hint', text: `仅显示前 500 行，共 ${rows.length} 行` }));
  return wrap;
}

function pageWindow(page, total) {
  const values = new Set([1, total]);
  for (let i = Math.max(1, page - 2); i <= Math.min(total, page + 2); i += 1) values.add(i);
  const sorted = [...values].filter((n) => n > 0).sort((a, b) => a - b);
  const out = [];
  sorted.forEach((n, i) => {
    if (i && n - sorted[i - 1] > 1) out.push('gap-' + n);
    out.push(n);
  });
  return out;
}

function runSearchPage(page) {
  const pageInput = $('f_page');
  const pagesInput = $('f_pages');
  if (pageInput) pageInput.value = page;
  if (pagesInput) pagesInput.value = 1;
  runOnce();
  document.getElementById('collector').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSearchGrid(payload) {
  const fragment = document.createDocumentFragment();
  const grid = el('div', { class: 'video-grid' });
  (payload.items || []).forEach((item) => {
    const link = item.arcurl || (item.bvid ? `https://www.bilibili.com/video/${item.bvid}` : '#');
    const cover = el('a', { class: 'video-cover', href: link, target: '_blank', rel: 'noopener' });
    const img = el('img', { src: imageUrl(item.pic), alt: item.title || '视频封面', loading: 'lazy' });
    img.addEventListener('error', () => { img.style.visibility = 'hidden'; });
    cover.appendChild(img);
    if (item.duration) cover.appendChild(el('span', { class: 'duration-chip', text: item.duration }));
    const title = el('h3', { class: 'video-title' }, [
      el('a', { href: link, target: '_blank', rel: 'noopener', text: item.title || item.bvid || '未命名视频' }),
    ]);
    const meta = el('div', { class: 'video-meta' }, [
      el('span', { text: `播放 ${fmtCount(item.play)}` }),
      el('span', { text: `弹幕 ${fmtCount(item.danmaku)}` }),
    ]);
    const author = el('div', { class: 'video-author' }, [
      el('span', { text: item.author || '未知 UP 主' }),
      el('span', { text: item.pubdate ? fmtTs(item.pubdate).slice(0, 10) : '' }),
    ]);
    grid.appendChild(el('article', { class: 'video-card' }, [cover, title, meta, author]));
  });
  fragment.appendChild(grid);

  const page = Number(payload.page_start || 1);
  const total = Math.max(1, Number(payload.total_pages || payload.page_end || 1));
  if (total > 1) {
    const pager = el('nav', { class: 'pagination', 'aria-label': '搜索结果分页' });
    pager.appendChild(el('button', { class: 'page-btn', text: '上一页', disabled: page <= 1,
      onclick: () => runSearchPage(page - 1) }));
    pageWindow(page, total).forEach((value) => {
      if (typeof value === 'string') pager.appendChild(el('span', { class: 'page-gap', text: '...' }));
      else pager.appendChild(el('button', {
        class: 'page-btn' + (value === page ? ' active' : ''),
        text: String(value), 'aria-current': value === page ? 'page' : 'false',
        onclick: () => runSearchPage(value),
      }));
    });
    pager.appendChild(el('button', { class: 'page-btn', text: '下一页', disabled: page >= total,
      onclick: () => runSearchPage(page + 1) }));
    fragment.appendChild(pager);
  }
  return fragment;
}

function renderVerdict(payload) {
  const v = payload.ad_verdict;
  if (!v) return null;
  const box = el('div');
  box.appendChild(el('div', {}, [
    el('b', { text: '判定：' }),
    el('span', { class: 'badge ' + v.category, text: v.category_label }),
    el('span', { text: '  ' + v.reason }),
  ]));
  const ev = el('ul');
  (v.traffic_evidence || []).forEach((e) => ev.appendChild(el('li', { text: '[投流证据] ' + e })));
  (v.promo_evidence || []).forEach((e) => ev.appendChild(el('li', { text: '[接广证据] ' + e })));
  box.appendChild(ev);
  box.appendChild(el('div', { class: 'note', text: v.boundary }));
  return box;
}

function renderResult(payload, spec) {
  const box = $('result');
  box.className = 'result';
  box.innerHTML = '';
  const verdict = spec.verdict ? renderVerdict(payload) : null;
  if (verdict) box.appendChild(verdict);
  box.appendChild(renderSummary(payload, spec.summary));
  if (spec.kind === 'search') box.appendChild(renderSearchGrid(payload));
  else if (spec.table) box.appendChild(renderTable(payload, spec.table));
  (spec.sub || []).forEach((s) => {
    const rows = get(payload, s.path) || [];
    box.appendChild(el('h3', { text: `${s.title}（${rows.length}）` }));
    box.appendChild(renderTable(payload, { path: s.path, cols: s.cols }));
  });
  if (payload.limitation) box.appendChild(el('div', { class: 'note', text: payload.limitation }));
  if (payload.hint) box.appendChild(el('div', { class: 'note', text: payload.hint }));

  let pretty = '';
  try { pretty = JSON.stringify(payload, null, 2); } catch (e) { pretty = String(payload); }
  const det = el('details', { class: 'raw-json hidden' }, [
    el('summary', { text: `原始 JSON（${pretty.length} 字符）` }),
    el('pre', { class: 'json', text: pretty.length > 400000 ? pretty.slice(0, 400000) + '\n…(已截断)' : pretty }),
  ]);
  box.appendChild(det);
}

function renderError(body) {
  const box = $('result');
  box.className = 'result';
  box.innerHTML = '';
  box.appendChild(el('div', { class: 'error', text: '失败：' + (body.error || '未知错误') + (body.code != null ? `（code ${body.code}）` : '') }));
}

function renderTrace(meta, ok) {
  const data = meta || { duration_ms: 0, http_calls: 0, trace: [] };
  const trace = data.trace || [];
  $('trace-summary').innerHTML = '';
  [
    [`${Number(data.duration_ms || 0).toFixed(0)}ms`, '总耗时'],
    [String(data.http_calls ?? trace.length), '请求数'],
    [ok ? '成功' : '失败', '状态'],
  ].forEach(([value, label]) => $('trace-summary').appendChild(
    el('div', {}, [el('strong', { text: value }), el('span', { text: label })])));

  const list = $('trace-list');
  list.innerHTML = '';
  if (!trace.length) {
    list.appendChild(el('div', { class: 'trace-empty', text: '本次调用没有产生外部 HTTP 请求。' }));
    return;
  }
  trace.forEach((item) => {
    const state = item.ok ? 'ok' : 'fail';
    list.appendChild(el('div', { class: `trace-row ${state}` }, [
      el('span', { class: 'trace-seq', text: String(item.sequence) }),
      el('div', { class: 'trace-main' }, [
        el('strong', { text: `${item.method} ${item.endpoint}`, title: `${item.host}${item.endpoint}` }),
        el('span', { text: `HTTP ${item.status ?? '-'}${item.business_code != null ? ` · code ${item.business_code}` : ''}${item.soft_risk ? ' · 软风控' : ''} · 网络 ${Number(item.request_ms || 0).toFixed(0)}ms · 等待 ${Number(item.wait_ms || 0).toFixed(0)}ms` }),
      ]),
      el('span', { class: 'trace-time', text: `${Number(item.duration_ms || 0).toFixed(0)}ms` }),
    ]));
  });
}

function flattenCsv(value, prefix = '', out = {}) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    Object.entries(value).forEach(([key, item]) => flattenCsv(item, prefix ? `${prefix}.${key}` : key, out));
  } else if (Array.isArray(value)) {
    out[prefix || 'value'] = JSON.stringify(value);
  } else {
    out[prefix || 'value'] = value ?? '';
  }
  return out;
}

function csvCell(value) {
  let text = String(value ?? '');
  if (/^[=+\-@]/.test(text)) text = "'" + text;
  return `"${text.replaceAll('"', '""')}"`;
}

function exportCurrentCsv() {
  if (!currentPayload) return;
  const source = Array.isArray(currentPayload.items) ? currentPayload.items : [currentPayload];
  const rows = source.map((item) => flattenCsv(item));
  const fields = [];
  rows.forEach((row) => Object.keys(row).forEach((key) => { if (!fields.includes(key)) fields.push(key); }));
  const csv = '\ufeff' + [fields.map(csvCell).join(','),
    ...rows.map((row) => fields.map((key) => csvCell(row[key])).join(','))].join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `biliwb-${current.kind}-${new Date().toISOString().slice(0, 19).replaceAll(':', '-')}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

/* ---------------------------------------------------------- 运行 */

async function runOnce() {
  const target = $('target').value.trim();
  if (!target) { alert('请填写目标'); return; }
  const accountId = $('job-account').value;
  const btn = $('btn-run');
  btn.disabled = true; btn.textContent = '采集中...';
  $('result').className = 'result empty-state loading-state';
  $('result').innerHTML = '<div class="empty-graphic" aria-hidden="true"><span></span><span></span><span></span></div>'
    + '<strong>正在采集数据</strong><p>接口响应会同步显示在右侧调用链</p>';
  $('result-status').textContent = '正在请求接口';
  $('btn-export-current').classList.add('hidden');
  $('btn-toggle-json').classList.add('hidden');
  $('trace-list').innerHTML = '<div class="trace-empty">正在等待接口响应...</div>';
  const body = await post('/api/call', {
    kind: current.kind, target, options: collectOptions(),
    account_id: accountId ? Number(accountId) : null,
  });
  btn.disabled = false; btn.textContent = '开始采集';
  renderTrace(body.meta, !!body.ok);
  currentMeta = body.meta || null;
  if (!body.ok) {
    currentPayload = null;
    $('result-status').textContent = `采集失败 · ${Number(body.meta?.duration_ms || 0).toFixed(0)}ms`;
    renderError(body);
    return;
  }
  currentPayload = body.data;
  renderResult(body.data, current);
  $('result-status').textContent = `已完成 · ${body.data.count ?? (body.data.items?.length ?? 1)} 条数据 · ${Number(body.meta?.duration_ms || 0).toFixed(0)}ms`;
  $('btn-export-current').classList.remove('hidden');
  $('btn-toggle-json').classList.remove('hidden');
  refreshStatus();
}

async function addBatch() {
  const lines = $('targets').value.split('\n').map((s) => s.trim()).filter(Boolean);
  const single = $('target').value.trim();
  const targets = lines.length ? lines : (single ? [single] : []);
  if (!targets.length) { alert('请填写批量目标（每行一个）'); return; }
  const accountId = $('job-account').value;
  const shard = $('job-shard').value === '1';
  if (shard && ACCOUNTS.filter((a) => a.last_status === 'ok').length < 2) {
    if (!confirm('健康账号不足 2 个，分片会退化为单账号串行。继续创建？')) return;
  }
  const body = await post('/api/jobs', {
    kind: current.kind, targets, options: collectOptions(),
    account_id: accountId ? Number(accountId) : null,
    shard,
  });
  if (!body.ok) { alert('创建任务失败：' + body.error); return; }
  alert(`已创建任务 #${body.data.job_id}，共 ${targets.length} 个目标`
    + (shard ? '\n已开启多账号分片并行' : ''));
  refreshJobs();
}

/* ---------------------------------------------------------- 任务 */

async function refreshJobs() {
  const body = await api('/api/jobs?limit=25');
  if (!body.ok) return;
  const list = $('job-list');
  list.innerHTML = '';
  if (!body.data.length) { list.appendChild(el('p', { class: 'hint', text: '暂无任务' })); return; }
  body.data.forEach((j) => {
    const label = (KIND_MAP[j.kind] || {}).label || j.kind;
    const row = el('div', { class: 'job-row', onclick: () => showJob(j.id) }, [
      el('span', { text: `#${j.id}` }),
      el('span', { class: 'grow', text: `${label} · ${j.targets.length} 个目标` }),
      el('span', { text: `${j.done}/${j.total}${j.failed ? ` 失败 ${j.failed}` : ''}` }),
      el('span', { class: `status ${j.status}`, text: { pending: '等待', running: '运行中', finished: '完成', cancelled: '已取消', failed: '失败', interrupted: '已中断（进程重启）' }[j.status] || j.status }),
    ]);
    list.appendChild(row);
  });
}

async function showJob(id) {
  const body = await api(`/api/jobs/${id}`);
  if (!body.ok) return;
  const j = body.data;
  const box = $('job-detail');
  box.innerHTML = '';
  const exportLink = el('a', {
    class: 'btn', href: `/api/jobs/${j.id}/export.csv`,
    download: `biliwb-job-${j.id}.csv`, text: '导出任务 CSV',
  });
  box.appendChild(el('div', { class: 'job-detail-head' }, [
    el('h3', { text: `任务 #${j.id} · ${(KIND_MAP[j.kind] || {}).label || j.kind}` }),
    exportLink,
  ]));
  box.appendChild(el('p', { class: 'hint', text:
    `状态 ${j.status} · 成功 ${j.done} · 失败 ${j.failed}`
    + (j.account_alias ? ` · 账号 ${j.account_alias}` : '')
    + (j.shard ? ' · 多账号分片' : '') }));

  const wrap = el('div', { class: 'scroll' });
  const table = el('table');
  table.appendChild(el('thead', {}, [el('tr', {}, [
    el('th', { text: '目标' }), el('th', { text: '结果' }), el('th', { text: '用时' }),
    el('th', { text: '接口数' }), el('th', { text: '详情与调用链' }),
  ])]));
  const tbody = el('tbody');
  (j.results || []).forEach((r) => {
    let detail = r.error || '';
    if (!detail && r.payload) {
      const t = Array.isArray(r.payload) ? `${r.payload.length} 条` : 'ok';
      detail = typeof r.payload === 'object'
        ? Object.entries(r.payload).slice(0, 6).map(([k, v]) =>
            `${k}=${typeof v === 'object' ? '…' : String(v).slice(0, 40)}`).join(' · ')
        : t;
    }
    const trace = Array.isArray(r.trace) ? r.trace : [];
    const details = el('div', { text: String(detail).slice(0, 300) });
    if (trace.length) {
      const traceDetails = el('details', { class: 'job-trace' });
      traceDetails.appendChild(el('summary', { text: `查看 ${trace.length} 条接口调用` }));
      trace.forEach((item) => traceDetails.appendChild(el('div', {
        text: `${item.sequence}. ${item.method} ${item.endpoint} · HTTP ${item.status ?? '-'}${item.business_code != null ? ` · code ${item.business_code}` : ''} · ${Number(item.duration_ms || 0).toFixed(0)}ms`,
      })));
      details.appendChild(traceDetails);
    }
    const tr = el('tr', {}, [
      el('td', { text: r.target }),
      el('td', { text: r.ok ? '成功' : '失败' }),
      el('td', { text: r.duration_ms == null ? '-' : `${Number(r.duration_ms).toFixed(0)}ms` }),
      el('td', { text: String(trace.length) }),
      el('td', {}, [details]),
    ]);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  box.appendChild(wrap);
}

/* ---------------------------------------------------------- 启动 */

$('btn-qr-close').onclick = closeQr;
$('btn-qr-x').onclick = closeQr;
$('btn-risk-send').onclick = riskSend;
$('btn-risk-resend').onclick = riskSend;
$('btn-risk-submit').onclick = riskSubmit;
$('btn-risk-close').onclick = closeRiskModal;
$('btn-risk-x').onclick = closeRiskModal;
$('risk-code').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); riskSubmit(); }
});
$('btn-verify-all').onclick = verifyAll;
$('btn-add-account').onclick = openAccountModal;
$('btn-apply-workers').onclick = applyWorkers;
$('btn-acc-cancel').onclick = () => $('account-modal').classList.add('hidden');
$('btn-acc-x').onclick = () => $('account-modal').classList.add('hidden');
$('btn-acc-create').onclick = createAccount;
$('acc-method').onchange = renderAccFields;
$('btn-run').onclick = runOnce;
$('btn-batch').onclick = addBatch;
$('btn-refresh-jobs').onclick = refreshJobs;
$('btn-export-current').onclick = exportCurrentCsv;
$('btn-toggle-json').onclick = () => {
  const raw = document.querySelector('.raw-json');
  if (!raw) return;
  raw.classList.toggle('hidden');
  $('btn-toggle-json').textContent = raw.classList.contains('hidden') ? '查看 JSON' : '隐藏 JSON';
  if (!raw.classList.contains('hidden')) raw.open = true;
};
$('target').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') { event.preventDefault(); runOnce(); }
});

renderNav();
renderForm();
refreshStatus();
refreshJobs();
setInterval(refreshJobs, 4000);
setInterval(refreshStatus, 20000);
