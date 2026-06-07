/* =========================================================================
   Sales Hub  フロントエンド (v2)
   - SPA: ナビでビュー切替、fetch で /api と通信
   - 音声入力: Web Speech API（連続認識・項目自動振り分け対応）
   ========================================================================= */

/* ---------- API ラッパ ---------- */
const api = {
  get: (u) => req(u),
  post: (u, b) => req(u, 'POST', b),
  put: (u, b) => req(u, 'PUT', b),
  patch: (u, b) => req(u, 'PATCH', b),
  del: (u) => req(u, 'DELETE'),
};
async function req(url, method = 'GET', body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const res = await fetch(url, opt);
  if (!res.ok) {
    let msg = 'エラーが発生しました';
    try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

/* ---------- ユーティリティ ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => (s == null ? '' : String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
const yen = (n) => '¥' + (Number(n) || 0).toLocaleString('ja-JP');
const fmtDate = (s) => s ? String(s).slice(0, 10) : '—';
const fmtDateTime = (s) => s ? String(s).replace('T', ' ').slice(0, 16) : '—';
const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const truncate = (s, n) => { s = s || ''; return s.length > n ? s.slice(0, n) + '…' : s; };

function dueInfo(due) {
  if (!due) return { cls: '', label: '—' };
  const t = todayStr();
  if (due < t) return { cls: 'due-over', label: fmtDate(due) + '（期限超過）' };
  // 3日以内
  const d1 = new Date(due), d0 = new Date(t);
  const diff = Math.round((d1 - d0) / 86400000);
  if (diff <= 3) return { cls: 'due-soon', label: fmtDate(due) + (diff === 0 ? '（本日）' : `（あと${diff}日）`) };
  return { cls: '', label: fmtDate(due) };
}

function toast(msg, icon = '✓') {
  const t = $('#toast');
  t.innerHTML = `<span>${icon}</span> ${esc(msg)}`;
  t.classList.remove('hidden');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add('hidden'), 2600);
}

/* ---------- モーダル ---------- */
function openModal(title, html, wide = false) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = html;
  $('#modal-box').classList.toggle('wide', !!wide);
  $('#modal-overlay').classList.remove('hidden');
}
function closeModal() { $('#modal-overlay').classList.add('hidden'); $('#modal-body').innerHTML = ''; }
$('#modal-close').onclick = closeModal;
$('#modal-overlay').onclick = (e) => { if (e.target.id === 'modal-overlay') closeModal(); };
window.closeModal = closeModal;

/* ---------- バッジ（未知キーは gray に） ---------- */
const STAGE_BADGE = { 'リード': 'gray', 'アプローチ': 'sky', 'ヒアリング': 'blue', '提案': 'violet', '見積': 'amber', 'クロージング': 'amber', '受注': 'green', '失注': 'red' };
const STATUS_BADGE = { '未着手': 'gray', '進行中': 'amber', '完了': 'green', '予定': 'blue', '実施済': 'green', '中止': 'red' };
const PRIORITY_BADGE = { '高': 'red', '中': 'amber', '低': 'gray' };
const STAGE_COLOR = { 'リード': '#94a3b8', 'アプローチ': '#0ea5e9', 'ヒアリング': '#6366f1', '提案': '#7c3aed', '見積': '#d98209', 'クロージング': '#f59e0b', '受注': '#15a06b', '失注': '#e11d48' };
const bdg = (map, k) => map[k] || 'gray';
function badge(map, k) { return `<span class="badge ${bdg(map, k)}">${esc(k)}</span>`; }

/* ---------- 共有キャッシュ ---------- */
let CACHE = { companies: [], deals: [], contacts: [], stages: [] };
async function refreshCache() {
  const [companies, deals, contacts, stages] = await Promise.all([
    api.get('/api/companies'), api.get('/api/deals'), api.get('/api/contacts'), api.get('/api/stages')
  ]);
  CACHE = { companies, deals, contacts, stages };
}
const companyOptions = (sel) => `<option value="">（未選択）</option>` + CACHE.companies.map(c => `<option value="${c.id}" ${sel == c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
const dealOptions = (sel) => `<option value="">（未選択）</option>` + CACHE.deals.map(d => `<option value="${d.id}" ${sel == d.id ? 'selected' : ''}>${esc(d.title)}</option>`).join('');
const contactOptions = (sel) => `<option value="">（未選択）</option>` + CACHE.contacts.map(c => `<option value="${c.id}" ${sel == c.id ? 'selected' : ''}>${esc(c.name)}${c.company_name ? '（' + esc(c.company_name) + '）' : ''}</option>`).join('');
const stageOptions = (sel) => CACHE.stages.map(s => `<option ${sel === s ? 'selected' : ''}>${s}</option>`).join('');

/* ---------- ルーティング ---------- */
const VIEWS = {};
let currentView = 'dashboard';
async function navigate(view) {
  currentView = view;
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $('#view-title').textContent = $(`.nav-item[data-view="${view}"]`).textContent.trim();
  $('#topbar-actions').innerHTML = '';
  $('#view').innerHTML = '<div class="empty">読み込み中…</div>';
  try {
    await refreshCache();
    await VIEWS[view]();
  } catch (e) {
    $('#view').innerHTML = `<div class="empty"><span class="em-ico">⚠️</span>読み込みに失敗しました：${esc(e.message)}</div>`;
  }
}
$$('.nav-item').forEach(b => b.onclick = () => navigate(b.dataset.view));
const emptyRow = (cols, msg, ico = '📭') => `<tr><td colspan="${cols}" class="empty"><span class="em-ico">${ico}</span>${msg}</td></tr>`;

/* =========================================================================
   ① ダッシュボード
   ========================================================================= */
VIEWS.dashboard = async function () {
  const [d, acts] = await Promise.all([api.get('/api/dashboard'), api.get('/api/activity')]);

  const statCard = (ico, cls, label, num, sub, numCls = '') =>
    `<div class="stat"><div class="st-top"><div class="st-ico ${cls}">${ico}</div></div>
     <div class="label" style="margin-top:10px">${label}</div><div class="num ${numCls}">${num}</div><div class="sub">${sub}</div></div>`;

  // パイプライン棒グラフ（ステージ別金額）
  const maxAmt = Math.max(1, ...CACHE.stages.map(s => d.stage_amounts[s] || 0));
  const bars = CACHE.stages.filter(s => s !== '失注').map(s => {
    const amt = d.stage_amounts[s] || 0, cnt = d.stage_counts[s] || 0;
    const w = Math.round((amt / maxAmt) * 100);
    return `<div class="bar-row"><div class="bl">${s}<span class="muted" style="font-weight:400"> ${cnt}</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${STAGE_COLOR[s]}"></div></div>
      <div class="bv">${amt ? '¥' + (amt / 10000).toLocaleString('ja-JP') + '万' : '—'}</div></div>`;
  }).join('');

  // 今日のタスク
  const todoHtml = d.todo_list.length ? d.todo_list.map(t => {
    const di = dueInfo(t.due_date);
    return `<div class="list-item"><div class="li-ico ${bdg(PRIORITY_BADGE, t.priority) === 'red' ? 'ic-red' : 'ic-amber'}">●</div>
      <div class="li-main"><div class="li-title">${esc(t.title)}</div><div class="li-sub">${esc(t.company_name) || '顧客未設定'}</div></div>
      <div class="li-right ${di.cls}">${di.label}</div></div>`;
  }).join('') : `<div class="empty" style="padding:24px"><span class="em-ico">🎉</span>未完了タスクはありません</div>`;

  // 予定の面談
  const meetHtml = d.upcoming_meeting_list.length ? d.upcoming_meeting_list.map(m =>
    `<div class="list-item"><div class="li-ico ic-sky">📅</div>
      <div class="li-main"><div class="li-title">${esc(m.title)}</div><div class="li-sub">${esc(m.company_name) || '顧客未設定'}・${esc(m.meeting_type)}</div></div>
      <div class="li-right">${fmtDateTime(m.scheduled_at)}</div></div>`).join('')
    : `<div class="empty" style="padding:24px"><span class="em-ico">🗓️</span>予定の面談はありません</div>`;

  // アクティビティ
  const actHtml = acts.length ? acts.map(a =>
    `<div class="list-item"><div class="li-ico ic-blue">${a.icon}</div>
      <div class="li-main"><div class="li-title">${esc(a.text)}</div><div class="li-sub">${esc(a.company) || '—'}</div></div>
      <div class="li-right">${fmtDateTime(a.ts)}</div></div>`).join('')
    : `<div class="empty">履歴はまだありません</div>`;

  $('#view').innerHTML = `
    <div class="cards">
      ${statCard('🏢', 'ic-blue', '顧客企業', d.companies, '登録社数')}
      ${statCard('📈', 'ic-violet', '進行中の商談', d.open_deals, '受注/失注を除く')}
      ${statCard('💰', 'ic-green', 'パイプライン金額', yen(d.pipeline_amount), '進行中合計', 'sm')}
      ${statCard('🎯', 'ic-sky', '加重見込み', yen(d.weighted_amount), '金額×確度', 'sm')}
      ${statCard('🏆', 'ic-amber', '受注率', d.win_rate + '%', `受注${d.won}/失注${d.lost}`)}
      ${statCard('✅', d.overdue_tasks ? 'ic-red' : 'ic-blue', '未完了タスク', d.open_tasks, d.overdue_tasks ? `⚠ 期限超過 ${d.overdue_tasks}件` : '要対応')}
    </div>

    <div class="grid-2">
      <div class="panel"><h3>📊 商談パイプライン <span class="pill">ステージ別金額</span></h3>
        <div class="bar-chart">${bars}</div>
      </div>
      <div class="panel"><h3>🔥 今日のタスク</h3>${todoHtml}</div>
    </div>

    <div class="grid-2">
      <div class="panel"><h3>🕑 最近のアクティビティ</h3>${actHtml}</div>
      <div class="panel"><h3>📅 予定の面談</h3>${meetHtml}</div>
    </div>`;
};

/* =========================================================================
   ② タスク抽出
   ========================================================================= */
let TASKS_CACHE = [];
VIEWS.tasks = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn" id="add-task">＋ タスク追加</button>`;
  $('#add-task').onclick = () => taskForm();
  TASKS_CACHE = await api.get('/api/tasks');

  $('#view').innerHTML = `
    <div class="panel">
      <h3>🧠 メモ・議事録からタスクを自動抽出 <span class="pill">音声対応</span></h3>
      <p class="muted" style="margin-bottom:12px;font-size:12.5px">商談メモや議事録を貼り付け／話すと、「やること」を自動で取り出します。期限や優先度も推定します。</p>
      <div class="voice-box">
        <div class="field-row-mic">
          <div><div class="vb-title">🎤 音声でメモを入力</div><div class="vb-desc" style="margin:0">マイクを押して話すと、下のメモ欄に文字が入ります。</div></div>
          <button type="button" class="mic-btn" id="mic-extract">🎤 録音開始</button>
        </div>
        <span class="voice-hint" id="mic-extract-hint"></span>
      </div>
      <div class="field"><textarea id="extract-text" rows="5" placeholder="例）次回までに提案資料を作成して山田部長にメール送付する。来週月曜に見積を提出。競合の状況も確認すること。"></textarea></div>
      <div class="form-actions" style="justify-content:flex-start">
        <button class="btn" id="do-extract">⚡ タスクを抽出</button>
        <button class="btn ghost" id="clear-extract">クリア</button>
      </div>
      <div id="extract-result"></div>
    </div>

    <div class="panel">
      <div class="toolbar">
        <div class="search"><span class="si">🔍</span><input id="task-search" placeholder="タスクを検索…"></div>
        <select class="filter-select" id="task-filter">
          <option value="">すべての状態</option><option>未着手</option><option>進行中</option><option>完了</option>
        </select>
        <select class="filter-select" id="task-pri"><option value="">すべての優先度</option><option>高</option><option>中</option><option>低</option></select>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th style="width:34px"></th><th>タスク</th><th>優先度</th><th>期限</th><th>顧客</th><th>状態</th><th></th></tr></thead>
        <tbody id="task-tbody"></tbody>
      </table></div>
    </div>`;

  $('#do-extract').onclick = doExtract;
  $('#clear-extract').onclick = () => { $('#extract-text').value = ''; $('#extract-result').innerHTML = ''; };
  setupMic('mic-extract', 'mic-extract-hint', (text) => { const ta = $('#extract-text'); ta.value = (ta.value ? ta.value + ' ' : '') + text; }, true);
  ['task-search', 'task-filter', 'task-pri'].forEach(id => $('#' + id).oninput = renderTasks);
  renderTasks();
};

function renderTasks() {
  const q = ($('#task-search').value || '').toLowerCase();
  const sf = $('#task-filter').value, pf = $('#task-pri').value;
  const rows = TASKS_CACHE.filter(t =>
    (!q || (t.title || '').toLowerCase().includes(q) || (t.company_name || '').toLowerCase().includes(q)) &&
    (!sf || t.status === sf) && (!pf || t.priority === pf)
  ).map(t => {
    const di = dueInfo(t.due_date);
    return `<tr>
      <td class="checkbox-cell"><input type="checkbox" ${t.status === '完了' ? 'checked' : ''} onchange="toggleTask(${t.id}, this.checked)"></td>
      <td style="${t.status === '完了' ? 'text-decoration:line-through;color:#9aa3b5' : ''}"><span class="list-link" onclick="editTask(${t.id})">${esc(t.title)}</span></td>
      <td>${badge(PRIORITY_BADGE, t.priority)}</td>
      <td class="nowrap ${di.cls}">${di.label}</td>
      <td>${t.company_name ? esc(t.company_name) : '<span class="muted">—</span>'}</td>
      <td>${badge(STATUS_BADGE, t.status)}</td>
      <td class="right"><button class="icon-btn" onclick="delTask(${t.id})">🗑</button></td>
    </tr>`;
  }).join('');
  $('#task-tbody').innerHTML = rows || emptyRow(7, 'タスクはありません', '✅');
}

async function doExtract() {
  const text = $('#extract-text').value.trim();
  if (!text) { toast('メモを入力してください', '✏️'); return; }
  const { candidates } = await api.post('/api/tasks/extract', { text });
  if (!candidates.length) {
    $('#extract-result').innerHTML = `<div class="empty" style="padding:18px"><span class="em-ico">🤔</span>抽出できるタスクが見つかりませんでした。「〜する」「送付」「確認」などの行動を含む文を入れてください。</div>`;
    return;
  }
  window._candidates = candidates;
  const rows = candidates.map((c, i) => `
    <label class="cand-card">
      <input type="checkbox" class="cand-chk" data-i="${i}" checked>
      <div style="flex:1"><div style="font-weight:600">${esc(c.title)}</div>
      <div class="muted" style="font-size:11.5px">優先度 ${esc(c.priority)}${c.due_date ? '・期限 ' + fmtDate(c.due_date) : ''}</div></div>
      ${badge(PRIORITY_BADGE, c.priority)}
    </label>`).join('');
  $('#extract-result').innerHTML = `
    <hr class="sep">
    <div class="section-row"><strong>抽出結果（${candidates.length}件）</strong></div>
    <div class="grid2"><div class="field"><label>関連顧客（任意・一括付与）</label><select id="cand-company">${companyOptions()}</select></div>
      <div class="field"><label>関連商談（任意）</label><select id="cand-deal">${dealOptions()}</select></div></div>
    ${rows}
    <div class="form-actions" style="justify-content:flex-start"><button class="btn" id="save-cands">✅ 選択したタスクを登録</button></div>`;
  $('#save-cands').onclick = saveCandidates;
}

async function saveCandidates() {
  const picks = $$('.cand-chk').filter(c => c.checked).map(c => window._candidates[c.dataset.i]);
  if (!picks.length) { toast('登録するタスクを選択してください', '✏️'); return; }
  const cid = $('#cand-company').value || null, did = $('#cand-deal').value || null;
  await api.post('/api/tasks/bulk', { tasks: picks.map(p => ({ title: p.title, due_date: p.due_date, priority: p.priority, source_text: p.source_text, status: '未着手', company_id: cid, deal_id: did })) });
  toast(`${picks.length}件のタスクを登録しました`);
  navigate('tasks');
}

function taskForm(data = {}) {
  const editing = !!data.id;
  openModal(editing ? 'タスクを編集' : 'タスク追加', `
    <div class="field"><label>タスク名 *</label><input id="t-title" value="${esc(data.title)}"></div>
    <div class="grid2">
      <div class="field"><label>優先度</label><select id="t-pri">${['高', '中', '低'].map(p => `<option ${data.priority === p ? 'selected' : ''}>${p}</option>`).join('')}</select></div>
      <div class="field"><label>期限</label><input id="t-due" type="date" value="${(data.due_date || '').slice(0, 10)}"></div>
    </div>
    <div class="grid2">
      <div class="field"><label>状態</label><select id="t-status">${['未着手', '進行中', '完了'].map(s => `<option ${data.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
      <div class="field"><label>関連顧客</label><select id="t-company">${companyOptions(data.company_id)}</select></div>
    </div>
    <div class="field"><label>関連商談</label><select id="t-deal">${dealOptions(data.deal_id)}</select></div>
    <div class="form-actions">${editing ? `<button class="btn danger" onclick="delTask(${data.id},true)">削除</button>` : ''}<span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="t-save">${editing ? '保存' : '登録'}</button></div>`);
  $('#t-save').onclick = async () => {
    const title = $('#t-title').value.trim();
    if (!title) { toast('タスク名を入力してください', '✏️'); return; }
    const body = { title, priority: $('#t-pri').value, due_date: $('#t-due').value || null, status: $('#t-status').value, company_id: $('#t-company').value || null, deal_id: $('#t-deal').value || null };
    if (editing) await api.put('/api/tasks/' + data.id, { title, priority: body.priority, due_date: body.due_date, status: body.status });
    else await api.post('/api/tasks', body);
    closeModal(); toast('保存しました'); navigate('tasks');
  };
}
window.editTask = (id) => taskForm(TASKS_CACHE.find(t => t.id == id) || {});
window.toggleTask = async (id, done) => { await api.put('/api/tasks/' + id, { status: done ? '完了' : '未着手' }); const t = TASKS_CACHE.find(x => x.id == id); if (t) t.status = done ? '完了' : '未着手'; renderTasks(); };
window.delTask = async (id, fromModal) => { if (confirm('このタスクを削除しますか？')) { await api.del('/api/tasks/' + id); if (fromModal) closeModal(); toast('削除しました'); navigate('tasks'); } };

/* =========================================================================
   ③ CRM（顧客）
   ========================================================================= */
VIEWS.crm = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn ghost" id="add-contact">＋ 担当者</button> <button class="btn" id="add-company">＋ 顧客企業</button>`;
  $('#add-company').onclick = () => companyForm();
  $('#add-contact').onclick = () => contactForm();

  $('#view').innerHTML = `
    <div class="panel">
      <div class="toolbar"><div class="search"><span class="si">🔍</span><input id="crm-search" placeholder="企業名・業種で検索…"></div></div>
      <div class="table-wrap"><table>
        <thead><tr><th>企業名</th><th>業種</th><th>担当者</th><th>進行中商談</th><th>電話</th><th></th></tr></thead>
        <tbody id="crm-tbody"></tbody>
      </table></div>
    </div>`;
  $('#crm-search').oninput = renderCompanies;
  renderCompanies();
};
function renderCompanies() {
  const q = ($('#crm-search').value || '').toLowerCase();
  const rows = CACHE.companies.filter(c => !q || (c.name || '').toLowerCase().includes(q) || (c.industry || '').toLowerCase().includes(q)).map(c => `
    <tr>
      <td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:32px;height:32px;font-size:13px;border-radius:9px">${esc((c.name || '?').slice(0, 1))}</div><span class="list-link" onclick="showCompany(${c.id})">${esc(c.name)}</span></div></td>
      <td>${esc(c.industry) || '<span class="muted">—</span>'}</td>
      <td>${c.contact_count || 0}名</td>
      <td>${c.open_deals ? `<span class="badge blue">${c.open_deals}件</span>` : '<span class="muted">—</span>'}</td>
      <td>${esc(c.phone) || '<span class="muted">—</span>'}</td>
      <td class="right"><button class="icon-btn" onclick="delCompany(${c.id})">🗑</button></td>
    </tr>`).join('');
  $('#crm-tbody').innerHTML = rows || emptyRow(6, '顧客企業がまだありません', '🏢');
}

window.showCompany = async (id) => {
  const c = await api.get('/api/companies/' + id);
  const contacts = c.contacts.map(p => `<tr><td>${esc(p.name)}</td><td>${esc(p.title) || '—'}</td><td>${esc(p.email) || '—'}</td><td>${esc(p.phone) || '—'}</td><td class="right"><button class="icon-btn" onclick="delContact(${p.id},${id})">🗑</button></td></tr>`).join('') || emptyRow(5, '担当者なし', '👤');
  const deals = c.deals.map(d => `<tr><td>${esc(d.title)}</td><td>${badge(STAGE_BADGE, d.stage)}</td><td class="right">${yen(d.amount)}</td></tr>`).join('') || emptyRow(3, '商談なし', '📈');
  const meets = c.meetings.map(m => `<tr><td>${esc(m.title)}</td><td>${fmtDateTime(m.scheduled_at)}</td><td>${badge(STATUS_BADGE, m.status)}</td></tr>`).join('') || emptyRow(3, '面談なし', '📅');
  const tasks = c.tasks.filter(t => t.status !== '完了').map(t => `<tr><td>${esc(t.title)}</td><td>${badge(PRIORITY_BADGE, t.priority)}</td><td class="nowrap ${dueInfo(t.due_date).cls}">${dueInfo(t.due_date).label}</td></tr>`).join('') || emptyRow(3, '未完了タスクなし', '✅');

  // アクティビティ統合
  const acts = [];
  c.deals.forEach(d => acts.push({ ico: '📈', t: `商談「${d.title}」（${d.stage}）`, ts: d.updated_at }));
  c.meetings.forEach(m => acts.push({ ico: '📅', t: `面談「${m.title}」`, ts: m.created_at }));
  (c.hearings || []).forEach(h => acts.push({ ico: '🎤', t: `ヒアリング「${h.title}」`, ts: h.created_at }));
  c.tasks.forEach(t => acts.push({ ico: '✅', t: `タスク「${t.title}」`, ts: t.created_at }));
  acts.sort((a, b) => (b.ts || '').localeCompare(a.ts || ''));
  const actHtml = acts.slice(0, 8).map(a => `<div class="list-item"><div class="li-ico ic-blue">${a.ico}</div><div class="li-main"><div class="li-title">${esc(a.t)}</div></div><div class="li-right">${fmtDateTime(a.ts)}</div></div>`).join('') || '<div class="muted" style="padding:10px">履歴なし</div>';

  openModal(c.name, `
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">
      <div class="avatar">${esc((c.name || '?').slice(0, 1))}</div>
      <div><div style="font-size:17px;font-weight:700">${esc(c.name)}</div><div class="muted" style="font-size:12.5px">${esc(c.industry) || '業種未設定'}</div></div>
    </div>
    <div class="chip-row" style="margin:14px 0">
      <button class="btn sm soft" onclick="quickDeal(${id})">＋ 商談</button>
      <button class="btn sm soft" onclick="quickMeeting(${id})">＋ 面談</button>
      <button class="btn sm soft" onclick="quickHearing(${id})">＋ ヒアリング</button>
      <button class="btn sm soft" onclick="quickTask(${id})">＋ タスク</button>
      <span class="spacer" style="flex:1"></span>
      <button class="btn sm ghost" onclick="editCompany(${id})">編集</button>
    </div>
    <dl class="kv">
      <dt>住所</dt><dd>${esc(c.address) || '—'}</dd>
      <dt>電話</dt><dd>${esc(c.phone) || '—'}</dd>
      <dt>Web</dt><dd>${c.website ? `<a href="${esc(c.website)}" target="_blank">${esc(c.website)}</a>` : '—'}</dd>
      <dt>メモ</dt><dd>${esc(c.notes) || '—'}</dd>
    </dl>
    <div class="modal-section-title">担当者</div>
    <div class="table-wrap"><table><thead><tr><th>氏名</th><th>役職</th><th>メール</th><th>電話</th><th></th></tr></thead><tbody>${contacts}</tbody></table></div>
    <div class="modal-section-title">商談</div>
    <div class="table-wrap"><table><thead><tr><th>商談名</th><th>ステージ</th><th class="right">金額</th></tr></thead><tbody>${deals}</tbody></table></div>
    <div class="modal-section-title">未完了タスク</div>
    <div class="table-wrap"><table><thead><tr><th>タスク</th><th>優先度</th><th>期限</th></tr></thead><tbody>${tasks}</tbody></table></div>
    <div class="modal-section-title">面談</div>
    <div class="table-wrap"><table><thead><tr><th>件名</th><th>日時</th><th>状態</th></tr></thead><tbody>${meets}</tbody></table></div>
    <div class="modal-section-title">アクティビティ</div>${actHtml}
  `, true);
};
window.quickDeal = (cid) => dealForm({ company_id: cid });
window.quickMeeting = (cid) => meetingForm({ company_id: cid });
window.quickHearing = (cid) => hearingForm({ company_id: cid });
window.quickTask = (cid) => taskForm({ company_id: cid });

function companyForm(data = {}) {
  const editing = !!data.id;
  openModal(editing ? '顧客企業を編集' : '顧客企業を追加', `
    <div class="field"><label>企業名 *</label><input id="c-name" value="${esc(data.name)}"></div>
    <div class="grid2">
      <div class="field"><label>業種</label><input id="c-ind" value="${esc(data.industry)}"></div>
      <div class="field"><label>電話</label><input id="c-phone" value="${esc(data.phone)}"></div>
    </div>
    <div class="field"><label>住所</label><input id="c-addr" value="${esc(data.address)}"></div>
    <div class="field"><label>Webサイト</label><input id="c-web" value="${esc(data.website)}"></div>
    <div class="field"><label>メモ</label><textarea id="c-notes">${esc(data.notes)}</textarea></div>
    <div class="form-actions"><button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="c-save">${editing ? '保存' : '登録'}</button></div>`);
  $('#c-save').onclick = async () => {
    const name = $('#c-name').value.trim();
    if (!name) { toast('企業名を入力してください', '✏️'); return; }
    const body = { name, industry: $('#c-ind').value, phone: $('#c-phone').value, address: $('#c-addr').value, website: $('#c-web').value, notes: $('#c-notes').value };
    if (editing) await api.put('/api/companies/' + data.id, body); else await api.post('/api/companies', body);
    closeModal(); toast('保存しました'); navigate('crm');
  };
}
window.editCompany = async (id) => { const c = await api.get('/api/companies/' + id); companyForm(c); };
window.delCompany = async (id) => { if (confirm('この顧客企業を削除しますか？関連データのひもづけは解除されます。')) { await api.del('/api/companies/' + id); toast('削除しました'); navigate('crm'); } };
window.delContact = async (id, cid) => { if (confirm('この担当者を削除しますか？')) { await api.del('/api/contacts/' + id); toast('削除しました'); showCompany(cid); } };

function contactForm() {
  openModal('担当者を追加', `
    <div class="field"><label>会社</label><select id="ct-company">${companyOptions()}</select></div>
    <div class="grid2"><div class="field"><label>氏名 *</label><input id="ct-name"></div><div class="field"><label>役職</label><input id="ct-title"></div></div>
    <div class="grid2"><div class="field"><label>メール</label><input id="ct-email"></div><div class="field"><label>電話</label><input id="ct-phone"></div></div>
    <div class="field"><label>メモ</label><textarea id="ct-notes"></textarea></div>
    <div class="form-actions"><button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="ct-save">登録</button></div>`);
  $('#ct-save').onclick = async () => {
    const name = $('#ct-name').value.trim();
    if (!name) { toast('氏名を入力してください', '✏️'); return; }
    await api.post('/api/contacts', { company_id: $('#ct-company').value || null, name, title: $('#ct-title').value, email: $('#ct-email').value, phone: $('#ct-phone').value, notes: $('#ct-notes').value });
    closeModal(); toast('登録しました'); navigate('crm');
  };
}

/* =========================================================================
   ④ 商談フロー（カンバン）
   ========================================================================= */
VIEWS.pipeline = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn" id="add-deal">＋ 商談追加</button>`;
  $('#add-deal').onclick = () => dealForm();

  const deals = CACHE.deals;
  const totalOpen = deals.filter(d => !['受注', '失注'].includes(d.stage)).reduce((s, d) => s + (d.amount || 0), 0);
  const weighted = deals.filter(d => !['受注', '失注'].includes(d.stage)).reduce((s, d) => s + (d.amount || 0) * (d.probability || 0) / 100, 0);

  const cols = CACHE.stages.map(stage => {
    const items = deals.filter(d => d.stage === stage);
    const sum = items.reduce((s, d) => s + (d.amount || 0), 0);
    const cards = items.map(d => `
      <div class="kcard" draggable="true" data-id="${d.id}" style="border-left-color:${STAGE_COLOR[stage]}">
        <div class="kt">${esc(d.title)}</div>
        <div class="kc">🏢 ${esc(d.company_name) || '顧客未設定'}</div>
        <div class="kbot"><span class="kamount">${yen(d.amount)}</span><span class="kprob">確度${d.probability || 0}%</span></div>
      </div>`).join('');
    return `<div class="kcol" data-stage="${stage}">
      <div class="kcol-head"><span>${badge(STAGE_BADGE, stage)}</span><span class="cnt">${items.length}</span></div>
      <div class="kcol-sum">${sum ? yen(sum) : '　'}</div>
      <div class="kcol-body">${cards || '<div class="muted" style="text-align:center;font-size:11.5px;padding:14px 0">―</div>'}</div>
    </div>`;
  }).join('');

  $('#view').innerHTML = `
    <div class="cards" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr))">
      <div class="stat"><div class="label">パイプライン総額</div><div class="num sm">${yen(totalOpen)}</div><div class="sub">進行中の合計</div></div>
      <div class="stat"><div class="label">加重見込み</div><div class="num sm" style="color:var(--green)">${yen(Math.round(weighted))}</div><div class="sub">金額×確度</div></div>
      <div class="stat"><div class="label">進行中の商談</div><div class="num">${deals.filter(d => !['受注', '失注'].includes(d.stage)).length}</div><div class="sub">件</div></div>
    </div>
    <p class="muted" style="margin:18px 0 10px;font-size:12.5px">💡 カードをドラッグして別ステージへ移動。クリックで編集できます。</p>
    <div class="kanban">${cols}</div>`;
  setupKanban();
};

function setupKanban() {
  let dragId = null, dragged = false;
  $$('.kcard').forEach(card => {
    card.addEventListener('dragstart', () => { dragId = card.dataset.id; dragged = true; card.classList.add('dragging'); });
    card.addEventListener('dragend', () => { card.classList.remove('dragging'); setTimeout(() => { dragged = false; }, 50); });
    // クリックは「ドラッグでなかった場合」のみ編集を開く
    card.addEventListener('click', () => { if (!dragged) editDeal(card.dataset.id); });
  });
  $$('.kcol').forEach(col => {
    col.addEventListener('dragover', (e) => { e.preventDefault(); col.classList.add('drop-hover'); });
    col.addEventListener('dragleave', () => col.classList.remove('drop-hover'));
    col.addEventListener('drop', async (e) => {
      e.preventDefault(); col.classList.remove('drop-hover');
      if (!dragId) return;
      const card = $(`.kcard[data-id="${dragId}"]`);
      if (card && card.closest('.kcol') === col) { dragId = null; return; } // 同じ列なら何もしない
      await api.patch('/api/deals/' + dragId + '/stage', { stage: col.dataset.stage });
      dragId = null;
      toast('ステージを更新しました', '📈');
      navigate('pipeline');
    });
  });
}

function dealForm(data = {}) {
  const editing = !!data.id;
  openModal(editing ? '商談を編集' : '商談を追加', `
    <div class="field"><label>商談名 *</label><input id="d-title" value="${esc(data.title)}"></div>
    <div class="grid2">
      <div class="field"><label>顧客企業</label><select id="d-company">${companyOptions(data.company_id)}</select></div>
      <div class="field"><label>ステージ</label><select id="d-stage">${stageOptions(data.stage)}</select></div>
    </div>
    <div class="grid2">
      <div class="field"><label>金額（円）</label><input id="d-amount" type="number" value="${data.amount || 0}"></div>
      <div class="field"><label>確度（%）</label><input id="d-prob" type="number" min="0" max="100" value="${data.probability || 0}"></div>
    </div>
    <div class="grid2">
      <div class="field"><label>受注予定日</label><input id="d-close" type="date" value="${(data.expected_close || '').slice(0, 10)}"></div>
      <div class="field"><label>担当者</label><input id="d-owner" value="${esc(data.owner)}"></div>
    </div>
    <div class="field"><label>メモ</label><textarea id="d-notes">${esc(data.notes)}</textarea></div>
    ${editing ? `<div class="chip-row" style="margin-bottom:14px"><button class="btn sm soft" onclick="quickMeeting(${data.company_id || 'null'})">＋ 面談設定</button><button class="btn sm soft" onclick="quickTask(${data.company_id || 'null'})">＋ タスク</button></div>` : ''}
    <div class="form-actions">${editing ? `<button class="btn danger" onclick="delDeal(${data.id})">削除</button>` : ''}<span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="d-save">${editing ? '保存' : '登録'}</button></div>`);
  $('#d-save').onclick = async () => {
    const title = $('#d-title').value.trim();
    if (!title) { toast('商談名を入力してください', '✏️'); return; }
    const body = { title, company_id: $('#d-company').value || null, stage: $('#d-stage').value, amount: Number($('#d-amount').value) || 0, probability: Number($('#d-prob').value) || 0, expected_close: $('#d-close').value || null, owner: $('#d-owner').value, notes: $('#d-notes').value };
    if (editing) await api.put('/api/deals/' + data.id, body); else await api.post('/api/deals', body);
    closeModal(); toast('保存しました'); navigate('pipeline');
  };
}
// バグ修正: 単一取得。見つからなければキャッシュ更新してから渡す
window.editDeal = async (id) => {
  let d = CACHE.deals.find(x => x.id == id);
  if (!d) { await refreshCache(); d = CACHE.deals.find(x => x.id == id); }
  if (!d) { toast('商談が見つかりません', '⚠️'); return; }
  dealForm(d);
};
window.delDeal = async (id) => { if (confirm('この商談を削除しますか？')) { await api.del('/api/deals/' + id); closeModal(); toast('削除しました'); navigate('pipeline'); } };

/* =========================================================================
   ⑤ ヒアリングシート（音声自動入力）
   ========================================================================= */
const HEARING_FIELDS = [
  ['current_situation', '現状', '今の業務・体制・使っているサービスなど'],
  ['challenges', '課題・困りごと', '現状で困っていること、解決したいこと'],
  ['needs', '要望・ニーズ', '実現したいこと、欲しい機能'],
  ['budget', '予算 (Budget)', '想定予算、費用感'],
  ['authority', '決裁者 (Authority)', '決裁権を持つ人、承認フロー'],
  ['timeline', '導入時期 (Timeline)', '検討・導入のスケジュール'],
  ['competitors', '競合・比較対象', '比較中の他社・他サービス'],
  ['next_action', '次のアクション', '次回までにやること、約束事'],
];

VIEWS.hearing = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn" id="new-hearing">＋ 新規ヒアリング</button>`;
  $('#new-hearing').onclick = () => hearingForm();
  window._hearings = await api.get('/api/hearings');
  $('#view').innerHTML = `
    <div class="panel">
      <div class="toolbar"><div class="search"><span class="si">🔍</span><input id="h-search" placeholder="タイトル・顧客で検索…"></div></div>
      <p class="muted" style="margin:4px 0 12px;font-size:12.5px">🎤 各項目のマイク、または「シート全体を音声入力」で話すだけ。AIが内容を項目ごとに振り分けます（Chrome/Edge推奨）。</p>
      <div class="table-wrap"><table>
        <thead><tr><th>タイトル</th><th>顧客</th><th>課題（抜粋）</th><th>作成日</th><th></th></tr></thead>
        <tbody id="h-tbody"></tbody>
      </table></div>
    </div>`;
  $('#h-search').oninput = renderHearings;
  renderHearings();
};
function renderHearings() {
  const q = ($('#h-search').value || '').toLowerCase();
  const rows = window._hearings.filter(h => !q || (h.title || '').toLowerCase().includes(q) || (h.company_name || '').toLowerCase().includes(q)).map(h => `
    <tr>
      <td><span class="list-link" onclick="editHearing(${h.id})">${esc(h.title)}</span></td>
      <td>${esc(h.company_name) || '<span class="muted">—</span>'}</td>
      <td>${esc(truncate(h.challenges, 40)) || '<span class="muted">—</span>'}</td>
      <td class="nowrap">${fmtDate(h.created_at)}</td>
      <td class="right"><button class="icon-btn" onclick="delHearing(${h.id})">🗑</button></td>
    </tr>`).join('');
  $('#h-tbody').innerHTML = rows || emptyRow(5, 'ヒアリングシートがまだありません', '🎤');
}

function hearingForm(data = {}) {
  const editing = !!data.id;
  const fieldHtml = HEARING_FIELDS.map(([key, label, ph]) => `
    <div class="field">
      <div class="field-row-mic"><label>${label}</label>
        <span><button type="button" class="mic-btn" id="mic-${key}">🎤</button><span class="voice-hint" id="mic-${key}-hint"></span></span></div>
      <textarea id="h-${key}" placeholder="${ph}">${esc(data[key])}</textarea>
    </div>`).join('');

  openModal(editing ? 'ヒアリングシート編集' : '新規ヒアリングシート', `
    <div class="grid2">
      <div class="field"><label>タイトル *</label><input id="h-title" value="${esc(data.title)}"></div>
      <div class="field"><label>顧客企業</label><select id="h-company">${companyOptions(data.company_id)}</select></div>
    </div>
    <div class="grid2">
      <div class="field"><label>担当者</label><select id="h-contact">${contactOptions(data.contact_id)}</select></div>
      <div class="field"><label>関連商談</label><select id="h-deal">${dealOptions(data.deal_id)}</select></div>
    </div>
    <div class="voice-box">
      <div class="field-row-mic"><div><div class="vb-title">🎙️ シート全体を音声入力</div><div class="vb-desc" style="margin:0">面談しながら自由に話すと、AIが内容を下の各項目へ自動で振り分けます。</div></div>
        <button type="button" class="mic-btn" id="mic-whole">🎤 録音開始</button></div>
      <textarea id="h-raw" rows="3" placeholder="（ここに話した内容が入ります）">${esc(data.raw_voice_text)}</textarea>
      <span class="voice-hint" id="mic-whole-hint"></span>
      <div class="form-actions" style="justify-content:flex-start;margin-top:8px"><button class="btn sm" id="route-fields">🪄 AIで各項目に振り分け</button></div>
    </div>
    ${fieldHtml}
    <div class="form-actions"><button class="btn soft" id="h-to-task">📌 次アクションをタスク化</button><span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="h-save">${editing ? '保存' : '登録'}</button></div>`, true);

  HEARING_FIELDS.forEach(([key]) => setupMic('mic-' + key, 'mic-' + key + '-hint', (text) => { const ta = $('#h-' + key); ta.value = (ta.value ? ta.value + ' ' : '') + text; }));
  setupMic('mic-whole', 'mic-whole-hint', (text) => { const ta = $('#h-raw'); ta.value = (ta.value ? ta.value + ' ' : '') + text; }, true);

  $('#route-fields').onclick = async () => {
    const text = $('#h-raw').value.trim();
    if (!text) { toast('先に音声またはテキストを入力してください', '✏️'); return; }
    const { fields } = await api.post('/api/hearings/parse_voice', { text });
    let n = 0;
    Object.entries(fields).forEach(([key, val]) => { const ta = $('#h-' + key); if (ta) { ta.value = (ta.value ? ta.value + ' ' : '') + val; n++; } });
    toast(`${n}項目に振り分けました`, '🪄');
  };
  $('#h-to-task').onclick = async () => {
    const na = $('#h-next_action').value.trim();
    if (!na) { toast('「次のアクション」が空です', '✏️'); return; }
    await api.post('/api/tasks', { title: na, source_text: 'ヒアリングシートより', priority: '中', status: '未着手', company_id: $('#h-company').value || null, deal_id: $('#h-deal').value || null });
    toast('次アクションをタスク登録しました', '📌');
  };
  $('#h-save').onclick = async () => {
    const title = $('#h-title').value.trim();
    if (!title) { toast('タイトルを入力してください', '✏️'); return; }
    const body = { title, company_id: $('#h-company').value || null, contact_id: $('#h-contact').value || null, deal_id: $('#h-deal').value || null, raw_voice_text: $('#h-raw').value };
    HEARING_FIELDS.forEach(([key]) => body[key] = $('#h-' + key).value);
    if (editing) await api.put('/api/hearings/' + data.id, body); else await api.post('/api/hearings', body);
    closeModal(); toast('保存しました'); navigate('hearing');
  };
}
window.editHearing = async (id) => { const h = await api.get('/api/hearings/' + id); hearingForm(h); };
window.delHearing = async (id) => { if (confirm('このヒアリングシートを削除しますか？')) { await api.del('/api/hearings/' + id); toast('削除しました'); navigate('hearing'); } };

/* =========================================================================
   ⑥ 面談管理
   ========================================================================= */
VIEWS.meetings = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn" id="add-meeting">＋ 面談予約</button>`;
  $('#add-meeting').onclick = () => meetingForm();
  window._meetings = await api.get('/api/meetings');
  $('#view').innerHTML = `
    <div class="panel">
      <div class="toolbar">
        <div class="search"><span class="si">🔍</span><input id="m-search" placeholder="件名・顧客で検索…"></div>
        <select class="filter-select" id="m-filter"><option value="">すべての状態</option><option>予定</option><option>実施済</option><option>中止</option></select>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>日時</th><th>件名</th><th>顧客</th><th>形式</th><th>状態</th><th></th></tr></thead>
        <tbody id="m-tbody"></tbody>
      </table></div>
    </div>`;
  $('#m-search').oninput = renderMeetings;
  $('#m-filter').oninput = renderMeetings;
  renderMeetings();
};
function renderMeetings() {
  const q = ($('#m-search').value || '').toLowerCase(), f = $('#m-filter').value;
  const rows = window._meetings.filter(m => (!q || (m.title || '').toLowerCase().includes(q) || (m.company_name || '').toLowerCase().includes(q)) && (!f || m.status === f)).map(m => `
    <tr>
      <td class="nowrap">${fmtDateTime(m.scheduled_at)}</td>
      <td><span class="list-link" onclick="editMeeting(${m.id})">${esc(m.title)}</span></td>
      <td>${esc(m.company_name) || '<span class="muted">—</span>'}</td>
      <td>${esc(m.meeting_type)}</td>
      <td>${badge(STATUS_BADGE, m.status)}</td>
      <td class="right"><button class="icon-btn" onclick="delMeeting(${m.id})">🗑</button></td>
    </tr>`).join('');
  $('#m-tbody').innerHTML = rows || emptyRow(6, '面談予定がまだありません', '📅');
}

function meetingForm(data = {}) {
  const editing = !!data.id;
  const dtVal = data.scheduled_at ? String(data.scheduled_at).slice(0, 16) : '';
  openModal(editing ? '面談を編集' : '面談を予約', `
    <div class="field"><label>件名 *</label><input id="m-title" value="${esc(data.title)}"></div>
    <div class="grid2">
      <div class="field"><label>日時</label><input id="m-dt" type="datetime-local" value="${dtVal}"></div>
      <div class="field"><label>所要時間（分）</label><input id="m-dur" type="number" value="${data.duration_min || 60}"></div>
    </div>
    <div class="grid2">
      <div class="field"><label>顧客企業</label><select id="m-company">${companyOptions(data.company_id)}</select></div>
      <div class="field"><label>担当者</label><select id="m-contact">${contactOptions(data.contact_id)}</select></div>
    </div>
    <div class="grid2">
      <div class="field"><label>形式</label><select id="m-type">${['オンライン', '対面', '電話'].map(t => `<option ${data.meeting_type === t ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="field"><label>状態</label><select id="m-status">${['予定', '実施済', '中止'].map(s => `<option ${data.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
    </div>
    <div class="grid2">
      <div class="field"><label>場所 / URL</label><input id="m-loc" value="${esc(data.location)}"></div>
      <div class="field"><label>関連商談</label><select id="m-deal">${dealOptions(data.deal_id)}</select></div>
    </div>
    <div class="field"><label>アジェンダ</label><textarea id="m-agenda">${esc(data.agenda)}</textarea></div>
    <div class="field">
      <div class="field-row-mic"><label>議事録</label>
        <span><button type="button" class="mic-btn" id="mic-min">🎤 音声</button><span class="voice-hint" id="mic-min-hint"></span></span></div>
      <textarea id="m-min" rows="4">${esc(data.minutes)}</textarea>
    </div>
    <div class="form-actions"><button class="btn soft" id="m-extract">⚡ 議事録からタスク抽出</button><span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="m-save">${editing ? '保存' : '登録'}</button></div>`);

  setupMic('mic-min', 'mic-min-hint', (text) => { const ta = $('#m-min'); ta.value = (ta.value ? ta.value + ' ' : '') + text; }, true);

  $('#m-extract').onclick = async () => {
    const text = $('#m-min').value.trim();
    if (!text) { toast('議事録が空です', '✏️'); return; }
    const { candidates } = await api.post('/api/tasks/extract', { text });
    if (!candidates.length) { toast('タスクが見つかりませんでした', '🤔'); return; }
    extractTasksDialog(candidates, { company_id: $('#m-company').value || null, deal_id: $('#m-deal').value || null });
  };
  $('#m-save').onclick = async () => {
    const title = $('#m-title').value.trim();
    if (!title) { toast('件名を入力してください', '✏️'); return; }
    const body = { title, scheduled_at: $('#m-dt').value || null, duration_min: Number($('#m-dur').value) || 60, company_id: $('#m-company').value || null, contact_id: $('#m-contact').value || null, deal_id: $('#m-deal').value || null, meeting_type: $('#m-type').value, status: $('#m-status').value, location: $('#m-loc').value, agenda: $('#m-agenda').value, minutes: $('#m-min').value };
    if (editing) await api.put('/api/meetings/' + data.id, body); else await api.post('/api/meetings', body);
    closeModal(); toast('保存しました'); navigate('meetings');
  };
}
// 議事録 → タスク抽出 確認ダイアログ（モーダルを置き換え）
function extractTasksDialog(candidates, ctx) {
  window._mcands = candidates;
  const rows = candidates.map((c, i) => `
    <label class="cand-card"><input type="checkbox" class="mc-chk" data-i="${i}" checked>
      <div style="flex:1"><div style="font-weight:600">${esc(c.title)}</div>
      <div class="muted" style="font-size:11.5px">優先度 ${esc(c.priority)}${c.due_date ? '・期限 ' + fmtDate(c.due_date) : ''}</div></div>
      ${badge(PRIORITY_BADGE, c.priority)}</label>`).join('');
  openModal('議事録から抽出したタスク', `
    <p class="muted" style="font-size:12.5px;margin-bottom:12px">登録するタスクを選んでください。関連顧客・商談は面談の設定を引き継ぎます。</p>
    ${rows}
    <div class="form-actions"><button class="btn ghost" onclick="closeModal()">閉じる</button><button class="btn" id="mc-save">✅ タスクを登録</button></div>`);
  $('#mc-save').onclick = async () => {
    const picks = $$('.mc-chk').filter(c => c.checked).map(c => window._mcands[c.dataset.i]);
    if (!picks.length) { toast('タスクを選択してください', '✏️'); return; }
    await api.post('/api/tasks/bulk', { tasks: picks.map(p => ({ title: p.title, due_date: p.due_date, priority: p.priority, source_text: '議事録より自動抽出', status: '未着手', company_id: ctx.company_id, deal_id: ctx.deal_id })) });
    closeModal(); toast(`${picks.length}件のタスクを登録しました`, '📌'); navigate('tasks');
  };
}
window.editMeeting = (id) => meetingForm((window._meetings || []).find(m => m.id == id) || {});
window.delMeeting = async (id) => { if (confirm('この面談を削除しますか？')) { await api.del('/api/meetings/' + id); toast('削除しました'); navigate('meetings'); } };

/* =========================================================================
   ⑦ 営業育成システム
   ========================================================================= */
VIEWS.training = async function () {
  const member = localStorage.getItem('member') || '自分';
  const [modules, progress] = await Promise.all([api.get('/api/training/modules'), api.get('/api/training/progress?member=' + encodeURIComponent(member))]);
  const pmap = {}; progress.forEach(p => pmap[p.module_id] = p);
  const done = modules.filter(m => pmap[m.id] && pmap[m.id].status === '習得').length;
  const pct = modules.length ? Math.round(done / modules.length * 100) : 0;
  window._modules = modules;

  const cats = {};
  modules.forEach(m => { (cats[m.category] = cats[m.category] || []).push(m); });
  const catHtml = Object.entries(cats).map(([cat, mods]) => `
    <div class="panel"><h3>📚 ${esc(cat)}</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>カリキュラム</th><th style="width:130px">習得状況</th><th style="width:80px">理解度</th><th></th></tr></thead>
        <tbody>${mods.map(m => { const p = pmap[m.id] || {};
          return `<tr>
            <td><span class="list-link" onclick="showModule(${m.id})">${esc(m.title)}</span></td>
            <td><select class="inline-edit" style="width:115px" onchange="setProgress(${m.id}, this.value)">${['未学習', '学習中', '習得'].map(s => `<option ${p.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
            <td>${p.score != null ? `<span class="badge ${p.score >= 70 ? 'green' : 'amber'}">${p.score}点</span>` : '<span class="muted">—</span>'}</td>
            <td class="right"><button class="btn sm ghost" onclick="scoreModule(${m.id})">採点</button></td>
          </tr>`; }).join('')}</tbody>
      </table></div>
    </div>`).join('');

  $('#view').innerHTML = `
    <div class="panel">
      <div class="section-row">
        <div><div class="muted" style="font-size:12px;font-weight:600;margin-bottom:4px">学習者</div>
          <input id="member-name" value="${esc(member)}" class="inline-edit" style="width:160px"></div>
        <div style="text-align:right"><div class="muted" style="font-size:12px">習得率</div><strong style="font-size:22px">${pct}%</strong> <span class="muted">（${done}/${modules.length}）</span></div>
      </div>
      <div class="pbar"><i style="width:${pct}%"></i></div>
    </div>
    ${catHtml}`;
  $('#member-name').onchange = (e) => { localStorage.setItem('member', e.target.value.trim() || '自分'); navigate('training'); };
};
window.showModule = (id) => {
  const m = window._modules.find(x => x.id == id);
  openModal(m.title, `<div class="badge blue" style="margin-bottom:14px">${esc(m.category)}</div>
    <div style="white-space:pre-wrap;line-height:1.9">${esc(m.content)}</div>
    <div class="form-actions" style="margin-top:18px"><button class="btn soft" onclick="scoreModule(${id})">この内容を採点する</button><button class="btn ghost" onclick="closeModal()">閉じる</button></div>`);
};
window.setProgress = async (moduleId, status) => { const member = localStorage.getItem('member') || '自分'; await api.post('/api/training/progress', { module_id: moduleId, member, status }); toast('進捗を保存しました'); };
window.scoreModule = (moduleId) => {
  const m = window._modules.find(x => x.id == moduleId);
  openModal('理解度チェック：' + m.title, `
    <div class="field"><label>理解度（0〜100点）</label><input id="sc-score" type="number" min="0" max="100" placeholder="例）80"><div class="hint">70点以上で「習得」になります。空欄なら点数は記録しません。</div></div>
    <div class="field"><label>メモ・振り返り</label><textarea id="sc-memo" placeholder="できたこと・課題など"></textarea></div>
    <div class="form-actions"><button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="sc-save">保存</button></div>`);
  $('#sc-save').onclick = async () => {
    const member = localStorage.getItem('member') || '自分';
    const raw = $('#sc-score').value.trim();
    const score = raw === '' ? null : Math.max(0, Math.min(100, Number(raw)));
    const status = score == null ? '学習中' : (score >= 70 ? '習得' : '学習中');
    await api.post('/api/training/progress', { module_id: moduleId, member, status, score, memo: $('#sc-memo').value });
    closeModal(); toast('採点を保存しました'); navigate('training');
  };
};

/* =========================================================================
   音声入力 (Web Speech API)
   continuous=true で連続認識。確定テキストを onText に逐次渡す。
   ========================================================================= */
function setupMic(btnId, hintId, onText, continuous = false) {
  const btn = $('#' + btnId);
  const hint = $('#' + hintId);
  if (!btn) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { btn.disabled = true; if (hint) hint.textContent = 'この環境は音声入力に非対応（Chrome/Edge推奨）'; return; }

  let rec = null, active = false;
  btn.onclick = () => {
    if (active) { try { rec && rec.stop(); } catch (e) {} return; }
    rec = new SR();
    rec.lang = 'ja-JP';
    rec.interimResults = true;
    rec.continuous = continuous;
    rec.onstart = () => { active = true; btn.classList.add('recording'); btn.innerHTML = continuous ? '⏹ 停止' : '⏹'; if (hint) hint.textContent = '🔴 聞き取り中…'; };
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const tr = e.results[i][0].transcript;
        if (e.results[i].isFinal) { if (tr.trim()) onText(tr.trim()); }
        else interim += tr;
      }
      if (hint) hint.textContent = interim ? '🟢 ' + interim.slice(-50) : '🔴 聞き取り中…';
    };
    rec.onerror = (e) => { if (hint) hint.textContent = '⚠ ' + (e.error === 'not-allowed' ? 'マイクの使用を許可してください' : e.error === 'no-speech' ? '音声が検出されませんでした' : e.error); };
    rec.onend = () => {
      active = false; btn.classList.remove('recording');
      btn.innerHTML = btn.id.includes('whole') || btn.id.includes('extract') ? '🎤 録音開始' : (btn.id.includes('min') ? '🎤 音声' : '🎤');
      if (hint && hint.textContent.startsWith('🔴')) hint.textContent = '✅ 入力しました';
      clearTimeout(hint && hint._t);
      if (hint) hint._t = setTimeout(() => { if (hint.textContent === '✅ 入力しました') hint.textContent = ''; }, 2200);
    };
    try { rec.start(); } catch (e) { if (hint) hint.textContent = '⚠ 開始できませんでした'; active = false; btn.classList.remove('recording'); }
  };
}

/* =========================================================================
   AI議事録（音声→文字起こし→議事録/要約/次アクション/話者分離）
   ========================================================================= */
const AI_STATUS_BADGE = { queued: 'amber', processing: 'blue', transcribed: 'sky', summarizing: 'blue', summarized: 'green', error: 'red' };
const AI_STATUS_LABEL = { queued: '順番待ち', processing: '文字起こし中', transcribed: '文字起こし済', summarizing: '議事録生成中', summarized: '完了', error: 'エラー' };

async function uploadForm(url, fd) {
  const res = await fetch(url, { method: 'POST', body: fd });
  if (!res.ok) { let m = 'エラー'; try { const j = await res.json(); m = j.detail || m; } catch (e) {} throw new Error(m); }
  return res.json();
}
function aiMd(md) {
  if (!md) return '';
  const lines = String(md).split('\n'); let html = '', inList = false;
  const inl = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  for (let line of lines) {
    if (/^###?\s/.test(line)) { if (inList) { html += '</ul>'; inList = false; } const lv = line.startsWith('###') ? 3 : 2; html += `<h${lv}>${inl(line.replace(/^#+\s/, ''))}</h${lv}>`; }
    else if (/^[-*]\s/.test(line)) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${inl(line.replace(/^[-*]\s/, ''))}</li>`; }
    else { if (inList) { html += '</ul>'; inList = false; } if (line.trim()) html += `<p>${inl(line)}</p>`; }
  }
  if (inList) html += '</ul>';
  return html;
}

VIEWS.minutes = async function () {
  $('#topbar-actions').innerHTML = '';
  const health = await api.get('/api/ai/health').catch(() => ({}));
  window._aiHealth = health;
  const demoBanner = health.demo_mode
    ? `<div class="panel" style="background:#fef9c3;border-color:#fde68a;color:#854d0e">🧪 デモモード: APIキー不要のサンプル応答で動作中(文字起こし・議事録はダミー)。本番は .env に DEMO_MODE=false と各APIキーを設定。</div>`
    : (!health.anthropic_configured ? `<div class="panel" style="background:#fee2e2;border-color:#fecaca;color:#b91c1c">⚠ APIキー未設定です。.env に ANTHROPIC_API_KEY（議事録生成）と OPENAI_API_KEY（文字起こし）を設定するか、DEMO_MODE=true でお試しください。</div>` : '');

  $('#view').innerHTML = `
    ${demoBanner}
    <div class="panel">
      <h3 style="margin:0 0 12px">音声・テキストを取り込む</h3>
      <div class="grid2">
        <div class="field"><label>タイトル *</label><input id="ai-title" placeholder="例: ○○社 商談（一次）"></div>
        <div class="field"><label>関連商談</label><select id="ai-deal">${dealOptions()}</select></div>
      </div>
      <div class="grid2">
        <div class="field"><label>顧客企業</label><select id="ai-company">${companyOptions()}</select></div>
        <div class="field"><label><input type="checkbox" id="ai-diarize" style="width:auto"> 🗣️ 本格的な話者分離（誰が話したか）</label></div>
      </div>
      <div class="grid3" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:8px">
        <div class="field"><label>A. 音声ファイル</label><input type="file" id="ai-file" accept="audio/*"><button class="btn" id="ai-upload" style="margin-top:6px;width:100%">アップロード</button></div>
        <div class="field"><label>B. ブラウザ録音</label><button class="btn" id="ai-rec-start" style="width:100%">● 録音開始</button><button class="btn ghost" id="ai-rec-stop" style="width:100%;margin-top:6px" disabled>■ 停止</button><span id="ai-rec-timer" class="voice-hint"></span></div>
        <div class="field"><label>C. テキスト貼付</label><textarea id="ai-text" rows="2" placeholder="文字起こし済テキスト"></textarea><button class="btn" id="ai-text-btn" style="margin-top:6px;width:100%">記録を作成</button></div>
      </div>
      <div id="ai-status" class="voice-hint" style="margin-top:8px;min-height:18px"></div>
    </div>
    <div class="panel">
      <div class="toolbar"><div class="search"><span class="si">🔍</span><input id="ai-search" placeholder="タイトル・要約で検索…"></div></div>
      <div class="table-wrap"><table>
        <thead><tr><th>作成</th><th>タイトル</th><th>顧客/商談</th><th>状態</th><th>タグ</th><th></th></tr></thead>
        <tbody id="ai-tbody"></tbody>
      </table></div>
    </div>`;

  $('#ai-upload').onclick = () => { const f = $('#ai-file').files[0]; if (!f) return toast('ファイルを選択してください', '✏️'); aiUpload(f); };
  $('#ai-text-btn').onclick = aiCreateFromText;
  $('#ai-search').oninput = renderMinutesList;
  setupAiRecorder();
  await loadMinutesList();
};

async function loadMinutesList() {
  window._minutes = await api.get('/api/minutes');
  renderMinutesList();
}
function renderMinutesList() {
  const q = ($('#ai-search') ? $('#ai-search').value || '' : '').toLowerCase();
  const rows = (window._minutes || []).filter(m => !q || (m.title || '').toLowerCase().includes(q) || (m.summary || '').toLowerCase().includes(q)).map(m => {
    const tags = (m.tags || []).map(t => `<span class="chip">${esc(t)}</span>`).join('');
    const rel = esc(m.company_name || m.deal_title || '') || '<span class="muted">—</span>';
    return `<tr>
      <td class="nowrap">${fmtDateTime(m.created_at)}</td>
      <td><span class="list-link" onclick="openMinutes(${m.id})">${esc(m.title)}</span></td>
      <td>${rel}</td>
      <td>${badge(AI_STATUS_BADGE, m.ai_status)} ${esc(AI_STATUS_LABEL[m.ai_status] || '')}</td>
      <td>${tags || '<span class="muted">—</span>'}</td>
      <td class="right"><button class="icon-btn" onclick="delMinutes(${m.id})">🗑</button></td>
    </tr>`;
  }).join('');
  $('#ai-tbody').innerHTML = rows || emptyRow(6, 'まだ記録がありません。音声かテキストを取り込んでください', '🎙️');
}

function aiSetStatus(msg) { const el = $('#ai-status'); if (el) el.textContent = msg; }

async function aiUpload(file) {
  const title = $('#ai-title').value.trim() || '無題の記録';
  const fd = new FormData();
  fd.append('file', file); fd.append('title', title);
  fd.append('diarize', $('#ai-diarize').checked ? 'true' : 'false');
  fd.append('auto_generate', 'true');
  if ($('#ai-company').value) fd.append('company_id', $('#ai-company').value);
  if ($('#ai-deal').value) fd.append('deal_id', $('#ai-deal').value);
  aiSetStatus('⏳ アップロード中…');
  try {
    const r = await uploadForm('/api/minutes/upload', fd);
    await aiPoll(r.id);
  } catch (e) { aiSetStatus('❌ ' + e.message); }
}
async function aiCreateFromText() {
  const text = $('#ai-text').value.trim();
  if (!text) return toast('テキストを入力してください', '✏️');
  aiSetStatus('記録を作成中…');
  try {
    const r = await api.post('/api/minutes/text', { title: $('#ai-title').value.trim() || '無題の記録', transcript: text, company_id: $('#ai-company').value || null, deal_id: $('#ai-deal').value || null });
    aiSetStatus('🤖 議事録を生成中…');
    await api.post(`/api/minutes/${r.id}/generate`, {});
    aiSetStatus('✅ 完了しました');
    await loadMinutesList(); openMinutes(r.id);
  } catch (e) { aiSetStatus('❌ ' + e.message); }
}
async function aiPoll(id) {
  for (let i = 0; i < 600; i++) {
    let m; try { m = await api.get('/api/minutes/' + id); } catch (e) { aiSetStatus('❌ ' + e.message); return; }
    aiSetStatus((m.ai_status === 'error' ? '❌ ' : (m.ai_status === 'summarized' ? '✅ ' : '⏳ ')) + (AI_STATUS_LABEL[m.ai_status] || m.ai_status) + (m.ai_status === 'error' && m.error_message ? '：' + m.error_message : ''));
    if (m.ai_status === 'summarized' || m.ai_status === 'error') { await loadMinutesList(); if (m.ai_status === 'summarized') openMinutes(id); return; }
    await new Promise(r => setTimeout(r, 2500));
  }
  aiSetStatus('タイムアウトしました');
}

async function openMinutes(id) {
  const m = await api.get('/api/minutes/' + id);
  const decisions = (m.decisions || []).map(d => `<li>${esc(d)}</li>`).join('');
  const actions = (m.next_actions || []).map(a => `<div class="action-row">☐ ${esc(a.task || a)}${a.owner ? ` <b>@${esc(a.owner)}</b>` : ''}${a.due ? ` ⏰${esc(a.due)}` : ''}</div>`).join('');
  const tags = (m.tags || []).map(t => `<span class="chip">${esc(t)}</span>`).join('');
  let spk = '';
  if (m.utterances && m.utterances.length) {
    const labels = [...new Set(m.utterances.map(u => u.speaker))].sort();
    const map = m.speaker_map || {};
    spk = `<div class="field" style="background:#f0f9ff;padding:10px;border-radius:8px">
      <label>👤 話者の名前を割り当てる</label>
      <div id="ai-spk-${id}">${labels.map(l => `話者${esc(l)} <input data-spk="${esc(l)}" value="${esc(map[l] || '')}" placeholder="実名" style="width:130px;display:inline-block;margin:2px 8px 2px 2px">`).join('')}
      <button class="btn soft" onclick="applyMinutesSpeakers(${id})">名前を適用</button></div></div>`;
  }
  const canRe = m.ai_status === 'error' && m.audio_filename;
  const html = `
    ${m.ai_status === 'error' ? `<div class="voice-hint" style="color:#b91c1c">❌ ${esc(m.error_message || '処理に失敗しました')}</div>` : ''}
    <div class="muted" style="font-size:13px">状態: ${esc(AI_STATUS_LABEL[m.ai_status] || m.ai_status || '—')} / 顧客: ${esc(m.company_name || '—')} / 商談: ${esc(m.deal_title || '—')}</div>
    <div style="margin:6px 0">${tags}</div>
    ${spk}
    ${m.summary ? `<h3>📝 要約</h3><div class="ai-box">${esc(m.summary)}</div>` : ''}
    ${decisions ? `<h3>✅ 決定事項</h3><ul>${decisions}</ul>` : ''}
    ${actions ? `<h3>📌 次のアクション</h3>${actions}` : ''}
    ${m.minutes_md ? `<h3>📄 議事録</h3><div class="ai-box">${aiMd(m.minutes_md)}</div>` : ''}
    ${m.dialogue_md ? `<details open><summary>🗣️ 発言録</summary><div class="ai-box">${aiMd(m.dialogue_md)}</div></details>` : ''}
    ${m.transcript ? `<details><summary>🎧 文字起こし全文</summary><div class="ai-box">${esc(m.transcript).replace(/\n/g, '<br>')}</div></details>` : ''}
    <div class="form-actions" style="margin-top:14px;flex-wrap:wrap;gap:6px">
      ${!m.summary ? `<button class="btn" onclick="genMinutes(${id})">🤖 議事録を生成</button>` : `<button class="btn soft" onclick="genMinutes(${id})">🔄 再生成</button>`}
      ${m.next_actions && m.next_actions.length ? `<button class="btn soft" onclick="actionsToTasks(${id})">📋 次アクションをタスク化</button>` : ''}
      ${m.summary ? `<button class="btn ghost" onclick="window.open('/api/minutes/${id}/export.md','_blank')">⬇️ Markdown</button>` : ''}
      ${canRe ? `<button class="btn soft" onclick="reprocessMinutes(${id})">🔄 音声から再処理</button>` : ''}
      <span class="spacer"></span><button class="btn ghost" onclick="delMinutes(${id})">削除</button>
    </div>`;
  openModal(esc(m.title), html, true);
}
window.openMinutes = openMinutes;

async function genMinutes(id) {
  try { toast('生成中…', '🤖'); await api.post(`/api/minutes/${id}/generate`, {}); await loadMinutesList(); openMinutes(id); }
  catch (e) { toast(e.message, '⚠'); }
}
window.genMinutes = genMinutes;
async function applyMinutesSpeakers(id) {
  const c = $('#ai-spk-' + id); const map = {};
  $$('input[data-spk]', c).forEach(i => { if (i.value.trim()) map[i.dataset.spk] = i.value.trim(); });
  try { await api.patch(`/api/minutes/${id}/speakers`, { speaker_map: map }); openMinutes(id); toast('話者名を適用しました'); }
  catch (e) { toast(e.message, '⚠'); }
}
window.applyMinutesSpeakers = applyMinutesSpeakers;
async function actionsToTasks(id) {
  try { const r = await api.post(`/api/minutes/${id}/actions_to_tasks`, {}); toast(`${r.created}件をタスクに登録しました`, '📋'); }
  catch (e) { toast(e.message, '⚠'); }
}
window.actionsToTasks = actionsToTasks;
async function reprocessMinutes(id) {
  try { await api.post(`/api/minutes/${id}/reprocess`, {}); closeModal(); aiSetStatus('🔄 再処理中…'); await aiPoll(id); }
  catch (e) { toast(e.message, '⚠'); }
}
window.reprocessMinutes = reprocessMinutes;
async function delMinutes(id) {
  if (!confirm('この記録を削除しますか？')) return;
  await api.del('/api/meetings/' + id); closeModal(); await loadMinutesList(); toast('削除しました');
}
window.delMinutes = delMinutes;

let _aiRec = null, _aiChunks = [], _aiTimer = null, _aiSec = 0;
function setupAiRecorder() {
  const start = $('#ai-rec-start'), stop = $('#ai-rec-stop');
  if (!start) return;
  start.onclick = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      _aiRec = new MediaRecorder(stream); _aiChunks = [];
      _aiRec.ondataavailable = e => _aiChunks.push(e.data);
      _aiRec.onstop = () => { stream.getTracks().forEach(t => t.stop()); const blob = new Blob(_aiChunks, { type: 'audio/webm' }); aiUpload(new File([blob], 'rec.webm', { type: 'audio/webm' })); };
      _aiRec.start(); start.disabled = true; stop.disabled = false;
      _aiSec = 0; $('#ai-rec-timer').textContent = '00:00';
      _aiTimer = setInterval(() => { _aiSec++; $('#ai-rec-timer').textContent = `${String((_aiSec / 60) | 0).padStart(2, '0')}:${String(_aiSec % 60).padStart(2, '0')}`; }, 1000);
    } catch (e) { aiSetStatus('マイク取得失敗: ' + e.message); }
  };
  stop.onclick = () => { if (_aiRec) _aiRec.stop(); clearInterval(_aiTimer); start.disabled = false; stop.disabled = true; };
}

/* ---- ログイン認証 ---- */
async function doLogin() {
  const msg = $('#login-msg');
  try {
    await api.post('/api/auth/login', { password: $('#login-pw').value });
    $('#login-overlay').classList.add('hidden');
    startApp();
  } catch (e) { msg.textContent = e.message; }
}
async function checkAuthAndStart() {
  let me;
  try { me = await api.get('/api/auth/me'); } catch (e) { startApp(); return; }
  if (me.auth_enabled && !me.authenticated) {
    $('#login-overlay').classList.remove('hidden');
    const btn = $('#login-btn'); if (btn) btn.onclick = doLogin;
    const pw = $('#login-pw'); if (pw) pw.onkeydown = (e) => { if (e.key === 'Enter') doLogin(); };
    return;
  }
  if (me.auth_enabled) {
    const ll = $('#logout-link');
    if (ll) ll.innerHTML = '<a href="#" id="do-logout" style="color:#94a3b8">ログアウト</a>';
    const dl = $('#do-logout'); if (dl) dl.onclick = async (e) => { e.preventDefault(); await api.post('/api/auth/logout', {}); location.reload(); };
  }
  startApp();
}
function startApp() { navigate('dashboard'); }

/* ---- 起動 ---- */
checkAuthAndStart();
