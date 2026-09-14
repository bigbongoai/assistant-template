/* The index page at /. The server puts every task, its steps and pages, and the
   categories in window.ASKAI_INDEX; this draws them and saves changes to
   _categories.json through POST /api/categories. Nothing else is stored in the
   browser except whether steps start open. */
(function () {
  'use strict';
  var DATA = window.ASKAI_INDEX;
  var TASKS_AREA = DATA.areas[0].id;
  var STEPS_KEY = 'askai-index-steps';
  /* Each column shows this many tasks before folding the older ones; below
     that the page simply scrolls. */
  var FOLD_AT = 50;
  var REDUCE = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var CHEVRON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5l4.5 4.5L6 12.5"/></svg>';

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  var sides = DATA.sides, cats = DATA.categories, placed = {};
  /* An unreadable _categories.json is shown, and never written over. */
  var locked = !!DATA.error;
  /* The copy of this workspace on briefings.page draws this same page from the
     same data, read-only: tasks are sorted on the computer the copy came from.
     There, DATA.public lists the pages anyone can read, by their link here. */
  var readonly = !!DATA.readonly;
  var publicAt = DATA.public || {};
  if (readonly) { document.body.classList.add('readonly'); }
  var tasks = DATA.tasks.slice();
  var byId = {};
  tasks.forEach(function (t) {
    byId[t.id] = t;
    if (t.area === TASKS_AREA && t.category) { placed[t.dir] = { category: t.category, guess: !!t.guess }; }
  });

  function readSteps() { try { return localStorage.getItem(STEPS_KEY) === 'all' ? 'all' : 'newest'; } catch (e) { return 'newest'; } }
  function writeSteps() { try { localStorage.setItem(STEPS_KEY, stepsMode); } catch (e) { /* private window */ } }

  var stepsMode = readSteps();
  var flipped = {};
  var sel = fromHash();
  var query = '';
  var unfolded = {};
  var stops = [];
  var cursorKey = null;
  var dragId = null;
  var toastTimer = null;
  var menuFor = null;
  var peekTest = null;

  var bar = $('#bar'), board = $('#board'), focusEl = $('#focus'), q = $('#q'), countEl = $('#count'),
    emptyEl = $('#empty'), menu = $('#menu'), toastEl = $('#toast'), looseEl = $('#unsorted'),
    othersEl = $('#others'), noticeEl = $('#notice');
  var holding = document.createDocumentFragment();

  function catById(id) {
    for (var i = 0; i < cats.length; i++) { if (cats[i].id === id) { return cats[i]; } }
    return null;
  }
  function sortable(t) { return t.area === TASKS_AREA; }
  function catOf(t) { var p = sortable(t) && placed[t.dir]; return p ? catById(p.category) : null; }
  function isGuess(t) { var p = placed[t.dir]; return !!(sortable(t) && p && p.guess && catOf(t)); }
  function sideName(id) {
    for (var i = 0; i < sides.length; i++) { if (sides[i].id === id) { return sides[i].name; } }
    return id;
  }
  function colorVar(c) { return c ? 'var(--cat-' + c.color + ')' : 'var(--cat-none)'; }
  /* The order of the buttons. */
  function orderedCats() {
    var out = [];
    sides.forEach(function (s) { cats.forEach(function (c) { if (c.side === s.id) { out.push(c); } }); });
    return out;
  }
  function usedSides() { return sides.filter(function (s) { return cats.some(function (c) { return c.side === s.id; }); }); }
  function label(t) { return (t.n !== null ? t.n + ' · ' : '') + t.name; }

  /* ---------------------------------------------------------------- the URL */
  function fromHash() {
    var h = decodeURIComponent(location.hash.slice(1));
    if (h.indexOf('side=') === 0) {
      var s = h.slice(5);
      if (sides.some(function (x) { return x.id === s; })) { return { kind: 'side', id: s }; }
    }
    if (h.indexOf('cat=') === 0) {
      var ids = h.slice(4).split(',').filter(function (id) { return catById(id); });
      if (ids.length) { return { kind: 'cats', ids: ids }; }
    }
    return { kind: 'all' };
  }
  function hashFor(s) {
    if (s.kind === 'side') { return '#side=' + s.id; }
    if (s.kind === 'cats') { return '#cat=' + s.ids.join(','); }
    return location.pathname + location.search;
  }
  /* Every view has its own address, so Back returns to the previous view. */
  function setSel(s) {
    sel = s;
    try { history.pushState(null, '', hashFor(s)); } catch (e) { /* file:// */ }
    cursorKey = null;
    render(true);
  }
  window.addEventListener('popstate', function () { sel = fromHash(); cursorKey = null; render(true); });

  function inSel(t) {
    var c = catOf(t);
    if (sel.kind === 'side') { return !!c && c.side === sel.id; }
    if (sel.kind === 'cats') { return !!c && sel.ids.indexOf(c.id) !== -1; }
    return true;
  }
  function headHay(t) {
    var c = catOf(t);
    return ((t.n !== null ? t.n : '') + ' ' + t.name + ' ' + t.dir + ' ' + (c ? c.name : 'not sorted') + ' ' +
      (t.status_label || '')).toLowerCase();
  }
  function stepHay(s) {
    return (s.num + ' ' + s.title + ' ' + s.more.map(function (p) { return p.title; }).join(' ')).toLowerCase();
  }
  function matchesQuery(t) {
    return !query || headHay(t).indexOf(query) !== -1 ||
      t.steps.some(function (s) { return stepHay(s).indexOf(query) !== -1; });
  }
  function selLabel() {
    if (sel.kind === 'side') { return sideName(sel.id); }
    if (sel.kind === 'cats') { return sel.ids.map(function (id) { return catById(id).name; }).join(' + '); }
    return 'All';
  }

  /* ----------------------------------------------------------------- steps */
  /* "Steps: All" opens every task; a click then closes just that one, and the
     reverse under "Newest only". Changing the setting forgets those clicks. */
  function openable(t) { return t.pages > 1; }
  function isOpen(t) { return openable(t) && (stepsMode === 'all' ? !flipped[t.id] : !!flipped[t.id]); }
  /* A search that finds a task only through one of its steps opens the task
     and shows just the steps that match. */
  function stepsShown(t) {
    if (query && openable(t) && headHay(t).indexOf(query) === -1) {
      var hits = t.steps.filter(function (s) { return stepHay(s).indexOf(query) !== -1; });
      if (hits.length) { return { open: true, steps: hits }; }
    }
    return { open: isOpen(t), steps: t.steps };
  }
  function pub(href) {
    return publicAt[href] ? '<span class="pub" title="Public: anyone with the link can read it">public</span>' : '';
  }
  /* A task with a public page says so on its own line too, because a one-page
     task has no list of steps to show it in. */
  function anyPublic(t) {
    return t.steps.some(function (s) {
      return publicAt[s.href] || s.more.some(function (p) { return publicAt[p.href]; });
    });
  }
  function taskPub(t) {
    return anyPublic(t) ? '<span class="pub" title="Has a public page: anyone with its link can read it">public</span>' : '';
  }
  /* How far along the task is, from its _task.json. */
  function statusChip(t) {
    return t.status ? '<span class="task-status" data-status="' + esc(t.status) + '">' + esc(t.status_label) + '</span>' : '';
  }
  function lines(steps, cls) {
    return steps.map(function (s) {
      var html = '<li><a class="' + cls + '" draggable="false" href="' + esc(s.href) + '"><span class="snum">' +
        esc(s.num) + '</span><span class="stitle">' + esc(s.title) + '</span><span class="meta">' + pub(s.href) +
        (s.threads ? '<span class="thr">threads</span>' : '') + '</span></a></li>';
      s.more.forEach(function (p) {
        html += '<li><a class="' + cls + ' page" draggable="false" href="' + esc(p.href) + '"><span class="snum"></span>' +
          '<span class="stitle">' + esc(p.title) + '</span><span class="meta">' + pub(p.href) +
          (p.threads ? '<span class="thr">threads</span>' : '') + '</span></a></li>';
      });
      return html;
    }).join('');
  }
  function paintSteps(t) {
    var a = rows[t.id], list = $('.subs', a), shown = stepsShown(t);
    a.classList.toggle('open', shown.open);
    var tw = $('button.tw', a);
    if (tw) {
      tw.setAttribute('aria-expanded', shown.open);
      tw.title = (shown.open ? 'Hide its steps (space)' : 'Show its steps (space)');
    }
    if (!shown.open) { list.hidden = true; list.innerHTML = ''; return; }
    list.innerHTML = lines(shown.steps, 'sub');
    list.hidden = false;
  }
  /* Open or close one task in place. The steps grow out of the line and the
     tasks below slide down with them. */
  function toggleSteps(id, want) {
    var t = byId[id];
    if (!openable(t) || !rows[id].isConnected) { return; }
    var now = stepsShown(t).open;
    if (want === undefined) { want = !now; }
    if (want === now) { return; }
    flipped[id] = !flipped[id];
    var a = rows[id], list = $('.subs', a);
    if (want) {
      paintSteps(t);
      if (!REDUCE) {
        list.animate([{ height: '0px', opacity: 0 }, { height: list.scrollHeight + 'px', opacity: 1 }],
          { duration: 200, easing: 'cubic-bezier(.2,.7,.2,1)' });
      }
      buildStops();
      paintExpand();
      return;
    }
    if (REDUCE) { paintSteps(t); buildStops(); paintExpand(); return; }
    var h = list.offsetHeight;
    a.classList.remove('open');
    paintExpand();
    list.animate([{ height: h + 'px', opacity: 1 }, { height: '0px', opacity: 0 }],
      { duration: 160, easing: 'ease-in' }).onfinish = function () { paintSteps(t); buildStops(); };
  }

  /* ------------------------------------------------------------------ rows */
  /* One element per task for the columns. They are moved, never rebuilt, so a
     task can be seen sliding to its new place. */
  var rows = {};
  tasks.forEach(function (t) {
    var s = t.steps[0], many = openable(t), movable = sortable(t);
    var count = t.steps.length > 1 ? plural(t.steps.length, 'step') : plural(t.pages, 'page');
    var a = document.createElement('article');
    a.className = 'row' + (movable ? '' : ' plain');
    a.dataset.id = t.id;
    a.draggable = movable && !readonly;
    a.innerHTML =
      (many ? '<button type="button" class="tw" aria-expanded="false">' + CHEVRON + '</button>' :
        '<span class="tw" aria-hidden="true"></span>') +
      '<a class="tl" draggable="false" href="' + esc(t.href) + '">' +
      (t.n !== null ? '<span class="num">' + t.n + '</span>' : '') + '<span class="tname">' + esc(t.name) + '</span>' +
      statusChip(t) + taskPub(t) + '</a>' +
      /* A task with no page yet has no newest step to show. */
      (!s ? '<span class="latest none">No page yet</span>' :
        '<a class="latest" draggable="false" tabindex="-1" href="' + esc(s.href) + '" title="Newest step: ' +
        esc((s.num ? s.num + ' ' : '') + s.title) + '"><span class="snum">' + esc(s.num) + '</span><span class="stitle">' +
        esc(s.title) + '</span></a>') +
      (many ? '<button type="button" class="more" title="Show its steps">' + count + '</button>' :
        '<span class="more" aria-hidden="true"></span>') +
      (!movable ? '' : readonly ? '<span class="cat"><i class="dot"></i><span class="cn"></span></span>' :
        '<button type="button" class="cat" aria-haspopup="menu"><i class="dot"></i><span class="cn"></span></button>') +
      '<span class="date">' + esc(t.date) + '</span>' +
      '<ol class="subs" hidden></ol>';
    rows[t.id] = a;
    holding.appendChild(a);
  });
  function paintRow(t) {
    var a = rows[t.id], c = catOf(t), guess = isGuess(t);
    a.style.setProperty('--cc', colorVar(c));
    a.classList.toggle('guess', guess);
    var btn = $('.cat', a);
    if (btn) {
      $('.cn', btn).textContent = c ? c.name + (guess ? ' ?' : '') : 'Not sorted';
      btn.title = readonly ? (guess ? "Claude's guess" : '') :
        (guess ? "Claude's guess - click to keep it here or move it" : 'Move to another category');
    }
    paintSteps(t);
  }

  /* ------------------------------------------------------ category buttons */
  function renderBar() {
    var html = '<button type="button" class="chip all" data-all="1" title="Every task">All <span class="c"></span></button>';
    usedSides().forEach(function (s) {
      html += '<span class="sep" aria-hidden="true"></span><span class="grp">' +
        '<button type="button" class="side" data-side="' + esc(s.id) + '" title="Only ' + esc(s.name) +
        ', across the full width">' + esc(s.name) + ' <span class="c"></span></button>';
      cats.forEach(function (c) {
        if (c.side !== s.id) { return; }
        html += '<button type="button" class="chip" data-cat="' + esc(c.id) + '" style="--cc:' + colorVar(c) +
          '" title="' + esc(readonly ? (c.holds || c.name) :
            (c.holds ? c.holds + '. ' : '') + 'Double-click to rename, right-click for more') + '"><i class="dot"></i><span class="lbl">' + esc(c.name) +
          '</span> <span class="c"></span></button>';
      });
      html += '</span>';
    });
    if (!readonly) {
      html += '<span class="sep" aria-hidden="true"></span>' +
        '<button type="button" class="chip manage" title="Rename, recolour, move, describe, add or delete categories">' +
        'Manage categories</button>';
    }
    bar.innerHTML = html;
  }
  function counts() {
    var byCat = {}, bySide = {}, total = 0, loose = 0, other = 0;
    cats.forEach(function (c) { byCat[c.id] = 0; });
    sides.forEach(function (s) { bySide[s.id] = 0; });
    tasks.forEach(function (t) {
      if (!matchesQuery(t)) { return; }
      total++;
      var c = catOf(t);
      if (c) { byCat[c.id]++; bySide[c.side]++; } else if (sortable(t)) { loose++; } else { other++; }
    });
    return { byCat: byCat, bySide: bySide, total: total, loose: loose, other: other };
  }
  function paintBar(k) {
    $$('.chip[data-cat]', bar).forEach(function (b) {
      var id = b.dataset.cat, n = k.byCat[id] || 0, on = sel.kind === 'cats' && sel.ids.indexOf(id) !== -1;
      $('.c', b).textContent = n;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on);
      b.classList.toggle('zero', !!query && n === 0);
    });
    $$('.side', bar).forEach(function (b) {
      var on = sel.kind === 'side' && sel.id === b.dataset.side;
      $('.c', b).textContent = k.bySide[b.dataset.side] || 0;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on);
    });
    var all = $('.chip.all', bar);
    $('.c', all).textContent = k.total;
    all.classList.toggle('on', sel.kind === 'all');
    all.setAttribute('aria-pressed', sel.kind === 'all');
  }

  /* ---------------------------------------------------------------- render */
  function render(animate) {
    closeMenu(false);
    var before = null;
    if (animate && !REDUCE) {
      before = new Map();
      tasks.forEach(function (t) {
        var r = rows[t.id];
        if (r.isConnected && !r.hidden) { before.set(r, r.getBoundingClientRect()); }
      });
    }
    tasks.forEach(paintRow);
    var k = counts();
    paintBar(k);
    var shown = tasks.filter(function (t) { return inSel(t) && matchesQuery(t); });
    var focusView = sel.kind !== 'all';
    [board, looseEl, othersEl].forEach(function (el) { el.innerHTML = ''; });
    tasks.forEach(function (t) { holding.appendChild(rows[t.id]); });
    if (focusView) {
      board.hidden = looseEl.hidden = othersEl.hidden = true;
      focusEl.hidden = false;
      renderFocus(shown, animate);
    } else {
      focusEl.hidden = true;
      focusEl.innerHTML = '';
      board.hidden = othersEl.hidden = false;
      renderOverview(shown);
    }
    emptyEl.hidden = shown.length !== 0 || (!query && tasks.length !== 0);
    countEl.textContent = describe(shown.length, k);
    if (before) { flip(before); }
    buildStops();
    paintExpand();
    /* A pointer resting on a category button keeps showing that category,
       including on anything this render has just drawn. */
    if (peekTest) { peek(peekTest); }
  }

  function describe(n, k) {
    if (sel.kind === 'all' && !query) {
      var bits = [plural(tasks.length, 'task')];
      usedSides().forEach(function (s) { bits.push(s.name + ' ' + (k.bySide[s.id] || 0)); });
      if (k.loose) { bits.push(k.loose + ' not sorted'); }
      return bits.join(' · ');
    }
    var parts = [n + ' of ' + plural(tasks.length, 'task')];
    if (sel.kind !== 'all') { parts.push(selLabel()); }
    if (query) { parts.push('"' + query + '"'); }
    return parts.join(' · ');
  }

  /* One panel: a heading, its rows, and the line that folds what is past 50. */
  function panel(key, head, list, emptyText) {
    var col = document.createElement('section');
    col.className = 'col';
    col.innerHTML = '<header class="colhead">' + head + '</header><div class="rows"></div>';
    var box = $('.rows', col);
    list.forEach(function (t) { var r = rows[t.id]; r.hidden = false; box.appendChild(r); });
    if (!list.length && emptyText) {
      var none = document.createElement('p');
      none.className = 'none';
      none.textContent = emptyText;
      col.appendChild(none);
    }
    var fold = document.createElement('button');
    fold.type = 'button';
    fold.className = 'fold';
    fold.hidden = true;
    fold.dataset.key = key;
    col.appendChild(fold);
    return col;
  }

  function renderOverview(shown) {
    var loose = shown.filter(function (t) { return sortable(t) && !catOf(t); });
    looseEl.hidden = !loose.length;
    if (loose.length) {
      looseEl.appendChild(panel('loose', '<span class="colname">Not sorted</span><span class="c">' + loose.length +
        '</span><span class="note">' + (readonly ? 'Sort them on your computer' :
          cats.length ? 'Drag each onto a category, or click "Not sorted" on it'
          : 'Add a category with Manage categories, then drag tasks onto it') + '</span>', loose));
    }
    var used = usedSides();
    board.style.setProperty('--cols', Math.max(1, used.length));
    used.forEach(function (s) {
      var mine = shown.filter(function (t) { var c = catOf(t); return c && c.side === s.id; });
      var legend = cats.filter(function (c) { return c.side === s.id; }).map(function (c) {
        return '<span class="lg" data-cat="' + esc(c.id) + '" style="--cc:' + colorVar(c) + '" title="Only ' +
          esc(c.name) + '"><i class="dot"></i>' + esc(c.name) + '</span>';
      }).join('');
      var col = panel('s:' + s.id, '<button type="button" class="sidebtn" data-side="' + esc(s.id) + '" title="Only ' +
        esc(s.name) + ', across the full width">' + esc(s.name) + '</button><span class="c">' + mine.length +
        '</span><span class="legend">' + legend + '</span>', mine, query ? 'Nothing here matches.' : 'No tasks yet.');
      col.dataset.side = s.id;
      board.appendChild(col);
    });
    board.hidden = !used.length;
    DATA.areas.slice(1).forEach(function (area) {
      var mine = shown.filter(function (t) { return t.area === area.id; });
      if (!mine.length) { return; }
      var wrap = document.createElement('section');
      wrap.className = 'area';
      wrap.innerHTML = '<div class="divider">' + esc(area.name) + '</div>';
      wrap.appendChild(panel('a:' + area.id, '<span class="colname">' + esc(area.name) + '</span><span class="c">' +
        mine.length + '</span>', mine));
      othersEl.appendChild(wrap);
    });
    foldColumns();
  }

  function foldColumns() {
    $$('main .col').forEach(function (col) {
      var fold = $('.fold', col);
      if (!fold) { return; }
      var key = fold.dataset.key, rs = $$('.row', $('.rows', col)), extra = rs.length - FOLD_AT;
      rs.forEach(function (r, i) { r.hidden = extra > 0 && !unfolded[key] && i >= FOLD_AT; });
      fold.hidden = extra <= 0;
      if (extra > 0) {
        fold.textContent = unfolded[key] ? 'Fold the ' + extra + ' older task' + (extra === 1 ? '' : 's') + ' ▴' :
          extra + ' earlier task' + (extra === 1 ? '' : 's') + ' ▾';
      }
    });
  }

  function renderFocus(shown, animate) {
    var dots = sel.kind === 'cats' ? sel.ids.map(function (id) {
      return '<i class="dot" style="--cc:' + colorVar(catById(id)) + '"></i>';
    }).join('') : '';
    var html = '<div class="fhead">' + dots + '<b>' + esc(selLabel()) + '</b><span class="c">' + plural(shown.length, 'task') +
      '</span><button type="button" class="back">Both columns <kbd>esc</kbd></button></div>';
    shown.forEach(function (t) {
      var c = catOf(t), guess = isGuess(t);
      var size = !t.pages ? 'No page yet' :
        t.steps.length > 1 ? plural(t.steps.length, 'step') + ' · ' + plural(t.pages, 'page') :
        (t.pages > 1 ? plural(t.pages, 'page') : 'One page');
      var chip = '<i class="dot"></i><span class="cn">' + esc(c.name + (guess ? ' ?' : '')) + '</span>';
      chip = readonly ? '<span class="cat">' + chip + '</span>' :
        '<button type="button" class="cat" aria-haspopup="menu" title="' +
        (guess ? "Claude's guess - click to keep it here or move it" : 'Move to another category') + '">' + chip + '</button>';
      html += '<article class="card' + (guess ? ' guess' : '') + '" data-id="' + esc(t.id) + '" draggable="' + !readonly +
        '" style="--cc:' + colorVar(c) + '"><div class="cside"><a class="tl" draggable="false" href="' + esc(t.href) + '">' +
        (t.n !== null ? '<span class="num">' + t.n + '</span>' : '') + '<span class="tname">' + esc(t.name) +
        '</span>' + statusChip(t) + taskPub(t) + '</a><div class="tmeta">' + chip + '<span>' + size + '</span><span>Changed ' +
        esc(t.date) + '</span></div></div><ol class="steps">' + lines(t.steps, 'pg') + '</ol></article>';
    });
    if (!shown.length && !query) {
      html += '<p class="none">No tasks in ' + esc(selLabel()) + ' yet.' + (readonly ? '' : ' Drag one onto its button.') + '</p>';
    }
    focusEl.innerHTML = html;
    if (animate && !REDUCE) {
      $$('.card', focusEl).slice(0, 14).forEach(function (card, i) {
        card.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }],
          { duration: 180, delay: i * 14, easing: 'ease-out', fill: 'backwards' });
      });
    }
  }

  /* Moved rows slide from where they were to where they are now. */
  function flip(before) {
    tasks.forEach(function (t) {
      var r = rows[t.id];
      if (!r.isConnected || r.hidden) { return; }
      var b = before.get(r), a = r.getBoundingClientRect();
      if (!b) {
        r.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 180, easing: 'ease-out' });
        return;
      }
      var dx = b.left - a.left, dy = b.top - a.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) { return; }
      r.animate([{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }],
        { duration: 260, easing: 'cubic-bezier(.2,.7,.2,1)' });
    });
  }

  /* ---------------------------------------------------------- the keyboard */
  /* The cursor remembers which task, and which of its pages, it is on - not a
     position in a list - so opening a task never makes it jump. */
  function holderOf(el) { return el.closest('[data-id]'); }
  function keyOf(el) {
    return { id: holderOf(el).dataset.id, href: el.classList.contains('tl') ? null : el.getAttribute('href') };
  }
  function elOf(k) {
    if (!k) { return null; }
    for (var i = 0; i < stops.length; i++) {
      var e = stops[i];
      if (holderOf(e).dataset.id !== k.id) { continue; }
      if (k.href === null ? e.classList.contains('tl') : (!e.classList.contains('tl') && e.getAttribute('href') === k.href)) {
        return e;
      }
    }
    return null;
  }
  function buildStops() {
    stops = focusEl.hidden ?
      $$('main .col .row:not([hidden]) .tl, main .col .row:not([hidden]) .subs:not([hidden]) .sub') :
      $$('.card .tl, .card .pg', focusEl);
    if (cursorKey && !elOf(cursorKey) && cursorKey.href !== null) { cursorKey = { id: cursorKey.id, href: null }; }
    if (cursorKey && !elOf(cursorKey)) { cursorKey = null; }
    if (!cursorKey && query && stops.length) { cursorKey = keyOf(stops[0]); }
    paintCursor(false);
  }
  function paintCursor(scroll) {
    $$('.row.on, .card.on, .sub.on, .pg.on').forEach(function (e) { e.classList.remove('on'); });
    var el = elOf(cursorKey);
    if (!el) { return; }
    var target = el.classList.contains('tl') ? holderOf(el) : el;
    target.classList.add('on');
    if (scroll) { target.scrollIntoView({ block: 'nearest' }); }
  }
  function moveCursor(step) {
    if (!stops.length) { return; }
    var i = stops.indexOf(elOf(cursorKey));
    i = i < 0 ? (step > 0 ? 0 : stops.length - 1) : (i + step + stops.length) % stops.length;
    cursorKey = keyOf(stops[i]);
    paintCursor(true);
  }
  /* The keyboard follows the highlight: a button clicked earlier lets go of
     it, so Enter and Space act on what is highlighted. */
  function letGo() {
    var a = document.activeElement;
    if (a && a !== q && a !== document.body && a.blur) { a.blur(); }
  }
  /* ← and → go to the same place in the column beside, as the eye moves
     between Work and Private. From anywhere else they go to the top of one. */
  function switchColumn(dir) {
    if (!focusEl.hidden) { return; }
    var cols = $$('.col', board);
    if (!cols.length) { return; }
    var el = elOf(cursorKey), row = el && holderOf(el), col = row && row.closest('.col');
    var at = col ? cols.indexOf(col) : -1, index = 0, target;
    if (at === -1) {
      target = cols[dir > 0 ? cols.length - 1 : 0];
    } else {
      target = cols[at + dir];
      index = $$('.row:not([hidden])', col).indexOf(row);
    }
    var list = target ? $$('.row:not([hidden])', target) : [];
    if (!list.length) { return; }
    cursorKey = { id: list[Math.min(Math.max(index, 0), list.length - 1)].dataset.id, href: null };
    paintCursor(true);
  }
  /* Space opens or closes the highlighted task; on one of its steps, it
     closes the task and goes back to its line. */
  function space() {
    var el = elOf(cursorKey);
    if (!el) { return; }
    var holder = holderOf(el);
    if (holder.classList.contains('card')) { return; }
    if (!el.classList.contains('tl')) {
      cursorKey = { id: holder.dataset.id, href: null };
      toggleSteps(holder.dataset.id, false);
      paintCursor(true);
      return;
    }
    toggleSteps(holder.dataset.id);
  }

  /* -------------------------------------------------------------- the menu */
  function openMenu(anchor, items) {
    menu.innerHTML = items.map(function (it, i) {
      if (it.heading) { return '<div class="mh">' + esc(it.heading) + '</div>'; }
      return '<button type="button" role="menuitem" data-i="' + i + '"' + (it.disabled ? ' disabled' : '') +
        (it.color ? ' style="--cc:var(--cat-' + it.color + ')"' : '') + '>' +
        (it.color ? '<i class="dot"></i>' : '<span class="ic">' + (it.icon || '') + '</span>') +
        '<span>' + esc(it.label) + '</span>' + (it.note ? '<span class="note">' + esc(it.note) + '</span>' : '') + '</button>';
    }).join('');
    menu.hidden = false;
    menuFor = { anchor: anchor, items: items };
    var r = anchor.getBoundingClientRect(), mw = menu.offsetWidth, mh = menu.offsetHeight;
    var left = Math.min(r.left, window.innerWidth - mw - 8), top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) { top = Math.max(8, r.top - mh - 6); }
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = top + 'px';
    var first = $('button:not([disabled])', menu);
    if (first) { first.focus({ preventScroll: true }); }
  }
  function closeMenu(restore) {
    if (menu.hidden) { return; }
    menu.hidden = true;
    var a = menuFor && menuFor.anchor;
    menuFor = null;
    if (restore && a && a.isConnected) { a.focus(); }
  }
  menu.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-i]');
    if (!b || !menuFor) { return; }
    var it = menuFor.items[+b.dataset.i];
    closeMenu(false);
    it.action();
  });
  menu.addEventListener('keydown', function (e) {
    var bs = $$('button:not([disabled])', menu), i = bs.indexOf(document.activeElement);
    if (!bs.length) { if (e.key === 'Escape') { closeMenu(true); } return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); bs[(i + 1) % bs.length].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); bs[(i - 1 + bs.length) % bs.length].focus(); }
    else if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); closeMenu(true); }
  });
  document.addEventListener('mousedown', function (e) {
    if (!menu.hidden && !menu.contains(e.target)) { closeMenu(false); }
  });

  function moveMenu(id, anchor) {
    var t = byId[id], cur = catOf(t), items = [];
    if (isGuess(t)) {
      items.push({ label: 'Keep in ' + cur.name, icon: '✓', note: "Claude's guess", action: function () { keepTask(id); } });
    }
    usedSides().forEach(function (s) {
      items.push({ heading: 'Move to · ' + s.name });
      cats.forEach(function (c) {
        if (c.side !== s.id) { return; }
        var here = !!cur && c.id === cur.id;
        items.push({ label: c.name, color: c.color, disabled: here, note: here ? 'here now' : '',
          action: function () { moveTask(id, c.id); } });
      });
    });
    if (!cats.length) { items.push({ label: 'No categories yet: add one with Manage categories', icon: '', disabled: true }); }
    openMenu(anchor, items);
  }

  function chipMenu(b) {
    var c = catById(b.dataset.cat);
    var n = tasks.filter(function (t) { var x = catOf(t); return x && x.id === c.id; }).length;
    var other = sides.filter(function (s) { return s.id !== c.side; })[0];
    var items = [{ heading: c.name }, { label: 'Rename', icon: '✎', action: function () { startRename(c.id); } }];
    if (other) {
      items.push({ label: 'Put under ' + other.name, icon: '⇄', action: function () {
        var was = c.side;
        change({ action: 'update', id: c.id, side: other.id }, c.name + ' is now under ' + other.name,
          { action: 'update', id: c.id, side: was });
      } });
    }
    items.push({ label: 'Delete', icon: '×', disabled: n > 0, note: n > 0 ? 'only when empty' : '',
      action: function () { deleteCat(c.id); } });
    items.push({ label: 'Manage categories', icon: '\u2699', action: function () { openManager(b); } });
    openMenu(b, items);
  }

  /* ------------------------------------------------------- saving to disk */
  /* Every change goes to the server, and the page then draws what the server
     says is on disk - so two tabs, or Claude editing the file, cannot leave the
     page showing something that is not saved. */
  function adopt(doc) {
    if (!doc || !doc.categories) { return; }
    sides = doc.sides;
    cats = doc.categories;
    placed = doc.tasks || {};
  }
  /* Changes go one at a time, in order, so an answer that arrives late can
     never draw an older state over a newer one. */
  var queue = Promise.resolve();
  function post(body) {
    var sent = queue.then(function () {
      return fetch('/api/categories', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          adopt(j);
          if (r.status !== 200 || !j.ok) { throw new Error(j.error || 'The change was not saved.'); }
          return j;
        });
      });
    });
    queue = sent.catch(function () { /* the caller reports it */ });
    return sent;
  }
  function refuse() {
    toast('Nothing can be changed until ' + DATA.file + ' is fixed: ' + DATA.error, null, true);
    return true;
  }
  /* Draw the change at once, save it, and if the server refuses, draw what it
     has instead and say why. */
  function change(body, done, undoBody, afterRender) {
    if (locked && refuse()) { return; }
    return post(body).then(function () {
      renderBar();
      render(true);
      refreshManager();
      if (afterRender) { afterRender(); }
      if (done) {
        toast(done, undoBody ? function () {
          change(undoBody, null, null, afterRender);
        } : null);
      }
    }).catch(function (err) {
      renderBar();
      render(true);
      refreshManager();
      toast(err.message, null, true);
    });
  }
  function moveTask(id, catId) {
    if (locked && refuse()) { return; }
    var t = byId[id], old = placed[t.dir] ? { category: placed[t.dir].category, guess: placed[t.dir].guess } : null;
    if (old && old.category === catId) { if (old.guess) { keepTask(id); } return; }
    placed[t.dir] = { category: catId, guess: false };
    land(id, true);
    post({ action: 'move', task: t.dir, category: catId }).then(function () {
      toast('Moved ' + label(t) + ' to ' + catById(catId).name, function () {
        placed[t.dir] = old;
        if (!old) { delete placed[t.dir]; }
        land(id, true);
        post({ action: 'move', task: t.dir, category: old ? old.category : null, guess: old ? old.guess : false })
          .catch(function (err) { render(true); toast(err.message, null, true); });
      });
    }).catch(function (err) { render(true); toast(err.message, null, true); });
  }
  function keepTask(id) {
    if (locked && refuse()) { return; }
    var t = byId[id], p = placed[t.dir];
    placed[t.dir] = { category: p.category, guess: false };
    land(id, false);
    post({ action: 'move', task: t.dir, category: p.category }).then(function () {
      toast('Kept ' + label(t) + ' in ' + catById(p.category).name, function () {
        placed[t.dir] = { category: p.category, guess: true };
        land(id, false);
        post({ action: 'move', task: t.dir, category: p.category, guess: true })
          .catch(function (err) { render(true); toast(err.message, null, true); });
      });
    }).catch(function (err) { render(true); toast(err.message, null, true); });
  }
  /* Re-draw, then make sure the task is visible where it landed and flash it. */
  function land(id, animate) {
    render(animate);
    var r = rows[id];
    if (r.isConnected && r.hidden) {
      unfolded[$('.fold', r.closest('.col')).dataset.key] = true;
      render(false);
    }
    var el = r.isConnected ? r : $('.card[data-id="' + id + '"]', focusEl);
    if (el && !el.hidden) {
      el.classList.remove('flash');
      void el.offsetWidth;
      el.classList.add('flash');
      el.scrollIntoView({ block: 'nearest' });
    }
  }
  function deleteCat(id) {
    var at = orderedCats().indexOf(catById(id)), gone = catById(id);
    if (sel.kind === 'cats' && sel.ids.indexOf(id) !== -1) {
      var ids = sel.ids.filter(function (x) { return x !== id; });
      sel = ids.length ? { kind: 'cats', ids: ids } : { kind: 'all' };
    }
    change({ action: 'delete', id: id }, 'Deleted ' + gone.name,
      { action: 'add', id: gone.id, name: gone.name, side: gone.side, color: gone.color, holds: gone.holds,
        at: cats.indexOf(gone) >= 0 ? cats.indexOf(gone) : at });
  }

  function toast(text, undo, bad) {
    clearTimeout(toastTimer);
    toastEl.innerHTML = '<span>' + esc(text) + '</span>' + (undo ? '<button type="button">Undo</button>' : '');
    toastEl.classList.toggle('bad', !!bad);
    toastEl.hidden = false;
    if (!REDUCE) {
      toastEl.animate([{ opacity: 0, transform: 'translate(-50%,8px)' }, { opacity: 1, transform: 'translate(-50%,0)' }],
        { duration: 160, easing: 'ease-out' });
    }
    var b = $('button', toastEl);
    if (b) { b.onclick = function () { toastEl.hidden = true; clearTimeout(toastTimer); undo(); }; }
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, bad ? 9000 : 6000);
  }

  /* ------------------------------------------------ new and renamed categories */
  /* ------------------------------------------------- managing the categories */
  /* One list to rename, recolour, move between the columns, describe, add and
     delete categories. Every change is saved as it is made. Nothing is picked
     for the person: a new category has no column until they choose one. */
  var PALETTE = ['blue', 'amber', 'teal', 'rose', 'violet', 'green', 'slate'];
  var manageEl = null, manageFrom = null, addSide = null;
  function sidePick(current) {
    return '<span class="sidepick" role="group" aria-label="Column">' + sides.map(function (s) {
      return '<button type="button" data-side="' + esc(s.id) + '" aria-pressed="' + (s.id === current) + '">' +
        esc(s.name) + '</button>';
    }).join('') + '</span>';
  }
  function openManager(from) {
    if (locked && refuse()) { return; }
    closeMenu(false);
    manageFrom = from || document.activeElement;
    if (!manageEl) {
      manageEl = document.createElement('div');
      manageEl.className = 'mgr-overlay';
      manageEl.id = 'manage';
      document.body.appendChild(manageEl);
      manageEl.addEventListener('mousedown', function (e) { if (e.target === manageEl) { closeManager(); } });
      manageEl.addEventListener('click', onManageClick);
      manageEl.addEventListener('keydown', onManageKey);
      manageEl.addEventListener('focusout', function (e) { if (e.target.matches('.mgr-row input')) { saveField(e.target); } });
      manageEl.addEventListener('input', function (e) { if (e.target.closest('.mgr-add')) { paintAdd(); } });
      manageEl.addEventListener('submit', onManageSubmit);
    }
    addSide = null;
    manageEl.hidden = false;
    renderManager();
    $('.mgr', manageEl).focus();
  }
  function closeManager() {
    if (!manageEl || manageEl.hidden) { return; }
    var active = document.activeElement;
    if (active && active.matches && active.matches('.mgr-row input')) { saveField(active); }
    manageEl.hidden = true;
    var back = manageFrom && manageFrom.isConnected ? manageFrom : $('.chip.manage', bar);
    if (back) { back.focus(); }
  }
  function refreshManager() { if (manageEl && !manageEl.hidden) { renderManager(); } }
  function renderManager() {
    var active = manageEl.contains(document.activeElement) ? document.activeElement : null;
    var keep = active && active.dataset.field ? { id: active.closest('[data-id]') ? active.closest('[data-id]').dataset.id : null,
      field: active.dataset.field, start: active.selectionStart, end: active.selectionEnd } : null;
    var old = $('.mgr-add', manageEl);
    var pending = old ? { name: $('.nm', old).value, holds: $('.hd', old).value } : { name: '', holds: '' };
    var held = {};
    tasks.forEach(function (t) { var c = catOf(t); if (c) { held[c.id] = (held[c.id] || 0) + 1; } });
    var either = sides.map(function (s) { return esc(s.name); }).join(' or ');
    var html = '<div class="mgr" role="dialog" aria-modal="true" aria-labelledby="mgr-title" tabindex="-1">' +
      '<header class="mgr-head"><h2 id="mgr-title">Categories</h2><p>Each category sits in one column, ' + either +
      '. Claude reads "What goes here" when it files a new task.</p>' +
      '<button type="button" class="mgr-x" aria-label="Close">×</button></header>' +
      '<div class="mgr-cols" aria-hidden="true"><span></span><span>Name</span><span>Column</span>' +
      '<span>What goes here</span><span>Tasks</span><span></span></div>';
    sides.forEach(function (s) {
      var mine = cats.filter(function (c) { return c.side === s.id; });
      if (!mine.length) { return; }
      html += '<div class="mgr-group">' + esc(s.name) + '</div>';
      mine.forEach(function (c) {
        var n = held[c.id] || 0;
        html += '<div class="mgr-row" data-id="' + esc(c.id) + '" style="--cc:' + colorVar(c) + '">' +
          '<button type="button" class="sw" aria-expanded="false" aria-label="Colour: ' + c.color +
          '. Change it" title="Change the colour"><i class="dot"></i></button>' +
          '<input class="nm" data-field="name" maxlength="30" aria-label="Name" value="' + esc(c.name) + '">' +
          sidePick(c.side) +
          '<input class="hd" data-field="holds" maxlength="240" aria-label="What goes here"' +
          ' placeholder="What belongs here, in a few words" value="' + esc(c.holds || '') + '">' +
          '<span class="n">' + plural(n, 'task') + '</span>' +
          '<button type="button" class="del"' + (n ? ' disabled title="Move its ' + plural(n, 'task') +
            ' to another category first"' : ' title="Delete ' + esc(c.name) + '"') + '>Delete</button></div>';
      });
    });
    if (!cats.length) { html += '<p class="none">No categories yet. Add the first one below.</p>'; }
    html += '<form class="mgr-add" autocomplete="off"><span class="sw" aria-hidden="true"></span>' +
      '<input class="nm" data-field="new-name" maxlength="30" aria-label="Name of the new category" placeholder="New category">' +
      sidePick(addSide) +
      '<input class="hd" data-field="new-holds" maxlength="240" aria-label="What goes in the new category" placeholder="What goes here">' +
      '<span class="n"></span><button type="submit" class="go">Add</button>' +
      '<p class="why" hidden>Pick ' + either + ' for it first.</p></form>' +
      '<footer class="mgr-foot"><span>' + esc(DATA.savedNote || 'Every change is saved as you make it, to ' + DATA.file + '.') + '</span>' +
      '<button type="button" class="done">Done</button></footer></div>';
    manageEl.innerHTML = html;
    $('.mgr-add .nm', manageEl).value = pending.name;
    $('.mgr-add .hd', manageEl).value = pending.holds;
    paintAdd();
    if (keep) {
      var back = keep.id ? $('.mgr-row[data-id="' + keep.id + '"] [data-field="' + keep.field + '"]', manageEl) :
        $('.mgr-add [data-field="' + keep.field + '"]', manageEl);
      if (back) {
        back.focus();
        try { back.setSelectionRange(keep.start, keep.end); } catch (e) { /* not a text field */ }
      }
    }
  }
  function paintAdd() {
    var form = $('.mgr-add', manageEl), name = $('.nm', form).value.trim();
    $('.go', form).disabled = !name || !addSide;
    $('.why', form).hidden = !(name && !addSide);
  }
  function flashRow(id) {
    var r = manageEl && $('.mgr-row[data-id="' + id + '"]', manageEl);
    if (!r) { return; }
    r.classList.remove('saved');
    void r.offsetWidth;
    r.classList.add('saved');
  }
  function update(id, fields, done, undo) {
    var body = { action: 'update', id: id }, back = null;
    Object.keys(fields).forEach(function (k) { body[k] = fields[k]; });
    if (undo) {
      back = { action: 'update', id: id };
      Object.keys(undo).forEach(function (k) { back[k] = undo[k]; });
    }
    return change(body, done, back, function () { flashRow(id); });
  }
  /* A name or a description is saved when the field is left, or on Enter. */
  function saveField(input) {
    var row = input.closest('.mgr-row'), c = row && catById(row.dataset.id);
    if (!c) { return; }
    var field = input.dataset.field, value = input.value.trim(), old = field === 'name' ? c.name : (c.holds || '');
    if (value === old || value === input.dataset.sent) { return; }
    if (field === 'name' && !value) { input.value = c.name; toast('A category needs a name.', null, true); return; }
    input.dataset.sent = value;
    var fields = {}, undo = {};
    fields[field] = value;
    undo[field] = old;
    update(c.id, fields, field === 'name' ? 'Renamed ' + old + ' to ' + value : 'Saved what goes in ' + c.name, undo);
  }
  function onManageClick(e) {
    var t = e.target;
    if (t.closest('.mgr-x') || t.closest('.done')) { closeManager(); return; }
    var pickBtn = t.closest('.sidepick button');
    if (pickBtn && t.closest('.mgr-add')) {
      addSide = pickBtn.dataset.side;
      $$('.mgr-add .sidepick button', manageEl).forEach(function (b) { b.setAttribute('aria-pressed', b === pickBtn); });
      paintAdd();
      $('.mgr-add .nm', manageEl).focus();
      return;
    }
    var row = t.closest('.mgr-row'), c = row && catById(row.dataset.id);
    if (!c) { return; }
    if (pickBtn) {
      if (pickBtn.dataset.side !== c.side) {
        update(c.id, { side: pickBtn.dataset.side }, c.name + ' is now under ' + sideName(pickBtn.dataset.side), { side: c.side });
      }
      return;
    }
    var colour = t.closest('.pal button');
    if (colour) {
      if (colour.dataset.color !== c.color) { update(c.id, { color: colour.dataset.color }); } else { $('.pal', row).remove(); }
      return;
    }
    if (t.closest('.sw')) {
      var had = $('.pal', row);
      $$('.pal', manageEl).forEach(function (x) { x.remove(); });
      $$('.sw[aria-expanded="true"]', manageEl).forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
      if (had) { return; }
      var pal = document.createElement('div');
      pal.className = 'pal';
      pal.innerHTML = PALETTE.map(function (name) {
        return '<button type="button" data-color="' + name + '" style="--cc:var(--cat-' + name + ')" aria-pressed="' +
          (name === c.color) + '" aria-label="' + name + '" title="' + name + '"></button>';
      }).join('');
      row.appendChild(pal);
      $('.sw', row).setAttribute('aria-expanded', 'true');
      return;
    }
    var del = t.closest('.del');
    if (del && !del.disabled) { deleteCat(c.id); }
  }
  function onManageKey(e) {
    e.stopPropagation();
    var t = e.target;
    if (e.key === 'Escape') {
      e.preventDefault();
      if ($('.pal', manageEl)) {
        $$('.pal', manageEl).forEach(function (x) { x.remove(); });
        $$('.sw', manageEl).forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
        return;
      }
      if (t.matches && t.matches('.mgr-row input')) {
        var c = catById(t.closest('.mgr-row').dataset.id);
        t.value = t.dataset.field === 'name' ? c.name : (c.holds || '');
        $('.mgr', manageEl).focus();
        return;
      }
      closeManager();
      return;
    }
    if (e.key === 'Enter' && t.matches && t.matches('.mgr-row input')) {
      e.preventDefault();
      saveField(t);
    }
  }
  function onManageSubmit(e) {
    e.preventDefault();
    var form = e.target, name = $('.nm', form).value.trim(), holds = $('.hd', form).value.trim(), side = addSide;
    if (!name || !side) { paintAdd(); (side ? $('.nm', form) : $('.sidepick button', form)).focus(); return; }
    var had = cats.map(function (c) { return c.id; });
    post({ action: 'add', name: name, side: side, holds: holds }).then(function () {
      var added = cats.filter(function (c) { return had.indexOf(c.id) === -1; })[0];
      addSide = null;
      $('.nm', form).value = '';
      $('.hd', form).value = '';
      renderBar();
      render(true);
      renderManager();
      if (added) { flashRow(added.id); }
      $('.mgr-add .nm', manageEl).focus();
      toast('Added ' + name + ' under ' + sideName(side) + '. Drag tasks onto it.', added ? function () {
        change({ action: 'delete', id: added.id });
      } : null);
    }).catch(function (err) { renderManager(); toast(err.message, null, true); });
  }
  /* The button becomes a small text field in place: Enter keeps, Esc drops. */
  function startRename(id) {
    if (locked && refuse()) { return; }
    var b = $('.chip[data-cat="' + id + '"]', bar), c = catById(id);
    if (!b || !c) { return; }
    var box = document.createElement('span');
    box.className = 'chip editing';
    box.style.setProperty('--cc', colorVar(c));
    box.innerHTML = '<i class="dot"></i><input aria-label="Category name" maxlength="30">';
    var input = $('input', box);
    input.value = c.name;
    input.style.width = Math.max(6, c.name.length + 1) + 'ch';
    b.replaceWith(box);
    input.focus();
    input.select();
    var done = false;
    function finish(keep) {
      if (done) { return; }
      done = true;
      var v = input.value.trim(), old = c.name;
      if (keep && v && v !== old) {
        change({ action: 'update', id: id, name: v }, 'Renamed ' + old + ' to ' + v, { action: 'update', id: id, name: old });
        return;
      }
      renderBar();
      render(false);
    }
    input.addEventListener('input', function () { input.style.width = Math.max(6, input.value.length + 1) + 'ch'; });
    input.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', function () { finish(true); });
  }

  /* ---------------------------------------------------------------- hover */
  /* Hovering a category shows where its tasks are without moving anything. */
  function peek(test) {
    peekTest = test;
    document.body.classList.add('peeking');
    tasks.forEach(function (t) { rows[t.id].classList.toggle('lit', test(t)); });
    $$('.card', focusEl).forEach(function (c) { c.classList.toggle('lit', test(byId[c.dataset.id])); });
  }
  function unpeek() { peekTest = null; document.body.classList.remove('peeking'); }
  function peekFrom(el) {
    if (dragId !== null || !el) { unpeek(); return; }
    if (el.dataset.cat) { var id = el.dataset.cat; peek(function (t) { var c = catOf(t); return !!c && c.id === id; }); return; }
    if (el.dataset.side) { var s = el.dataset.side; peek(function (t) { var c = catOf(t); return !!c && c.side === s; }); return; }
    unpeek();
  }
  bar.addEventListener('mouseover', function (e) { peekFrom(e.target.closest('.chip[data-cat], .side')); });
  bar.addEventListener('mouseleave', unpeek);
  board.addEventListener('mouseover', function (e) { peekFrom(e.target.closest('.lg')); });
  board.addEventListener('mouseleave', unpeek);

  /* --------------------------------------------------------------- clicks */
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b || e.detail > 1) { return; }
    if (b.classList.contains('manage')) { openManager(b); return; }
    if (b.dataset.all) { setSel({ kind: 'all' }); return; }
    if (b.classList.contains('side')) {
      var s = b.dataset.side;
      setSel(sel.kind === 'side' && sel.id === s ? { kind: 'all' } : { kind: 'side', id: s });
      return;
    }
    if (b.dataset.cat) {
      var id = b.dataset.cat;
      if (e.metaKey || e.shiftKey || e.ctrlKey) {
        var ids = sel.kind === 'cats' ? sel.ids.slice() : [];
        var at = ids.indexOf(id);
        if (at === -1) { ids.push(id); } else { ids.splice(at, 1); }
        setSel(ids.length ? { kind: 'cats', ids: ids } : { kind: 'all' });
      } else {
        setSel(sel.kind === 'cats' && sel.ids.length === 1 && sel.ids[0] === id ? { kind: 'all' } : { kind: 'cats', ids: [id] });
      }
    }
  });
  bar.addEventListener('dblclick', function (e) {
    var b = e.target.closest('.chip[data-cat]');
    if (b && !readonly) { e.preventDefault(); startRename(b.dataset.cat); }
  });
  bar.addEventListener('contextmenu', function (e) {
    var b = e.target.closest('.chip[data-cat]');
    if (b && !readonly) { e.preventDefault(); chipMenu(b); }
  });
  document.addEventListener('click', function (e) {
    var tw = e.target.closest('.row button.tw, .row button.more');
    if (tw) { toggleSteps(holderOf(tw).dataset.id); return; }
    var cat = e.target.closest('.row .cat, .card .cat');
    if (cat && !readonly) { e.preventDefault(); moveMenu(holderOf(cat).dataset.id, cat); return; }
    var sb = e.target.closest('.sidebtn');
    if (sb) {
      setSel(sel.kind === 'side' && sel.id === sb.dataset.side ? { kind: 'all' } : { kind: 'side', id: sb.dataset.side });
      return;
    }
    var lg = e.target.closest('.lg[data-cat]');
    if (lg) { setSel({ kind: 'cats', ids: [lg.dataset.cat] }); return; }
    var fold = e.target.closest('.fold');
    if (fold) { unfolded[fold.dataset.key] = !unfolded[fold.dataset.key]; render(true); return; }
    if (e.target.closest('.fhead .back')) { setSel({ kind: 'all' }); }
  });

  /* ------------------------------------------------------- drag and drop */
  function clearDrag() {
    document.body.classList.remove('dragging');
    $$('.ghost, .over, .from').forEach(function (x) { x.classList.remove('ghost', 'over', 'from'); });
    dragId = null;
  }
  function dropTarget(e) { return e.target.closest ? e.target.closest('.chip[data-cat]') : null; }
  document.addEventListener('dragstart', function (e) {
    var h = e.target.closest && e.target.closest('.row, .card');
    if (!h || readonly || !sortable(byId[h.dataset.id])) { return; }
    dragId = h.dataset.id;
    try { e.dataTransfer.setData('text/plain', dragId); e.dataTransfer.effectAllowed = 'move'; } catch (x) { /* old browsers */ }
    closeMenu(false);
    unpeek();
    document.body.classList.add('dragging');
    h.classList.add('ghost');
    var c = catOf(byId[dragId]), from = c && $('.chip[data-cat="' + c.id + '"]', bar);
    if (from) { from.classList.add('from'); }
  });
  document.addEventListener('dragover', function (e) {
    if (dragId === null) { return; }
    var t = dropTarget(e);
    $$('.over').forEach(function (o) { if (o !== t) { o.classList.remove('over'); } });
    if (!t) { return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    t.classList.add('over');
  });
  document.addEventListener('drop', function (e) {
    var t = dropTarget(e);
    if (dragId === null || !t) { return; }
    e.preventDefault();
    var id = dragId, catId = t.dataset.cat;
    clearDrag();
    moveTask(id, catId);
  });
  document.addEventListener('dragend', clearDrag);

  /* ------------------------------------------------------ everything else */
  q.addEventListener('input', function () {
    query = q.value.trim().toLowerCase();
    cursorKey = null;
    render(false);
  });
  /* One button that says what it will do: open every task, or close every
     open one. The page remembers which way it was left. */
  var expandBtn = $('#expand');
  function anyOpen() {
    return tasks.some(function (t) { var r = rows[t.id]; return r.isConnected && !r.hidden && r.classList.contains('open'); });
  }
  function paintExpand() {
    if (!expandBtn) { return; }
    var open = anyOpen();
    expandBtn.textContent = open ? 'Collapse all' : 'Expand all';
    expandBtn.title = open ? 'Close every task, so each is one line again' : 'Open every task, to see all its steps and pages';
    expandBtn.setAttribute('aria-expanded', open);
    expandBtn.hidden = !focusEl.hidden || !tasks.some(openable);
  }
  if (expandBtn) {
    expandBtn.addEventListener('click', function () {
      stepsMode = anyOpen() ? 'newest' : 'all';
      flipped = {};
      writeSteps();
      render(true);
    });
  }

  document.addEventListener('keydown', function (e) {
    if (manageEl && !manageEl.hidden) { if (e.key === 'Escape') { closeManager(); } return; }
    if (!menu.hidden) { return; }
    var active = document.activeElement, typing = active === q;
    if (active && active.tagName === 'INPUT' && !typing) { return; }
    if (e.metaKey || e.ctrlKey || e.altKey) { return; }
    if (e.key === '/' && !typing) { e.preventDefault(); q.focus(); q.select(); return; }
    if (e.key === 'Escape') {
      if (q.value) { q.value = ''; query = ''; cursorKey = null; render(false); return; }
      if (sel.kind !== 'all') { setSel({ kind: 'all' }); return; }
      q.blur();
      return;
    }
    var free = !typing || !q.value;
    if (e.key === 'ArrowDown') { e.preventDefault(); letGo(); moveCursor(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); letGo(); moveCursor(-1); return; }
    if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && free) {
      e.preventDefault();
      letGo();
      switchColumn(e.key === 'ArrowRight' ? 1 : -1);
      return;
    }
    if (e.key === ' ' && free && cursorKey && !(active && active !== q && /^(BUTTON|A|SUMMARY)$/.test(active.tagName))) {
      e.preventDefault();
      space();
      return;
    }
    /* Enter opens what is highlighted, whatever button was clicked last; with
       nothing highlighted, a focused button keeps its usual Enter. */
    if (e.key === 'Enter') {
      var el = elOf(cursorKey) || (stops.length === 1 ? stops[0] : null);
      if (el) { e.preventDefault(); location.href = el.getAttribute('href'); }
    }
  });
  window.addEventListener('resize', function () { closeMenu(false); });

  if (DATA.error) {
    noticeEl.innerHTML = '<b>' + esc(DATA.file) + ' could not be read</b> (' + esc(DATA.error) + '). ' +
      'Every task shows as not sorted, and nothing is written to the file until it is fixed.';
    noticeEl.hidden = false;
  }
  renderBar();
  render(false);
  q.focus({ preventScroll: true });
})();
