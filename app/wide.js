// 一覧を広げたときの画面。
// 取ってきた分は WIDE_TASKS に持ち、タブ・並び順・絞り込みはここで組み替える
// （押すたびに取りに行かないので、切り替えに待ちがない）。
// ── 一覧を広げたとき ──────────────────────────────────────

// newestFirst = 期限が遠いものを上に。期限切れは下に溜まる。
// query = 絞り込みに打った文字。取り直さず手元で絞る。
const WIDE = { open: false, scope: 'today', busy: false, newestFirst: true, query: '' };

// 取ってきた分をそのまま持っておく。タブと並び順はここから作り直すだけで、
// 押すたびに ClickUp へ取りにいかない（切り替えが待たされないため）。
let WIDE_TASKS = [];

// 取りに行ける分を使い切ったか。立っていれば、ここに出ているのが全部ではない。
let WIDE_MORE = false;

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

// 絞り込みの当たり判定。タスク名・メモ・リスト名のどれかに当たればよい。
// 「どこに書いたか」は覚えていないのが普通なので、欄を分けても意味がない。
function matchesQuery(task, tokens) {
  if (!tokens.length) return true;
  const hay = [task.name, task.memo, task.list_name].filter(Boolean).join(' ').toLowerCase();
  return tokens.every(t => hay.includes(t));
}

function wideRows() {
  const tokens = tokenize(WIDE.query);      // 全角スペースも区切りになる（picker.js）
  const rows = WIDE_TASKS.filter(task => inScope(task, WIDE.scope) && matchesQuery(task, tokens));
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
    pendingComplete.set(String(task.id), res => {
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
    bridge.completeTask(String(task.id), String(task.list_id || ''));
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

// 期限。押すと入力画面と同じ 6 つが出て、その 1 件だけ送り直せる。
function buildWideDue(task) {
  const due = dueLabel(task.due);
  const el  = document.createElement('button');
  el.type = 'button';
  el.className = 'wide-due ' + due.cls;
  el.textContent = due.text;
  el.title = '押すと期限を変えられます';
  el.addEventListener('click', e => {
    // 行そのものが「ClickUp を開く」を持っている。渡すとブラウザが開いてしまう。
    e.stopPropagation();
    openPicker('reschedule', { task, el });
  });
  return el;
}

// 期限の返事を、押した行へ配る（完了と同じ理由）。
const pendingReschedule = new Map();

function onTaskRescheduled(res) {
  const done = pendingReschedule.get(String(res.id));
  if (!done) return;
  pendingReschedule.delete(String(res.id));
  done(res);
}

// 期限を選んだあと。ClickUp 側が変わったのを確かめてから手元の控えを差し替える。
// 先に画面を書き換えると、失敗したときに嘘の期限が残る。
function applyReschedule(target, preset) {
  const { task, el } = target;
  if (!bridge) return;
  el.classList.add('busy');
  pendingReschedule.set(String(task.id), res => {
    el.classList.remove('busy');
    if (!res.ok) { showError(res.error || '期限を変えられませんでした'); return; }
    // 元の配列は書き換えない。差し替えた新しい配列にする。
    WIDE_TASKS = WIDE_TASKS.map(x => x.id === task.id ? { ...x, due: res.due } : x);
    renderWide();     // タブの範囲から外れれば行は消える。それがタブの意味なので知らせない
  });
  bridge.rescheduleTask(String(task.id), preset);
}

function buildWideRow(task) {
  const row = document.createElement('div');
  row.className = 'wide-row';
  row.title = 'クリックで ClickUp を開く';

  const side = document.createElement('div');
  side.className = 'wide-side';
  side.appendChild(buildWideDue(task));

  row.append(buildWideCheck(task, row), buildWideMain(task), side);
  row.addEventListener('click', () => { if (bridge && task.url) bridge.openTask(task.url); });
  return row;
}

const SCOPE_LABEL = { overdue: '期限切れ', today: '今日', week: '今週', all: 'すべて' };

function updateWideFoot(shown, total) {
  const label = SCOPE_LABEL[WIDE.scope] || '';
  const notes = [];
  if (WIDE.query) {
    // 探しているときに期限で切られていると、「無い」のか「このタブに無い」のかが
    // 分からない。ほかのタブに何件あるかを言っておく。
    // 数えられるのは手元にある分だけ。取りに行けた範囲で打ち切っているなら、
    // 確かな件数として読まれないよう「以上」と断る。
    const hits = WIDE_TASKS.filter(t => matchesQuery(t, tokenize(WIDE.query))).length;
    notes.push(hits > shown ? `ほかのタブに ${hits - shown} 件${WIDE_MORE ? '以上' : ''}`
                            : '絞り込み中');
  }
  if (total !== undefined && total !== shown)
    notes.push(WIDE_MORE ? `ここまでで ${total} 件` : `中断中ぜんぶで ${total} 件`);
  // 取れる分を使い切っていた。「出ているのが全部」と読まれると、
  // 一覧に無いタスクを「もう無い」と扱ってしまう。
  if (WIDE_MORE) notes.push('この先はまだ見ていません');
  wideFoot.textContent = `${label}: ${shown} 件`
                       + (notes.length ? `（${notes.join(' · ')}）` : '');
}

// pause.pyw が裏で取ってきた分を受け取る。絞るのはこちら側。
function setWideTasks(data) {
  WIDE.busy = false;
  if (!data.ok) {
    WIDE_TASKS = [];
    WIDE_MORE  = false;
    wideBody.replaceChildren(note('取得できませんでした。⟳ で取り直してください'));
    wideFoot.textContent = '';
    return;
  }
  WIDE_TASKS = data.tasks || [];
  WIDE_MORE  = !!data.more;
  renderWide();
}

// 1 件も出ないときの言い分け。絞り込みのせいなのか、そもそも無いのかを分ける。
function emptyNote() {
  if (WIDE.query) return `「${WIDE.query}」に当たるものはありません`;
  const base = {
    overdue: '期限切れのものはありません',
    today:   '今日が期限のものはありません',
    week:    '今週が期限のものはありません',
    all:     '中断中のタスクはありません',
  }[WIDE.scope];
  return base + (WIDE.scope === 'all' ? '' : '。「すべて」を押すと期限で切らずに出ます');
}

function renderWide() {
  const rows = wideRows();
  wideBody.replaceChildren();
  if (!rows.length) {
    wideBody.appendChild(note(emptyNote()));
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

// ── 出さないリスト ────────────────────────────────────────

// 出す／出さないを切り替える。押した瞬間に画面へ反映し、駄目なら戻す（★と同じ）。
function toggleExcluded(item) {
  const id  = String(item.id);
  const was = EXCLUDED.includes(id);
  EXCLUDED = was ? EXCLUDED.filter(x => x !== id) : [...EXCLUDED, id];
  // 外したぶんは手元から落とせる。戻したぶんは手元に無いので取り直すしかないが、
  // それは保存できてから（下のコールバック）。ここで頼むと、Python 側は
  // 頼まれた順に処理するので、まだ外したままの設定で取りに行ってしまう。
  if (!was) WIDE_TASKS = WIDE_TASKS.filter(t => String(t.list_id) !== id);
  if (isOpen()) renderPicker();
  renderWide();

  if (!bridge) return;
  bridge.setListExcluded(id, !was, raw => {
    const res = JSON.parse(raw);
    if (res.ok) {
      if (was) loadWide();      // 戻した。新しい設定で取り直す
      return;
    }
    EXCLUDED = was ? [...EXCLUDED, id] : EXCLUDED.filter(x => x !== id);
    showError(res.error || '設定を保存できませんでした');
    if (isOpen()) renderPicker();
    loadWide();                 // 落としたぶんを取り戻す（設定は変わっていない）
  });
}

// ── 絞り込み ──────────────────────────────────────────────

function clearWideSearch() {
  WIDE.query = '';
  wideSearch.value = '';
  wideSearch.classList.remove('on');
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
  clearWideSearch();      // 前回の絞り込みを引きずらない（件数を見誤る）
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
wideExclude.addEventListener('click', () => { if (!WIDE.busy) openPicker('exclude'); });
wideSort.addEventListener('click', () => {
  if (WIDE.busy) return;
  WIDE.newestFirst = !WIDE.newestFirst;
  renderSortButton();
  renderWide();
});

// 絞り込みは input で拾う。keydown だと日本語変換の途中が反映されない。
wideSearch.addEventListener('input', () => {
  WIDE.query = wideSearch.value;
  wideSearch.classList.toggle('on', !!WIDE.query);
  renderWide();
});
