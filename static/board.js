// Canvas-рендер доски «Коридор» (этап 4). Без зависимостей, ES-модуль.
//
// Слои разделены так, чтобы этап 5 воткнул сеть в ОДИН шов (`commitAction`):
//   1) геометрия (orientation-aware transform, поворот 180° для P1);
//   2) render(state) — единая точка отрисовки (этап 5 вызовет её на сокет-событии);
//   3) HiDPI + resize;
//   4) hover-хит-тест по hints (клик ход НЕ отправляет — пустой шов).
//
// Правил игры в JS нет (решение B1): легальность считает сервер, клиент рисует
// то, что пришло в `hints`. Координаты ядра — канонические (col,row), 0..8;
// якоря стен (c,r) — 0..7, ориентация o ∈ {"H","V"} (см. game/board.py wall_edges).

const SIZE = 9;        // клеток по стороне
const SLOTS = 8;       // пазов под стену по стороне (между клетками)

// --- входные данные (инлайн-JSON, шов под этап 5) ---
const { view, hints, my_side } = JSON.parse(
  document.getElementById("game-data").textContent,
);

// Эгоцентрик: своя пешка снизу, цель сверху. Дом P1 — канонический ряд 0 (верх),
// поэтому его доску поворачиваем на 180°. P2 видит канонику как есть.
const rotate180 = my_side === 1;

// Множества легального для хит-теста (ключи — строки).
const legalMoveCells = new Set(); // "c,r"
const legalWalls = new Set();     // "c,r,o"
for (const m of hints.moves) {
  if (m.type === "move") legalMoveCells.add(`${m.to[0]},${m.to[1]}`);
  else if (m.type === "wall") legalWalls.add(`${m.c},${m.r},${m.o}`);
}

// --- палитра: единственный источник — CSS-переменные :root ---
const css = getComputedStyle(document.documentElement);
const c = (name) => css.getPropertyValue(name).trim();
const COLORS = {
  bg: c("--bp-bg"),
  cell: c("--bp-cell"),
  line: c("--bp-line"),
  wall: c("--bp-wall"),
  p1: c("--bp-p1"),
  p2: c("--bp-p2"),
  legal: c("--bp-legal"),
};

const canvas = document.getElementById("board");
const ctx = canvas.getContext("2d");

// === 1. Геометрия (orientation-aware transform) ====================
// layout подгоняется под целевой пиксельный размер (фикс. max ~540px, ужимается).
const layout = { CELL: 0, GAP: 0, MARGIN: 0, PITCH: 0, px: 0 };

function computeLayout() {
  const wrap = canvas.parentElement;
  const avail = Math.min(540, (wrap ? wrap.clientWidth : 540) || 540);
  const S = Math.max(280, avail);
  const MARGIN = Math.round(S * 0.03);
  const inner = S - 2 * MARGIN;
  const ratio = 0.18; // GAP = ratio * CELL (паз тоньше клетки)
  const CELL = inner / (SIZE + (SIZE - 1) * ratio);
  const GAP = CELL * ratio;
  layout.CELL = CELL;
  layout.GAP = GAP;
  layout.MARGIN = MARGIN;
  layout.PITCH = CELL + GAP; // шаг сетки: клетка + паз
  layout.px = 2 * MARGIN + SIZE * CELL + (SIZE - 1) * GAP;
}

// левый/верхний край клетки экранной координаты bc/br
const cellX = (bc) => layout.MARGIN + bc * layout.PITCH;
const cellY = (br) => layout.MARGIN + br * layout.PITCH;

// клетка: каноника <-> экран (180° самообратен на диапазоне 0..8)
const toScreenCell = (col, row) =>
  rotate180 ? [SIZE - 1 - col, SIZE - 1 - row] : [col, row];
const toCanonCell = (bc, br) =>
  rotate180 ? [SIZE - 1 - bc, SIZE - 1 - br] : [bc, br];

// стена: якорь каноника <-> экран. H(c,r)→H(7-c,7-r), V(c,r)→V(7-c,7-r).
const toScreenWall = (col, row) =>
  rotate180 ? [SLOTS - 1 - col, SLOTS - 1 - row] : [col, row];
const toCanonWall = (sc, sr) =>
  rotate180 ? [SLOTS - 1 - sc, SLOTS - 1 - sr] : [sc, sr];

// прямоугольник стены в px по ЭКРАННОМУ якорю (sc,sr) и ориентации o.
// H — горизонтальный брус в пазу под рядом sr, на 2 клетки (столбцы sc, sc+1).
// V — вертикальный брус в пазу справа от столбца sc, на 2 клетки (ряды sr, sr+1).
function wallToRect(sc, sr, o) {
  const x = cellX(sc), y = cellY(sr);
  if (o === "H") {
    return { x, y: y + layout.CELL, w: 2 * layout.CELL + layout.GAP, h: layout.GAP };
  }
  return { x: x + layout.CELL, y, w: layout.GAP, h: 2 * layout.CELL + layout.GAP };
}

// px → каноническая клетка {c,r} или null (если курсор в пазу/за доской)
function pixelToCell(px, py) {
  const rx = px - layout.MARGIN, ry = py - layout.MARGIN;
  if (rx < 0 || ry < 0) return null;
  const bc = Math.floor(rx / layout.PITCH);
  const br = Math.floor(ry / layout.PITCH);
  if (bc < 0 || bc >= SIZE || br < 0 || br >= SIZE) return null;
  if (rx - bc * layout.PITCH > layout.CELL) return null; // попал в паз
  if (ry - br * layout.PITCH > layout.CELL) return null;
  const [col, row] = toCanonCell(bc, br);
  return { c: col, r: row };
}

// px → ближайший паз {c,r,o} в канонике. H/V — по близости к гориз./верт. пазу.
function pixelToWallSlot(px, py) {
  const clamp = (v) => Math.max(0, Math.min(SLOTS - 1, v));
  const sc = clamp(Math.round((px - layout.MARGIN - layout.CELL - layout.GAP / 2) / layout.PITCH));
  const sr = clamp(Math.round((py - layout.MARGIN - layout.CELL - layout.GAP / 2) / layout.PITCH));
  const vlineX = cellX(sc) + layout.CELL + layout.GAP / 2; // линия верт. паза
  const hlineY = cellY(sr) + layout.CELL + layout.GAP / 2; // линия гориз. паза
  const o = Math.abs(px - vlineX) < Math.abs(py - hlineY) ? "V" : "H";
  const [col, row] = toCanonWall(sc, sr);
  return { c: col, r: row, o };
}

// === 2. render(state) — единая точка отрисовки =====================
let hover = null; // {kind:'cell',c,r} | {kind:'wall',c,r,o} — только легальное

function drawPawn(pos, color) {
  const [bc, br] = toScreenCell(pos[0], pos[1]);
  const cx = cellX(bc) + layout.CELL / 2, cy = cellY(br) + layout.CELL / 2;
  ctx.beginPath();
  ctx.arc(cx, cy, layout.CELL * 0.32, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
}

function drawMoveDot(col, row) {
  const [bc, br] = toScreenCell(col, row);
  const cx = cellX(bc) + layout.CELL / 2, cy = cellY(br) + layout.CELL / 2;
  ctx.save();
  ctx.globalAlpha = 0.45;
  ctx.fillStyle = COLORS.legal;
  ctx.beginPath();
  ctx.arc(cx, cy, layout.CELL * 0.14, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawHover() {
  ctx.save();
  if (hover.kind === "cell") {
    const [bc, br] = toScreenCell(hover.c, hover.r);
    ctx.globalAlpha = 0.30;
    ctx.fillStyle = COLORS.legal;
    ctx.fillRect(cellX(bc), cellY(br), layout.CELL, layout.CELL);
  } else {
    const [sc, sr] = toScreenWall(hover.c, hover.r);
    const r = wallToRect(sc, sr, hover.o);
    ctx.globalAlpha = 0.7;
    ctx.fillStyle = COLORS.legal; // ghost легальной стены — зелёная
    ctx.fillRect(r.x, r.y, r.w, r.h);
  }
  ctx.restore();
}

function render() {
  ctx.clearRect(0, 0, layout.px, layout.px);
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, layout.px, layout.px);

  // клетки
  ctx.fillStyle = COLORS.cell;
  for (let bc = 0; bc < SIZE; bc++) {
    for (let br = 0; br < SIZE; br++) {
      ctx.fillRect(cellX(bc), cellY(br), layout.CELL, layout.CELL);
    }
  }

  // подсветка легальных целей пешки (всегда видна)
  for (const key of legalMoveCells) {
    const [col, row] = key.split(",").map(Number);
    drawMoveDot(col, row);
  }

  // стены
  ctx.fillStyle = COLORS.wall;
  for (const w of view.walls) {
    const [sc, sr] = toScreenWall(w.c, w.r);
    const r = wallToRect(sc, sr, w.o);
    ctx.fillRect(r.x, r.y, r.w, r.h);
  }

  // пешки
  drawPawn(view.pawns["1"], COLORS.p1);
  drawPawn(view.pawns["2"], COLORS.p2);

  // ghost под курсором
  if (hover) drawHover();
}

// === 3. HiDPI + resize =============================================
function resizeCanvas() {
  computeLayout();
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${layout.px}px`;
  canvas.style.height = `${layout.px}px`;
  canvas.width = Math.round(layout.px * dpr);
  canvas.height = Math.round(layout.px * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // рисуем в CSS-пикселях
  render();
}

// === 4. Hover (scope этапа 4) + шов commitAction ===================
function hitTest(px, py) {
  const cell = pixelToCell(px, py);
  if (cell && legalMoveCells.has(`${cell.c},${cell.r}`)) {
    return { kind: "cell", c: cell.c, r: cell.r };
  }
  const slot = pixelToWallSlot(px, py);
  if (slot && legalWalls.has(`${slot.c},${slot.r},${slot.o}`)) {
    return { kind: "wall", c: slot.c, r: slot.r, o: slot.o };
  }
  return null;
}

canvas.addEventListener("mousemove", (e) => {
  const next = hitTest(e.offsetX, e.offsetY);
  if (JSON.stringify(next) !== JSON.stringify(hover)) {
    hover = next;
    render();
  }
});

canvas.addEventListener("mouseleave", () => {
  if (hover) {
    hover = null;
    render();
  }
});

// Клик строит action и зовёт шов — но СЕТИ НЕТ (этап 5 подключит commitAction).
canvas.addEventListener("click", (e) => {
  const hit = hitTest(e.offsetX, e.offsetY);
  if (!hit) return;
  const action = hit.kind === "cell"
    ? { type: "move", to: [hit.c, hit.r] }
    : { type: "wall", c: hit.c, r: hit.r, o: hit.o };
  commitAction(action);
});

function commitAction(action) {
  /* этап 5: отправить action по сокету и перерисовать на ответ сервера. */
  void action;
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();
