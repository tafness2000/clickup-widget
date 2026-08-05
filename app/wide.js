// 一覧を広げたときの画面。
// 取ってきた分は WIDE_TASKS に持ち、タブと並び順はここで組み替える
// （押すたびに取りに行かないので、切り替えに待ちがない）。
// ── 一覧を広げたとき ──────────────────────────────────────

// newestFirst = 期限が遠いものを上に。期限切れは下に溜まる。
const WIDE = { open: false, scope: 'today', busy: false, newestFirst: true };

// 取ってきた分をそのまま持っておく。タブと並び順はここから作り直すだけで、
// 押すたびに ClickUp へ取りにいかない（切り替えが待たされないため）。
let WIDE_TASKS = [];

// タブごとの期限の範囲。null は「その側は絞らない」。
function scopeBounds(scope) {
  const start = new Date(); start.setHours(0, 0, 0, 0);
  const end   = new Date(); end.setHours(23, 59, 59, 999);
  const friday = new Date(end);
  friday.setDate(friday.getDate() + ((5 - end.getDay() + 7) % 7));   // 0=日 … 5=金
  if (scope === 'overdue') return [null, start.getTime() - 1];
  if (scope === 'today')   return [start.getTime(), end.getTime()];
  if (scope === 'week')    return [start.getTime(), friday.getTime()];
  return [null, null];                                               // すべて
}

function inScope(task, scope) {
  const [low, high] = scopeBounds(scope);
  if (low === null && high === null) return true;
  if (!task.due) return false;          // 期限なしは「すべて」でだけ出す
  const value = Number(task.due);
  if (low !== null && value < low) return false;
  if (high !== null && value > high) return false;
  return true;
}

function wideRows() {
  const rows = WIDE_TASKS.filter(task => inScope(task, WIDE.scope));
  // 期限なしは向きに関わらず末尾。日付が無いものを間に挟むと並びが読めなくなる。
  return rows.sort((a, b) => {
    if (!a.due && !b.due) return 0;
    if (!a.due) return 1;
    if (!b.due) return -1;
    return WIDE.newestFirst ? Number(b.due) - Number(a.due) : Number(a.due) - Number(b.due);
  });
}

// 期限は日数で言い換える。生の日付より「あと何日か」の方が速く読める。
function dueLabel(ms) {
  if (!ms) return { text: '期限なし', cls: '' };
  const due   = new Date(Number(ms));
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day   = new Date(due); day.setHours(0, 0, 0, 0);
  const days  = Math.round((day - today) / 86400000);
  if (days <  0) return { text: `${-days} 日超過`, cls: 'over' };
  if (days === 0) return { text: '今日', cls: 'today' };
  if (days === 1) return { text: '明日', cls: '' };
  if (days <  7) return { text: `${days} 日後`, cls: '' };
  return { text: `${due.getMonth() + 1}/${due.getDate()}`, cls: '' };
}

// 完了の丸。押すと ClickUp 側を確かめてから、行と手元の控えの両方から外す。
function buildWideCheck(task, row) {
  const check = document.createElement('button');
  check.className = 'feed-check';
  check.title = '完了にする';
  check.innerHTML =
    '<svg viewBox="0 0 12 12" fill="none" stroke-width="2.4" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M2 6.2L4.8 9L10 3"/></svg>';
  check.addEventListener('click', e => {
    e.stopPropagation();
    if (!bridge) return;
    check.disabled = true;
    bridge.completeTask(task.id, String(task.list_id || ''), raw => {
      const res = JSON.parse(raw);
      if (res.ok) {
        // 手元の控えからも外す。タブを切り替えたときに戻ってこないように。
        WIDE_TASKS = WIDE_TASKS.filter(x => x.id !== task.id);
        row.remove();
        if (!wideBody.children.length) renderWide();
        else updateWideFoot(wideBody.children.length, WIDE_TASKS.length);
      } else {
        check.disabled = false;
        showError(res.error || '完了にできませんでした');
      }
    });
  });
  return check;
}

function buildWideMain(task) {
  const main = document.createElement('div');
  main.className = 'wide-main';

  const name = document.createElement('div');
  name.className = 'wide-name';
  name.textContent = task.name;
  main.appendChild(name);

  if (task.memo) {
    const memo = document.createElement('div');
    memo.className = 'wide-sub';
    memo.textContent = task.memo;
    main.appendChild(memo);
  }
  const where = document.createElement('div');
  where.className = 'wide-sub';
  where.textContent = [task.list_name, task.status].filter(Boolean).join(' · ');
  main.appendChild(where);
  return main;
}

function buildWideRow(task) {
  const row = document.createElement('div');
  row.className = 'wide-row';
  row.title = 'クリックで ClickUp を開く';

  const side = document.createElement('div');
  side.className = 'wide-side';
  const due   = dueLabel(task.due);
  const dueEl = document.createElement('div');
  dueEl.className = 'wide-due ' + due.cls;
  dueEl.textContent = due.text;
  side.appendChild(dueEl);

  row.append(buildWideCheck(task, row), buildWideMain(task), side);
  row.addEventListener('click', () => { if (bridge && task.url) bridge.openTask(task.url); });
  return row;
}

const SCOPE_LABEL = { overdue: '期限切れ', today: '今日', week: '今週', all: 'すべて' };

function updateWideFoot(shown, total) {
  const label = SCOPE_LABEL[WIDE.scope] || '';
  wideFoot.textContent = total === undefined
    ? `${label}: ${shown} 件`
    : `${label}: ${shown} 件${total !== shown ? `（中断中ぜんぶで ${total} 件）` : ''}`;
}

// pause.pyw が裏で取ってきた分を受け取る。絞るのはこちら側。
function setWideTasks(data) {
  WIDE.busy = false;
  if (!data.ok) {
    WIDE_TASKS = [];
    wideBody.replaceChildren(note('取得できませんでした。⟳ で取り直してください'));
    wideFoot.textContent = '';
    return;
  }
  WIDE_TASKS = data.tasks || [];
  renderWide();
}

function renderWide() {
  const rows = wideRows();
  wideBody.replaceChildren();
  if (!rows.length) {
    const empty = {
      overdue: '期限切れのものはありません',
      today:   '今日が期限のものはありません',
      week:    '今週が期限のものはありません',
      all:     '中断中のタスクはありません',
    }[WIDE.scope];
    wideBody.appendChild(note(
      empty + (WIDE.scope === 'all' ? '' : '。「すべて」を押すと期限で切らずに出ます')));
    updateWideFoot(0, WIDE_TASKS.length);
    return;
  }
  rows.forEach(task => wideBody.appendChild(buildWideRow(task)));
  updateWideFoot(rows.length, WIDE_TASKS.length);
}

function note(text) {
  const el = document.createElement('div');
  el.className = 'feed-note';
  el.textContent = text;
  return el;
}

function renderSortButton() {
  wideSort.textContent = WIDE.newestFirst ? '↓' : '↑';
  wideSort.title = WIDE.newestFirst
    ? 'いまは期限が遠い順。押すと近い順（期限切れが上）'
    : 'いまは期限が近い順。押すと遠い順';
}

function loadWide() {
  if (!bridge) return;
  WIDE.busy = true;
  renderSortButton();
  wideBody.replaceChildren(note('読み込み中…'));
  wideFoot.textContent = '';
  bridge.loadWide();
}

function openWide() {
  if (WIDE.open) return;
  WIDE.open = true;
  closePicker(false);
  document.body.classList.add('wide');
  if (bridge) bridge.setViewMode('wide');
  loadWide();
}

function closeWide() {
  if (!WIDE.open) return;
  WIDE.open = false;
  document.body.classList.remove('wide');
  if (bridge) bridge.setViewMode('normal');
  setTimeout(() => taskInput.focus(), 30);
}

// タブと並び順は手元のぶんを組み替えるだけ。取りに行かないので待ちがない。
wideTabs.addEventListener('click', e => {
  const tab = e.target.closest('.wide-tab');
  if (!tab || WIDE.busy) return;
  WIDE.scope = tab.dataset.scope;
  [...wideTabs.children].forEach(el => el.classList.toggle('on', el === tab));
  renderWide();
});

expandBtn.addEventListener('click', openWide);
wideBack.addEventListener('click', closeWide);
wideReload.addEventListener('click', () => { if (!WIDE.busy) loadWide(); });
wideSort.addEventListener('click', () => {
  if (WIDE.busy) return;
  WIDE.newestFirst = !WIDE.newestFirst;
  renderSortButton();
  renderWide();
});
