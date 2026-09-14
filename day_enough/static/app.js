'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {low: '低', medium: '中', high: '高'};
let state, csrfToken, busy = false, filter = 'active', search = '', confirmAction;
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
  const delta = Math.round((Date.parse(day + 'T00:00:00Z') - Date.parse(state.day + 'T00:00:00Z')) / 86400000);
  return delta < 0 ? `已逾期 ${-delta} 天` : delta === 0 ? '今天截止' : delta === 1 ? '明天截止' : `${day.slice(5).replace('-', '/')} 截止`;
}
function openDialog(id, base = context()) {
  const dialog = $(id); const form = $('form', dialog);
  formContext.set(form, base); $('.form-error', form).textContent = ''; dialog.showModal();
}
function confirm(title, description, action, restore = false) {
  $('#confirm-title').textContent = title; $('#confirm-description').textContent = description;
  $('#restore-confirm-field').hidden = !restore; $('#restore-word').value = '';
  $('#restore-word').required = restore;
  $('#confirm-submit').textContent = restore ? '替换并恢复' : '确认';
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
  const statusText = item.status === 'skipped' ? '今天先放一放' : item.task_status === 'archived' ? '任务已归档' : item.task_status === 'done' ? '任务已完成' : '今日份额已完成';
  return `<article class="card task-card ${pending ? '' : 'finished'}">
    <div class="task-title-row"><span class="task-number" aria-hidden="true">${pending ? String(index+1).padStart(2,'0') : item.status === 'skipped' ? '—' : '✓'}</span>
      <div class="task-main"><h3>${esc(item.title)}</h3><div class="tag-row"><span class="tag ${item.energy}">${labels[item.energy]}消耗</span><span>${esc(dueLabel(item.due_date))}</span></div></div>
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
  if (!plan) body = empty('↗', tasks.length ? '让今天有一个起点' : '从一件小事开始', tasks.length ? '根据今天的时间和状态，生成一份有终点的安排。' : '记下要做的事和大致用时，我们一起决定今天先推进什么。', tasks.length ? '' : '<button class="button primary" data-action="new-task">＋ 添加第一件任务</button>');
  else {
    if (!pending.length) {
      const completed = done > 0 || state.worked_minutes > 0;
      body += empty(completed ? '✓' : '☁', completed ? '今天，可以到这里。' : '给今天留一点空间', completed ? '当前安排已处理完。剩下的事可以明天继续，系统不会自动给你加量。' : '当前没有待执行的安排。可能是时间为零、任务已跳过，或精力预算不足；按需要调整即可。', '', true);
    }
    body += `<div class="task-stack">${state.items.map(planItem).join('')}</div>`;
  }
  return intro('MAKE ROOM FOR WHAT MATTERS', '今天，适量就好。', '把重要的事往前推一点，也给自己留一点余地。', `<span class="day-stamp">${plan ? '◉ 今日安排已保存' : '○ 今天还未安排'}</span>`) +
    `<div class="today-layout"><section><div class="card summary"><div><span class="stat-label">今日时间预算</span><span class="stat-value">${budget}<span class="stat-unit">分钟</span></span></div><div><span class="stat-label">已记录投入</span><span class="stat-value">${state.worked_minutes}<span class="stat-unit">分钟</span></span></div><div><span class="stat-label">安排中还剩</span><span class="stat-value">${state.remaining_planned}<span class="stat-unit">分钟</span></span></div></div><div class="section-heading"><h2>今天先做这些</h2><span>${pending.length} 项待推进${done ? ` · ${done} 项已处理` : ''}</span></div>${body}<p class="list-note">完成「今日份额」会按安排分钟记录投入，整个任务可以继续留到明天。</p></section>
    <aside class="today-aside"><form id="plan-form" class="card plan-panel"><div class="panel-title"><span aria-hidden="true">◷</span><h3>今天的节奏</h3></div><p>不用理想状态，就按现在的你。</p><label for="plan-budget">今天有多少可支配时间？</label><div class="input-with-unit"><input id="plan-budget" name="budget" type="number" min="0" max="960" step="1" value="${budget}" required><span>分钟</span></div><fieldset><legend>此刻的精力怎么样？</legend><div class="energy-options">${[['low','◡','有点累'],['medium','◒','还不错'],['high','☀','很充沛']].map(([val,icon,label])=>`<label class="energy-option"><input type="radio" name="energy" value="${val}" ${(plan?.energy || 'medium')===val?'checked':''}><span><b aria-hidden="true">${icon}</b>${label}</span></label>`).join('')}</div></fieldset><p class="form-error error-text" role="alert"></p><button class="button primary wide" type="submit">${plan ? '重新安排今天' : '生成今日安排'} <span aria-hidden="true">↗</span></button><p class="plan-help">${plan ? '已投入时间会计入预算；已完成和跳过的份额保留。' : '高消耗任务会随精力状态适量安排，剩余时间不必填满。'}</p></form><div class="rest-note"><p class="eyebrow">A GENTLE REMINDER</p><h3>做得刚刚好，<br>也是一种进步。</h3><p>计划是为了帮你减轻负担。完成今天的份额，就可以安心停下。</p></div>${state.warnings.length ? `<section class="warnings"><h3>关于截止日期的小提醒</h3><ul>${state.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></section>` : ''}</aside></div>`;
}
function libraryCards() {
  const tasks = state.tasks.filter(t => t.status === filter && (t.title + t.next_step).toLowerCase().includes(search.toLowerCase()));
  if (!tasks.length) return empty('▤', search ? '没有找到匹配的任务' : filter === 'active' ? '把想推进的事，放在这里' : '这里暂时还没有任务', search ? '试试其他关键词。' : '不需要一次列完，先记下眼前最重要的一件事。', !search && filter === 'active' ? '<button class="button primary" data-action="new-task">＋ 新建任务</button>' : '');
  return `<div class="task-grid">${tasks.map(t=>`<article class="card library-card"><h3>${esc(t.title)}</h3><div class="tag-row"><span class="tag ${t.energy}">${labels[t.energy]}消耗</span><span class="tag ${t.consequence==='high'?'high':''}">后果${labels[t.consequence]}</span><span>${esc(dueLabel(t.due_date))}</span></div><p class="next-step">${t.next_step ? `↳ ${esc(t.next_step)}` : '<span class="muted">可以补充一个具体的下一步。</span>'}</p><div class="library-stats"><span>预计还需 <b>${t.remaining_minutes}</b> 分钟</span><span>累计投入 <b>${t.worked_minutes}</b> 分钟</span></div><div class="progress-wrap">按投入与剩余估计展示<progress max="${Math.max(1,t.remaining_minutes+t.worked_minutes)}" value="${t.status==='done'?Math.max(1,t.worked_minutes):t.worked_minutes}" aria-label="${esc(t.title)} 整体进度"></progress></div><div class="task-actions"><button class="button small" data-action="edit-task" data-id="${t.id}">编辑</button>${t.status==='active'?`<button class="link-button" data-action="work" data-id="${t.id}">记录投入</button><button class="link-button" data-action="complete-task" data-id="${t.id}">全部完成</button>`:t.remaining_minutes>0?`<button class="link-button" data-action="activate-task" data-id="${t.id}">继续推进</button>`:''}${t.status!=='archived'?`<button class="link-button" data-action="archive-task" data-id="${t.id}">归档</button>`:''}</div></article>`).join('')}</div>`;
}
function tasksPage() {
  return intro('A PLACE FOR EVERY TASK', '事情很多，慢慢来。', '把任务记下来，让大脑腾出一些空间。') + `<div class="task-toolbar"><div class="filters" role="group" aria-label="任务状态">${[['active','进行中'],['done','已完成'],['archived','已归档']].map(([v,l])=>`<button class="${filter===v?'active':''}" data-action="filter" data-value="${v}" aria-pressed="${filter===v}">${l} · ${state.tasks.filter(t=>t.status===v).length}</button>`).join('')}</div><input id="task-search" type="search" value="${esc(search)}" placeholder="搜索任务或下一步…" aria-label="搜索任务"></div><div id="library-results">${libraryCards()}</div>`;
}
function settingsPage() {
  return intro('YOUR OWN RHYTHM', '按你的方式来。', '简单的设置，留给真正需要的事。') + `<div class="settings-grid"><section class="card settings-card"><h2>默认每日时间</h2><p>生成新一天的安排时使用，也用于估算截止风险。当天可以单独修改。</p><form id="settings-form"><label for="default-minutes">每天默认可支配分钟</label><input id="default-minutes" name="default_minutes" type="number" min="0" max="960" step="1" required value="${state.settings.default_minutes}"><p class="form-error error-text" role="alert"></p><button class="button primary" type="submit">保存设置</button></form><p class="footnote">日期统一按中国标准时间（Asia/Shanghai）计算。</p></section><section class="card settings-card"><h2>带走你的数据</h2><p>导出所有任务、每日安排和投入记录。备份不包含密码或登录信息。</p><div class="backup-actions"><a href="/api/export" class="button" download>↓ 导出 JSON 备份</a><button class="button ghost" data-action="import">↑ 从备份恢复</button><input id="backup-file" type="file" accept="application/json,.json" hidden></div><p class="footnote">恢复会替换全部现有任务数据。建议先导出当前备份。</p></section><section class="card settings-card"><h2>个人密码</h2><p>修改后，其他电脑上的会话需要重新登录。</p><form id="password-form"><div class="password-fields"><div><label for="old-password">当前密码</label><input id="old-password" name="old_password" type="password" autocomplete="current-password" maxlength="256" required></div><div><label for="new-password">新密码（至少 12 个字符）</label><input id="new-password" name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></div></div><p class="form-error error-text" role="alert"></p><button class="button primary" type="submit">更新密码</button></form></section><section class="card settings-card"><p class="eyebrow">SMALL STEPS, STEADY DAYS</p><h2>为你自己留一份余地</h2><p>推荐依据截止日期、剩余用时、后果严重度和当天精力。它是一份可以调整的建议，不是对你的评判。</p><p>第一版不会自动学习你的状态。用几天后，按实际情况修正用时估计，安排会更贴近现实。</p><button class="button ghost" data-action="logout">退出当前登录</button></section></div>`;
}
function render() {
  $('#today-date').textContent = dateLabel(state.day);
  $('#task-count').textContent = state.tasks.filter(t => t.status === 'active').length;
  $$('[data-page]').forEach(a => {a.classList.toggle('active', a.dataset.page === page()); if (a.dataset.page === page()) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current');});
  $('#main-content').innerHTML = page()==='tasks'?tasksPage():page()==='settings'?settingsPage():todayPage();
  $$('main form').forEach(f=>formContext.set(f, context()));
  $('#sync-status').textContent = '已读取最新数据';
  document.title = `${{today:'今天', tasks:'我的任务', settings:'设置'}[page()]} · DayEnough`;
}
function taskDialog(task) {
  const form = $('#task-form'); form.reset();
  $('#task-dialog-title').textContent = task ? '调整这件事' : '添加一件要做的事';
  form.elements.task_id.value = task?.id || '';
  form.elements.title.value = task?.title || '';
  form.elements.due_date.value = task?.due_date || state.day;
  form.elements.remaining_minutes.value = task?.remaining_minutes ?? 60;
  form.elements.remaining_minutes.min = task ? 0 : 1;
  form.elements.consequence.value = task?.consequence || 'medium';
  form.elements.energy.value = task?.energy || 'medium';
  form.elements.next_step.value = task?.next_step || '';
  openDialog('#task-dialog', {...context(), version:task?.version, status:task?.status});
}
function workDialog(task) {
  $('#work-form').reset(); $('#work-task-title').textContent = task.title;
  const item = state.items.find(i=>i.task_id===task.id && i.status==='pending');
  $('#work-minutes').value = Math.min(25, task.remaining_minutes, item ? Math.max(1,item.planned_minutes-item.done_minutes) : 25);
  openDialog('#work-dialog', {...context(), taskId:task.id});
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
  const close=event.target.closest('[data-close]'); if(close && !busy) {close.closest('dialog').close(); return;}
  const button=event.target.closest('[data-action]'); if(!button || busy) return;
  const {action,id,value}=button.dataset;
  const task=state?.tasks.find(t=>t.id===id);
  if(action==='new-task') return taskDialog();
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
    confirm(status==='done'?'整个任务已经完成？':status==='archived'?'暂时归档这件事？':'继续推进这件事？',status==='done'?'会将剩余估计清零，但不会虚构投入记录。':status==='archived'?'归档后不再参与推荐，已有进度会保留，可以随时恢复。':'恢复后可参与下一次推荐。', async base=>{
      await mutate(`/tasks/${id}`,{...task,status},base);toast('任务已更新');
    });
  }
});
document.addEventListener('input',event=>{
  if(event.target.id==='task-search') {search=event.target.value;$('#library-results').innerHTML=libraryCards();}
});
document.addEventListener('change',event=>{
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
    if(values.task_id) body.status=body.remaining_minutes>0&&base.status==='done'?'active':base.status;
    await mutate(values.task_id?`/tasks/${values.task_id}`:'/tasks',body,{revision:base.revision,day:base.day});
    $('#task-dialog').close();toast(values.task_id?'任务已更新。已有计划不会自动增加份额。':'任务已添加，生成或重排今日计划时会参与推荐。');
  },form);
  if(form.id==='work-form') return run(async()=>{
    await mutate(`/tasks/${base.taskId}/work`,{minutes:Number(values.minutes)},{revision:base.revision,day:base.day});$('#work-dialog').close();toast('这次推进，记下了。');
  },form);
  if(form.id==='plan-form') {
    const body={budget:Number(values.budget),energy:values.energy};
    if(state.plan) return confirm('重新安排今天？','会依据当前任务和状态重新分配剩余时间。已记录的投入、已完成和跳过的份额会保留。',async()=>{await mutate('/plan',body,base);toast('今天的安排已更新');});
    return run(async()=>{await mutate('/plan',body,base);toast('今日安排已保存');},form);
  }
  if(form.id==='settings-form') return run(async()=>{await mutate('/settings',{default_minutes:Number(values.default_minutes)},base);toast('默认时间已保存');},form);
  if(form.id==='password-form') return run(async()=>{await mutate('/password',values,base);toast('密码已更新，其他设备需要重新登录');},form);
  if(form.id==='confirm-form') return run(async()=>{await confirmAction(base);$('#confirm-dialog').close();},form);
});
$$('dialog').forEach(dialog=>dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();}));
boot().catch(error=>{
  $('#boot').textContent=error.message;
  const retry=document.createElement('button');retry.className='button';retry.textContent='重新加载';retry.addEventListener('click',()=>location.reload());$('#boot').append(retry);
});
