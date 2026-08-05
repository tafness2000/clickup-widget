// 新しい版のお知らせ。
// pause.pyw が起動したときに 1 回だけ確認して、あるときだけチップを出す。
// 押すと中身を見せて、そこから更新できる。更新そのものは別のプロセスがやる。

const chipUpdate = document.getElementById('chipUpdate');

let UPDATE = null;      // 新しい版があるときだけ入る

// pause.pyw が確認の結果を流し込む。
function setUpdate(status) {
  UPDATE = (status && status.state === 'available') ? status : null;
  chipUpdate.classList.toggle('on', !!UPDATE);
}

// 更新が終わった直後に一度だけ出す知らせ。
function setUpdateResult(run) {
  if (!run || !run.state) return;
  if (run.state === 'completed') {
    successText.textContent = run.message || '新しい版になりました';
    formArea.style.display = 'none';
    successArea.style.display = 'flex';
    setTimeout(() => { formArea.style.display = ''; successArea.style.display = 'none'; }, 2400);
  } else if (run.state === 'failed') {
    showError(run.message || '更新できませんでした');
  }
}

function updateLine(text, cls) {
  const el = document.createElement('div');
  el.className = cls;
  el.textContent = text;
  return el;
}

// 候補パネルの場所を借りて、更新の中身を見せる。
function openUpdatePanel() {
  if (!UPDATE) return;
  closePicker(false);
  closeWide();

  pickerList.replaceChildren();

  const head = document.createElement('div');
  head.className = 'update-head';
  head.textContent = `新しい版があります（${UPDATE.behind} 件の更新）`;
  const sha = document.createElement('div');
  sha.className = 'sha';
  sha.textContent = `${(UPDATE.localSha || '').slice(0, 7)} → ${(UPDATE.remoteSha || '').slice(0, 7)}`;
  head.appendChild(sha);
  pickerList.appendChild(head);

  const changes = UPDATE.changes || [];
  if (changes.length) {
    changes.forEach(line => pickerList.appendChild(updateLine('・' + line, 'update-line')));
  } else {
    pickerList.appendChild(updateLine('（変更の一覧を取れませんでした）', 'update-line'));
  }

  const actions = document.createElement('div');
  actions.className = 'update-actions';

  const later = document.createElement('button');
  later.type = 'button';
  later.className = 'update-later';
  later.textContent = 'あとで';
  later.addEventListener('click', () => closeUpdatePanel());

  const go = document.createElement('button');
  go.type = 'button';
  go.className = 'update-go';
  go.textContent = 'いま更新する';
  go.addEventListener('click', () => {
    go.disabled = true;
    go.textContent = '更新しています…';
    if (!bridge) return;
    bridge.startUpdate(raw => {
      const res = JSON.parse(raw);
      if (res.ok) {
        // ここから先は別のプロセスの仕事。この窓はまもなく閉じる。
        go.textContent = '更新中です。しばらくお待ちください';
      } else {
        go.disabled = false;
        go.textContent = 'いま更新する';
        closeUpdatePanel();
        showError(res.error || '更新できませんでした');
      }
    });
  });

  actions.append(later, go);
  pickerList.appendChild(actions);

  state.kind = 'update';          // Esc と暗幕の扱いを候補パネルと合わせる
  state.rows = [];
  picker.classList.add('open', 'update');
  pickerScrim.classList.add('open');
}

function closeUpdatePanel() {
  picker.classList.remove('open', 'update');
  pickerScrim.classList.remove('open');
  pickerList.replaceChildren();
  state.kind = null;
  setTimeout(() => taskInput.focus(), 30);
}

chipUpdate.addEventListener('click', openUpdatePanel);
