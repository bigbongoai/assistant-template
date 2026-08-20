/* Ask AI - injected into every page by _askai/server.py.
 *
 * Select a passage, ask about it, and the passage stays highlighted permanently
 * with its thread attached. A highlight IS a thread that was started from a
 * passage, so there is no separate highlight store to drift.
 *
 * Vanilla, no dependencies, no build step. Builds all of its own DOM so a host
 * page needs zero markup. */
(function () {
"use strict";

if (window.__askaiLoaded) return;
window.__askaiLoaded = true;

var DOC = window.ASKAI_DOC || "";
var Q = "doc=" + encodeURIComponent(DOC);

/* Content root: where highlights may live. Never the Ask AI UI itself. */
var MAIN = document.querySelector("main") || document.querySelector("article") || document.body;

var threadId = null, selectedText = "", busy = false, threadMeta = {}, lastThreadId = null;

/* ------------------------------------------------------------------ markdown */
/* Escape first, then build only known tags. Model output can never inject HTML. */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, function (m, a) { return "<code>" + a + "</code>"; })
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(src) {
  var lines = esc(src).split("\n"), out = [], buf = [], fence = null, i = 0;
  function flush() {
    if (buf.length) { out.push("<p>" + inline(buf.join(" ")) + "</p>"); buf = []; }
  }
  function cells(row) {
    return row.trim().replace(/^\||\|$/g, "").split("|")
      .map(function (c) { return inline(c.trim()); });
  }
  while (i < lines.length) {
    var ln = lines[i];
    if (fence !== null) {
      if (/^\s*```/.test(ln)) { out.push("<pre><code>" + fence.join("\n") + "</code></pre>"); fence = null; }
      else fence.push(ln);
      i++; continue;
    }
    if (/^\s*```/.test(ln)) { flush(); fence = []; i++; continue; }
    if (/^\s*$/.test(ln)) { flush(); i++; continue; }

    if (/^\s*\|.*\|\s*$/.test(ln) && i + 1 < lines.length &&
        /^\s*\|[\s:\-|]+\|\s*$/.test(lines[i + 1])) {
      flush();
      var html = "<table><thead><tr>" +
        cells(ln).map(function (c) { return "<th>" + c + "</th>"; }).join("") +
        "</tr></thead><tbody>";
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        html += "<tr>" + cells(lines[i]).map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>";
        i++;
      }
      out.push(html + "</tbody></table>");
      continue;
    }
    var h = ln.match(/^(#{1,6})\s+(.*)$/);
    if (h) { flush(); out.push("<h" + h[1].length + ">" + inline(h[2]) + "</h" + h[1].length + ">"); i++; continue; }
    if (/^\s*&gt;\s?/.test(ln)) {
      flush();
      var quote = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^\s*&gt;\s?/, "")); i++;
      }
      out.push("<blockquote>" + inline(quote.join(" ")) + "</blockquote>");
      continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(ln)) {
      flush();
      var ordered = /^\s*\d+\./.test(ln), items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push("<li>" + inline(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, "")) + "</li>");
        i++;
      }
      out.push((ordered ? "<ol>" : "<ul>") + items.join("") + (ordered ? "</ol>" : "</ul>"));
      continue;
    }
    buf.push(ln.trim()); i++;
  }
  if (fence !== null) out.push("<pre><code>" + fence.join("\n") + "</code></pre>");
  flush();
  return out.join("");
}

/* ------------------------------------------------------------------- DOM ---- */

var root = document.createElement("div");
root.id = "askai-root";
var CRUMB = window.ASKAI_CRUMB || {};

/* The bar is whatever the server says it is, so this file carries no
 * assumptions about how a workspace names its folders. */
function crumbHtml() {
  var lead = "";
  if (CRUMB.badge) {
    lead = '<span class="num">' + esc(CRUMB.badge) + '</span>' +
           (CRUMB.badge_note
              ? '<span class="st st-info">' + esc(CRUMB.badge_note) + '</span>' : '') +
           '<span class="sep">\u00b7</span>';
  }
  var sub = CRUMB.sub
    ? '<span class="sub">' + esc(CRUMB.sub) + '</span><span class="sep">\u00b7</span>' : '';
  return '<a class="home" href="/" title="' + esc(CRUMB.home_label || "All pages") + '">' +
           '<svg viewBox="0 0 24 24">' +
             '<rect x="3" y="3" width="7" height="7" rx="1"/>' +
             '<rect x="14" y="3" width="7" height="7" rx="1"/>' +
             '<rect x="3" y="14" width="7" height="7" rx="1"/>' +
             '<rect x="14" y="14" width="7" height="7" rx="1"/>' +
           '</svg><span>' + esc(CRUMB.home_label || "All pages") + '</span>' +
         '</a>' +
         '<span class="sep">/</span>' + lead + sub +
         '<span class="title">' + esc(CRUMB.title || document.title) + '</span>';
}

root.innerHTML =
  '<div id="askai-crumb">' + crumbHtml() + '</div>' +
  '<button id="askai-btn">\u2726 Ask AI</button>' +
  '<button id="askai-launch" title="Ask AI" aria-label="Ask AI">' +
    '<svg viewBox="0 0 24 24">' +
      '<path d="M12 3l1.9 5.3L19 10l-5.1 1.7L12 17l-1.9-5.3L5 10l5.1-1.7z"/>' +
      '<path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>' +
    '</svg>' +
  '</button>' +
  '<div id="askai-tip"></div>' +
  '<aside id="askai-drawer">' +
    '<div id="askai-grip" title="Drag to resize"></div>' +
    '<div class="head">' +
      '<span class="t">Ask AI</span>' +
      '<button data-act="history">History</button>' +
      '<button data-act="new">New</button>' +
      '<button data-act="close">\u2715</button>' +
    '</div>' +
    '<div class="quote" id="askai-quote"></div>' +
    '<div id="askai-msgs"></div>' +
    '<div id="askai-composer">' +
      '<textarea id="askai-input" rows="1" placeholder="Ask about the selected text..."></textarea>' +
      '<div id="askai-bar">' +
        '<button disabled title="Attach files (not enabled)">' +
          '<svg viewBox="0 0 24 24"><path d="M21.4 11.05 12.25 20.2a5.5 5.5 0 1 1-7.78-7.78l9.2-9.2a3.67 3.67 0 1 1 5.18 5.18l-9.2 9.2a1.83 1.83 0 1 1-2.6-2.6l8.5-8.48"/></svg>' +
        '</button>' +
        '<button disabled title="Add context (not enabled)">' +
          '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
        '</button>' +
        '<button disabled title="Voice (not enabled)">' +
          '<svg viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/></svg>' +
        '</button>' +
        '<select id="askai-model" title="Model"><option>claude-opus-5</option></select>' +
        '<span class="sp"></span>' +
        '<button class="send" id="askai-send" title="Send">' +
          '<svg viewBox="0 0 24 24"><path d="M4 12h15M13 6l6 6-6 6"/></svg>' +
        '</button>' +
      '</div>' +
    '</div>' +
    '<div id="askai-note">Shift+Enter for a new line</div>' +
  '</aside>';
document.body.appendChild(root);

var btn    = root.querySelector("#askai-btn");
var launch = root.querySelector("#askai-launch");
var tip    = root.querySelector("#askai-tip");
var msgs   = root.querySelector("#askai-msgs");
var quote  = root.querySelector("#askai-quote");
var input  = root.querySelector("#askai-input");
var send   = root.querySelector("#askai-send");
var note   = root.querySelector("#askai-note");

function open()  { document.body.classList.add("askai-open"); setTimeout(function(){ input.focus(); }, 300); }
function close() { document.body.classList.remove("askai-open"); }

root.querySelector('[data-act="close"]').addEventListener("click", close);
root.querySelector('[data-act="new"]').addEventListener("click", function () {
  threadId = null; selectedText = "";
  quote.classList.remove("on"); quote.textContent = "";
  msgs.innerHTML = ""; input.value = ""; size();
  open();
});
root.querySelector('[data-act="history"]').addEventListener("click", showHistory);

/* --------------------------------------------------- highlight anchoring ---- */
/* Anchor on the passage TEXT, not offsets or XPaths: text survives edits above
 * it and fails gracefully. The index below is whitespace-normalised, because
 * String(selection) collapses whitespace while node.nodeValue does not. */

function skipsAskaiUi(node) {
  return node.parentElement && node.parentElement.closest("#askai-root");
}
function walker(rootEl) {
  return document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
    acceptNode: function (node) {
      return skipsAskaiUi(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    }
  });
}
function buildIndex(rootEl) {
  var w = walker(rootEl), out = "", map = [], node, i, ch, lastWasSpace = true;
  while ((node = w.nextNode())) {
    var v = node.nodeValue;
    for (i = 0; i < v.length; i++) {
      ch = v.charAt(i);
      if (ch === " " || ch === "\n" || ch === "\t" || ch === "\r") {
        if (lastWasSpace) continue;
        out += " "; map.push({ node: node, off: i }); lastWasSpace = true;
      } else {
        out += ch; map.push({ node: node, off: i }); lastWasSpace = false;
      }
    }
  }
  return { text: out, map: map };
}
function findRange(needle, rootEl) {
  var n = String(needle).replace(/\s+/g, " ").trim();
  if (n.length < 4) return null;
  var idx = buildIndex(rootEl), at = idx.text.indexOf(n);
  if (at < 0) {
    n = n.slice(0, 60);
    at = idx.text.indexOf(n);
    if (at < 0) return null;
  }
  var s = idx.map[at], e = idx.map[at + n.length - 1];
  if (!s || !e) return null;
  var r = document.createRange();
  try { r.setStart(s.node, s.off); r.setEnd(e.node, e.off + 1); }
  catch (err) { return null; }
  return r;
}
function wrapRange(range, id, rootEl) {
  var nodes = [], w = walker(rootEl), nd;
  while ((nd = w.nextNode())) if (range.intersectsNode(nd)) nodes.push(nd);

  /* Capture every offset BEFORE mutating: surroundContents splits text nodes,
     which invalidates the range's references to later ones. */
  var plan = [];
  nodes.forEach(function (node) {
    if (node.parentElement && node.parentElement.closest("mark.askai-hl")) return;
    var s = (node === range.startContainer) ? range.startOffset : 0;
    var e = (node === range.endContainer) ? range.endOffset : node.nodeValue.length;
    if (e > s) plan.push({ node: node, s: s, e: e });
  });

  var made = 0;
  plan.forEach(function (p) {
    try {
      var r = document.createRange();
      r.setStart(p.node, p.s); r.setEnd(p.node, p.e);
      var m = document.createElement("mark");
      m.className = "askai-hl"; m.dataset.thread = id;
      r.surroundContents(m);
      made++;
    } catch (err) { /* fragment straddles an element edge - skip just that piece */ }
  });
  return made > 0;
}
function applyHighlight(text, id, rootEl) {
  if (!text || !id) return false;
  if (rootEl.querySelector('mark.askai-hl[data-thread="' + id + '"]')) return true;
  var r = findRange(text, rootEl);
  return r ? wrapRange(r, id, rootEl) : false;
}
function group(id) { return MAIN.querySelectorAll('mark.askai-hl[data-thread="' + id + '"]'); }

function refreshHighlights() {
  return fetch("/api/threads?" + Q)
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      if (!rows || !rows.length) return;
      lastThreadId = String(rows[0].id);     /* ordered most recent first */
      rows.forEach(function (t) {
        threadMeta[t.id] = {
          question: t.first_question, answer: t.first_answer,
          count: t.msg_count, text: t.selected_text
        };
        if (t.selected_text) applyHighlight(t.selected_text, t.id, MAIN);
      });
    })
    .catch(function () { /* proxy down - page still fine, just unhighlighted */ });
}

/* ------------------------------------------------------------- selection ---- */

document.addEventListener("mouseup", function (e) {
  if (root.contains(e.target)) return;
  setTimeout(function () {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) { btn.classList.remove("on"); return; }
    var txt = String(sel).trim();
    if (txt.length < 4 || !MAIN.contains(sel.anchorNode)) { btn.classList.remove("on"); return; }
    var r = sel.getRangeAt(0).getBoundingClientRect();
    btn.style.top  = Math.max(8, r.top - 40) + "px";
    btn.style.left = Math.min(Math.max(8, r.left), window.innerWidth - 120) + "px";
    btn.dataset.text = txt;
    btn.classList.add("on");
  }, 10);
});
btn.addEventListener("mousedown", function (e) { e.preventDefault(); });
btn.addEventListener("click", function () {
  var txt = btn.dataset.text || "";
  btn.classList.remove("on");
  var sel = window.getSelection();
  var inside = sel && sel.anchorNode && sel.anchorNode.parentElement
    ? sel.anchorNode.parentElement.closest("mark.askai-hl") : null;
  if (inside) { loadThread(inside.dataset.thread); return; }  /* reopen, never duplicate */

  /* A new selection MUST reset the thread, or the new passage silently never
     gets a highlight (a thread stores exactly one anchor). */
  threadId = null;
  selectedText = txt;
  quote.textContent = txt;
  quote.classList.add("on");
  msgs.innerHTML = ""; input.value = ""; size();
  open();
});

/* The persistent launcher resumes the LAST conversation rather than starting a
 * new one - "New" is the only control that clears the thread. */
launch.addEventListener("click", function () {
  if (document.body.classList.contains("askai-open")) { close(); return; }
  if (lastThreadId && threadMeta[lastThreadId]) { loadThread(lastThreadId); return; }
  threadId = null; selectedText = "";
  quote.classList.remove("on"); quote.textContent = "";
  msgs.innerHTML = "";
  open();
});

/* --------------------------------------------------------------- messages --- */

function bubble(cls, text) {
  var d = document.createElement("div");
  d.className = "msg " + cls;
  if (text != null) d.textContent = text;
  msgs.appendChild(d); down();
  return d;
}
function dots() {
  var d = document.createElement("div");
  d.className = "dots"; d.innerHTML = "<i></i><i></i><i></i>";
  msgs.appendChild(d); down();
  return d;
}
function tool(name, detail) {
  var d = document.createElement("details");
  d.className = "tool";
  var s = document.createElement("summary"); s.textContent = name;
  var b = document.createElement("div"); b.className = "body"; b.textContent = detail || "";
  d.appendChild(s); d.appendChild(b);
  msgs.appendChild(d); down();
}
function down() { msgs.scrollTop = msgs.scrollHeight; }

/* --------------------------------------------------------------- composer --- */

root.querySelector("#askai-composer").addEventListener("click", function (e) {
  if (!e.target.closest("button") && !e.target.closest("select")) input.focus();
});
function size() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 15 * 20 + 15) + "px";  /* 15 lines, then scroll */
}
input.addEventListener("input", size);
input.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); }
});
send.addEventListener("click", ask);

/* ----------------------------------------------------------------- server --- */

function loadThread(id) {
  threadId = String(id);
  msgs.innerHTML = "";
  var meta = threadMeta[threadId];
  selectedText = (meta && meta.text) ? meta.text : "";
  quote.textContent = selectedText;
  quote.classList.toggle("on", !!selectedText);
  open();
  fetch("/api/threads/" + threadId + "?" + Q)
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      rows.forEach(function (m) {
        if (m.role === "user") bubble("user", m.content);
        else bubble("ai").innerHTML = md(m.content);
      });
    })
    .catch(function () {
      bubble("ai err", "Could not load this thread. Is the proxy still running?");
    });
}

function showHistory() {
  fetch("/api/threads?" + Q).then(function (r) { return r.json(); }).then(function (rows) {
    msgs.innerHTML = "";
    quote.classList.remove("on");
    threadId = null;
    open();
    if (!rows.length) { bubble("ai").innerHTML = md("_No threads on this page yet._"); return; }
    var wrap = bubble("ai");
    wrap.innerHTML = "<h3>History</h3>";
    rows.forEach(function (t) {
      var b = document.createElement("button");
      b.className = "histbtn";
      b.textContent = (t.first_question || t.title || "Thread " + t.id) + "  (" + t.msg_count + ")";
      b.addEventListener("click", function () { loadThread(t.id); });
      wrap.appendChild(b);
    });
  }).catch(function () {
    bubble("ai err", "Could not reach the proxy.");
  });
}

function pageText() {
  var clone = MAIN.cloneNode(true);
  var ui = clone.querySelector("#askai-root");
  if (ui) ui.remove();
  return clone.innerText || "";
}

function ask() {
  var q = input.value.trim();
  if (!q || busy) return;
  busy = true; send.disabled = true;
  bubble("user", q);
  input.value = ""; size();

  var spinner = dots(), target = null, acc = "";

  fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      doc: DOC, threadId: threadId, selectedText: selectedText,
      context: pageText(), question: q
    })
  }).then(function (res) {
    if (!res.ok || !res.body) throw new Error("bad response");
    var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) return;
        buf += dec.decode(r.value, { stream: true });
        var parts = buf.split("\n\n");
        buf = parts.pop();
        parts.forEach(function (chunk) {
          var line = chunk.split("\n").filter(function (l) { return l.indexOf("data:") === 0; })[0];
          if (!line) return;
          var ev;
          try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { return; }

          if (ev.type === "thread") { threadId = String(ev.threadId); }
          else if (ev.type === "sources") {
            if (ev.files && ev.files.length)
              note.textContent = "Grounded in " + ev.files.length + " source file(s): " + ev.files.join(", ");
          }
          else if (ev.type === "tool") {
            if (spinner) { spinner.remove(); spinner = null; }
            tool(ev.name || "Tool", ev.detail || "");
            target = null;
          }
          else if (ev.type === "text") {
            if (spinner) { spinner.remove(); spinner = null; }
            if (!target) { target = bubble("ai"); acc = ""; }
            acc += ev.text;
            target.innerHTML = md(acc);
            down();
          }
          else if (ev.type === "error") {
            if (spinner) { spinner.remove(); spinner = null; }
            bubble("ai err").innerHTML = md("**Error:** " + ev.message);
          }
        });
        return pump();
      });
    }
    return pump();
  }).catch(function () {
    if (spinner) { spinner.remove(); spinner = null; }
    bubble("ai err").innerHTML = md(
      "**Proxy not reachable.** Start it with `python3 specs/_askai/server.py`.");
  }).then(function () {
    busy = false; send.disabled = false;
    if (spinner) { spinner.remove(); spinner = null; }
    refreshHighlights();
  });
}

/* ------------------------------------------------------------------ tooltip - */
/* A tooltip that dismisses on mouseout is unreachable. The grace period plus the
 * mouseenter cancel is what makes it usable. */

var tipTimer = null, tipFor = null;

function showTip(mark) {
  var id = mark.dataset.thread, meta = threadMeta[id];
  if (!meta) return;
  tipFor = id;
  [].forEach.call(group(id), function (n) { n.classList.add("active"); });

  tip.innerHTML = "";
  var m = document.createElement("div"); m.className = "meta";
  m.textContent = "Asked about this \u00B7 " + (meta.count || 0) + " messages";
  var q = document.createElement("div"); q.className = "q"; q.textContent = meta.question || "";
  var a = document.createElement("div"); a.className = "a"; a.textContent = meta.answer || "";
  var acts = document.createElement("div"); acts.className = "acts";
  var openBtn = document.createElement("button");
  openBtn.className = "p"; openBtn.textContent = "Open thread";
  openBtn.addEventListener("click", function () { hideTip(); loadThread(id); });
  var copy = document.createElement("button");
  copy.textContent = "Copy link";
  copy.addEventListener("click", function () { copyLink(meta.text, copy); });
  acts.appendChild(openBtn); acts.appendChild(copy);
  tip.appendChild(m); tip.appendChild(q); tip.appendChild(a); tip.appendChild(acts);
  tip.classList.add("on");

  var r = mark.getBoundingClientRect(), t = tip.getBoundingClientRect();
  var left = Math.min(Math.max(r.left, 12), window.innerWidth - t.width - 12);
  var top = r.bottom + 10;
  if (top + t.height > window.innerHeight - 12) top = r.top - t.height - 10;   /* flip above */
  /* Clamp regardless: a mark can sit off-screen and the tooltip must not follow. */
  top = Math.min(Math.max(top, 12), Math.max(12, window.innerHeight - t.height - 12));
  tip.style.left = Math.max(left, 12) + "px";
  tip.style.top = top + "px";
}
function hideTip() {
  tip.classList.remove("on");
  if (tipFor) [].forEach.call(group(tipFor), function (n) { n.classList.remove("active"); });
  tipFor = null;
}
MAIN.addEventListener("mouseover", function (e) {
  var m = e.target.closest && e.target.closest("mark.askai-hl");
  if (!m) return;
  clearTimeout(tipTimer);
  showTip(m);
});
MAIN.addEventListener("mouseout", function (e) {
  var m = e.target.closest && e.target.closest("mark.askai-hl");
  if (!m) return;
  tipTimer = setTimeout(hideTip, 280);
});
tip.addEventListener("mouseenter", function () { clearTimeout(tipTimer); });
tip.addEventListener("mouseleave", function () { tipTimer = setTimeout(hideTip, 200); });
MAIN.addEventListener("click", function (e) {
  var m = e.target.closest && e.target.closest("mark.askai-hl");
  if (m) loadThread(m.dataset.thread);
});

/* Sharing only. The browser's own fragment highlight is not hoverable or
 * scriptable, so it complements the marks rather than replacing them. */
function copyLink(text, button) {
  var t = String(text || "").replace(/\s+/g, " ").trim().slice(0, 140);
  var url = location.origin + location.pathname + "#:~:text=" +
            encodeURIComponent(t).replace(/-/g, "%2D");
  var done = function () {
    var old = button.textContent;
    button.textContent = "Copied \u2713";
    setTimeout(function () { button.textContent = old; }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText)
    navigator.clipboard.writeText(url).then(done, done);
  else done();
}

/* ---------------------------------------------------------------- resizer --- */
/* One variable drives both halves of the push layout: `#askai-drawer` reads
 * --askai-w for its width and `body.askai-open` reads it for its margin. Writing
 * it once on <html> moves them together, so there is no way for the drawer and
 * the gap it leaves to disagree mid-drag. */

var MIN_W = 320;
function maxW() { return Math.max(MIN_W, Math.round(window.innerWidth * 0.6)); }
function setW(px) {
  var w = Math.min(Math.max(Math.round(px), MIN_W), maxW());
  document.documentElement.style.setProperty("--askai-w", w + "px");
  return w;
}

try {
  var savedW = parseInt(localStorage.getItem("askai-w"), 10);
  if (savedW) setW(savedW);
} catch (e) {}

var grip = root.querySelector("#askai-grip");
grip.addEventListener("pointerdown", function (e) {
  e.preventDefault();
  grip.setPointerCapture(e.pointerId);
  /* Transitions are for the open/close slide. During a drag they lag the pointer. */
  document.body.classList.add("askai-resizing");

  function move(ev) { setW(window.innerWidth - ev.clientX); }
  function up(ev) {
    grip.removeEventListener("pointermove", move);
    grip.removeEventListener("pointerup", up);
    grip.releasePointerCapture(ev.pointerId);
    document.body.classList.remove("askai-resizing");
    try {
      var cur = getComputedStyle(document.documentElement)
        .getPropertyValue("--askai-w").trim();
      localStorage.setItem("askai-w", parseInt(cur, 10) || 420);
    } catch (err) {}
  }
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", up);
});

/* A width that was fine on a wide monitor must not swallow a narrow window. */
window.addEventListener("resize", function () {
  var cur = parseInt(getComputedStyle(document.documentElement)
    .getPropertyValue("--askai-w"), 10);
  if (cur) setW(cur);
});

/* --------------------------------------------------------------------- boot - */

/* Explainers pin their own sidebars and TOCs with `position:sticky; top:0`, which
 * would slide under the fixed bar. Offsetting them by computed style rather than
 * by class name covers every layout - and any explainer written later. */
function clearTheBar() {
  var h = parseFloat(getComputedStyle(document.documentElement)
            .getPropertyValue("--askai-crumb-h")) || 44;
  var all = document.body.querySelectorAll("*");
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    if (root.contains(el)) continue;
    var cs = getComputedStyle(el);
    if (cs.position !== "sticky" || parseFloat(cs.top) !== 0) continue;
    el.style.top = h + "px";
    /* A full-height sticky rail would now overflow by exactly the bar height. */
    if (Math.abs(el.getBoundingClientRect().height - window.innerHeight) < 2) {
      el.style.height = "calc(100vh - " + h + "px)";
    }
  }
}

size();
clearTheBar();
refreshHighlights();      /* never blocks first render */
})();
