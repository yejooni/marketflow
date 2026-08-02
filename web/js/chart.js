/* Kiwoom-style daily candlestick chart on canvas.
 *
 * Follows Korean HTS convention: 양봉(close>=open) red, 음봉 blue, a volume
 * pane beneath the price pane, moving averages drawn as thin lines with a
 * value legend across the top, right-hand price axis, and a crosshair that
 * reports the hovered session.
 *
 * No dependencies: the drawing is direct 2D canvas so the conventions match
 * 영웅문 exactly rather than approximating them through a generic library.
 */

const MA_SET = [
  { n: 5,   key: '--ma5'   },
  { n: 20,  key: '--ma20'  },
  { n: 60,  key: '--ma60'  },
  { n: 120, key: '--ma120' },
];

const PAD = { top: 26, right: 66, bottom: 22, left: 8 };
const VOL_RATIO = 0.24;   // share of plot height given to the volume pane
const PANE_GAP = 10;
const MIN_BARS = 20;
const LEVEL_STRETCH = 0.35;  // most a reference line may expand the price scale

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function sma(values, n) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= n) sum -= values[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

function niceStep(raw) {
  const exp = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / exp;
  const step = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return step * exp;
}

const fmtInt = (v) => Math.round(v).toLocaleString('ko-KR');

function fmtVol(v) {
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '억';
  if (v >= 1e4) return Math.round(v / 1e4).toLocaleString('ko-KR') + '만';
  return fmtInt(v);
}

function fmtDate(s) {
  return `${s.slice(0, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}`;
}

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

function fmtDateFull(s) {
  const d = new Date(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8));
  return `${fmtDate(s)} (${WEEKDAYS[d.getDay()]})`;
}

function fmtEok(v) {
  const e = v / 1e8;
  return e >= 100 ? Math.round(e).toLocaleString('ko-KR') : e.toFixed(1);
}

function signed(p) {
  return (p > 0 ? '+' : '') + p.toFixed(2) + '%';
}

export class KiwoomChart {
  constructor(host, data, opts = {}) {
    this.host = host;
    this.opts = Object.assign({ height: 460, levels: [], showMA: true, showLevels: true }, opts);

    this.canvas = document.createElement('canvas');
    this.host.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');

    // Tooltip lives in the DOM rather than on the canvas: text layout, wrapping
    // and theme colours come free, and it can overflow the plot area cleanly.
    this.tip = document.createElement('div');
    this.tip.className = 'chart-tip';
    this.host.appendChild(this.tip);

    this.hover = null;
    this.hoverPane = 'price';
    this.pointer = null;
    this.drag = null;
    this.setData(data);

    this._onResize = () => this.resize();
    window.addEventListener('resize', this._onResize);
    if (window.matchMedia) {
      this._mq = window.matchMedia('(prefers-color-scheme: dark)');
      this._onScheme = () => this.draw();
      this._mq.addEventListener?.('change', this._onScheme);
    }

    this.canvas.addEventListener('mousemove', (e) => this.onMove(e));
    this.canvas.addEventListener('mouseleave', () => {
      this.hover = null; this.pointer = null; this.draw();
    });
    this.canvas.addEventListener('mousedown', (e) => this.onDown(e));
    window.addEventListener('mouseup', () => { this.drag = null; });
    this.canvas.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });

    this.canvas.addEventListener('touchstart', (e) => this.onTouch(e), { passive: true });
    this.canvas.addEventListener('touchmove', (e) => this.onTouch(e), { passive: true });
    this.canvas.addEventListener('touchend', () => {
      this.hover = null; this.pointer = null; this.draw();
    });

    this.resize();
  }

  destroy() {
    window.removeEventListener('resize', this._onResize);
    this._mq?.removeEventListener?.('change', this._onScheme);
  }

  setData(d) {
    this.d = d;
    this.n = d.c.length;
    this.ma = {};
    for (const m of MA_SET) this.ma[m.n] = sma(d.c, m.n);
    this.view = { a: 0, b: this.n };
    this.setRange(this.opts.initialBars || this.n);
  }

  /** Show the most recent `bars` sessions. */
  setRange(bars) {
    const b = this.n;
    const a = Math.max(0, b - Math.max(MIN_BARS, Math.min(bars, this.n)));
    this.view = { a, b };
    this.draw();
  }

  resize() {
    const w = this.host.clientWidth;
    const h = this.opts.height;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.height = h + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w;
    this.h = h;
    this.draw();
  }

  /* ---------- geometry ---------- */

  layout() {
    const plotL = PAD.left;
    const plotR = this.w - PAD.right;
    const plotW = plotR - plotL;
    const totalH = this.h - PAD.top - PAD.bottom - PANE_GAP;
    const volH = Math.round(totalH * VOL_RATIO);
    const priceH = totalH - volH;
    return {
      plotL, plotR, plotW,
      priceT: PAD.top,
      priceB: PAD.top + priceH,
      volT: PAD.top + priceH + PANE_GAP,
      volB: PAD.top + priceH + PANE_GAP + volH,
    };
  }

  bandWidth(L) {
    return L.plotW / (this.view.b - this.view.a);
  }

  xOf(i, L) {
    const bw = this.bandWidth(L);
    return L.plotL + (i - this.view.a + 0.5) * bw;
  }

  indexAt(px, L) {
    const bw = this.bandWidth(L);
    return Math.floor((px - L.plotL) / bw) + this.view.a;
  }

  scales(L) {
    const { a, b } = this.view;
    let lo = Infinity, hi = -Infinity, vhi = 0;
    for (let i = a; i < b; i++) {
      if (this.d.l[i] < lo) lo = this.d.l[i];
      if (this.d.h[i] > hi) hi = this.d.h[i];
      if (this.d.v[i] > vhi) vhi = this.d.v[i];
    }
    if (this.opts.showMA) {
      for (const m of MA_SET) {
        for (let i = a; i < b; i++) {
          const v = this.ma[m.n][i];
          if (v == null) continue;
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
    }
    if (this.opts.showLevels) {
      // A 12-month high far above the current price would flatten the candles
      // into a strip, so a level may only stretch the scale so far. Levels
      // beyond that are simply not drawn -- the period cards state the value.
      const span = hi - lo || hi || 1;
      const ceiling = hi + span * LEVEL_STRETCH;
      const floor = lo - span * LEVEL_STRETCH;
      for (const lv of this.opts.levels) {
        if (lv.value > hi && lv.value <= ceiling) hi = lv.value;
        if (lv.value < lo && lv.value >= floor) lo = lv.value;
      }
    }
    if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
    const pad = (hi - lo) * 0.06 || hi * 0.05 || 1;
    lo -= pad; hi += pad;
    if (lo < 0) lo = 0;

    const priceY = (p) => L.priceB - ((p - lo) / (hi - lo)) * (L.priceB - L.priceT);
    const volY = (v) => L.volB - (vhi > 0 ? (v / vhi) * (L.volB - L.volT) : 0);
    return { lo, hi, vhi, priceY, volY };
  }

  /* ---------- interaction ---------- */

  localPos(e) {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  onMove(e) {
    const L = this.layout();
    const p = this.localPos(e);
    if (this.drag) {
      const bw = this.bandWidth(L);
      const shift = Math.round((this.drag.x - p.x) / bw);
      if (shift !== 0) {
        const span = this.view.b - this.view.a;
        let a = this.drag.a + shift;
        a = Math.max(0, Math.min(this.n - span, a));
        this.view = { a, b: a + span };
        this.draw();
      }
      return;
    }
    if (p.x < L.plotL || p.x > L.plotR) {
      if (this.hover !== null) { this.hover = null; this.pointer = null; this.draw(); }
      return;
    }
    const i = Math.max(this.view.a, Math.min(this.view.b - 1, this.indexAt(p.x, L)));
    // Which pane the cursor is in decides what the tooltip reports.
    const pane = p.y >= L.volT - PANE_GAP / 2 ? 'volume' : 'price';
    const changed = i !== this.hover || pane !== this.hoverPane;
    this.hover = i;
    this.hoverPane = pane;
    this.pointer = p;
    if (changed) this.draw(); else this.placeTip(p);
  }

  onDown(e) {
    const p = this.localPos(e);
    this.drag = { x: p.x, a: this.view.a };
  }

  onWheel(e) {
    e.preventDefault();
    const L = this.layout();
    const p = this.localPos(e);
    const focus = Math.max(0, Math.min(this.n - 1, this.indexAt(p.x, L)));
    const span = this.view.b - this.view.a;
    const next = Math.max(MIN_BARS, Math.min(this.n, Math.round(span * (e.deltaY > 0 ? 1.15 : 0.87))));
    const frac = (focus - this.view.a) / span;
    let a = Math.round(focus - frac * next);
    a = Math.max(0, Math.min(this.n - next, a));
    this.view = { a, b: a + next };
    this.draw();
  }

  onTouch(e) {
    if (!e.touches.length) return;
    const L = this.layout();
    const r = this.canvas.getBoundingClientRect();
    const x = e.touches[0].clientX - r.left;
    const y = e.touches[0].clientY - r.top;
    if (x < L.plotL || x > L.plotR) return;
    const i = Math.max(this.view.a, Math.min(this.view.b - 1, this.indexAt(x, L)));
    this.hover = i;
    this.hoverPane = y >= L.volT - PANE_GAP / 2 ? 'volume' : 'price';
    this.pointer = { x, y };
    this.draw();
  }

  /* ---------- painting ---------- */

  draw() {
    if (!this.ctx || !this.w) return;
    const c = this.ctx;
    const L = this.layout();
    const S = this.scales(L);

    const col = {
      bg: cssVar('--chart-bg'), grid: cssVar('--grid'), ink: cssVar('--ink'),
      muted: cssVar('--muted'), border: cssVar('--border'),
      up: cssVar('--up'), down: cssVar('--down'), cross: cssVar('--crosshair'),
      surface: cssVar('--surface'),
    };

    c.clearRect(0, 0, this.w, this.h);
    c.fillStyle = col.bg;
    c.fillRect(0, 0, this.w, this.h);

    this.drawGrid(c, L, S, col);
    if (this.opts.showLevels) this.drawLevels(c, L, S, col);
    this.drawVolume(c, L, S, col);
    this.drawCandles(c, L, S, col);
    if (this.opts.showMA) this.drawMAs(c, L, S);
    this.drawAxes(c, L, S, col);
    this.drawLegend(c, L, col);
    if (this.hover != null) this.drawCrosshair(c, L, S, col);
    this.renderTip();
  }

  /* ---------- tooltip ---------- */

  renderTip() {
    const i = this.hover;
    if (i == null || i < this.view.a || i >= this.view.b || !this.pointer) {
      this.tip.style.display = 'none';
      return;
    }

    const d = this.d;
    const prev = i > 0 ? d.c[i - 1] : null;
    const rel = (v) => (prev ? `<i class="${v >= prev ? 'up' : 'down'}">${signed((v / prev - 1) * 100)}</i>` : '');

    let rows;
    if (this.hoverPane === 'volume') {
      const shares = this.opts.shares;
      const amount = d.v[i] * (d.o[i] + d.h[i] + d.l[i] + d.c[i]) / 4;
      rows = [
        ['상장주식수', shares ? fmtInt(shares) : '–'],
        ['거래량', fmtInt(d.v[i])],
        ['주식수 대비', shares ? (d.v[i] / shares * 100).toFixed(2) + '%' : '–'],
        ['거래대금(억)', fmtEok(amount)],
      ].map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join('');
    } else {
      const cls = d.c[i] >= d.o[i] ? 'up' : 'down';
      rows = [['시가', d.o[i]], ['고가', d.h[i]], ['저가', d.l[i]], ['종가', d.c[i]]]
        .map(([k, v]) =>
          `<tr><th>${k}</th><td class="${cls}">${fmtInt(v)}</td><td class="p">${rel(v)}</td></tr>`)
        .join('');
    }

    this.tip.innerHTML = `<div class="d">${fmtDateFull(d.d[i])}</div><table>${rows}</table>`;
    this.tip.style.display = 'block';
    this.placeTip(this.pointer);
  }

  /** Keep the tooltip beside the cursor but always inside the chart. */
  placeTip(p) {
    if (this.tip.style.display === 'none') return;
    const pad = 14;
    const w = this.tip.offsetWidth;
    const h = this.tip.offsetHeight;
    let x = p.x + pad;
    let y = p.y + pad;
    if (x + w > this.w - 4) x = p.x - w - pad;
    if (y + h > this.h - 4) y = Math.max(4, p.y - h - pad);
    this.tip.style.left = Math.max(4, x) + 'px';
    this.tip.style.top = y + 'px';
  }

  priceTicks(S) {
    const span = S.hi - S.lo;
    const step = niceStep(span / 6);
    const out = [];
    for (let v = Math.ceil(S.lo / step) * step; v <= S.hi; v += step) out.push(v);
    return out;
  }

  drawGrid(c, L, S, col) {
    c.strokeStyle = col.grid;
    c.lineWidth = 1;
    c.beginPath();
    for (const v of this.priceTicks(S)) {
      const y = Math.round(S.priceY(v)) + 0.5;
      c.moveTo(L.plotL, y); c.lineTo(L.plotR, y);
    }
    // month boundaries as vertical guides
    for (let i = this.view.a + 1; i < this.view.b; i++) {
      if (this.d.d[i].slice(4, 6) !== this.d.d[i - 1].slice(4, 6)) {
        const x = Math.round(this.xOf(i, L)) + 0.5;
        c.moveTo(x, L.priceT); c.lineTo(x, L.priceB);
        c.moveTo(x, L.volT); c.lineTo(x, L.volB);
      }
    }
    c.stroke();
  }

  drawLevels(c, L, S, col) {
    c.save();
    c.setLineDash([5, 4]);
    c.lineWidth = 1;
    for (const lv of this.opts.levels) {
      const y = Math.round(S.priceY(lv.value)) + 0.5;
      if (y < L.priceT || y > L.priceB) continue;
      c.strokeStyle = lv.color || col.muted;
      c.beginPath(); c.moveTo(L.plotL, y); c.lineTo(L.plotR, y); c.stroke();

      c.setLineDash([]);
      c.font = '600 10px ' + cssVar('--mono');
      const label = lv.label;
      const tw = c.measureText(label).width + 8;
      c.fillStyle = col.bg;
      c.fillRect(L.plotL + 4, y - 13, tw, 12);
      c.fillStyle = lv.color || col.muted;
      c.textAlign = 'left'; c.textBaseline = 'middle';
      c.fillText(label, L.plotL + 8, y - 7);
      c.setLineDash([5, 4]);
    }
    c.restore();
  }

  drawVolume(c, L, S, col) {
    const bw = this.bandWidth(L);
    const w = Math.max(1, Math.min(bw * 0.7, bw - 1));
    for (let i = this.view.a; i < this.view.b; i++) {
      const up = this.d.c[i] >= this.d.o[i];
      c.fillStyle = up ? col.up : col.down;
      c.globalAlpha = 0.5;
      const x = this.xOf(i, L) - w / 2;
      const y = S.volY(this.d.v[i]);
      c.fillRect(x, y, w, L.volB - y);
    }
    c.globalAlpha = 1;
    c.strokeStyle = col.border;
    c.beginPath();
    c.moveTo(L.plotL, L.volB + 0.5); c.lineTo(L.plotR, L.volB + 0.5);
    c.stroke();
  }

  drawCandles(c, L, S, col) {
    const bw = this.bandWidth(L);
    const w = Math.max(1, Math.min(bw * 0.7, bw - 1));
    const thin = w < 2.5;

    for (let i = this.view.a; i < this.view.b; i++) {
      const o = this.d.o[i], h = this.d.h[i], l = this.d.l[i], cl = this.d.c[i];
      const up = cl >= o;
      const color = up ? col.up : col.down;
      const x = this.xOf(i, L);
      const yo = S.priceY(o), yc = S.priceY(cl);
      const yh = S.priceY(h), yl = S.priceY(l);

      // wick
      c.strokeStyle = color;
      c.lineWidth = 1;
      const xw = Math.round(x) + 0.5;
      c.beginPath(); c.moveTo(xw, yh); c.lineTo(xw, yl); c.stroke();

      if (thin) continue;
      // body — filled, Korean HTS style
      const top = Math.min(yo, yc);
      const bh = Math.max(1, Math.abs(yc - yo));
      c.fillStyle = color;
      c.fillRect(Math.round(x - w / 2), Math.round(top), Math.round(w), Math.round(bh));
    }
  }

  drawMAs(c, L, S) {
    for (const m of MA_SET) {
      const series = this.ma[m.n];
      c.strokeStyle = cssVar(m.key);
      c.lineWidth = 1.2;
      c.beginPath();
      let started = false;
      for (let i = this.view.a; i < this.view.b; i++) {
        const v = series[i];
        if (v == null) { started = false; continue; }
        const x = this.xOf(i, L), y = S.priceY(v);
        if (!started) { c.moveTo(x, y); started = true; } else c.lineTo(x, y);
      }
      c.stroke();
    }
  }

  drawAxes(c, L, S, col) {
    c.font = '11px ' + cssVar('--mono');
    c.fillStyle = col.muted;
    c.textAlign = 'left';
    c.textBaseline = 'middle';

    for (const v of this.priceTicks(S)) {
      c.fillText(fmtInt(v), L.plotR + 6, S.priceY(v));
    }
    c.fillText(fmtVol(S.vhi), L.plotR + 6, L.volT + 6);

    // date axis: label the first session of each month
    c.textAlign = 'center';
    c.textBaseline = 'top';
    let last = -999;
    for (let i = this.view.a; i < this.view.b; i++) {
      const isFirst = i === this.view.a
        || this.d.d[i].slice(4, 6) !== this.d.d[i - 1].slice(4, 6);
      if (!isFirst) continue;
      const x = this.xOf(i, L);
      if (x - last < 44) continue;
      last = x;
      const s = this.d.d[i];
      const label = s.slice(4, 6) === '01' ? s.slice(0, 4) : `${+s.slice(4, 6)}월`;
      c.fillText(label, x, L.volB + 6);
    }

    // last-close marker on the price axis
    const li = this.view.b - 1;
    const lc = this.d.c[li];
    const up = lc >= this.d.o[li];
    const y = S.priceY(lc);
    c.fillStyle = up ? col.up : col.down;
    c.fillRect(L.plotR + 1, y - 8, PAD.right - 2, 16);
    c.fillStyle = '#fff';
    c.font = '600 11px ' + cssVar('--mono');
    c.textAlign = 'left'; c.textBaseline = 'middle';
    c.fillText(fmtInt(lc), L.plotR + 6, y);
  }

  drawLegend(c, L, col) {
    const i = this.hover != null ? this.hover : this.view.b - 1;
    c.font = '11px ' + cssVar('--mono');
    c.textBaseline = 'middle';
    c.textAlign = 'left';
    let x = L.plotL + 2;
    const y = 13;

    const o = this.d.o[i], h = this.d.h[i], l = this.d.l[i], cl = this.d.c[i];
    const prev = i > 0 ? this.d.c[i - 1] : o;
    const chg = prev ? (cl / prev - 1) * 100 : 0;

    c.fillStyle = col.ink;
    c.fillText(fmtDate(this.d.d[i]), x, y);
    x += c.measureText(fmtDate(this.d.d[i])).width + 12;

    const parts = [['시', o], ['고', h], ['저', l], ['종', cl]];
    for (const [k, v] of parts) {
      c.fillStyle = col.muted;
      c.fillText(k, x, y); x += c.measureText(k).width + 3;
      c.fillStyle = cl >= o ? col.up : col.down;
      const s = fmtInt(v);
      c.fillText(s, x, y); x += c.measureText(s).width + 9;
    }
    c.fillStyle = chg > 0 ? col.up : chg < 0 ? col.down : col.muted;
    const cs = (chg > 0 ? '+' : '') + chg.toFixed(2) + '%';
    c.fillText(cs, x, y); x += c.measureText(cs).width + 12;

    if (this.opts.showMA) {
      for (const m of MA_SET) {
        const v = this.ma[m.n][i];
        if (v == null) continue;
        const label = `MA${m.n} ${fmtInt(v)}`;
        c.fillStyle = cssVar(m.key);
        c.fillText(label, x, y);
        x += c.measureText(label).width + 10;
        if (x > L.plotR - 60) break;
      }
    }
  }

  drawCrosshair(c, L, S, col) {
    const i = this.hover;
    if (i < this.view.a || i >= this.view.b) return;
    const x = Math.round(this.xOf(i, L)) + 0.5;

    c.save();
    c.setLineDash([3, 3]);
    c.strokeStyle = col.cross;
    c.lineWidth = 1;
    c.beginPath();
    c.moveTo(x, L.priceT); c.lineTo(x, L.volB);
    c.stroke();
    c.restore();

    // date tag under the axis
    const label = fmtDate(this.d.d[i]);
    c.font = '11px ' + cssVar('--mono');
    const tw = c.measureText(label).width + 10;
    c.fillStyle = col.cross;
    c.fillRect(x - tw / 2, L.volB + 3, tw, 15);
    c.fillStyle = col.bg;
    c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText(label, x, L.volB + 11);

    // volume readout
    c.fillStyle = col.muted;
    c.font = '10px ' + cssVar('--mono');
    c.textAlign = 'left'; c.textBaseline = 'top';
    c.fillText('거래량 ' + fmtVol(this.d.v[i]), L.plotL + 2, L.volT + 2);
  }
}

export { fmtInt, fmtVol, fmtDate };
