'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {low: '低', medium: '中', high: '高'};
let state, csrfToken, busy = false, filter = 'overview', search = '', confirmAction;
let toastTimer;
const formContext = new WeakMap();

function context() { return {revision: state.revision, day: state.day}; }
function uid() {
  const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}
function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 3800);
}
function errorMessage(message, form) {
  const element = form ? $('.form-error', form) : $('#global-error');
  element.textContent = message; element.hidden = false;
}
async function api(path, body, base) {
  const options = {headers: {}, credentials: 'same-origin'};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type':'application/json', 'X-CSRF-Token':csrfToken, 'Idempotency-Key':uid()};
    options.body = JSON.stringify(base ? {...body, ...base} : body);
  }
  let response;
  try { response = await fetch('/api' + path, options); }
  catch (_) { throw new Error('暂时无法连接服务器。若刚刚提交了进度，请先刷新确认结果，再决定是否重试。'); }
  let result;
  try { result = await response.json(); }
  catch (_) { throw new Error('服务器暂时未能返回数据，请稍后刷新。'); }
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') {
      $$('dialog[open]').forEach(d => d.close());
      await boot();
    }
    throw new Error(result.error || '操作未成功，请稍后重试。');
  }
  return result;
}
async function run(fn, form) {
  if (busy) return;
  busy = true;
  const buttons = $$('button:not(:disabled)'); buttons.forEach(b => b.disabled = true);
  $('#global-error').hidden = true;
  if (form && $('.form-error', form)) $('.form-error', form).textContent = '';
  try { await fn(); }
  catch (error) { errorMessage(error.message, form); }
  finally { busy = false; buttons.forEach(b => { if (b.isConnected) b.disabled = false; }); }
}
async function mutate(path, body = {}, base = context()) {
  state = await api(path, body, base); render();
}
function page() { return ['today','tasks','settings'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'today'; }
function dateLabel(day) {
  return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', year:'numeric', month:'long', day:'numeric', weekday:'long'}).format(new Date(day + 'T12:00:00+08:00'));
}
function dueLabel(day) {
  if (!day) return '无截止日期';
  const delta = Math.round((Date.parse(day + 'T00:00:00Z') - Date.parse(state.day + 'T00:00:00Z')) / 86400000);
  return delta < 0 ? `已逾期 ${-delta} 天` : delta === 0 ? '今天截止' : delta === 1 ? '明天截止' : `${day.slice(5).replace('-', '/')} 截止`;
}
function scheduleTags(task) {
  return `${task.planned_date ? `<span class="tag">计划完成 ${esc(task.planned_date)}</span>` : ''}${task.status === 'active' && task.planned_date && task.planned_date < state.day ? '<span class="tag high">已超过计划完成日期</span>' : ''}${task.recurrence_id ? `<span class="tag">周期 · ${esc(task.occurrence_date)}</span>` : ''}${task.missed ? '<span class="tag high">未完成 · 不补做</span>' : ''}`;
}
function frequencyLabel(rule) {
  if (rule.frequency === 'daily') return '每天';
  const weekdays = ['周一','周二','周三','周四','周五','周六','周日'];
  const planned = rule.frequency === 'weekly' ? rule.weekdays.map(d => weekdays[d]).join('、') : rule.month_day ? `每月 ${rule.month_day} 日` : '每月月末';
  const due = rule.due_day >= 0 ? (rule.frequency === 'weekly' ? weekdays[rule.due_day] : rule.due_day === 0 ? '月末' : `${rule.due_day} 日`) : '';
  return planned + (due ? `计划 · ${due}截止` : '');
}
function openDialog(id, base = context()) {
  const dialog = $(id); const form = $('form', dialog);
  formContext.set(form, base); $('.form-error', form).textContent = ''; dialog.showModal();
}
function confirm(title, description, action, confirmation = '') {
  $('#confirm-title').textContent = title; $('#confirm-description').textContent = description;
  const word = confirmation === true ? '恢复' : confirmation;
  $('#restore-confirm-field').hidden = !word; $('#restore-word').value = '';
  $('#restore-word').required = !!word;
  $('#confirm-word-label').textContent = word === '恢复' ? '输入「恢复」以确认替换' : `输入「${word}」以确认`;
  $('#confirm-submit').textContent = word === '恢复' ? '替换并恢复' : word === '删除' ? '确认删除' : '确认';
  confirmAction = action; openDialog('#confirm-dialog');
}
function intro(eyebrow, title, description, extra = '') {
  return `<div class="page-intro"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="muted">${description}</p></div>${extra}</div>`;
}
function empty(icon, title, description, button = '', enough = false) {
  return `<div class="card empty ${enough ? 'enough' : ''}"><div class="empty-icon" aria-hidden="true">${icon}</div><h2>${title}</h2><p>${description}</p>${button}</div>`;
}
function planItem(item, index) {
  const pending = item.status === 'pending' && item.task_status === 'active';
  const left = pending ? Math.min(item.remaining_minutes, Math.max(0, item.planned_minutes-item.done_minutes)) : 0;
  const statusText = item.status === 'skipped' ? '今天先放一放' : item.task_status === 'archived' ? (item.missed ? '本次未完成' : '任务已搁置') : item.task_status === 'done' ? '任务已完成' : '今日份额已完成';
  return `<article class="card task-card ${pending ? '' : 'finished'}">
    <div class="task-title-row"><span class="task-number" aria-hidden="true">${pending ? String(index+1).padStart(2,'0') : item.status === 'skipped' ? '—' : '✓'}</span>
      <div class="task-main"><h3>${esc(item.title)}</h3><div class="tag-row"><span class="tag ${item.energy}">${labels[item.energy]}消耗</span>${scheduleTags(item)}<span>${esc(dueLabel(item.due_date))}</span></div></div>
      <div class="task-time">${pending ? left : '✓'}<small>${pending ? '分钟' : ''}</small></div>
    </div>
    ${item.next_step ? `<p class="next-step">↳ ${esc(item.next_step)}</p>` : ''}
    <p class="task-reason">${pending ? esc(item.reason) : statusText}</p>
    ${item.done_minutes ? `<div class="progress-wrap">今日已投入 ${item.done_minutes} / 原安排 ${item.planned_minutes} 分钟<progress max="${item.planned_minutes}" value="${Math.min(item.done_minutes,item.planned_minutes)}" aria-label="今日份额进度"></progress></div>` : ''}
    ${pending ? `<div class="task-actions"><button class="button small" data-action="finish-share" data-id="${item.id}">✓ 完成今日份额</button><button class="link-button" data-action="work" data-id="${item.task_id}">记一部分</button><button class="link-button" data-action="skip" data-id="${item.id}">跳过今天</button><span class="move-buttons"><button class="link-button" data-action="move-up" data-id="${item.id}" aria-label="上移 ${esc(item.title)}" ${index===0?'disabled':''}>↑</button><button class="link-button" data-action="move-down" data-id="${item.id}" aria-label="下移 ${esc(item.title)}" ${index===state.items.length-1?'disabled':''}>↓</button></span></div>` : ''}
  </article>`;
}
function todayPage() {
  const plan = state.plan, tasks = state.tasks.filter(t => t.status === 'active');
  const budget = plan ? plan.budget : state.settings.default_minutes;
  const pending = state.items.filter(i => i.status === 'pending' && i.task_status === 'active');
  const done = state.items.filter(i => i.status === 'done' || i.task_status !== 'active').length;
  let body = '';
  const unplanned = state.tasks.filter(t => state.unplanned_scheduled.includes(t.id));
  const scheduledNotice = unplanned.length ? `<section class="warnings scheduled-notice"><h3>还有 ${unplanned.length} 件待办尚未加入今日安排</h3><p>${unplanned.map(t=>esc(t.title)).join('、')}</p><p>可在任务列表中查看，或按当前预算主动重新安排。${unplanned.some(t=>t.recurrence_id) ? '周期任务同样需要占用时间和精力。' : ''}</p></section>` : '';
  if (!plan) body = empty('↗', tasks.length ? '让今天有一个起点' : '从一件小事开始', tasks.length ? '根据今天的时间和状态，生成一份有终点的安排。' : '记下要做的事和大致用时，我们一起决定今天先推进什么。', tasks.length ? '' : '<button class="button primary" data-action="new-task">＋ 添加第一件任务</button>');
  else {
    if (!pending.length) {
      const completed = done > 0 || state.worked_minutes > 0;
      body += empty(completed ? '✓' : '☁', completed ? '今天，可以到这里。' : '给今天留一点空间', completed ? '当前安排已处理完。剩下的事可以明天继续，系统不会自动给你加量。' : '当前没有待执行的安排。可能是时间为零、任务已跳过，或精力预算不足；按需要调整即可。', '', true);
    }
    body += `<div class="task-stack">${state.items.map(planItem).join('')}</div>`;
  }
  body = scheduledNotice + body;
  return intro('MAKE ROOM FOR WHAT MATTERS', '今天，适量就好。', '把重要的事往前推一点，也给自己留一点余地。', `<span class="day-stamp">${plan ? '◉ 今日安排已保存' : '○ 今天还未安排'}</span>`) +
    `<div class="today-layout"><section><div class="card summary"><div><span class="stat-label">今日时间预算</span><span class="stat-value">${budget}<span class="stat-unit">分钟</span></span></div><div><span class="stat-label">已记录投入</span><span class="stat-value">${state.worked_minutes}<span class="stat-unit">分钟</span></span></div><div><span class="stat-label">安排中还剩</span><span class="stat-value">${state.remaining_planned}<span class="stat-unit">分钟</span></span></div></div><div class="section-heading"><h2>今天先做这些</h2><span>${pending.length} 项待推进${done ? ` · ${done} 项已处理` : ''}</span></div>${body}<p class="list-note">完成「今日份额」会按安排分钟记录投入，整个任务可以继续留到明天。</p></section>
    <aside class="today-aside"><form id="plan-form" class="card plan-panel"><div class="panel-title"><span aria-hidden="true">◷</span><h3>今天的节奏</h3></div><p>不用理想状态，就按现在的你。</p><label for="plan-budget">今天有多少可支配时间？</label><div class="input-with-unit"><input id="plan-budget" name="budget" type="number" min="0" max="960" step="1" value="${budget}" required><span>分钟</span></div><fieldset><legend>此刻的精力怎么样？</legend><div class="energy-options">${[['low','◡','有点累'],['medium','◒','还不错'],['high','☀','很充沛']].map(([val,icon,label])=>`<label class="energy-option"><input type="radio" name="energy" value="${val}" ${(plan?.energy || 'medium')===val?'checked':''}><span><b aria-hidden="true">${icon}</b>${label}</span></label>`).join('')}</div></fieldset><p class="form-error error-text" role="alert"></p><button class="button primary wide" type="submit">${plan ? '重新安排今天' : '生成今日安排'} <span aria-hidden="true">↗</span></button><button class="button ghost wide manual-launch" type="button" data-action="manual-plan">自己安排</button><p class="plan-help">${plan ? '已投入时间会计入预算；已完成和跳过的份额保留。' : '高消耗任务会随精力状态适量安排，剩余时间不必填满。'}</p></form><div class="rest-note"><p class="eyebrow">A GENTLE REMINDER</p><h3>做得刚刚好，<br>也是一种进步。</h3><p>计划是为了帮你减轻负担。完成今天的份额，就可以安心停下。</p></div>${state.warnings.length ? `<section class="warnings"><h3>今日的小提醒</h3><ul>${state.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></section>` : ''}</aside></div>`;
}
function libraryCards() {
  if (filter === 'overview') return overviewCards();
  if (filter === 'recurring') return recurrenceCards();
  const tasks = state.tasks.filter(t => !t.recurrence_id && t.status === filter && (t.title + t.next_step).toLowerCase().includes(search.toLowerCase()));
  if (!tasks.length) return empty('▤', search ? '没有找到匹配的任务' : filter === 'active' ? '把想推进的事，放在这里' : '这里暂时还没有任务', search ? '试试其他关键词。' : '不需要一次列完，先记下眼前最重要的一件事。', !search && filter === 'active' ? '<button class="button primary" data-action="new-task">＋ 新建任务</button>' : '');
  return `<div class="task-grid">${tasks.map(taskCard).join('')}</div>`;
}
function overviewTasks() {
  return state.tasks.filter(t => (!t.recurrence_id && t.status === 'active') ||
    (t.recurrence_id && (t.status === 'active' || t.cycle_end >= state.day)));
}
function overviewCards() {
  const query = search.toLowerCase();
  const matches = task => (task.title + task.next_step).toLowerCase().includes(query);
  const ordinary = overviewTasks().filter(t => !t.recurrence_id && matches(t));
  const current = overviewTasks().filter(t => t.recurrence_id && matches(t));
  const rules = state.recurrences.filter(r => (r.title + r.next_step).toLowerCase().includes(query));
  if (!ordinary.length && !current.length && !rules.length)
    return empty('▤', search ? '没有找到匹配的任务' : '从一件小事开始', '普通任务和当前周期的任务都会出现在这里。', search ? '' : '<button class="button primary" data-action="new-task">＋ 新建任务</button>');
  const section = (title, tasks) => tasks.length ? `<section class="overview-section"><h2>${title} · ${tasks.length}</h2><div class="task-grid">${tasks.map(taskCard).join('')}</div></section>` : '';
  return section('普通任务', ordinary) + section('当前及待完成的周期任务', current)
    + (rules.length ? `<section class="overview-section"><h2>重复规则 · ${rules.length}</h2><div class="task-grid">${rules.map(rule => `<article class="card recurrence-card"><h3>${esc(rule.title)}</h3><div class="tag-row"><span class="tag">${esc(frequencyLabel(rule))}</span><span class="tag">${rule.status === 'paused' ? '已暂停' : '重复中'}</span></div><div class="task-actions"><button class="button small" data-action="edit-rule" data-id="${rule.id}">编辑重复规则</button><button class="link-button" data-action="toggle-rule" data-id="${rule.id}">${rule.status === 'paused' ? '恢复重复' : '暂停重复'}</button><button class="link-button" data-action="delete-rule" data-id="${rule.id}">删除重复规则</button></div></article>`).join('')}</div></section>` : '');
}
function taskCard(t) {
  return `<article class="card library-card"><h3>${esc(t.title)}</h3><div class="tag-row"><span class="tag">${t.recurrence_id?'周期任务 · 本次':'普通任务'}</span><span class="tag ${t.energy}">${labels[t.energy]}消耗</span><span class="tag ${t.consequence==='high'?'high':''}">后果${labels[t.consequence]}</span>${scheduleTags(t)}<span>${esc(dueLabel(t.due_date))}</span>${t.recurrence_id ? `<span class="tag">${{active:'待推进',done:'已完成',archived:t.missed?'未完成':'已搁置'}[t.status]}</span>` : ''}</div><p class="next-step">${t.next_step ? `↳ ${esc(t.next_step)}` : '<span class="muted">可以补充一个具体的下一步。</span>'}</p><div class="library-stats"><span>预计还需 <b>${t.remaining_minutes}</b> 分钟</span><span>累计投入 <b>${t.worked_minutes}</b> 分钟</span></div><div class="progress-wrap">按投入与剩余估计展示<progress max="${Math.max(1,t.remaining_minutes+t.worked_minutes)}" value="${t.status==='done'?Math.max(1,t.worked_minutes):t.worked_minutes}" aria-label="${esc(t.title)} 整体进度"></progress></div><div class="task-actions"><button class="button small" data-action="edit-task" data-id="${t.id}">${t.recurrence_id?'编辑本次':'编辑'}</button>${t.status==='active'?`<button class="link-button" data-action="work" data-id="${t.id}">记录投入</button><button class="link-button" data-action="complete-task" data-id="${t.id}">${t.recurrence_id?'本次完成':'全部完成'}</button>`:t.remaining_minutes>0&&!t.missed?`<button class="link-button" data-action="activate-task" data-id="${t.id}">继续推进</button>`:''}${t.status==='active'?`<button class="link-button" data-action="archive-task" data-id="${t.id}">暂时搁置</button>`:''}<button class="link-button" data-action="delete-task" data-id="${t.id}">${t.recurrence_id?'删除本次':'删除任务'}</button></div></article>`;
}
function recurrenceCards() {
  const rules = state.recurrences.filter(r => (r.title + r.next_step).toLowerCase().includes(search.toLowerCase()));
  if (!rules.length) return empty('↻', search ? '没有找到匹配的周期任务' : '给日常留一个固定位置', '每天背单词、每周整理笔记、每月总结，都可以只设置一次。', '<button class="button primary" data-action="new-rule">＋ 新建周期任务</button>');
  return `<div class="task-grid">${rules.map(r=>{
    const instances = state.tasks.filter(t=>t.recurrence_id===r.id).sort((a,b)=>b.occurrence_date.localeCompare(a.occurrence_date));
    return `<article class="card recurrence-card"><h3>${esc(r.title)}</h3><div class="tag-row"><span class="tag">${esc(frequencyLabel(r))}</span><span class="tag">每次 ${r.minutes} 分钟</span><span class="tag ${r.status==='paused'?'high':''}">${r.status==='paused'?'已暂停':'重复中'}</span></div><p class="muted">${r.missed_policy==='skip'?'漏做不补做':'漏做保留待办'}${r.due_on_planned?' · 计划日也是截止日':''}</p><p class="field-note">${r.status==='paused'?'暂停期间不生成新任务，已有待办仍保留。':`下个未生成任务的计划完成日期：${esc(r.next_date)}${r.frequency==='monthly'?' · 缺少指定日期时取月末':''}`}</p><div class="task-actions"><button class="button small" data-action="edit-rule" data-id="${r.id}">编辑规则</button><button class="link-button" data-action="toggle-rule" data-id="${r.id}">${r.status==='paused'?'恢复重复':'暂停重复'}</button><button class="link-button" data-action="delete-rule" data-id="${r.id}">删除重复规则</button></div><details class="occurrence-history"><summary>本次与历史记录（${instances.length}）</summary><div class="task-stack">${instances.length?instances.map(taskCard).join(''):'<p class="muted">开始日期到达后，提前生成当前周期内的任务。</p>'}</div></details></article>`;
  }).join('')}</div>`;
}
function tasksPage() {
  return intro('A PLACE FOR EVERY TASK', '任务总览', '普通任务、当前周期任务和重复规则，都可以在这里找到并修改。') + `<div class="task-toolbar"><div class="filters" role="group" aria-label="任务状态">${[['overview','任务总览'],['active','普通任务'],['recurring','周期规则与历史'],['done','已完成'],['archived','已搁置']].map(([v,l])=>`<button class="${filter===v?'active':''}" data-action="filter" data-value="${v}" aria-pressed="${filter===v}">${l} · ${v==='overview'?overviewTasks().length:v==='recurring'?state.recurrences.length:state.tasks.filter(t=>!t.recurrence_id&&t.status===v).length}</button>`).join('')}</div><input id="task-search" type="search" value="${esc(search)}" placeholder="搜索任务或下一步…" aria-label="搜索任务"></div><div id="library-results">${libraryCards()}</div>`;
}
function settingsPage() {
  return intro('YOUR OWN RHYTHM', '按你的方式来。', '简单的设置，留给真正需要的事。') + `<div class="settings-grid"><section class="card settings-card"><h2>默认每日时间</h2><p>生成新一天的安排时使用，也用于估算截止风险。当天可以单独修改。</p><form id="settings-form"><label for="default-minutes">每天默认可支配分钟</label><input id="default-minutes" name="default_minutes" type="number" min="0" max="960" step="1" required value="${state.settings.default_minutes}"><p class="form-error error-text" role="alert"></p><button class="button primary" type="submit">保存设置</button></form><p class="footnote">日期统一按中国标准时间（Asia/Shanghai）计算。</p></section><section class="card settings-card"><h2>带走你的数据</h2><p>导出所有任务、每日安排和投入记录。备份不包含密码或登录信息。</p><div class="backup-actions"><a href="/api/export" class="button" download>↓ 导出 JSON 备份</a><button class="button ghost" data-action="import">↑ 从备份恢复</button><input id="backup-file" type="file" accept="application/json,.json" hidden></div><p class="footnote">恢复会替换全部现有任务数据。建议先导出当前备份。</p></section><section class="card settings-card"><h2>个人密码</h2><p>修改后，其他电脑上的会话需要重新登录。</p><form id="password-form"><div class="password-fields"><div><label for="old-password">当前密码</label><input id="old-password" name="old_password" type="password" autocomplete="current-password" maxlength="256" required></div><div><label for="new-password">新密码（至少 12 个字符）</label><input id="new-password" name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></div></div><p class="form-error error-text" role="alert"></p><button class="button primary" type="submit">更新密码</button></form></section><section class="card settings-card"><p class="eyebrow">SMALL STEPS, STEADY DAYS</p><h2>为你自己留一份余地</h2><p>推荐依据截止日期、剩余用时、后果严重度和当天精力。它是一份可以调整的建议，不是对你的评判。</p><p>第一版不会自动学习你的状态。用几天后，按实际情况修正用时估计，安排会更贴近现实。</p><button class="button ghost" data-action="logout">退出当前登录</button></section></div>`;
}
function render() {
  $('#today-date').textContent = dateLabel(state.day);
  $('#task-count').textContent = overviewTasks().length;
  $$('[data-page]').forEach(a => {a.classList.toggle('active', a.dataset.page === page()); if (a.dataset.page === page()) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current');});
  $('#main-content').innerHTML = page()==='tasks'?tasksPage():page()==='settings'?settingsPage():todayPage();
  $$('main form').forEach(f=>formContext.set(f, context()));
  $('#sync-status').textContent = '已读取最新数据';
  document.title = `${{today:'今天', tasks:'任务总览', settings:'设置'}[page()]} · DayEnough`;
}
function updateTaskKind() {
  const kind = $('#task-kind').value;
  const recurring = kind === 'recurring';
  const form = $('#task-form');
  if (form.dataset.kind !== kind) $('#task-more').open = !recurring;
  form.dataset.kind = kind;
  const editing = !!form.elements.task_id.value;
  $('#task-dialog-title').textContent = recurring ? (editing ? '编辑重复规则' : '添加周期任务') : kind === 'occurrence' ? '编辑本次任务' : editing ? '调整这件事' : '添加普通任务';
  $('#task-save').textContent = recurring ? (editing ? '保存重复规则' : '创建周期任务') : '保存任务';
  $('#task-title').placeholder = recurring ? '例如：背单词、整理笔记、每月总结' : '例如：完成课程报告';
  $$('[data-task-kind]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.taskKind === kind));
    button.disabled = editing;
    button.hidden = button.dataset.taskKind === 'occurrence' ? kind !== 'occurrence' : kind === 'occurrence';
  });
  $('#recurrence-fields').hidden = !recurring;
  $('#recurrence-fields').disabled = !recurring;
  $('#rule-policy-field').hidden = !recurring;
  $('#task-due-field').hidden = recurring;
  $('#task-due').disabled = recurring;
  $('#task-planned').required = recurring || kind === 'occurrence';
  $('#planned-label').textContent = recurring ? '从哪天开始重复' : kind === 'occurrence' ? '本次计划完成日期' : '计划完成日期（可选）';
  $('#planned-help').textContent = recurring ? '规则从这天生效；本周或本月的任务会提前参与推荐。' : '希望哪天完成；创建后即可参与推荐，这不是硬性截止日期。';
  $('#minutes-label').textContent = recurring ? '每次预计多少分钟' : '预计还需多少分钟';
  if (recurring && !$('#task-planned').value) $('#task-planned').value = state.day;
  $('#rule-weekdays').hidden = $('#rule-frequency').value !== 'weekly';
  $('#rule-month').hidden = $('#rule-frequency').value !== 'monthly';
  const frequency = $('#rule-frequency').value;
  const deadline = $('#rule-deadline');
  if (deadline.dataset.frequency !== frequency) {
    const options = frequency === 'weekly' ? ['周一','周二','周三','周四','周五','周六','周日'].map((label,value)=>[value,label]) : [[0,'月末'],...Array.from({length:31},(_,i)=>[i+1,`${i+1} 日`])];
    deadline.innerHTML = '<option value="-1">不设截止</option><option value="same">每次计划当天</option>' + options.map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
    deadline.dataset.frequency = frequency;
  }
  $('#rule-deadline-field').hidden = !recurring || frequency === 'daily';
  $('#rule-deadline-label').textContent = frequency === 'weekly' ? '截止星期（可选）' : '每月截止日期（可选）';
  $('#rule-due-field').hidden = !recurring || frequency !== 'daily';
  updateRuleSummary();
}
function updateRuleSummary() {
  if ($('#task-kind').value !== 'recurring') return;
  const frequency = $('#rule-frequency').value;
  const weekdays = $$('[name="weekdays"]:checked').map(input=>['周一','周二','周三','周四','周五','周六','周日'][Number(input.value)]);
  const schedule = frequency === 'daily' ? '每天' : frequency === 'weekly' ? `每周 ${weekdays.join('、') || '（请选择计划星期）'}` : `每月 ${$('#rule-month-day').selectedOptions[0].textContent}`;
  const due = frequency === 'daily' ? ($('#rule-due').checked ? '当天截止' : '不设截止') : $('#rule-deadline').selectedOptions[0].textContent;
  const wrap = frequency === 'weekly' && Number($('#rule-deadline').value) >= 0 && $$('[name="weekdays"]:checked').some(input=>Number(input.value)>Number($('#rule-deadline').value));
  const monthlyWrap = frequency === 'monthly' && Number($('#rule-deadline').value)>0 && ($('#rule-month-day').value==='0' || Number($('#rule-deadline').value)<Number($('#rule-month-day').value));
  $('#rule-summary').textContent = `从 ${$('#task-planned').value || '所选开始日期'} 起，${schedule}计划完成，每次 ${$('#task-remaining').value || '—'} 分钟；截止：${due}${wrap?'（早于计划星期的顺延到下一周）':monthlyWrap?'（取计划日当天或之后最近的日期，必要时顺延到下个月）':''}；${$('#rule-missed').value==='skip'?'到期未完成不补做':'未完成保留待办'}。`;
}
function taskDialog(task, rule = null, newRule = false) {
  const form = $('#task-form'); form.reset();
  delete form.dataset.kind;
  delete $('#rule-deadline').dataset.frequency;
  const editing = rule || task;
  $('#task-dialog-title').textContent = rule ? '调整重复规则' : task?.recurrence_id ? '调整本次任务' : task ? '调整这件事' : '添加一件要做的事';
  form.elements.task_id.value = editing?.id || '';
  form.elements.task_kind.value = rule || newRule ? 'recurring' : task?.recurrence_id ? 'occurrence' : 'ordinary';
  form.elements.task_kind.disabled = !!editing;
  form.elements.title.value = editing?.title || '';
  form.elements.due_date.value = task?.due_date || '';
  form.elements.planned_date.value = rule?.start_date || task?.planned_date || '';
  form.elements.planned_date.readOnly = !!rule;
  form.elements.remaining_minutes.value = rule?.minutes ?? task?.remaining_minutes ?? 60;
  form.elements.remaining_minutes.min = task ? 0 : 1;
  form.elements.consequence.value = editing?.consequence || 'medium';
  form.elements.energy.value = editing?.energy || 'medium';
  form.elements.next_step.value = editing?.next_step || '';
  form.elements.frequency.value = rule?.frequency || 'daily';
  form.elements.month_day.value = rule?.month_day || 0;
  form.elements.missed_policy.value = rule?.missed_policy || 'skip';
  form.elements.due_on_planned.checked = !!rule?.due_on_planned;
  $$('[name="weekdays"]', form).forEach(input=>input.checked = (rule?.weekdays || []).includes(Number(input.value)));
  $('#rule-edit-help').textContent = rule ? '修改仅影响尚未生成的任务，已有份额与进度保持原样。' : '每次生成独立任务，完成一次不会结束整个周期。';
  updateTaskKind();
  $('#rule-deadline').value = rule?.due_on_planned ? 'same' : String(rule?.due_day ?? -1);
  updateRuleSummary();
  openDialog('#task-dialog', {...context(), version:editing?.version, status:task?.status});
}
function workDialog(task) {
  $('#work-form').reset(); $('#work-task-title').textContent = task.title;
  const item = state.items.find(i=>i.task_id===task.id && i.status==='pending');
  $('#work-minutes').value = Math.min(25, task.remaining_minutes, item ? Math.max(1,item.planned_minutes-item.done_minutes) : 25);
  openDialog('#work-dialog', {...context(), taskId:task.id});
}
function manualRows() { return $$('.manual-row', $('#manual-list')); }
function updateManualSummary() {
  const rows = manualRows();
  const chosen = rows.filter(row => $('.manual-check', row).checked);
  for (const row of rows) $('.manual-minutes', row).disabled = !$('.manual-check', row).checked;
  const minutes = chosen.reduce((sum, row) => sum + (Number($('.manual-minutes', row).value) || 0), 0);
  const budget = Number($('#manual-budget').value) || 0;
  const total = state.worked_minutes + minutes;
  $('#manual-summary').textContent = `已选 ${chosen.length} 项 · 待投入 ${minutes} 分钟 · 今日已投入 ${state.worked_minutes} 分钟 · 预算 ${budget} 分钟`;
  const warning = $('#manual-warning');
  warning.hidden = total <= budget;
  warning.textContent = total > budget ? `比今日预算多 ${total-budget} 分钟。可以调整份额或预算，也可以按自己的判断直接保存。` : '';
}
function manualDialog() {
  const planForm = $('#plan-form');
  $('#manual-budget').value = $('#plan-budget').value;
  $('#manual-energy').value = $('input[name="energy"]:checked', planForm).value;
  $('#manual-search').value = '';
  const pending = state.items.filter(item => item.status === 'pending' && item.task_status === 'active');
  const ordered = [...pending.map(item => state.tasks.find(task => task.id === item.task_id)),
    ...state.tasks.filter(task => task.status === 'active' && task.remaining_minutes > 0 && !pending.some(item => item.task_id === task.id))].filter(Boolean);
  $('#manual-list').innerHTML = ordered.length ? ordered.map(task => {
    const item = pending.find(i => i.task_id === task.id);
    const minutes = item ? Math.min(task.remaining_minutes, Math.max(1, item.planned_minutes-item.done_minutes)) : Math.min(30, task.remaining_minutes);
    return `<div class="manual-row" data-id="${esc(task.id)}"><label class="manual-task"><input class="manual-check" type="checkbox" ${item?'checked':''}><span><strong>${esc(task.title)}</strong><small>${task.recurrence_id?'周期任务 · 本次':'普通任务'} · 还需约 ${task.remaining_minutes} 分钟${task.planned_date ? ` · 计划 ${esc(task.planned_date)}` : ''}</small></span></label><div class="manual-row-tools"><label>安排 <input class="manual-minutes" type="number" min="1" max="${task.remaining_minutes}" step="1" value="${minutes}" ${item?'':'disabled'} required> 分钟</label><button type="button" class="link-button" data-manual-move="up" aria-label="上移 ${esc(task.title)}">↑</button><button type="button" class="link-button" data-manual-move="down" aria-label="下移 ${esc(task.title)}">↓</button></div></div>`;
  }).join('') : '<p class="muted">目前没有可安排的任务。可以先在任务总览添加任务。</p>';
  updateManualSummary();
  openDialog('#manual-dialog');
}
async function boot() {
  const session = await api('/session'); csrfToken = session.csrf;
  $('#boot').hidden = true; $('#login-screen').hidden = session.authenticated; $('#app').hidden = !session.authenticated;
  $('#setup-notice').hidden = session.configured; $('#login-password').disabled = !session.configured;
  $('#login-form button').disabled = !session.configured;
  if (session.authenticated) { state = await api('/state'); render(); }
}
$('#login-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  busy=true; const button=$('#login-form button'); button.disabled=true; $('#login-error').textContent='';
  try { const result = await api('/login',{password:$('#login-password').value}); csrfToken=result.csrf; $('#login-password').value=''; await boot(); }
  catch(error) {$('#login-error').textContent=error.message;}
  finally {busy=false;button.disabled=false;}
});
$('#refresh-button').addEventListener('click',()=>run(async()=>{state=await api('/state');render();toast('已读取最新数据');}));
async function logout() { await api('/logout',{}); await boot(); }
$('#logout-button').addEventListener('click',()=>run(logout));
window.addEventListener('hashchange',()=>{if(state)render();});
document.addEventListener('click',event=>{
  const move = event.target.closest('[data-manual-move]');
  if (move && !busy) {
    const row = move.closest('.manual-row'), sibling = move.dataset.manualMove === 'up' ? row.previousElementSibling : row.nextElementSibling;
    if (sibling) {
      if (move.dataset.manualMove === 'up') sibling.before(row); else sibling.after(row);
    }
    return;
  }
  const kindButton = event.target.closest('[data-task-kind]');
  if (kindButton && !kindButton.disabled) {
    $('#task-kind').value = kindButton.dataset.taskKind;
    updateTaskKind();
    return;
  }
  const close=event.target.closest('[data-close]'); if(close && !busy) {close.closest('dialog').close(); return;}
  const button=event.target.closest('[data-action]'); if(!button || busy) return;
  const {action,id,value}=button.dataset;
  const task=state?.tasks.find(t=>t.id===id);
  if(action==='new-task') return taskDialog();
  if(action==='manual-plan') return manualDialog();
  if(action==='new-rule') return taskDialog(null, null, true);
  if(action==='edit-rule') return taskDialog(null, state.recurrences.find(r=>r.id===id));
  if(action==='toggle-rule') {
    const rule = state.recurrences.find(r=>r.id===id);
    const status = rule.status==='active'?'paused':'active';
    return confirm(status==='paused'?'暂停这个周期任务？':'恢复这个周期任务？', status==='paused'?'暂停后不再生成新任务。已生成的待办和历史记录保留。':'从今天起继续重复，暂停期间的任务不会补生成。', async base=>{
      await mutate(`/recurrences/${id}/status`,{status,version:rule.version},base);toast('重复规则已更新');
    });
  }
  if(action==='delete-task') {
    const title = task.recurrence_id ? '删除这一次周期任务？' : '删除这项任务？';
    return confirm(title, `「${task.title}」及其投入记录、每日安排记录会永久删除。${task.recurrence_id ? '只删除本次，不影响重复规则和其他次数；刷新后不会重新生成本次。' : ''}`, async base=>{
      await mutate(`/tasks/${id}/delete`,{version:task.version,confirmation:$('#restore-word').value},base);
      toast('任务已删除。');
    }, '删除');
  }
  if(action==='delete-rule') {
    const rule = state.recurrences.find(r=>r.id===id);
    return confirm('删除整条重复规则？', `「${rule.title}」的规则、全部已生成任务、投入记录和每日安排记录都会永久删除。若只想停止以后重复，可取消并使用「暂停重复」。`, async base=>{
      await mutate(`/recurrences/${id}/delete`,{version:rule.version,confirmation:$('#restore-word').value},base);
      toast('重复规则及其记录已删除。');
    }, '删除');
  }
  if(action==='edit-task') return taskDialog(task);
  if(action==='work') return workDialog(task);
  if(action==='filter') {filter=value;render();return;}
  if(action==='import') {$('#backup-file').click();return;}
  if(action==='logout') {run(logout);return;}
  if(action==='finish-share') {
    const item=state.items.find(i=>i.id===id);
    const minutes=Math.min(item.remaining_minutes, item.planned_minutes-item.done_minutes);
    return run(async()=>{await mutate(`/tasks/${item.task_id}/work`,{minutes});toast('今日份额已记录。给自己一点肯定。');});
  }
  if(action==='skip') return run(async()=>{await mutate(`/items/${id}/skip`);toast('今天先放一放，任务仍保留在列表里。');});
  if(action==='move-up'||action==='move-down') {
    const ids=state.items.map(i=>i.id), index=ids.indexOf(id), target=index+(action==='move-up'?-1:1);
    if(target<0||target>=ids.length) return;
    [ids[index],ids[target]]=[ids[target],ids[index]];
    return run(()=>mutate('/plan/order',{ids}));
  }
  const statuses={'archive-task':'archived','complete-task':'done','activate-task':'active'};
  if(statuses[action]) {
    const status=statuses[action];
    confirm(status==='done'?'整个任务已经完成？':status==='archived'?'暂时搁置这件事？':'继续推进这件事？',status==='done'?'会将剩余估计清零，但不会虚构投入记录。':status==='archived'?'搁置后不再参与推荐，已有进度会保留，可以随时继续做。':'继续后可参与下一次推荐。', async base=>{
      await mutate(`/tasks/${id}`,{...task,status},base);toast('任务已更新');
    });
  }
});
document.addEventListener('input',event=>{
  if(event.target.id==='manual-search') {
    const query=event.target.value.trim().toLowerCase();
    manualRows().forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(query));
  }
  if(event.target.id==='manual-budget'||event.target.classList.contains('manual-minutes')) updateManualSummary();
  if(event.target.closest('#task-form')) updateRuleSummary();
  if(event.target.id==='task-search') {search=event.target.value;$('#library-results').innerHTML=libraryCards();}
});
document.addEventListener('change',event=>{
  if(event.target.classList.contains('manual-check')) updateManualSummary();
  if(event.target.id==='task-kind'||event.target.id==='rule-frequency') {updateTaskKind();return;}
  if(event.target.closest('#task-form')) updateRuleSummary();
  if(event.target.id!=='backup-file'||!event.target.files[0]) return;
  const file=event.target.files[0];
  run(async()=>{
    if(file.size>9*1024*1024) throw new Error('备份文件过大，请使用不超过 9MB 的 JSON 文件。');
    let data; try {data=JSON.parse(await file.text());} catch(_){throw new Error('无法读取 JSON 备份文件。');}
    confirm('从备份恢复数据？','恢复会替换现有任务、每日计划和投入记录。密码保持不变。\n请先导出当前备份，以便需要时撤回。',async base=>{
      await mutate('/restore',{backup:data,confirmation:$('#restore-word').value},base);toast('数据已恢复');
    },true);
  });
});
document.addEventListener('submit',event=>{
  const form=event.target;
  if(form.id==='login-form') return;
  event.preventDefault();
  const base=formContext.get(form)||context();
  const values=Object.fromEntries(new FormData(form));
  if(form.id==='task-form') return run(async()=>{
    const body={...values,remaining_minutes:Number(values.remaining_minutes),version:base.version};
    const recurring = form.elements.task_kind.value==='recurring';
    if (recurring) {
      body.weekdays = new FormData(form).getAll('weekdays').map(Number);
      body.month_day = Number(values.month_day);
      body.due_on_planned = values.frequency === 'daily' ? form.elements.due_on_planned.checked : values.due_day === 'same';
      body.due_day = values.frequency === 'daily' || body.due_on_planned ? -1 : Number(values.due_day);
    } else if(values.task_id) body.status=body.remaining_minutes>0&&base.status==='done'?'active':base.status;
    const collection = recurring ? '/recurrences' : '/tasks';
    await mutate(values.task_id?`${collection}/${values.task_id}`:collection,body,{revision:base.revision,day:base.day});
    $('#task-dialog').close();toast(recurring?'周期规则已保存，今日计划仍需主动重排。':values.task_id?'任务已更新。已有计划不会自动增加份额。':'任务已添加，已进入推荐候选；生成或重排时可安排。');
  },form);
  if(form.id==='work-form') return run(async()=>{
    await mutate(`/tasks/${base.taskId}/work`,{minutes:Number(values.minutes)},{revision:base.revision,day:base.day});$('#work-dialog').close();toast('这次推进，记下了。');
  },form);
  if(form.id==='plan-form') {
    const body={budget:Number(values.budget),energy:values.energy};
    if(state.plan) return confirm('重新安排今天？','会依据当前任务和状态重新分配剩余时间。已记录的投入、已完成和跳过的份额会保留。',async()=>{await mutate('/plan',body,base);toast('今天的安排已更新');});
    return run(async()=>{await mutate('/plan',body,base);toast('今日安排已保存');},form);
  }
  if(form.id==='manual-form') return run(async()=>{
    const items=manualRows().filter(row=>$('.manual-check',row).checked).map(row=>({task_id:row.dataset.id,minutes:Number($('.manual-minutes',row).value)}));
    await mutate('/plan/manual',{budget:Number(values.budget),energy:values.energy,items},base);
    $('#manual-dialog').close();toast('自己安排的今日计划已保存');
  },form);
  if(form.id==='settings-form') return run(async()=>{await mutate('/settings',{default_minutes:Number(values.default_minutes)},base);toast('默认时间已保存');},form);
  if(form.id==='password-form') return run(async()=>{await mutate('/password',values,base);toast('密码已更新，其他设备需要重新登录');},form);
  if(form.id==='confirm-form') return run(async()=>{await confirmAction(base);$('#confirm-dialog').close();},form);
});
$$('dialog').forEach(dialog=>dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();}));
$('#rule-month-day').insertAdjacentHTML('beforeend', Array.from({length:31},(_,i)=>`<option value="${i+1}">${i+1} 日</option>`).join(''));
boot().catch(error=>{
  $('#boot').textContent=error.message;
  const retry=document.createElement('button');retry.className='button';retry.textContent='重新加载';retry.addEventListener('click',()=>location.reload());$('#boot').append(retry);
});
