/* Task page - served by _askai/server.py at /task/<area>/<task>/.
 *
 * The server lays out the columns and the cards. This file draws the arrows
 * between cards from where the cards really are, keeps the whole map on one
 * screen, and renames a step in place. Vanilla, no dependencies, no build step. */
(function () {
"use strict";

var board = document.getElementById("board");
if (!board) return;

var DATA = {};
try { DATA = JSON.parse(document.getElementById("task-data").textContent) || {}; }
catch (e) { DATA = {}; }
var ARROWS = DATA.arrows || [];
var NS = "http://www.w3.org/2000/svg";
var svg = board.querySelector("svg.wires");
var layer = board.querySelector(".labels");
var GRID = board.getAttribute("data-mode") === "grid";
var NCOLS = +board.getAttribute("data-cols") || 1;

/* Below these the columns stack into one list and each arrow becomes a line of
 * text inside its card, so a phone never has to scroll sideways. */
var MIN_CARD = 184, MIN_GAP = 92, PHONE = 760;

/* ---------------------------------------------------------------- geometry - */

var origin = null;
function rect(x, y, w, h) { return { x: x, y: y, w: w, h: h, r: x + w, b: y + h }; }
function box(el) {
  var r = el.getBoundingClientRect();
  return rect(r.left - origin.left, r.top - origin.top, r.width, r.height);
}
function grow(a, d) { return rect(a.x - d, a.y - d, a.w + 2 * d, a.h + 2 * d); }
function overlap(a, b) {
  var w = Math.min(a.r, b.r) - Math.max(a.x, b.x);
  var h = Math.min(a.b, b.b) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}
function n1(v) { return Math.round(v * 10) / 10; }
function pt(x, y) { return n1(x) + " " + n1(y); }

/* A path through right-angled turns, each corner rounded off. */
function rounded(points, radius) {
  var p = [];
  points.forEach(function (q) {
    var last = p[p.length - 1];
    if (!last || Math.abs(last[0] - q[0]) > 0.5 || Math.abs(last[1] - q[1]) > 0.5) p.push(q);
  });
  var d = "M" + pt(p[0][0], p[0][1]);
  for (var i = 1; i < p.length - 1; i++) {
    var a = p[i - 1], b = p[i], c = p[i + 1];
    var l1 = Math.hypot(b[0] - a[0], b[1] - a[1]);
    var l2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
    var r = Math.min(radius, l1 / 2, l2 / 2);
    var s = [b[0] + (a[0] - b[0]) * r / l1, b[1] + (a[1] - b[1]) * r / l1];
    var e = [b[0] + (c[0] - b[0]) * r / l2, b[1] + (c[1] - b[1]) * r / l2];
    d += " L" + pt(s[0], s[1]) + " Q" + pt(b[0], b[1]) + " " + pt(e[0], e[1]);
  }
  var z = p[p.length - 1];
  return d + " L" + pt(z[0], z[1]);
}

/* ------------------------------------------------------------------ drawing - */

function clear() {
  [].slice.call(svg.childNodes).forEach(function (node) {
    if (node.nodeName.toLowerCase() !== "defs") svg.removeChild(node);
  });
  layer.innerHTML = "";
  board.style.paddingBottom = "";
}

function stacked() {
  if (GRID) return false;
  if (window.innerWidth <= PHONE) return true;
  return board.clientWidth < NCOLS * MIN_CARD + (NCOLS - 1) * MIN_GAP;
}

function draw() {
  clear();
  board.setAttribute("data-layout", stacked() ? "stack" : "columns");
  if (GRID || board.getAttribute("data-layout") !== "columns" || !ARROWS.length) return;
  origin = board.getBoundingClientRect();

  var cols = [].slice.call(board.querySelectorAll(".col"));
  var colBox = cols.map(box);
  var W = board.clientWidth;
  var cards = {}, obstacles = [];
  var floorOf = cols.map(function () { return 0; });   /* lowest thing in each column */

  [].forEach.call(board.querySelectorAll(".card"), function (el) {
    var col = cols.indexOf(el.closest(".col")), b = box(el);
    cards[el.getAttribute("data-step")] = { el: el, col: col, box: b, ports: { l: [], r: [] } };
    obstacles.push(b);
    floorOf[col] = Math.max(floorOf[col], b.b);
  });
  [].forEach.call(board.querySelectorAll(".g-head"), function (el) {
    var col = cols.indexOf(el.closest(".col")), b = box(el);
    obstacles.push(b);
    floorOf[col] = Math.max(floorOf[col], b.b);
  });

  /* The empty strips either side of every column. Arrows and their labels
   * live only in these, which is what keeps them off the cards. */
  var gaps = [];
  for (var g = 0; g <= cols.length; g++) {
    var left = g === 0 ? 0 : colBox[g - 1].r;
    var right = g === cols.length ? W : colBox[g].x;
    gaps.push({ x: left, r: right, w: right - left, load: 0 });
  }

  var list = [];
  ARROWS.forEach(function (a) {
    var A = cards[a.from], B = cards[a.to];
    if (A && B) list.push({ from: a.from, to: a.to, label: a.label || "", A: A, B: B });
  });
  function span(a) { return Math.abs(a.A.box.y - a.B.box.y); }
  function mid(c) { return c.box.y + c.box.h / 2; }

  /* Neighbouring columns: straight across the gap between them. Further apart:
   * down a gap, under the columns in between, and up the far gap. */
  list.forEach(function (a) {
    var ca = a.A.col, cb = a.B.col;
    if (ca === cb) { a.kind = "same"; return; }
    var right = cb > ca;
    a.kind = Math.abs(cb - ca) === 1 ? "next" : "far";
    a.sideA = right ? "r" : "l";
    a.sideB = right ? "l" : "r";
    if (a.kind === "next") { a.gap = Math.max(ca, cb); gaps[a.gap].load++; }
  });
  /* Two cards in one column: the arrow bulges into whichever side gap carries
   * fewer labels. The page edge is never wide enough to use. */
  list.filter(function (a) { return a.kind === "same"; })
    .sort(function (p, q) { return span(q) - span(p); })
    .forEach(function (a) {
      var c = a.A.col, R = gaps[c + 1], L = gaps[c];
      var okR = R.w >= 64, okL = L.w >= 64;
      var useR = okR && (!okL || R.load <= L.load);
      if (!okR && !okL) useR = R.w >= L.w;
      a.sideA = a.sideB = useR ? "r" : "l";
      a.gap = useR ? c + 1 : c;
      gaps[a.gap].load++;
    });

  /* Where each arrow meets its card: spread down the edge, in the order of
   * the cards at the other end, so arrows fan out instead of crossing. */
  list.forEach(function (a) {
    a.A.ports[a.sideA].push({ a: a, end: "A", other: a.B });
    a.B.ports[a.sideB].push({ a: a, end: "B", other: a.A });
  });
  Object.keys(cards).forEach(function (key) {
    var c = cards[key];
    ["l", "r"].forEach(function (side) {
      var ports = c.ports[side], n = ports.length;
      if (!n) return;
      ports.sort(function (p, q) { return mid(p.other) - mid(q.other); });
      var top = c.box.y + 10, bottom = c.box.b - 10;
      ports.forEach(function (p, i) {
        var y = n === 1 ? c.box.y + Math.min(c.box.h / 2, 28)
                        : top + (bottom - top) * (i + 0.5) / n;
        var x = side === "r" ? c.box.r : c.box.x;
        if (p.end === "A") { p.a.x1 = x; p.a.y1 = y; } else { p.a.x2 = x; p.a.y2 = y; }
      });
    });
  });

  /* Arrows sharing a side gap nest: the shortest hugs the column. */
  var nests = {};
  list.forEach(function (a) {
    if (a.kind !== "same") return;
    var key = a.gap + a.sideA;
    (nests[key] = nests[key] || []).push(a);
  });
  Object.keys(nests).forEach(function (key) {
    nests[key].sort(function (p, q) { return Math.abs(p.y2 - p.y1) - Math.abs(q.y2 - q.y1); })
      .forEach(function (a, i) { a.bulge = Math.min(gaps[a.gap].w * 0.4, 16 + i * 11); });
  });

  var far = list.filter(function (a) { return a.kind === "far"; });
  var lowest = board.scrollHeight;
  list.forEach(function (a) {
    var d;
    if (a.kind === "next") {
      var mx = (a.x1 + a.x2) / 2;
      d = "M" + pt(a.x1, a.y1) + " C" + pt(mx, a.y1) + " " + pt(mx, a.y2) + " " + pt(a.x2, a.y2);
    } else if (a.kind === "same") {
      var cx = a.x1 + (a.sideA === "r" ? 1 : -1) * a.bulge * 4 / 3;
      d = "M" + pt(a.x1, a.y1) + " C" + pt(cx, a.y1) + " " + pt(cx, a.y2) + " " + pt(a.x2, a.y2);
    } else {
      var i = far.indexOf(a), shift = (i - (far.length - 1) / 2) * 8;
      var toRight = a.B.col > a.A.col;
      var gA = gaps[toRight ? a.A.col + 1 : a.A.col];
      var gB = gaps[toRight ? a.B.col : a.B.col + 1];
      var lo = Math.min(a.A.col, a.B.col) + 1, hi = Math.max(a.A.col, a.B.col) - 1, under = 0;
      for (var k = lo; k <= hi; k++) under = Math.max(under, floorOf[k]);
      a.yc = under + 24 + i * 18;
      a.gx1 = gA.x + gA.w / 2 + shift;
      a.gx2 = gB.x + gB.w / 2 + shift;
      d = rounded([[a.x1, a.y1], [a.gx1, a.y1], [a.gx1, a.yc], [a.gx2, a.yc],
                   [a.gx2, a.y2], [a.x2, a.y2]], 10);
      lowest = Math.max(lowest, a.yc + 30);
    }
    var path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", "wire");
    path.setAttribute("marker-end", "url(#tk-mk)");
    path.setAttribute("data-from", a.from);
    path.setAttribute("data-to", a.to);
    svg.appendChild(path);
    a.path = path;
  });
  /* An arrow that runs under a column needs room below the tallest one. */
  if (lowest > board.offsetHeight) board.style.paddingBottom = (lowest - board.offsetHeight) + "px";

  placeLabels(list, gaps, obstacles, W, Math.max(board.offsetHeight, lowest));
}

/* Each label sits on its own arrow, somewhere along it where it covers no
 * card, no group heading and no other label. Short arrows go first, since
 * they have the fewest places to put one. */
function placeLabels(list, gaps, obstacles, W, H) {
  var placed = [];
  list.slice()
    .sort(function (p, q) { return p.path.getTotalLength() - q.path.getTotalLength(); })
    .forEach(function (a) {
      if (!a.label) return;
      var el = document.createElement("div");
      el.className = "w-label";
      el.textContent = a.label;
      el.setAttribute("data-from", a.from);
      el.setAttribute("data-to", a.to);
      var gap = a.kind === "far" ? null : gaps[a.gap];
      el.style.maxWidth = (gap ? Math.max(56, Math.min(160, gap.w - 14)) : 170) + "px";
      layer.appendChild(el);
      var w = el.offsetWidth, h = el.offsetHeight;

      var spots = [];
      if (a.kind === "far") {
        [0.5, 0.38, 0.62, 0.26, 0.74, 0.14, 0.86].forEach(function (t) {
          spots.push([a.gx1 + (a.gx2 - a.gx1) * t, a.yc]);
        });
      } else {
        var len = a.path.getTotalLength();
        [0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74, 0.18, 0.82, 0.12, 0.88].forEach(function (t) {
          var q = a.path.getPointAtLength(len * t);
          spots.push([q.x, q.y]);
        });
      }

      var best = null, cost = Infinity;
      var nudges = [0, -(h / 2 + 3), h / 2 + 3];
      search:
      for (var n = 0; n < nudges.length; n++) {
        for (var s = 0; s < spots.length; s++) {
          var x = spots[s][0] - w / 2, y = spots[s][1] - h / 2 + nudges[n];
          if (gap) x = Math.max(gap.x + 5, Math.min(x, gap.r - 5 - w));
          x = Math.max(2, Math.min(x, W - w - 2));
          y = Math.max(2, Math.min(y, H - h - 2));
          var r = rect(x, y, w, h), c = 0;
          obstacles.forEach(function (o) { c += overlap(r, grow(o, 4)); });
          placed.forEach(function (o) { c += overlap(r, grow(o, 3)); });
          if (c < cost) { best = r; cost = c; }
          if (c === 0) break search;
        }
      }
      el.style.left = n1(best.x) + "px";
      el.style.top = n1(best.y) + "px";
      if (cost > 0) el.setAttribute("data-overlap", "1");
      placed.push(best);
    });
}

/* ---------------------------------------------------------------- one screen */

function overflowing() {
  var de = document.documentElement;
  return de.scrollHeight > window.innerHeight + 1 || de.scrollWidth > window.innerWidth + 1;
}

function layout() {
  board.classList.remove("compact", "tight");
  draw();
  var levels = ["compact", "tight"];
  for (var i = 0; i < levels.length && overflowing() &&
                  board.getAttribute("data-layout") !== "stack"; i++) {
    board.classList.add(levels[i]);
    draw();
  }
  board.setAttribute("data-fit", overflowing() ? "no" : "yes");
  highlight(hovered);
}

/* ------------------------------------------------------------------ hovering */
/* Pointing at a step lights its own arrows and fades the rest, so one step's
 * connections can be read even where many arrows share a gap. */

var hovered = null;
function highlight(step) {
  hovered = step || null;
  board.classList.toggle("focus", !!hovered);
  var related = {};
  [].forEach.call(svg.querySelectorAll(".wire"), function (p) {
    var on = !!hovered && (p.getAttribute("data-from") === hovered ||
                           p.getAttribute("data-to") === hovered);
    p.classList.toggle("on", on);
    p.setAttribute("marker-end", on ? "url(#tk-mk-on)" : "url(#tk-mk)");
    if (on) {
      related[p.getAttribute("data-from")] = true;
      related[p.getAttribute("data-to")] = true;
      svg.appendChild(p);                       /* lit arrows draw on top */
    }
  });
  [].forEach.call(layer.querySelectorAll(".w-label"), function (l) {
    l.classList.toggle("on", !!hovered && (l.getAttribute("data-from") === hovered ||
                                           l.getAttribute("data-to") === hovered));
  });
  [].forEach.call(board.querySelectorAll(".card"), function (c) {
    var step = c.getAttribute("data-step");
    c.classList.toggle("rel", !!related[step] && step !== hovered);
  });
}
function cardStep(target) {
  var card = target && target.closest ? target.closest(".card") : null;
  return card ? card.getAttribute("data-step") : null;
}
board.addEventListener("mouseover", function (e) {
  var step = cardStep(e.target);
  if (step !== hovered) highlight(step);
});
board.addEventListener("mouseleave", function () { highlight(null); });
board.addEventListener("focusin", function (e) { highlight(cardStep(e.target)); });

/* ------------------------------------------------------------------ renaming */
/* Changes the name shown here, in the list and in the top bar. The server
 * writes it into `_task.json`; the folder name never moves. */

board.addEventListener("click", function (e) {
  var button = e.target.closest && e.target.closest(".c-ren");
  if (!button) return;
  e.preventDefault();
  e.stopPropagation();
  edit(button.closest(".card"));
});

function edit(card) {
  var open = card.querySelector(".c-form");
  if (open) { open.querySelector(".c-input").focus(); return; }
  var link = card.querySelector(".c-title");
  var num = card.querySelector(".c-num").textContent || "this step";
  var form = document.createElement("form");
  form.className = "c-form";
  form.setAttribute("novalidate", "");
  form.innerHTML =
    '<input class="c-input" type="text" autocomplete="off" spellcheck="false">' +
    '<div class="c-actions"><button type="submit" class="c-save">Save</button>' +
    '<button type="button" class="c-cancel">Cancel</button></div>' +
    '<p class="c-msg" role="status">Changes the name shown here and in the list. ' +
    'The folder keeps its name.</p>';
  var input = form.querySelector(".c-input");
  var msg = form.querySelector(".c-msg");
  var save = form.querySelector(".c-save");
  input.value = link.textContent;
  input.setAttribute("aria-label", "New name for " + num);
  link.hidden = true;
  link.parentNode.insertBefore(form, link.nextSibling);
  card.classList.add("editing");
  layout();
  input.focus();
  input.select();

  function close() {
    form.remove();
    link.hidden = false;
    card.classList.remove("editing");
    layout();
    link.focus();
  }
  form.querySelector(".c-cancel").addEventListener("click", close);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); close(); }
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    save.disabled = true;
    msg.classList.remove("err");
    msg.textContent = "Saving...";
    fetch("/api/task/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: DATA.task, step: card.getAttribute("data-step"),
                             title: input.value })
    }).then(function (res) {
      return res.json().then(function (body) { return { ok: res.ok, body: body || {} }; },
                             function () { return { ok: false, body: {} }; });
    }).then(function (r) {
      save.disabled = false;
      if (!r.ok || !r.body.ok) {
        msg.classList.add("err");
        msg.textContent = r.body.error || "The new name was not saved.";
        layout();
        input.focus();
        return;
      }
      link.textContent = r.body.title;
      close();
      card.classList.remove("saved");
      void card.offsetWidth;                     /* restart the animation */
      card.classList.add("saved");
    }).catch(function () {
      save.disabled = false;
      msg.classList.add("err");
      msg.textContent = "Could not reach the proxy. Is it still running?";
    });
  });
}

/* --------------------------------------------------------------------- boot - */

var timer = null;
window.addEventListener("resize", function () {
  clearTimeout(timer);
  timer = setTimeout(layout, 120);
});
window.addEventListener("load", layout);
layout();
})();
