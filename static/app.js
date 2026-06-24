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
const STAGE_BADGE = { '反響・予約': 'gray', '人生相談': 'blue', 'プレゼン': 'violet', '交渉': 'amber', '契約': 'green', '失注': 'red' };
const STATUS_BADGE = { '未着手': 'gray', '進行中': 'amber', '完了': 'green', '予定': 'blue', '実施済': 'green', '中止': 'red' };
const PRIORITY_BADGE = { '高': 'red', '中': 'amber', '低': 'gray' };
const STAGE_COLOR = { '反響・予約': '#94a3b8', '人生相談': '#6366f1', 'プレゼン': '#7c3aed', '交渉': '#f59e0b', '契約': '#15a06b', '失注': '#e11d48' };
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
$$('.nav-item').forEach(b => b.onclick = () => { navigate(b.dataset.view); closeNav(); });
const emptyRow = (cols, msg, ico = '📭') => `<tr><td colspan="${cols}" class="empty"><span class="em-ico">${ico}</span>${msg}</td></tr>`;

/* ---------- モバイル：ハンバーガー開閉 ---------- */
function closeNav() { document.body.classList.remove('nav-open'); }
(function setupNav() {
  const h = $('#hamburger'), ov = $('#nav-overlay');
  if (h) h.onclick = () => document.body.classList.toggle('nav-open');
  if (ov) ov.onclick = closeNav;
})();

/* ダッシュボードの記録をクリックで開く（該当ビューへ移動して該当レコードを開く） */
window.dashOpen = async (view, fn, id) => { await navigate(view); if (typeof window[fn] === 'function') window[fn](id); };
window.dashAct = (type) => navigate({ deal: 'pipeline', meeting: 'meetings', hearing: 'hearing', task: 'tasks', training: 'training' }[type] || 'dashboard');

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
    return `<div class="list-item clickable" onclick="dashOpen('tasks','editTask',${t.id})"><div class="li-ico ${bdg(PRIORITY_BADGE, t.priority) === 'red' ? 'ic-red' : 'ic-amber'}">●</div>
      <div class="li-main"><div class="li-title">${esc(t.title)}</div><div class="li-sub">${esc(t.company_name) || '顧客未設定'}</div></div>
      <div class="li-right ${di.cls}">${di.label}</div></div>`;
  }).join('') : `<div class="empty" style="padding:24px"><span class="em-ico">🎉</span>未完了タスクはありません</div>`;

  // 予定の面談
  const meetHtml = d.upcoming_meeting_list.length ? d.upcoming_meeting_list.map(m =>
    `<div class="list-item clickable" onclick="dashOpen('meetings','editMeeting',${m.id})"><div class="li-ico ic-sky">📅</div>
      <div class="li-main"><div class="li-title">${esc(m.title)}</div><div class="li-sub">${esc(m.company_name) || '顧客未設定'}・${esc(m.meeting_type)}</div></div>
      <div class="li-right">${fmtDateTime(m.scheduled_at)}</div></div>`).join('')
    : `<div class="empty" style="padding:24px"><span class="em-ico">🗓️</span>予定の面談はありません</div>`;

  // アクティビティ
  const actHtml = acts.length ? acts.map(a =>
    `<div class="list-item clickable" onclick="dashAct('${a.type}')"><div class="li-ico ic-blue">${a.icon}</div>
      <div class="li-main"><div class="li-title">${esc(a.text)}</div><div class="li-sub">${esc(a.company) || '—'}</div></div>
      <div class="li-right">${fmtDateTime(a.ts)}</div></div>`).join('')
    : `<div class="empty">履歴はまだありません</div>`;

  $('#view').innerHTML = `
    <div class="cards">
      ${statCard('🏆', 'ic-amber', '成約率', d.win_rate + '%', `契約${d.won}/失注${d.lost}`)}
      ${statCard('💴', 'ic-green', '平均成約単価', yen(d.avg_won_amount || 0), '契約1件あたり', 'sm')}
      ${statCard('🎯', 'ic-sky', '売上予測', yen(d.weighted_amount), '金額×確度', 'sm')}
      ${statCard('📅', 'ic-violet', '今週の面談', (d.this_week_meetings || 0), `予約 ${d.upcoming_meetings}件`)}
      ${statCard('📈', 'ic-blue', '進行中の商談', d.open_deals, '契約/失注を除く')}
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
  const adminBtn = (ME && ME.is_admin) ? `<button class="btn ghost" id="hs-btn">🔗 HubSpot</button> ` : '';
  $('#topbar-actions').innerHTML = `${adminBtn}<button class="btn ghost" id="add-contact">＋ 担当者</button> <button class="btn" id="add-company">＋ 顧客企業</button>`;
  $('#add-company').onclick = () => companyForm();
  $('#add-contact').onclick = () => contactForm();
  const hsb = $('#hs-btn'); if (hsb) hsb.onclick = hubspotPanel;

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
  (c.hearings || []).forEach(h => acts.push({ ico: '🎤', t: `人生相談カルテ「${h.title}」`, ts: h.created_at }));
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
      <button class="btn sm soft" onclick="quickHearing(${id})">＋ 相談カルテ</button>
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

async function hubspotPanel() {
  let st = { configured: false };
  try { st = await api.get('/api/integrations/hubspot/status'); } catch (e) {}
  const body = st.configured
    ? `<p class="muted" style="font-size:12.5px;margin-bottom:14px">✅ HubSpot 連携が有効です（HUBSPOT_TOKEN 設定済み）。</p>
       <div class="chip-row">
         <button class="btn" id="hs-push">⬆ ローカル → HubSpotへ送信</button>
         <button class="btn ghost" id="hs-pull">⬇ HubSpotの会社を取り込み</button>
       </div>
       <div id="hs-result" style="margin-top:14px"></div>`
    : `<p class="muted" style="font-size:12.5px;line-height:1.7">
         ⚠️ まだ連携が設定されていません。<br>
         HubSpotの <b>Private App トークン</b> を取得し、サーバーの <code>.env</code> に
         <code>HUBSPOT_TOKEN=...</code> を追加して再起動すると有効になります。<br>
         （会社・担当者・商談を双方向で同期できます）
       </p>`;
  openModal('🔗 HubSpot 連携', body);
  if (!st.configured) return;
  const run = async (path, label) => {
    const box = $('#hs-result'); box.innerHTML = `<span class="muted">${label}中…</span>`;
    try {
      const r = await api.post(path, {});
      if (r.ok === false) { box.innerHTML = `<span style="color:var(--red)">失敗：${esc(r.error || '')}</span>`; return; }
      const parts = [];
      if (r.companies != null) parts.push(`会社 ${r.companies}`);
      if (r.contacts != null) parts.push(`担当者 ${r.contacts}`);
      if (r.deals != null) parts.push(`商談 ${r.deals}`);
      if (r.imported != null) parts.push(`取込 ${r.imported}`);
      if (r.updated != null) parts.push(`更新 ${r.updated}`);
      let html = `<div class="badge green">完了</div> ${esc(parts.join(' / '))}`;
      if (r.errors && r.errors.length) html += `<div style="margin-top:8px;color:var(--amber);font-size:12px">${r.errors.map(esc).join('<br>')}</div>`;
      box.innerHTML = html;
    } catch (e) { box.innerHTML = `<span style="color:var(--red)">失敗：${esc(e.message)}</span>`; }
  };
  $('#hs-push').onclick = () => run('/api/integrations/hubspot/push', '送信');
  $('#hs-pull').onclick = () => run('/api/integrations/hubspot/pull', '取り込み');
}
window.hubspotPanel = hubspotPanel;

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
  const totalOpen = deals.filter(d => !['契約', '失注'].includes(d.stage)).reduce((s, d) => s + (d.amount || 0), 0);
  const weighted = deals.filter(d => !['契約', '失注'].includes(d.stage)).reduce((s, d) => s + (d.amount || 0) * (d.probability || 0) / 100, 0);

  const cols = CACHE.stages.map(stage => {
    const items = deals.filter(d => d.stage === stage);
    const sum = items.reduce((s, d) => s + (d.amount || 0), 0);
    const cards = items.map(d => {
      const pc = presCount(d.presentation);
      return `
      <div class="kcard" draggable="true" data-id="${d.id}" style="border-left-color:${STAGE_COLOR[stage]}">
        <div class="kt">${esc(d.title)}</div>
        <div class="kc">🏢 ${esc(d.company_name) || '顧客未設定'}</div>
        <div class="kbot"><span class="kamount">${yen(d.amount)}</span><span class="kprob">確度${d.probability || 0}%</span></div>
        ${pc ? `<div style="font-size:11px;color:#4338ca;margin-top:4px">📋 4章プレゼン ${pc}/${PRES_STEPS.length}</div>` : ''}
      </div>`; }).join('');
    return `<div class="kcol" data-stage="${stage}">
      <div class="kcol-head"><span>${badge(STAGE_BADGE, stage)}</span><span class="cnt">${items.length}</span></div>
      <div class="kcol-sum">${sum ? yen(sum) : '　'}</div>
      <div class="kcol-body">${cards || '<div class="muted" style="text-align:center;font-size:11.5px;padding:14px 0">―</div>'}</div>
    </div>`;
  }).join('');

  $('#view').innerHTML = `
    <div class="cards" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr))">
      <div class="stat"><div class="label">パイプライン総額</div><div class="num sm">${yen(totalOpen)}</div><div class="sub">進行中の合計</div></div>
      <div class="stat"><div class="label">売上予測</div><div class="num sm" style="color:var(--green)">${yen(Math.round(weighted))}</div><div class="sub">金額×確度</div></div>
      <div class="stat"><div class="label">進行中の商談</div><div class="num">${deals.filter(d => !['契約', '失注'].includes(d.stage)).length}</div><div class="sub">件</div></div>
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

const PRES_STEPS = ['人生相談', '①家は買うべき', '②今買うべき', '③ここを買うべき', '④うちから買うべき', '資金計画', 'クロージング'];
function presCount(presJson) {
  let p = {}; try { p = JSON.parse(presJson || '{}'); } catch (e) {}
  return PRES_STEPS.filter(s => p[s]).length;
}
function dealForm(data = {}) {
  const editing = !!data.id;
  let pres = {}; try { pres = JSON.parse(data.presentation || '{}'); } catch (e) {}
  const presHtml = editing ? `<div class="field"><label>📋 4章プレゼン進捗（クリックで✓）</label>
    <div id="d-pres" style="display:flex;flex-wrap:wrap;gap:6px 14px;background:#f8fafc;padding:10px;border-radius:8px">
      ${PRES_STEPS.map(s => `<label style="font-size:13px;font-weight:500;display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" data-step="${esc(s)}" ${pres[s] ? 'checked' : ''} style="width:auto"> ${esc(s)}</label>`).join('')}
    </div></div>` : '';
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
      <div class="field"><label>契約予定日</label><input id="d-close" type="date" value="${(data.expected_close || '').slice(0, 10)}"></div>
      <div class="field"><label>担当者</label><input id="d-owner" value="${esc(data.owner)}"></div>
    </div>
    <div class="field"><label>メモ</label><textarea id="d-notes">${esc(data.notes)}</textarea></div>
    ${presHtml}
    ${editing ? `<div class="chip-row" style="margin-bottom:14px"><button class="btn sm soft" onclick="quickMeeting(${data.company_id || 'null'})">＋ 面談設定</button><button class="btn sm soft" onclick="quickTask(${data.company_id || 'null'})">＋ タスク</button></div>` : ''}
    <div class="form-actions">${editing ? `<button class="btn danger" onclick="delDeal(${data.id})">削除</button>` : ''}<span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="d-save">${editing ? '保存' : '登録'}</button></div>`);
  $('#d-save').onclick = async () => {
    const title = $('#d-title').value.trim();
    if (!title) { toast('商談名を入力してください', '✏️'); return; }
    const body = { title, company_id: $('#d-company').value || null, stage: $('#d-stage').value, amount: Number($('#d-amount').value) || 0, probability: Number($('#d-prob').value) || 0, expected_close: $('#d-close').value || null, owner: $('#d-owner').value, notes: $('#d-notes').value };
    if (editing) {
      await api.put('/api/deals/' + data.id, body);
      const presState = {};
      $$('#d-pres input[data-step]').forEach(i => { if (i.checked) presState[i.dataset.step] = true; });
      await api.patch('/api/deals/' + data.id + '/presentation', { presentation: presState });
    } else {
      await api.post('/api/deals', body);
    }
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
   ⑤ 人生相談カルテ（人生6大項目・音声自動入力）
   ========================================================================= */
const HEARING_FIELDS = [
  ['current_situation', '① 家計の現状', '収入・支出・貯蓄・家賃／住居費・ローン返済など'],
  ['challenges', '② 住環境(今の住まい・理想)', '今の住まいの不満、理想の暮らし・間取り・立地'],
  ['needs', '③ 万が一への備え', '生命保険・遺族の保障・もしもの備え'],
  ['budget', '④ 老後への備え', '老後資金・年金・セカンドライフの見通し'],
  ['authority', '⑤ 災害への備え', '地震・水害・防災・ハザード状況'],
  ['timeline', '⑥ 健康・病気への備え', '健康状態・持病・医療/介護への備え'],
  ['competitors', 'お客様の想い・背景', '家族構成・将来像・大切にしたい価値観'],
  ['next_action', '次の一手', '次回の提案・宿題・約束事'],
];

VIEWS.hearing = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn" id="new-hearing">＋ 新規カルテ</button>`;
  $('#new-hearing').onclick = () => hearingForm();
  window._hearings = await api.get('/api/hearings');
  $('#view').innerHTML = `
    <div class="panel">
      <div class="toolbar"><div class="search"><span class="si">🔍</span><input id="h-search" placeholder="タイトル・顧客で検索…"></div></div>
      <p class="muted" style="margin:4px 0 12px;font-size:12.5px">🎤 人生6大項目（家計・住環境・万が一・老後・災害・病気）を一緒に整理。各項目のマイク、または「シート全体を音声入力」で話すだけでAIが振り分けます（Chrome/Edge推奨）。</p>
      <div class="table-wrap"><table>
        <thead><tr><th>タイトル</th><th>顧客</th><th>相談内容（抜粋）</th><th>作成日</th><th></th></tr></thead>
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
  $('#h-tbody').innerHTML = rows || emptyRow(5, '人生相談カルテがまだありません', '🎤');
}

function hearingForm(data = {}) {
  const editing = !!data.id;
  const fieldHtml = HEARING_FIELDS.map(([key, label, ph]) => `
    <div class="field">
      <div class="field-row-mic"><label>${label}</label>
        <span><button type="button" class="mic-btn" id="mic-${key}">🎤</button><span class="voice-hint" id="mic-${key}-hint"></span></span></div>
      <textarea id="h-${key}" placeholder="${ph}">${esc(data[key])}</textarea>
    </div>`).join('');

  openModal(editing ? '人生相談カルテ編集' : '新規 人生相談カルテ', `
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
    ${editing ? `<div class="field" style="background:#f0f9ff;padding:10px;border-radius:8px">
      <div class="form-actions" style="justify-content:flex-start;margin:0"><label style="margin:0">🤖 AI提案トーク</label><button class="btn sm" id="gen-talk">${data.talk_points ? '再生成' : '生成'}</button></div>
      <div id="talk-box" class="ai-box" style="margin-top:8px;${data.talk_points ? '' : 'display:none'}">${data.talk_points ? aiMd(data.talk_points) : ''}</div>
    </div>` : '<p class="muted" style="font-size:12px">※ AI提案トークは、一度保存してから生成できます。</p>'}
    <div class="form-actions"><button class="btn soft" id="h-to-task">📌 次アクションをタスク化</button><span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="h-save">${editing ? '保存' : '登録'}</button></div>`, true);

  HEARING_FIELDS.forEach(([key]) => setupMic('mic-' + key, 'mic-' + key + '-hint', (text) => { const ta = $('#h-' + key); ta.value = (ta.value ? ta.value + ' ' : '') + text; }));
  setupMic('mic-whole', 'mic-whole-hint', (text) => { const ta = $('#h-raw'); ta.value = (ta.value ? ta.value + ' ' : '') + text; }, true);

  const gt = $('#gen-talk');
  if (gt) gt.onclick = async () => {
    gt.disabled = true; const o = gt.textContent; gt.textContent = '🤖 生成中…';
    try { const r = await api.post('/api/hearings/' + data.id + '/talk_points', {}); const b = $('#talk-box'); b.style.display = ''; b.innerHTML = aiMd(r.talk_points); toast('提案トークを生成しました'); gt.textContent = '再生成'; }
    catch (e) { toast(e.message, '⚠'); gt.textContent = o; }
    finally { gt.disabled = false; }
  };

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
    await api.post('/api/tasks', { title: na, source_text: '人生相談カルテより', priority: '中', status: '未着手', company_id: $('#h-company').value || null, deal_id: $('#h-deal').value || null });
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
window.delHearing = async (id) => { if (confirm('この人生相談カルテを削除しますか？')) { await api.del('/api/hearings/' + id); toast('削除しました'); navigate('hearing'); } };

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
      <div class="table-wrap"><table class="train-tbl">
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
   ⑧ 幸せ意識度チェック（飛込・1回目アンケート）
   ========================================================================= */
const HAPPINESS_QUESTIONS = [
  { id: 'q1', label: '将来の「ライフイベント資金」、もう十分に準備できていますか？', hint: '婚活・結婚・育児・教育' },
  { id: 'q2', label: '貯金、今のままで十分ですか？', hint: '' },
  { id: 'q3', label: '今の住環境に不満はまったくないですか？', hint: '広さ・遮音性・収納' },
  { id: 'q4', label: '万が一のとき、金銭面の心配はありませんか？', hint: '生命保険' },
  { id: 'q5', label: '老後に向けた資金や住まい、もう準備できていますか？', hint: '投資信託' },
  { id: 'q6', label: '健康のために、具体的な対策をしていますか？', hint: '' },
  { id: 'q7', label: '巨大地震の備え、ちゃんとできていますか？', hint: '耐震等級・ライフライン・食料の備蓄' },
];

VIEWS.happiness = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn" id="new-hap">＋ 新規チェック</button>`;
  $('#new-hap').onclick = () => happinessForm();
  window._haps = await api.get('/api/happiness');
  $('#view').innerHTML = `
    <div class="panel">
      <div class="toolbar"><div class="search"><span class="si">🔍</span><input id="hap-search" placeholder="お客様名・顧客で検索…"></div></div>
      <p class="muted" style="margin:4px 0 12px;font-size:12.5px">飛込・初回接触で使う7問のYES/NOチェック。<b>NOが3つ以上で「マイホーム見込み」</b>と判定します。</p>
      <div class="table-wrap"><table>
        <thead><tr><th>タイトル</th><th>顧客</th><th>NO数</th><th>判定</th><th>作成日</th><th></th></tr></thead>
        <tbody id="hap-tbody"></tbody>
      </table></div>
    </div>`;
  $('#hap-search').oninput = renderHaps;
  renderHaps();
};
function hapVerdict(n) {
  return n >= 3 ? `<span class="badge green">マイホーム見込み ◎</span>` : `<span class="badge gray">継続フォロー</span>`;
}
function renderHaps() {
  const q = ($('#hap-search').value || '').toLowerCase();
  const rows = window._haps.filter(h => !q || (h.title || '').toLowerCase().includes(q) || (h.company_name || '').toLowerCase().includes(q)).map(h => `
    <tr>
      <td><span class="list-link" onclick="editHap(${h.id})">${esc(h.title)}</span></td>
      <td>${esc(h.company_name) || '<span class="muted">—</span>'}</td>
      <td><b>${h.no_count}</b> / 7</td>
      <td>${hapVerdict(h.no_count)}</td>
      <td class="nowrap">${fmtDate(h.created_at)}</td>
      <td class="right"><button class="icon-btn" onclick="delHap(${h.id})">🗑</button></td>
    </tr>`).join('');
  $('#hap-tbody').innerHTML = rows || emptyRow(6, 'まだありません', '🌟');
}

function happinessForm(data = {}) {
  const editing = !!data.id;
  const ans = Object.assign({}, data.answers || {});
  const qHtml = HAPPINESS_QUESTIONS.map(q => `
    <div class="hq">
      <div class="q">${q.label}${q.hint ? `<small>${q.hint}</small>` : ''}</div>
      <div class="hbtns" data-qid="${q.id}">
        <button type="button" class="hbtn ${ans[q.id] === 'yes' ? 'on-yes' : ''}" data-v="yes">YES</button>
        <button type="button" class="hbtn ${ans[q.id] === 'no' ? 'on-no' : ''}" data-v="no">NO</button>
      </div>
    </div>`).join('');
  openModal(editing ? '幸せ意識度チェック（編集）' : '幸せ意識度チェック（新規）', `
    <div class="grid2">
      <div class="field"><label>タイトル / お客様名 *</label><input id="hap-title" value="${esc(data.title)}" placeholder="例）山田様（飛込）"></div>
      <div class="field"><label>顧客企業</label><select id="hap-company">${companyOptions(data.company_id)}</select></div>
    </div>
    <div id="hap-verdict" class="verdict-box"></div>
    ${qHtml}
    <div class="field" style="margin-top:6px">
      <div class="field-row-mic"><label>メモ</label><button type="button" class="mic-btn" id="mic-hap">🎤</button></div>
      <textarea id="hap-memo" placeholder="気づき・反応など">${esc(data.memo)}</textarea>
    </div>
    <div class="form-actions">${editing ? `<button class="btn danger" onclick="delHap(${data.id},true)">削除</button><button class="btn ghost" onclick="printHap(${data.id})">🖨️ PDF / 印刷</button>` : ''}<span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="hap-save">${editing ? '保存' : '登録'}</button></div>`);

  const updateVerdict = () => {
    const n = Object.values(ans).filter(v => v === 'no').length;
    const box = $('#hap-verdict');
    box.style.background = n >= 3 ? 'var(--green-soft)' : '#eef1f6';
    box.style.color = n >= 3 ? 'var(--green)' : 'var(--muted)';
    box.innerHTML = n >= 3 ? `NO ${n}個 → 🏠 マイホーム見込み（提案へ）` : `NO ${n}個（3つ以上で見込み）`;
  };
  $$('.hbtns').forEach(g => {
    const qid = g.dataset.qid;
    $$('.hbtn', g).forEach(b => b.onclick = () => {
      ans[qid] = (ans[qid] === b.dataset.v) ? '' : b.dataset.v; // 再クリックで解除
      $$('.hbtn', g).forEach(x => x.classList.remove('on-yes', 'on-no'));
      if (ans[qid] === 'yes') b.classList.add('on-yes');
      if (ans[qid] === 'no') b.classList.add('on-no');
      updateVerdict();
    });
  });
  updateVerdict();
  setupMic('mic-hap', null, (t) => { const m = $('#hap-memo'); m.value = (m.value ? m.value + ' ' : '') + t; }, true);

  $('#hap-save').onclick = async () => {
    const title = $('#hap-title').value.trim();
    if (!title) { toast('タイトルを入力してください', '✏️'); return; }
    const body = { title, company_id: $('#hap-company').value || null, answers: ans, memo: $('#hap-memo').value };
    if (editing) await api.put('/api/happiness/' + data.id, body); else await api.post('/api/happiness', body);
    closeModal(); toast('保存しました'); navigate('happiness');
  };
}
window.editHap = async (id) => { const h = await api.get('/api/happiness/' + id); happinessForm(h); };
window.delHap = async (id, fromModal) => { if (confirm('このチェックを削除しますか？')) { await api.del('/api/happiness/' + id); if (fromModal) closeModal(); toast('削除しました'); navigate('happiness'); } };

/* =========================================================================
   ⑨ ライフメイクカルテ（2回目アンケート・全項目）
   ========================================================================= */
const KARTE_SCHEMA = [
  { sec: '基本情報', fields: [
    { id: 'name', label: 'お名前', type: 'text' },
    { id: 'address', label: '住所', type: 'text' },
    { id: 'age', label: '年齢', type: 'num' },
    { id: 'family', label: '現在の家族構成', type: 'text', hint: '人数・続柄' },
    { id: 'birth', label: '生年月日', type: 'text' },
    { id: 'staff', label: '担当', type: 'text' },
    { id: 'date', label: '実施日', type: 'date' },
    { id: 'partner', label: '彼女・結婚予定', type: 'text', hint: 'いる/募集中・結婚予定 ある/まだない' },
  ]},
  { sec: '住まい・家賃', fields: [
    { id: 'rent', label: '家賃(円)', type: 'num' },
    { id: 'rent_self', label: '自己負担(円)', type: 'num' },
    { id: 'parking', label: '駐車場', type: 'radio', opts: ['込', '別', 'なし'] },
    { id: 'layout', label: '間取り(広さ)', type: 'text' },
    { id: 'live_years', label: '居住年数', type: 'text' },
    { id: 'satisfy', label: '現在のお住まい', type: 'radio', opts: ['満足', '不満足'] },
    { id: 'prev_home', label: 'その前は？', type: 'text' },
  ]},
  { sec: '生命保険', fields: [
    { id: 'ins_join', label: '保険加入', type: 'radio', opts: ['有', '無'] },
    { id: 'ins_type', label: '種類', type: 'checks', opts: ['定期', '終身', '養老', '医療', 'ガン'] },
    { id: 'ins_fee', label: '月額保険料(円)', type: 'num' },
  ]},
  { sec: '勤務先（ご主人様／奥様）', fields: [
    { id: 'work_name', label: '勤務先名', type: 'ptext' },
    { id: 'work_emp', label: '雇用形態', type: 'ptext', hint: '正社員 等' },
    { id: 'work_cap', label: '資本金', type: 'ptext' },
    { id: 'work_empnum', label: '社員数', type: 'ptext' },
    { id: 'work_years', label: '勤続/社会人年数', type: 'ptext' },
    { id: 'work_place', label: '勤務地', type: 'ptext' },
    { id: 'commute', label: '通勤方法・時間', type: 'ptext', hint: '車/徒歩/自転車/バス/電車・分' },
    { id: 'tenkin', label: '転勤', type: 'pradio', opts: ['あり', 'なし'] },
    { id: 'tenkin_hope', label: '転勤希望', type: 'pradio', opts: ['あり', 'なし'] },
    { id: 'tenshoku', label: '転職希望', type: 'ptext', hint: '○/×・その前は？' },
  ]},
  { sec: '給与・貯蓄・借入（ご主人様／奥様）', fields: [
    { id: 'salary', label: '月手取り(万円)', type: 'ptext' },
    { id: 'income', label: '年収(万円)', type: 'ptext' },
    { id: 'kakeibo', label: '家計簿', type: 'pradio', opts: ['付けてる', '付けてない'] },
    { id: 'save_month', label: '毎月貯蓄額', type: 'ptext' },
    { id: 'save_total', label: '貯蓄額総額(万円)', type: 'ptext' },
    { id: 'gamble', label: 'ギャンブル', type: 'pradio', opts: ['無', '有'] },
    { id: 'gamble_type', label: 'ギャンブル種類', type: 'ptext', hint: 'パチンコ/公営 等' },
    { id: 'loan_count', label: '借入件数', type: 'ptext' },
    { id: 'card_count', label: 'クレジットカード(枚)', type: 'ptext' },
    { id: 'loan_from', label: '借入先', type: 'ptext' },
    { id: 'loan_type', label: '種類', type: 'ptext' },
    { id: 'loan_rest', label: '残債', type: 'ptext' },
    { id: 'loan_years', label: '残年数', type: 'ptext' },
    { id: 'loan_monthly', label: '月々返済', type: 'ptext' },
    { id: 'loan_delay', label: '遅延', type: 'ptext' },
    { id: 'guarantor', label: '保証人', type: 'ptext' },
  ]},
  { sec: '生活（ご主人様／奥様）', fields: [
    { id: 'kitchen', label: '自炊（週 日）', type: 'ptext' },
    { id: 'laundry', label: '洗濯（週 回）', type: 'ptext' },
    { id: 'bath', label: 'お風呂', type: 'pradio', opts: ['浴槽に入る', 'シャワーのみ'] },
    { id: 'bath_long', label: '入浴', type: 'pradio', opts: ['長い', '早い'] },
    { id: 'disaster', label: '災害対策', type: 'pradio', opts: ['あり', 'なし'] },
    { id: 'health', label: '健康対策', type: 'pradio', opts: ['あり', 'なし'] },
    { id: 'hobby', label: '趣味', type: 'ptext' },
  ]},
  { sec: '出身・実家・相続（ご主人様／奥様）', fields: [
    { id: 'birthplace', label: '出身地', type: 'ptext' },
    { id: 'parent_home', label: '実家の住まい', type: 'pradio', opts: ['持家一戸建て', '借家', 'マンション', '無し'] },
    { id: 'parent_age', label: '実家 築年数', type: 'ptext' },
    { id: 'care', label: '介護', type: 'pradio', opts: ['有', '無'] },
    { id: 'souzoku', label: '相続', type: 'pradio', opts: ['相談済み', '相談無し'] },
    { id: 'siblings', label: '兄弟姉妹', type: 'ptext', hint: '一人っ子/兄/弟/姉/妹' },
  ]},
  { sec: '固定費', fields: [
    { id: 'fc_rent', label: '家賃(円)', type: 'num' },
    { id: 'fc_ins', label: '生命保険料 定期(円)', type: 'num' },
    { id: 'fc_tax', label: '税金(円)', type: 'num' },
    { id: 'fc_util', label: '電気代・返済等(円)', type: 'num' },
    { id: 'fc_total', label: '合計(円・自動計算)', type: 'num' },
    { id: 'fc_ratio', label: '手取りに対する固定費の割合', type: 'text' },
  ]},
  { sec: '老後・マイホーム', fields: [
    { id: 'oldage_home', label: '老後の住まい', type: 'radio', opts: ['実家', '賃貸', 'マイホーム購入'] },
    { id: 'oldage_note', label: 'マイホーム購入以外の方、具体的には？', type: 'longtext' },
    { id: 'buy_age', label: 'マイホーム購入は何歳？', type: 'num' },
    { id: 'buy_after', label: '何年後？', type: 'num' },
    { id: 'buy_reason_later', label: '先にする理由は？', type: 'longtext' },
    { id: 'buy_problem', label: '今マイホームを持つと不都合は？', type: 'radio', opts: ['ない', 'ある'] },
    { id: 'buy_problem_reason', label: '不都合の理由', type: 'longtext' },
  ]},
  { sec: '人生診断（4大リスク・該当にチェック）', fields: [
    { id: 'save_max_now', label: '「今」出来る月々の最大貯蓄額(円)', type: 'num' },
    { id: 'save_at60', label: '「60歳」の貯蓄額(万円)', type: 'num' },
    { id: 'risk_oldage', label: '①老後対策', type: 'checks', opts: ['老後貯蓄の余裕がない', '資産形成が出来ていない', '老後の経費削減が出来ていない', '老後の住居確保が出来ていない'] },
    { id: 'risk_emergency', label: '②万が一対策', type: 'checks', opts: ['無駄な支払いが多く必要保障が足りない', '遺族の住居確保が出来ていない'] },
    { id: 'risk_health', label: '③健康対策', type: 'checks', opts: ['自炊環境が弱い', '免疫力UP環境が弱い'] },
    { id: 'risk_disaster', label: '④災害対策', type: 'checks', opts: ['地震・火災・台風に弱い', 'ライフラインの確保が出来ていない', '食料備蓄と防災用品の保管スペースがない', '資金確保が難しい'] },
  ]},
];
const KARTE_LONGTEXT = [];
KARTE_SCHEMA.forEach(s => s.fields.forEach(f => { if (f.type === 'longtext') KARTE_LONGTEXT.push(f.id); }));

VIEWS.karte = async function () {
  $('#topbar-actions').innerHTML = `<button class="btn" id="new-karte">＋ 新規カルテ</button>`;
  $('#new-karte').onclick = () => karteForm();
  window._kartes = await api.get('/api/kartes');
  $('#view').innerHTML = `
    <div class="panel">
      <div class="toolbar"><div class="search"><span class="si">🔍</span><input id="karte-search" placeholder="お客様名・顧客で検索…"></div></div>
      <p class="muted" style="margin:4px 0 12px;font-size:12.5px">2回目面談で使う詳細カルテ。家計・住環境・保険・貯蓄・老後・マイホーム計画などを聞き取り記録します（各自由記入欄は🎤音声入力対応）。</p>
      <div class="table-wrap"><table>
        <thead><tr><th>タイトル</th><th>顧客</th><th>作成日</th><th></th></tr></thead>
        <tbody id="karte-tbody"></tbody>
      </table></div>
    </div>`;
  $('#karte-search').oninput = renderKartes;
  renderKartes();
};
function renderKartes() {
  const q = ($('#karte-search').value || '').toLowerCase();
  const rows = window._kartes.filter(k => !q || (k.title || '').toLowerCase().includes(q) || (k.company_name || '').toLowerCase().includes(q)).map(k => `
    <tr>
      <td><span class="list-link" onclick="editKarte(${k.id})">${esc(k.title)}</span></td>
      <td>${esc(k.company_name) || '<span class="muted">—</span>'}</td>
      <td class="nowrap">${fmtDate(k.created_at)}</td>
      <td class="right"><button class="icon-btn" onclick="delKarte(${k.id})">🗑</button></td>
    </tr>`).join('');
  $('#karte-tbody').innerHTML = rows || emptyRow(4, 'まだありません', '📋');
}

function _kfield(f, D) {
  const v = (id) => esc(D[id] == null ? '' : D[id]);
  const hintHtml = f.hint ? ` <span class="muted" style="font-weight:400;font-size:11px">${f.hint}</span>` : '';
  if (f.type === 'ptext') {
    return `<div class="field"><label>${f.label}${hintHtml}</label><div class="grid2">
      <input data-fid="${f.id}__h" placeholder="ご主人様" value="${v(f.id + '__h')}">
      <input data-fid="${f.id}__w" placeholder="奥様" value="${v(f.id + '__w')}"></div></div>`;
  }
  if (f.type === 'pradio') {
    const sel = (suf, ph) => `<select data-fid="${f.id}${suf}"><option value="">${ph}…</option>${f.opts.map(o => `<option ${D[f.id + suf] === o ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
    return `<div class="field"><label>${f.label}</label><div class="grid2">${sel('__h', 'ご主人様')}${sel('__w', '奥様')}</div></div>`;
  }
  if (f.type === 'radio') {
    return `<div class="field"><label>${f.label}</label><select data-fid="${f.id}"><option value="">—</option>${f.opts.map(o => `<option ${D[f.id] === o ? 'selected' : ''}>${o}</option>`).join('')}</select></div>`;
  }
  if (f.type === 'checks') {
    return `<div class="field"><label>${f.label}</label><div class="chk-grid">${f.opts.map(o => `<label class="chk"><input type="checkbox" data-check="${f.id}" value="${esc(o)}" ${(D[f.id] || []).includes(o) ? 'checked' : ''}> ${esc(o)}</label>`).join('')}</div></div>`;
  }
  if (f.type === 'longtext') {
    return `<div class="field"><div class="field-row-mic"><label>${f.label}</label><button type="button" class="mic-btn" id="mic-k-${f.id}">🎤</button></div><textarea data-fid="${f.id}">${v(f.id)}</textarea></div>`;
  }
  const t = f.type === 'num' ? 'number' : (f.type === 'date' ? 'date' : 'text');
  return `<div class="field"><label>${f.label}${hintHtml}</label><input type="${t}" data-fid="${f.id}" value="${v(f.id)}"></div>`;
}

function karteForm(data = {}) {
  const editing = !!data.id;
  const D = data.data || {};
  const secHtml = KARTE_SCHEMA.map(s => {
    const simple = !s.fields.some(f => ['ptext', 'pradio', 'checks', 'longtext'].includes(f.type));
    return `<div class="modal-section-title">${s.sec}</div>
      <div${simple ? ' class="grid2"' : ''}>${s.fields.map(f => _kfield(f, D)).join('')}</div>`;
  }).join('');
  openModal(editing ? 'ライフメイクカルテ（編集）' : 'ライフメイクカルテ（新規）', `
    <div class="grid2">
      <div class="field"><label>タイトル / お客様名 *</label><input id="k-title" value="${esc(data.title)}" placeholder="例）山田様 ライフメイクカルテ"></div>
      <div class="field"><label>顧客企業</label><select id="k-company">${companyOptions(data.company_id)}</select></div>
    </div>
    <div class="field"><label>関連商談</label><select id="k-deal">${dealOptions(data.deal_id)}</select></div>
    <div class="voice-box">
      <div class="field-row-mic"><div><div class="vb-title">🎤 音声メモ（聞き取りメモ）</div><div class="vb-desc" style="margin:0">面談中に話した内容をそのまま記録。各項目は下のフォームに入力します。</div></div>
        <button type="button" class="mic-btn" id="mic-kmemo">🎤 録音開始</button></div>
      <textarea data-fid="_voice_memo" rows="3" placeholder="（聞き取りメモ）">${esc(D._voice_memo)}</textarea>
    </div>
    ${secHtml}
    <div class="form-actions">${editing ? `<button class="btn danger" onclick="delKarte(${data.id},true)">削除</button><button class="btn ghost" onclick="printKarte(${data.id})">🖨️ PDF / 印刷</button>` : ''}<span class="spacer"></span>
      <button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="k-save">${editing ? '保存' : '登録'}</button></div>`, true);

  // 音声入力（メモ＋各自由記入欄）
  setupMic('mic-kmemo', null, (t) => { const m = $('[data-fid="_voice_memo"]'); m.value = (m.value ? m.value + ' ' : '') + t; }, true);
  KARTE_LONGTEXT.forEach(id => setupMic('mic-k-' + id, null, (t) => { const m = $(`[data-fid="${id}"]`); if (m) m.value = (m.value ? m.value + ' ' : '') + t; }, true));

  // 固定費 合計の自動計算
  const sumFixed = () => {
    const g = (id) => Number(($(`[data-fid="${id}"]`) || {}).value) || 0;
    const t = g('fc_rent') + g('fc_ins') + g('fc_tax') + g('fc_util');
    const el = $('[data-fid="fc_total"]'); if (el) el.value = t || '';
  };
  ['fc_rent', 'fc_ins', 'fc_tax', 'fc_util'].forEach(id => { const el = $(`[data-fid="${id}"]`); if (el) el.oninput = sumFixed; });

  $('#k-save').onclick = async () => {
    const title = $('#k-title').value.trim();
    if (!title) { toast('タイトルを入力してください', '✏️'); return; }
    const out = {};
    $$('#modal-body [data-fid]').forEach(el => { const val = (el.value || '').trim(); if (val !== '') out[el.dataset.fid] = val; });
    $$('#modal-body [data-check]').forEach(cb => { if (cb.checked) { const k = cb.dataset.check; (out[k] = out[k] || []).push(cb.value); } });
    const body = { title, company_id: $('#k-company').value || null, deal_id: $('#k-deal').value || null, data: out };
    if (editing) await api.put('/api/kartes/' + data.id, body); else await api.post('/api/kartes', body);
    closeModal(); toast('保存しました'); navigate('karte');
  };
}
window.editKarte = async (id) => { const k = await api.get('/api/kartes/' + id); karteForm(k); };
window.delKarte = async (id, fromModal) => { if (confirm('このカルテを削除しますか？')) { await api.del('/api/kartes/' + id); if (fromModal) closeModal(); toast('削除しました'); navigate('karte'); } };

/* ---- 帳票出力（PDF/印刷）：新ウィンドウに印刷用HTMLを書き出し、ブラウザの印刷→PDF保存 ---- */
function printWindow(title, bodyHtml) {
  const w = window.open('', '_blank');
  if (!w) { toast('ポップアップがブロックされました。許可してください', '⚠️'); return; }
  w.document.write(`<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>${esc(title)}</title>
    <style>
      body{font-family:"Yu Gothic","Hiragino Sans","Noto Sans JP",sans-serif;max-width:760px;margin:30px auto;line-height:1.65;color:#222;padding:0 16px}
      h1{font-size:20px;border-bottom:2px solid #4f46e5;padding-bottom:6px;margin:0 0 6px}
      h2{font-size:14px;margin:16px 0 6px;color:#4338ca}
      .meta{color:#666;font-size:12px;margin:0 0 14px}
      table{width:100%;border-collapse:collapse;margin:4px 0}
      table.grid td{border:1px solid #ccc;padding:6px 8px;font-size:12.5px;vertical-align:top}
      .sec{font-size:13px;font-weight:700;color:#4338ca;margin:16px 0 4px;border-bottom:1px solid #dcdfea;padding-bottom:3px}
      table.kv td{border:1px solid #dde;padding:5px 8px;font-size:12px;vertical-align:top}
      table.kv td.l{background:#f5f6fb;width:38%;color:#555}
      .verdict{font-weight:700;background:#eef0ff;padding:8px 12px;border-radius:6px;display:inline-block;margin-top:8px}
      .print-btn{position:fixed;top:12px;right:12px;padding:8px 16px;background:#4f46e5;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:13px}
      @media print{body{margin:0}.print-btn{display:none}}
    </style></head><body>
    <button class="print-btn" onclick="window.print()">🖨️ 印刷 / PDF保存</button>
    ${bodyHtml}</body></html>`);
  w.document.close();
  setTimeout(() => { try { w.print(); } catch (e) {} }, 500);
}

window.printHap = async (id) => {
  const h = await api.get('/api/happiness/' + id);
  const ans = h.answers || {};
  const n = Object.values(ans).filter(v => v === 'no').length;
  const rows = HAPPINESS_QUESTIONS.map((q, i) => {
    const v = ans[q.id];
    return `<tr><td>${i + 1}. ${esc(q.label)}${q.hint ? `<br><span style="color:#888;font-size:11px">${esc(q.hint)}</span>` : ''}</td>
      <td style="text-align:center;width:64px;font-weight:700;color:${v === 'yes' ? '#15a06b' : '#bbb'}">${v === 'yes' ? '● YES' : 'YES'}</td>
      <td style="text-align:center;width:64px;font-weight:700;color:${v === 'no' ? '#e11d48' : '#bbb'}">${v === 'no' ? '● NO' : 'NO'}</td></tr>`;
  }).join('');
  const verdict = n >= 3 ? `NO ${n}個 → 🏠 マイホーム見込み（ご提案へ）` : `NO ${n}個（3つ以上で見込み）`;
  printWindow(`幸せ意識度チェック - ${h.title}`, `
    <h1>将来の幸せ意識度チェック</h1>
    <p class="meta">お客様: ${esc(h.title)}　／　顧客: ${esc(h.company_name || '—')}　／　作成: ${fmtDate(h.created_at)}</p>
    <table class="grid"><tbody>${rows}</tbody></table>
    <p class="verdict">判定：${esc(verdict)}</p>
    ${h.memo ? `<h2>メモ</h2><p>${esc(h.memo).replace(/\n/g, '<br>')}</p>` : ''}`);
};

window.printKarte = async (id) => {
  const k = await api.get('/api/kartes/' + id);
  const D = k.data || {};
  const val = (f) => {
    if (f.type === 'checks') return esc((D[f.id] || []).join('、')) || '—';
    if (f.type === 'ptext' || f.type === 'pradio') return `ご主人様: ${esc(D[f.id + '__h'] || '—')}　／　奥様: ${esc(D[f.id + '__w'] || '—')}`;
    if (f.type === 'longtext') return esc(D[f.id] || '—').replace(/\n/g, '<br>');
    return esc(D[f.id] || '—');
  };
  const secs = KARTE_SCHEMA.map(s => `
    <div class="sec">${esc(s.sec)}</div>
    <table class="kv"><tbody>${s.fields.map(f => `<tr><td class="l">${esc(f.label)}</td><td>${val(f)}</td></tr>`).join('')}</tbody></table>`).join('');
  printWindow(`ライフメイクカルテ - ${k.title}`, `
    <h1>ライフメイクカルテ</h1>
    <p class="meta">お客様: ${esc(k.title)}　／　顧客: ${esc(k.company_name || '—')}　／　作成: ${fmtDate(k.created_at)}</p>
    ${D._voice_memo ? `<h2>聞き取りメモ</h2><p>${esc(D._voice_memo).replace(/\n/g, '<br>')}</p>` : ''}
    ${secs}`);
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

  const idleLabel = btn.id.includes('whole') || btn.id.includes('extract') ? '🎤 録音開始' : (btn.id.includes('min') ? '🎤 音声' : '🎤');
  let rec = null, active = false, manualStop = false;
  btn.onclick = () => {
    if (active) { manualStop = true; try { rec && rec.stop(); } catch (e) {} return; }
    manualStop = false;
    rec = new SR();
    rec.lang = 'ja-JP';
    rec.interimResults = true;
    rec.continuous = continuous;   // ※モバイルは無視されるので onend で再開する
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
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') { manualStop = true; if (hint) hint.textContent = '⚠ マイクの使用を許可してください'; }
      else if (e.error === 'no-speech') { if (hint) hint.textContent = '🔴 聞き取り中…'; }  // 連続モードでは続行
      else if (hint) hint.textContent = '⚠ ' + e.error;
    };
    rec.onend = () => {
      // 連続モードでユーザーが止めていなければ自動で再開（モバイルで途切れる対策）
      if (continuous && !manualStop) { try { rec.start(); return; } catch (e) {} }
      active = false; btn.classList.remove('recording'); btn.innerHTML = idleLabel;
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
  let demoBanner = '';
  if (health.demo_mode) {
    demoBanner = `<div class="panel" style="background:#fef9c3;border-color:#fde68a;color:#854d0e">🧪 デモモード: APIキー不要のサンプル応答で動作中(文字起こし・議事録はダミー)。本番は .env に DEMO_MODE=false と各APIキーを設定。</div>`;
  } else if (health.local_whisper) {
    demoBanner = `<div class="panel" style="background:#e3f8ee;border-color:#bbf0d4;color:#15803d">🎧 ローカル文字起こし(無料・キー不要)で動作中。音声をアップロードすると本物の文字起こしが出ます。${health.can_generate ? '' : '<br>※ 議事録・要約の自動生成には Anthropic(Claude)のキーが必要です（無い間は「文字起こし全文」まで表示）。'}</div>`;
  } else if (!health.can_generate && !health.openai_configured) {
    demoBanner = `<div class="panel" style="background:#fee2e2;border-color:#fecaca;color:#b91c1c">⚠ 文字起こしの設定がありません。.env で LOCAL_WHISPER=true(無料) か OPENAI_API_KEY を設定してください。</div>`;
  }

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
        <div class="field"><label>A. 音声ファイル（mp3 / m4a / wav など）</label><input type="file" id="ai-file" accept="audio/*,.mp3,.m4a,.aac,.wav,.webm,.mp4,.mpga,.ogg,.oga,.flac,.opus"><button class="btn" id="ai-upload" style="margin-top:6px;width:100%">アップロード</button></div>
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
  // 議事録生成が無い構成(ローカルWhisper＋Claudeキー無し)では transcribed で完了
  const canGen = !(window._aiHealth && window._aiHealth.can_generate === false);
  for (let i = 0; i < 600; i++) {
    let m; try { m = await api.get('/api/minutes/' + id); } catch (e) { aiSetStatus('❌ ' + e.message); return; }
    const doneTranscribe = m.ai_status === 'transcribed' && !canGen;
    aiSetStatus((m.ai_status === 'error' ? '❌ ' : (m.ai_status === 'summarized' || doneTranscribe ? '✅ ' : '⏳ ')) +
      (doneTranscribe ? '文字起こし完了' : (AI_STATUS_LABEL[m.ai_status] || m.ai_status)) +
      (m.ai_status === 'error' && m.error_message ? '：' + m.error_message : ''));
    if (m.ai_status === 'summarized' || m.ai_status === 'error' || doneTranscribe) {
      await loadMinutesList();
      if (m.ai_status === 'summarized' || doneTranscribe) openMinutes(id);
      return;
    }
    await new Promise(r => setTimeout(r, 2500));
  }
  aiSetStatus('タイムアウトしました');
}

async function openMinutes(id) {
  const m = await api.get('/api/minutes/' + id);
  const decisions = (m.decisions || []).map(d => `<li>${esc(d)}</li>`).join('');
  const actions = (m.next_actions || []).map((a, i) => `<div class="action-row" style="display:flex;justify-content:space-between;align-items:center;gap:8px"><span>☐ ${esc(a.task || a)}${a.owner ? ` <b>@${esc(a.owner)}</b>` : ''}${a.due ? ` ⏰${esc(a.due)}` : ''}</span><button class="btn sm soft" style="flex-shrink:0" onclick="actionToTask(${id},${i})">＋To-Do</button></div>`).join('');
  const linkBox = `<div class="field" style="background:#f8fafc;padding:10px;border-radius:8px;margin:8px 0">
    <label>🔗 顧客・商談にひも付け</label>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <select id="mlink-company-${id}" style="flex:1;min-width:130px">${companyOptions(m.company_id)}</select>
      <select id="mlink-deal-${id}" style="flex:1;min-width:130px">${dealOptions(m.deal_id)}</select>
      <button class="btn sm soft" onclick="saveMinutesLink(${id})">保存</button>
    </div></div>`;
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
    ${linkBox}
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
      ${(m.summary || m.transcript) ? `<button class="btn ghost" onclick="window.open('/api/minutes/${id}/export.md','_blank')">⬇️ Markdown</button>` : ''}
      ${(m.summary || m.transcript) ? `<button class="btn ghost" onclick="printMinutes(${id})">🖨️ PDF / 印刷</button>` : ''}
      ${canRe ? `<button class="btn soft" onclick="reprocessMinutes(${id})">🔄 音声から再処理</button>` : ''}
      <span class="spacer"></span><button class="btn ghost" onclick="delMinutes(${id})">削除</button>
    </div>`;
  openModal(esc(m.title), html, true);
}
window.openMinutes = openMinutes;

async function genMinutes(id) {
  if (window._aiHealth && window._aiHealth.can_generate === false) { toast('議事録・要約の自動生成には Anthropic(Claude) のAPIキーが必要です。文字起こし全文はそのまま使えます。', 'ℹ️'); return; }
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
window.actionToTask = async (id, index) => {
  try { const r = await api.post(`/api/minutes/${id}/action_to_task`, { index }); toast('To-Do に登録: ' + r.task, '✅'); }
  catch (e) { toast(e.message, '⚠'); }
};
window.saveMinutesLink = async (id) => {
  const cid = $('#mlink-company-' + id).value, did = $('#mlink-deal-' + id).value;
  try { await api.patch(`/api/minutes/${id}/link`, { company_id: cid ? Number(cid) : null, deal_id: did ? Number(did) : null }); toast('ひも付けを保存しました'); await loadMinutesList(); openMinutes(id); }
  catch (e) { toast(e.message, '⚠'); }
};
window.printMinutes = async (id) => {
  const m = await api.get('/api/minutes/' + id);
  const w = window.open('', '_blank');
  const acts = (m.next_actions || []).map(a => `<li>${esc(a.task || a)}${a.owner ? ' @' + esc(a.owner) : ''}${a.due ? '（' + esc(a.due) + '）' : ''}</li>`).join('');
  const decs = (m.decisions || []).map(d => `<li>${esc(d)}</li>`).join('');
  w.document.write(`<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>${esc(m.title)}</title>
    <style>body{font-family:"Yu Gothic","Hiragino Sans",sans-serif;max-width:720px;margin:36px auto;line-height:1.8;color:#222;padding:0 16px}
    h1{font-size:20px;border-bottom:2px solid #4f46e5;padding-bottom:6px}h2{font-size:15px;margin-top:18px;color:#4338ca}ul{padding-left:20px}</style></head><body>
    <h1>${esc(m.title)}</h1>
    <p style="color:#666;font-size:13px">顧客: ${esc(m.company_name || '—')} / 商談: ${esc(m.deal_title || '—')} / 作成: ${fmtDateTime(m.created_at)}</p>
    ${m.summary ? `<h2>要約</h2><p>${esc(m.summary)}</p>` : ''}
    ${decs ? `<h2>決定事項</h2><ul>${decs}</ul>` : ''}
    ${acts ? `<h2>次のアクション</h2><ul>${acts}</ul>` : ''}
    ${m.minutes_md ? `<h2>議事録</h2>${aiMd(m.minutes_md)}` : ''}
    ${m.dialogue_md ? `<h2>発言録</h2>${aiMd(m.dialogue_md)}` : ''}
    ${(!m.summary && m.transcript) ? `<h2>文字起こし</h2><p>${esc(m.transcript).replace(/\n/g, '<br>')}</p>` : ''}
    </body></html>`);
  w.document.close(); setTimeout(() => w.print(), 400);
};
async function reprocessMinutes(id) {
  try { await api.post(`/api/minutes/${id}/reprocess`, {}); closeModal(); aiSetStatus('🔄 再処理中…'); await aiPoll(id); }
  catch (e) { toast(e.message, '⚠'); }
}
window.reprocessMinutes = reprocessMinutes;
async function delMinutes(id) {
  if (!confirm('この記録を削除しますか？')) return;
  await api.del('/api/minutes/' + id); closeModal(); await loadMinutesList(); toast('削除しました');
}
window.delMinutes = delMinutes;

let _aiRec = null, _aiChunks = [], _aiTimer = null, _aiSec = 0;
function setupAiRecorder() {
  const start = $('#ai-rec-start'), stop = $('#ai-rec-stop');
  if (!start) return;
  start.onclick = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // ブラウザが対応する音声形式を選ぶ（iOS Safari は webm 非対応＝mp4 を使う）
      const mime = ['audio/webm', 'audio/mp4', 'audio/ogg', 'audio/mpeg'].find(t => window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) || '';
      _aiRec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      _aiChunks = [];
      _aiRec.ondataavailable = e => { if (e.data && e.data.size) _aiChunks.push(e.data); };
      _aiRec.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        const type = _aiRec.mimeType || mime || 'audio/webm';
        const ext = type.includes('mp4') ? 'mp4' : type.includes('ogg') ? 'ogg' : type.includes('mpeg') ? 'mp3' : 'webm';
        const blob = new Blob(_aiChunks, { type });
        aiUpload(new File([blob], 'rec.' + ext, { type }));
      };
      _aiRec.start(); start.disabled = true; stop.disabled = false;
      _aiSec = 0; $('#ai-rec-timer').textContent = '00:00';
      _aiTimer = setInterval(() => { _aiSec++; $('#ai-rec-timer').textContent = `${String((_aiSec / 60) | 0).padStart(2, '0')}:${String(_aiSec % 60).padStart(2, '0')}`; }, 1000);
    } catch (e) { aiSetStatus('マイク取得失敗: ' + e.message); }
  };
  stop.onclick = () => { if (_aiRec) _aiRec.stop(); clearInterval(_aiTimer); start.disabled = false; stop.disabled = true; };
}

/* ---- ログイン認証 ---- */
let ME = null;
async function doLogin() {
  const msg = $('#login-msg');
  try {
    await api.post('/api/auth/login', { username: $('#login-user').value.trim() || 'admin', password: $('#login-pw').value });
    location.reload();
  } catch (e) { msg.textContent = e.message; }
}
async function checkAuthAndStart() {
  let me;
  try { me = await api.get('/api/auth/me'); } catch (e) { startApp(); return; }
  ME = me;
  if (me.auth_enabled && !me.authenticated) {
    $('#login-overlay').classList.remove('hidden');
    const btn = $('#login-btn'); if (btn) btn.onclick = doLogin;
    ['login-user', 'login-pw'].forEach(id => { const el = $('#' + id); if (el) el.onkeydown = (e) => { if (e.key === 'Enter') doLogin(); }; });
    return;
  }
  // サイドバー下部: ユーザー名・ロール＋管理リンク＋ログアウト
  const ll = $('#logout-link');
  if (ll) {
    const u = me.user;
    let html = '';
    if (u) html += `<div style="margin-bottom:4px">👤 ${esc(u.display_name || u.username)}${u.role === 'admin' ? '（管理者）' : ''}</div>`;
    if (me.is_admin) html += `<a href="#" id="open-users" style="color:#94a3b8">ユーザー管理</a>　`;
    if (u) html += `<a href="#" id="open-pw" style="color:#94a3b8">PW変更</a>　<a href="#" id="do-logout" style="color:#94a3b8">ログアウト</a>`;
    ll.innerHTML = html;
    const dl = $('#do-logout'); if (dl) dl.onclick = async (e) => { e.preventDefault(); await api.post('/api/auth/logout', {}); location.reload(); };
    const ou = $('#open-users'); if (ou) ou.onclick = (e) => { e.preventDefault(); userAdmin(); };
    const op = $('#open-pw'); if (op) op.onclick = (e) => { e.preventDefault(); myPasswordForm(); };
  }
  startApp();
}
function startApp() { navigate('dashboard'); }

/* ---- ユーザー管理（管理者） ---- */
async function userAdmin() {
  const users = await api.get('/api/users');
  const rows = users.map(u => `
    <tr>
      <td>${esc(u.display_name || u.username)}<div class="muted" style="font-size:11px">@${esc(u.username)}</div></td>
      <td>${badge({ admin: 'violet', member: 'gray' }, u.role)}</td>
      <td>${u.active ? '<span class="badge green">有効</span>' : '<span class="badge red">無効</span>'}</td>
      <td class="right nowrap">
        <button class="btn sm ghost" onclick="userResetPw(${u.id})">PW再設定</button>
        <button class="icon-btn" onclick="userDel(${u.id})">🗑</button>
      </td>
    </tr>`).join('');
  openModal('ユーザー管理', `
    <div class="section-row"><strong>登録ユーザー（${users.length}名）</strong><button class="btn sm" id="add-user">＋ ユーザー追加</button></div>
    <div class="table-wrap"><table><thead><tr><th>氏名</th><th>権限</th><th>状態</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted" style="font-size:11.5px;margin-top:10px">※「無効」「削除」「PW再設定」を行うと、その人の既存ログインは即時無効になります（トークン失効）。</p>`, true);
  $('#add-user').onclick = userForm;
}
window.userAdmin = userAdmin;
function userForm() {
  openModal('ユーザー追加', `
    <div class="grid2">
      <div class="field"><label>ユーザー名（ログインID）*</label><input id="u-username" placeholder="例）tanaka"></div>
      <div class="field"><label>表示名</label><input id="u-name" placeholder="例）田中 健"></div>
    </div>
    <div class="grid2">
      <div class="field"><label>パスワード *（4文字以上）</label><input id="u-pw" type="text"></div>
      <div class="field"><label>権限</label><select id="u-role"><option value="member">メンバー</option><option value="admin">管理者</option></select></div>
    </div>
    <div class="form-actions"><button class="btn ghost" onclick="userAdmin()">戻る</button><button class="btn" id="u-save">登録</button></div>`);
  $('#u-save').onclick = async () => {
    try {
      await api.post('/api/users', { username: $('#u-username').value.trim(), display_name: $('#u-name').value.trim(), password: $('#u-pw').value, role: $('#u-role').value });
      toast('ユーザーを追加しました'); userAdmin();
    } catch (e) { toast(e.message, '⚠️'); }
  };
}
window.userDel = async (id) => { if (confirm('このユーザーを削除しますか？（ログインも無効化されます）')) { try { await api.del('/api/users/' + id); toast('削除しました'); userAdmin(); } catch (e) { toast(e.message, '⚠️'); } } };
window.userResetPw = (id) => {
  openModal('パスワード再設定', `
    <div class="field"><label>新しいパスワード（4文字以上）</label><input id="rp-pw" type="text"></div>
    <div class="form-actions"><button class="btn ghost" onclick="userAdmin()">戻る</button><button class="btn" id="rp-save">再設定</button></div>`);
  $('#rp-save').onclick = async () => {
    try { await api.post(`/api/users/${id}/password`, { password: $('#rp-pw').value }); toast('再設定しました'); userAdmin(); }
    catch (e) { toast(e.message, '⚠️'); }
  };
};
function myPasswordForm() {
  openModal('パスワード変更', `
    <div class="field"><label>新しいパスワード（4文字以上）</label><input id="mp-pw" type="password"></div>
    <div class="form-actions"><button class="btn ghost" onclick="closeModal()">キャンセル</button><button class="btn" id="mp-save">変更</button></div>`);
  $('#mp-save').onclick = async () => {
    try { await api.post('/api/account/password', { password: $('#mp-pw').value }); closeModal(); toast('変更しました。再ログインしてください'); setTimeout(() => location.reload(), 1200); }
    catch (e) { toast(e.message, '⚠️'); }
  };
}

/* ---- 起動 ---- */
checkAuthAndStart();
