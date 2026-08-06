// 候補パネル（リスト・担当者・期限）。
// 状態（DIR / FAV / picked*）は ui.js が持っている。ここは探し方と見せ方だけ。
// ── 検索 ──────────────────────────────────────────────────

// 全角スペースも区切りとして扱う。「grand kyoto」でも「archive grand kyoto」でも当たる。
function tokenize(q) {
  return (q || '').toLowerCase().split(/[\s　]+/).filter(Boolean);
}

// 打った並びそのままで当たったものを上に。「blue moon」で「BlueMoon」より
// 「Blue Moon」が先に来てほしい、という当たり前の期待に合わせる。
function rankList(item, tokens, phrase) {
  const name = item.name.toLowerCase();
  const path = (item.path || '').toLowerCase();
  const hay  = name + ' ' + path;
  if (!tokens.every(t => hay.includes(t))) return -1;
  if (name.startsWith(phrase)) return 0;
  if (name.includes(phrase))   return 1;
  if (name.startsWith(tokens[0])) return 2;
  if (tokens.every(t => name.includes(t))) return 3;
  return 4;                                  // 親パスの助けで当たった
}

function searchLists(q) {
  const tokens = tokenize(q);
  const phrase = tokens.join(' ');
  if (!tokens.length) {
    // 空欄のときは「★ → 最近使った → 既定 → 残り」。探す前に手が届くように。
    // 既定を最近より下に置くのは、既定はいつでもそこにあると分かっているのに対し、
    // 直前に使った先はもう一度使う見込みが高いため。
    const byId = new Map(DIR.lists.map(l => [String(l.id), l]));
    const head = [];
    const seen = new Set();
    const push = (id, tag) => {
      const item = byId.get(String(id));
      if (item && !seen.has(String(id))) { head.push({ item, tag }); seen.add(String(id)); }
    };
    // ★のタグは付けない。行の右端で★ボタンが光っているので二重になる。
    FAV.lists.forEach(id => push(id, ''));
    RECENT.forEach(id => push(id, '最近'));
    push(DEFAULT_LIST.id, '既定');
    const rest = DIR.lists.filter(l => !seen.has(String(l.id))).map(item => ({ item, tag: '' }));
    return head.concat(rest);
  }
  return DIR.lists
    .map(item => ({ item, rank: rankList(item, tokens, phrase) }))
    .filter(r => r.rank >= 0)
    .sort((a, b) => a.rank - b.rank
                 || favRank(a.item, 'list') - favRank(b.item, 'list')
                 || a.item.name.length - b.item.name.length)
    .map(r => ({ item: r.item, tag: '' }));
}

function searchMembers(q) {
  const tokens = tokenize(q);
  const hit = m => {
    const hay = (m.name + ' ' + (m.email || '')).toLowerCase();
    return tokens.every(t => hay.includes(t));
  };
  const self = DIR.members.find(m => m.id === SELF.id) || SELF;
  if (!tokens.length) {
    // 「自分 → ★ → 残り」。他人に振るのは★の人がほとんど、という前提。
    const out  = [{ item: self, tag: '自分' }];
    const seen = new Set([String(self.id)]);
    FAV.members.forEach(id => {
      const m = DIR.members.find(x => String(x.id) === String(id));
      if (m && !seen.has(String(id))) { out.push({ item: m, tag: '' }); seen.add(String(id)); }
    });
    DIR.members.filter(m => !seen.has(String(m.id)))
               .forEach(item => out.push({ item, tag: '' }));
    return out;
  }
  const out = [];
  if (hit(self)) out.push({ item: self, tag: '自分' });
  DIR.members
    .filter(m => m.id !== SELF.id && hit(m))
    .sort((a, b) => favRank(a, 'user') - favRank(b, 'user'))
    .forEach(item => out.push({ item, tag: '' }));
  return out;
}

// 期限は 6 つで固定。絞り込む必要がないので検索欄も出さない。
function searchDue() {
  return DUE_PRESETS.map(item => ({ item, tag: item.id === DEFAULT_DUE ? '既定' : '' }));
}

// 一致した部分だけ太くする。textContent 経由で組むので中身が HTML でも壊れない。
function highlight(text, tokens) {
  const frag = document.createDocumentFragment();
  if (!tokens.length) { frag.appendChild(document.createTextNode(text)); return frag; }
  const lower = text.toLowerCase();
  const marks = new Array(text.length).fill(false);
  tokens.forEach(t => {
    let from = 0;
    for (;;) {
      const at = lower.indexOf(t, from);
      if (at < 0) break;
      for (let i = at; i < at + t.length; i++) marks[i] = true;
      from = at + t.length;
    }
  });
  let i = 0;
  while (i < text.length) {
    const on = marks[i];
    let j = i;
    while (j < text.length && marks[j] === on) j++;
    const chunk = text.slice(i, j);
    if (on) {
      const m = document.createElement('mark');
      m.textContent = chunk;
      frag.appendChild(m);
    } else {
      frag.appendChild(document.createTextNode(chunk));
    }
    i = j;
  }
  return frag;
}

// ── 候補パネル ────────────────────────────────────────────

// target は「何に対して選んでいるか」。期限ずらしのときだけ入る（対象の 1 件）。
const state = { kind: null, rows: [], active: 0, target: null };

function isOpen() { return state.kind !== null; }

// 選ぶものが 6 つで固定のパネル。検索欄を出さず、丈も詰める。
function isFixedList(kind) { return kind === 'due' || kind === 'reschedule'; }

function renderPicker() {
  const q = pickerSearch.value;
  const tokens = isFixedList(state.kind) ? [] : tokenize(q);
  state.rows = state.kind === 'list'       ? searchLists(q)
             : state.kind === 'user'       ? searchMembers(q)
             : state.kind === 'exclude'    ? searchExclude(q)
             : state.kind === 'reschedule' ? searchReschedule()
             : searchDue();
  // 開き直したとき、いま選んでいるものに合わせておく（毎回先頭に戻さない）。
  //
  // 当たるものが無いときは、どこも光らせない（-1）。
  //   ・出さないリスト  … そもそも「選んであるもの」という概念が無い
  //   ・期限ずらし      … いまの期限が 6 つのどれでもないことがある（「3 日後」など）
  // ここで先頭を光らせると「今日が選んである」ように見えて、Enter を押した拍子に
  // その期限へ動いてしまう。出さないリストなら、そのリストが一覧から外れてしまう。
  const found = state.rows.findIndex(r => r.item.id === currentPick().id);
  state.active = state.kind === 'exclude' ? -1
               : found >= 0               ? found
               : isFixedList(state.kind)  ? -1 : 0;

  pickerNote.textContent = state.kind === 'exclude'
    ? 'チェックを外したリストは、この一覧にも「最近登録したタスク」にも出なくなります'
    : '';
  pickerNote.style.display = state.kind === 'exclude' ? '' : 'none';

  pickerList.replaceChildren();
  if (!state.rows.length) {
    const empty = document.createElement('div');
    empty.className = 'pick-empty';
    empty.textContent = '見つかりません';
    pickerList.appendChild(empty);
    return;
  }

  // 200 件を全部組むと打鍵ごとに重くなるので、見えるぶんだけに切る。
  state.rows = state.rows.slice(0, 60);
  state.rows.forEach((row, index) => pickerList.appendChild(buildPickerRow(row, index, tokens)));
  // 選んであるところまで送る。-1（どこも光らせない）のときは触らない。
  if (state.active > 0) setActive(state.active);
}

// ── その 1 件の期限を選び直す ──────────────────────────────

// 既定を変える話ではないので ⌂ は出さない。いま付いている期限に「いま」と付けるだけ。
function searchReschedule() {
  const now = currentDuePreset(state.target.task);
  return DUE_PRESETS.map(item => ({ item, tag: item.id === now ? 'いま' : '' }));
}

// いま付いている期限が 6 つのどれに当たるか。当たらなければ ''。
// 「3 日後」などは日付そのものが残っているだけで、どのプリセットで入れたかは分からない。
function currentDuePreset(task) {
  if (!task.due) return 'none';
  const label = dueLabel(task.due);
  if (label.text === '今日') return 'today';
  if (label.text === '明日') return 'tomorrow';
  return '';
}

// ── 一覧に出さないリスト ──────────────────────────────────

// 並びが肝心。「200 件から探して外す」ではなく、動機はいつでも
// 「いま見えているこの行のリストが邪魔」なので、その順に並べる。
function searchExclude(q) {
  const tokens = tokenize(q);
  const phrase = tokens.join(' ');
  const inView = new Set(WIDE_TASKS.map(t => String(t.list_id)).filter(Boolean));
  const rankOf = item => EXCLUDED.includes(String(item.id)) ? 0
                       : inView.has(String(item.id))        ? 1 : 2;
  // タグは「外してある」だけ。いま出ているものぜんぶに付けると、
  // 全行に同じ札が並んで何も言っていないのと同じになる（並びが上なのがその印）。
  const tagOf  = item => EXCLUDED.includes(String(item.id)) ? '外してある' : '';
  return DIR.lists
    .filter(item => !tokens.length || rankList(item, tokens, phrase) >= 0)
    .map(item => ({ item, tag: tagOf(item), rank: rankOf(item) }))
    .sort((a, b) => a.rank - b.rank)     // 同じ段の中は元の並びのまま（sort は安定）
    .map(r => ({ item: r.item, tag: r.tag }));
}

// チェックの入り切りにする。「出す・出さない」は入り切りの話であって、
// ◉ のような記号では、いまどちらの状態なのかが読み取れない。
function buildEyeButton(item) {
  const off = EXCLUDED.includes(String(item.id));
  const eye = document.createElement('button');
  eye.type = 'button';
  eye.className = 'pick-eye' + (off ? ' off' : '');
  eye.textContent = off ? '☐' : '☑';
  eye.title = off ? '一覧に出すようにする' : 'このリストは一覧に出さない';
  fixMousedown(eye, () => toggleExcluded(item));
  return eye;
}

// 候補 1 行ぶん。行の下に出す文字は、リストなら親フォルダ、
// 担当者ならメールアドレス、期限なら言い換え。
function pickerSubText(item) {
  if (state.kind === 'list' || state.kind === 'exclude') return item.path  || '';
  if (state.kind === 'user') return item.email || '';
  return item.hint || '';
}

function buildFavButton(item) {
  const on  = isFav(item, state.kind);
  const fav = document.createElement('button');
  fav.type = 'button';
  fav.className = 'pick-fav' + (on ? ' on' : '');
  fav.textContent = on ? '★' : '☆';
  fav.title = on ? 'よく使うものから外す' : 'よく使うものに入れる';
  fixMousedown(fav, () => toggleFav(item, state.kind));
  return fav;
}

// いま既定になっているか。既定の行には「既定」タグが出るので、ピンは出さない。
function isDefaultItem(item) {
  if (state.kind === 'list') return String(item.id) === String(DEFAULT_LIST.id);
  if (state.kind === 'due')  return item.id === DEFAULT_DUE;
  return false;                    // 担当者に既定は無い（自分が既定）
}

function buildPinButton(item) {
  const pin = document.createElement('button');
  pin.type = 'button';
  pin.className = 'pick-pin';
  pin.textContent = '⌂';
  pin.title = 'これを既定にする';
  fixMousedown(pin, () => setDefault(item, state.kind));
  return pin;
}

// 行の上に載せたボタンは、行の mousedown より先に自分の用事を済ませる。
function fixMousedown(el, run) {
  el.addEventListener('mousedown', e => {
    e.preventDefault();
    e.stopPropagation();
    run();
  });
}

function buildPickerRow(row, index, tokens) {
  const el = document.createElement('div');
  el.className = 'pick-row' + (index === state.active ? ' active' : '');

  const body = document.createElement('div');
  body.className = 'pick-body';

  const name = document.createElement('div');
  name.className = 'pick-name';
  name.appendChild(highlight(row.item.name, tokens));
  body.appendChild(name);

  const sub = pickerSubText(row.item);
  if (sub) {
    const path = document.createElement('div');
    path.className = isFixedList(state.kind) ? 'pick-hint' : 'pick-path';
    path.appendChild(highlight(sub, tokens));
    body.appendChild(path);
  }
  el.appendChild(body);

  if (row.tag) {
    const tag = document.createElement('span');
    tag.className = 'pick-tag';
    tag.textContent = row.tag;
    el.appendChild(tag);
  }

  // 既定を移せるのはリストと期限の候補だけ。期限ずらしは「その 1 件」を動かすもので、
  // 既定とは別物なので ⌂ を出さない（出すと、1 件のつもりが次からぜんぶ変わる）。
  if ((state.kind === 'list' || state.kind === 'due') && !isDefaultItem(row.item))
    el.appendChild(buildPinButton(row.item));
  // 期限は数が決まっているので★を付ける意味がない。
  if (state.kind === 'list' || state.kind === 'user') el.appendChild(buildFavButton(row.item));
  // 出さないリストは、選ぶのではなくその場で切り替える。
  if (state.kind === 'exclude') {
    el.classList.toggle('excluded', EXCLUDED.includes(String(row.item.id)));
    el.appendChild(buildEyeButton(row.item));
  }

  el.addEventListener('mousedown', e => { e.preventDefault(); choose(index); });
  el.addEventListener('mousemove', () => setActive(index));
  return el;
}

function setActive(index) {
  const els = pickerList.children;
  if (!els.length) return;
  state.active = Math.max(0, Math.min(index, els.length - 1));
  for (let i = 0; i < els.length; i++) els[i].classList.toggle('active', i === state.active);
  els[state.active].scrollIntoView({ block: 'nearest' });
}

function currentPick() {
  if (state.kind === 'list')       return pickedList;
  if (state.kind === 'user')       return pickedUser;
  if (state.kind === 'reschedule') return { id: currentDuePreset(state.target.task) };
  if (state.kind === 'exclude')    return { id: '' };   // 「いま選んでいるもの」は無い
  return pickedDue;
}

function openPicker(kind, target) {
  state.kind   = kind;
  state.target = target || null;
  pickerSearch.value = '';
  pickerSearch.placeholder = kind === 'exclude' ? '出したくないリストを探す…'
                           : kind === 'list'    ? 'リストを絞り込む…'
                           : '担当者を絞り込む…';
  picker.classList.add('open');
  picker.classList.toggle('due', isFixedList(kind));
  pickerScrim.classList.add('open');
  renderPicker();
  if (isFixedList(kind)) return;    // 検索欄が無いので、キーは document 側で拾う
  pickerSearch.focus();
  // リスト名も担当者名もアルファベット。ここに入ったら半角英数で打ち始めたい。
  // focus のあとに頼む（Chromium が要素に合わせて IME を触るのが先なので）。
  if (bridge) bridge.imeAlphanumeric();
}

function closePicker(backToChip) {
  if (!isOpen()) return;
  // 更新の知らせは別物（選ぶものが無い）。専用の閉じ方に任せる。
  if (state.kind === 'update') { closeUpdatePanel(); return; }
  const kind = state.kind;
  state.kind   = null;
  state.target = null;
  picker.classList.remove('open', 'due');
  pickerScrim.classList.remove('open');
  pickerList.replaceChildren();
  // 入力モードは戻さない。閉じた後に戻そうとしても効かなかったため。
  // 戻す先のチップがあるのは入力画面の 3 つだけ。一覧から開いたぶんには戻り先が無い。
  if (backToChip && (kind === 'list' || kind === 'user' || kind === 'due'))
    (kind === 'list' ? chipList : kind === 'user' ? chipUser : chipDue).focus();
}

function choose(index) {
  const row = state.rows[index];
  if (!row) return;
  // 出さないリストは選ぶものではなく、その場で切り替えるもの。パネルは開けたままにする
  //（続けて何件か外したいことが多い）。
  if (state.kind === 'exclude') { toggleExcluded(row.item); return; }
  if (state.kind === 'reschedule') {
    const target = state.target;      // 閉じると消えるので先に控える
    closePicker(false);
    applyReschedule(target, row.item.id);
    return;
  }
  if (state.kind === 'list')      pickedList = row.item;
  else if (state.kind === 'user') pickedUser = row.item;
  else                            pickedDue  = row.item;
  closePicker(false);
  renderTargets();
  // 選んだら本題へ戻す。選択は手段であって目的ではないため。
  taskInput.focus();
}

chipList.addEventListener('click', () => openPicker('list'));
chipUser.addEventListener('click', () => openPicker('user'));
chipDue.addEventListener('click',  () => openPicker('due'));

// 絞り込みは input で拾う。keydown だと日本語変換の途中が反映されない。
pickerSearch.addEventListener('input', () => { if (isOpen()) renderPicker(); });

// パネルの外を押したら戻る。暗幕が受けるので、下にある一覧は反応しない。
pickerScrim.addEventListener('mousedown', e => { e.preventDefault(); closePicker(false); });
