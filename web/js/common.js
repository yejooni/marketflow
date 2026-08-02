/* Shared helpers: data loading, formatting, theme toggle, global search. */

export const PERIOD_LABELS = { '1M': '1개월', '3M': '3개월', '6M': '6개월', '12M': '12개월' };

const cache = new Map();

export async function loadJSON(path) {
  if (cache.has(path)) return cache.get(path);
  const p = fetch(path, { cache: 'no-cache' }).then((r) => {
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  });
  cache.set(path, p);
  return p;
}

/* ---------- formatting ---------- */

export const nf = (v, d = 0) =>
  v == null || !isFinite(v) ? '–'
    : v.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });

export function pct(v, d = 2, sign = true) {
  if (v == null || !isFinite(v)) return '–';
  return (sign && v > 0 ? '+' : '') + v.toFixed(d) + '%';
}

export function money(v) {
  if (v == null || !isFinite(v)) return '–';
  if (v >= 1e12) return (v / 1e12).toFixed(2) + '조';
  if (v >= 1e8) return (v / 1e8).toFixed(0) + '억';
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '만';
  return nf(v);
}

/** Won -> 억 units, the denomination the 거래대금 filter is expressed in.
 *  Whole 억 above 100 (nobody reads decimals on a 1,234억 print), one decimal
 *  below that so small caps do not all collapse to the same number. */
export function eok(v) {
  if (v == null || !isFinite(v)) return '–';
  const e = v / 1e8;
  return e >= 100 ? Math.round(e).toLocaleString('ko-KR') : e.toFixed(1);
}

/** Korean market convention: positive is red, negative is blue. */
export const dirClass = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');

export function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) {
    if (k == null || k === false) continue;
    n.appendChild(typeof k === 'string' || typeof k === 'number'
      ? document.createTextNode(String(k)) : k);
  }
  return n;
}

/* ---------- chrome ---------- */

export function initTheme() {
  const saved = localStorage.getItem('mf-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  const btn = document.getElementById('theme-btn');
  if (!btn) return;
  const sync = () => {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark'
      || (!document.documentElement.hasAttribute('data-theme')
          && matchMedia('(prefers-color-scheme: dark)').matches);
    btn.textContent = dark ? '☀' : '☾';
    btn.title = dark ? '라이트 모드' : '다크 모드';
  };
  btn.addEventListener('click', () => {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark'
      || (!document.documentElement.hasAttribute('data-theme')
          && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('mf-theme', next);
    sync();
    window.dispatchEvent(new Event('mf-theme'));
  });
  sync();
}

export function markNav(page) {
  document.querySelectorAll('nav.links a').forEach((a) => {
    if (a.dataset.page === page) a.classList.add('active');
  });
}

/* ---------- search ---------- */

export async function initSearch() {
  const input = document.getElementById('q');
  const box = document.getElementById('qres');
  if (!input || !box) return;

  let list = [];
  try {
    list = await loadJSON('data/index.json');
  } catch {
    return;
  }

  let sel = -1, shown = [];

  const close = () => { box.classList.remove('open'); sel = -1; };

  const render = () => {
    box.innerHTML = '';
    shown.forEach((row, i) => {
      const [code, name, market, themes] = row;
      box.appendChild(el('a', {
        href: `stock.html?code=${code}`,
        class: i === sel ? 'sel' : '',
      },
        el('span', { class: 'nm' }, name),
        el('span', { class: 'rc' }, code),
        el('span', { class: 'rt' }, (themes || []).join(' · ') || market),
      ));
    });
    box.classList.toggle('open', shown.length > 0);
  };

  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { shown = []; close(); box.innerHTML = ''; return; }
    const starts = [], contains = [];
    for (const row of list) {
      const [code, name] = row;
      const n = name.toLowerCase();
      if (n.startsWith(q) || code.startsWith(q)) starts.push(row);
      else if (n.includes(q) || code.includes(q)) contains.push(row);
      if (starts.length >= 12) break;
    }
    shown = starts.concat(contains).slice(0, 12);
    sel = -1;
    render();
  });

  input.addEventListener('keydown', (e) => {
    if (!shown.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = (sel + 1) % shown.length; render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = (sel - 1 + shown.length) % shown.length; render(); }
    else if (e.key === 'Enter') {
      const pick = shown[sel >= 0 ? sel : 0];
      if (pick) location.href = `stock.html?code=${pick[0]}`;
    } else if (e.key === 'Escape') { close(); input.blur(); }
  });

  document.addEventListener('click', (e) => {
    if (!box.contains(e.target) && e.target !== input) close();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== input) {
      e.preventDefault(); input.focus();
    }
  });
}

/** Sortable tables: click a th with data-sort to reorder.
 *
 * Callers re-invoke this whenever the filtered row set changes, so the header
 * listeners are bound once per table and kept on the element. Re-binding each
 * time would stack handlers and make one click toggle direction repeatedly.
 */
export function makeSortable(table, rows, render, initial) {
  const st = table._mfSort || (table._mfSort = {
    key: initial.key,
    dir: initial.dir || -1,
    bound: false,
  });
  st.rows = rows;
  st.render = render;

  const apply = () => {
    const { key, dir } = st;
    const sorted = [...st.rows].sort((a, b) => {
      const x = a[key], y = b[key];
      const xn = x == null || (typeof x === 'number' && !isFinite(x));
      const yn = y == null || (typeof y === 'number' && !isFinite(y));
      if (xn && yn) return 0;
      if (xn) return 1;          // missing values always sink
      if (yn) return -1;
      if (typeof x === 'string') return dir * x.localeCompare(y, 'ko');
      return dir * (x - y);
    });
    st.render(sorted);
    table.querySelectorAll('th[data-sort]').forEach((th) => {
      const a = th.querySelector('.arrow');
      if (a) a.remove();
      if (th.dataset.sort === key) {
        th.appendChild(el('span', { class: 'arrow' }, dir < 0 ? '▼' : '▲'));
      }
    });
  };
  st.apply = apply;

  if (!st.bound) {
    st.bound = true;
    table.querySelectorAll('th[data-sort]').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.sort;
        if (k === st.key) st.dir = -st.dir;
        else { st.key = k; st.dir = th.dataset.asc ? 1 : -1; }
        st.apply();
      });
    });
  }

  apply();
  return st;
}

/** Probability cell: a bar for comparison plus the value. Null means the
 *  sample was too small to estimate, which must not read as 0%. */
export function probCell(prob) {
  if (prob == null || !isFinite(prob)) {
    return el('div', { class: 'meter' },
      el('span', { class: 'val muted', title: '표본 부족' }, '–'));
  }
  const p = prob * 100;
  return el('div', { class: 'meter' },
    el('div', { class: 'track' },
      el('div', { class: 'fill', style: `width:${Math.min(100, p)}%` })),
    el('span', { class: 'val' }, p.toFixed(1) + '%'));
}

export function themeChips(themes, limit = 2) {
  return (themes || []).slice(0, limit).map((t) =>
    el('a', { class: 'chip', href: `theme.html?id=${t.id}`, title: t.name,
              onclick: (e) => e.stopPropagation() }, t.name));
}
