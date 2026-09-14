// The index page at /, checked end to end in a real browser against a
// throwaway workspace, so nothing real is ever written.
//
//   node _askai/tests/index.e2e.mjs
//
// Needs python3 and the playwright package. Copies _askai/ into a temporary
// folder with a few made-up tasks, starts the proxy there on a free port, and
// checks the page and what it writes to _categories.json.
import { chromium } from 'playwright';
import { execFileSync, spawn } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ASKAI = dirname(dirname(fileURLToPath(import.meta.url)));
const results = [];
const check = (name, ok, detail) => results.push({ name, ok: !!ok, detail });
const errors = [];

const CATEGORIES = {
  about: 'test',
  sides: [{ id: 'work', name: 'Work' }, { id: 'private', name: 'Private' }],
  categories: [
    { id: 'acme', name: 'Acme', side: 'work', color: 'blue', holds: 'Work for Acme' },
    { id: 'home', name: 'Home', side: 'private', color: 'rose', holds: 'Life at home' },
  ],
  tasks: { '01.alpha': { category: 'acme' }, '02.beta': { category: 'home', guess: true } },
};

function workspace(categories, extra) {
  const root = mkdtempSync(join(tmpdir(), 'askai-index-'));
  mkdirSync(join(root, '_askai'));
  for (const f of readdirSync(ASKAI)) {
    if (/\.(py|js|css)$/.test(f)) { copyFileSync(join(ASKAI, f), join(root, '_askai', f)); }
  }
  const put = (rel, title) => {
    mkdirSync(dirname(join(root, rel)), { recursive: true });
    writeFileSync(join(root, rel), `<!doctype html><title>${title}</title><p>${title}</p>`);
  };
  put('tasks/01.alpha/01-01.first/index.html', 'Alpha first');
  put('tasks/01.alpha/01-02.second/index.html', 'Alpha second');
  put('tasks/01.alpha/01-02.second/extra.html', 'Alpha second extra');
  put('tasks/02.beta/index.html', 'Beta page');
  put('tasks/03.gamma/03-01.only/index.html', 'Gamma only');
  put('examples/01.example/index.html', 'Example page');
  if (categories !== undefined) {
    writeFileSync(join(root, '_categories.json'), typeof categories === 'string' ? categories : JSON.stringify(categories, null, 2));
  }
  if (extra) {
    extra((rel, text) => {
      mkdirSync(dirname(join(root, rel)), { recursive: true });
      writeFileSync(join(root, rel), text);
    });
  }
  return root;
}
const onDisk = root => JSON.parse(readFileSync(join(root, '_categories.json'), 'utf8'));
const freePort = () => new Promise(done => {
  const s = net.createServer();
  s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => done(port)); });
});
async function serve(root) {
  const port = await freePort();
  const proc = spawn('python3', [join(root, '_askai', 'server.py')], {
    env: { ...process.env, ASKAI_PORT: String(port), PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  await new Promise((done, fail) => {
    const timer = setTimeout(() => fail(new Error('the proxy did not start')), 10000);
    proc.stdout.on('data', d => { if (String(d).includes('Ask AI on')) { clearTimeout(timer); done(); } });
    proc.on('exit', code => fail(new Error(`the proxy exited with ${code}`)));
  });
  return { proc, url: `http://127.0.0.1:${port}/` };
}

const browser = await chromium.launch();
async function open(url, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, ...opts });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') { errors.push(m.text()); } });
  p.on('pageerror', e => errors.push(e.message));
  await p.goto(url);
  await p.waitForTimeout(400);
  return p;
}
const settle = p => p.waitForTimeout(400);
const idsIn = (p, sel) => p.$$eval(`${sel} .row`, rs => rs.filter(r => !r.hidden).map(r => r.dataset.id));
async function pick(p, text) {
  await p.evaluate(t => [...document.querySelectorAll('#menu button')]
    .find(b => b.querySelector('span:not(.note):not(.ic)')?.textContent === t).click(), text);
  await settle(p);
}

// --------------------------------------------------------- with categories
{
  const root = workspace(CATEGORIES);
  const { proc, url } = await serve(root);
  try {
    const p = await open(url);
    check('every task with a page is drawn once', (await p.$$('.row')).length === 4);
    check('Work holds Acme\'s task', JSON.stringify(await idsIn(p, '.col[data-side="work"]')) === '["tasks/01.alpha"]');
    check('Private holds Home\'s task', JSON.stringify(await idsIn(p, '.col[data-side="private"]')) === '["tasks/02.beta"]');
    check('a task with no category sits under Not sorted', JSON.stringify(await idsIn(p, '#unsorted')) === '["tasks/03.gamma"]');
    check('examples get a section of their own', JSON.stringify(await idsIn(p, '#others')) === '["examples/01.example"]');
    check('a guess has a dotted bar', await p.$eval('.row[data-id="tasks/02.beta"]', r => r.classList.contains('guess')));
    check('only a task with more than one page has an arrow',
      (await p.$$('.row[data-id="tasks/01.alpha"] button.tw')).length === 1 && (await p.$$('.row[data-id="tasks/02.beta"] button.tw')).length === 0);

    const on = () => p.$eval('.row.on', r => r.dataset.id).catch(() => null);
    const isOpen = id => p.$eval(`.row[data-id="${id}"]`, r => r.classList.contains('open'));
    await p.focus('#q');
    await p.keyboard.press('ArrowRight');
    check('→ goes to the right-hand column', await on() === 'tasks/02.beta', await on());
    await p.keyboard.press('ArrowLeft');
    check('← goes to the same place in the left-hand column', await on() === 'tasks/01.alpha', await on());
    await p.keyboard.press('Space');
    await settle(p);
    check('Space opens the highlighted task in place', await isOpen('tasks/01.alpha'));
    await p.keyboard.press('Space');
    await settle(p);
    check('Space again closes it', !(await isOpen('tasks/01.alpha')));
    check('with nothing open the button offers to expand all', await p.$eval('#expand', b => b.textContent) === 'Expand all');
    await p.click('#expand');
    await settle(p);
    check('Expand all opens every task with more than one page, and then offers to collapse',
      await isOpen('tasks/01.alpha') && await p.$eval('#expand', b => b.textContent) === 'Collapse all');
    await p.click('#expand');
    await settle(p);
    check('Collapse all closes them again', (await p.$$('.row.open')).length === 0);

    await p.click('.row[data-id="tasks/01.alpha"] button.tw');
    await settle(p);
    const opened = await p.$$eval('.row[data-id="tasks/01.alpha"] .subs .sub', a => a.map(x => x.textContent.trim()));
    check('the arrow lists both steps and the second step\'s other page, in place',
      opened.length === 3 && opened[1].includes('Alpha second extra') && p.url() === url, opened);

    await p.click('.row[data-id="tasks/03.gamma"] .cat');
    await p.waitForTimeout(150);
    await pick(p, 'Acme');
    check('moving a task writes it to _categories.json', onDisk(root).tasks['03.gamma']?.category === 'acme', onDisk(root).tasks);
    check('the Not sorted panel goes once it is empty', await p.$eval('#unsorted', e => e.hidden));
    await p.click('#toast button');
    await settle(p);
    check('Undo takes it back out of the file', !('03.gamma' in onDisk(root).tasks));

    await p.click('.row[data-id="tasks/02.beta"] .cat');
    await p.waitForTimeout(150);
    await pick(p, 'Keep in Home');
    check('keeping a guess drops "guess" from the file', JSON.stringify(onDisk(root).tasks['02.beta']) === '{"category":"home"}');

    await p.dragAndDrop('.row[data-id="tasks/01.alpha"]', '.chip[data-cat="home"]');
    await settle(p);
    check('dragging a task onto a button moves it on disk', onDisk(root).tasks['01.alpha'].category === 'home');

    await p.click('.chip.manage');
    await settle(p);
    check('Manage categories opens a list of every category',
      !(await p.$eval('#manage', m => m.hidden)) && (await p.$$('#manage .mgr-row')).length === 2);
    await p.fill('#manage .mgr-add .nm', 'Paddle');
    check('a new category cannot be added until its column is chosen',
      await p.$eval('#manage .mgr-add .go', b => b.disabled) && await p.$eval('#manage .mgr-add .why', w => !w.hidden));
    await p.click('#manage .mgr-add [data-side="private"]');
    await p.fill('#manage .mgr-add .hd', 'Padel games');
    await p.click('#manage .mgr-add .go');
    await settle(p);
    const added = onDisk(root).categories.find(c => c.name === 'Paddle');
    check('the new category is written with the column that was picked',
      added && added.side === 'private' && added.holds === 'Padel games' && added.color === 'amber', added);
    const row = `#manage .mgr-row[data-id="${added.id}"]`;
    const saved = () => onDisk(root).categories.find(c => c.id === added.id);
    await p.fill(`${row} .nm`, 'Padel');
    await p.keyboard.press('Enter');
    await settle(p);
    check('renaming it in the list saves it', saved().name === 'Padel');
    await p.click(`${row} [data-side="work"]`);
    await settle(p);
    check('moving it to the other column saves it', saved().side === 'work');
    await p.click(`${row} .sw`);
    await p.click(`${row} .pal [data-color="green"]`);
    await settle(p);
    check('changing its colour saves it', saved().color === 'green');
    await p.fill(`${row} .hd`, 'Padel, the sport');
    await p.keyboard.press('Tab');
    await settle(p);
    check('changing what goes in it saves it', saved().holds === 'Padel, the sport');
    check('a category with tasks cannot be deleted', await p.$eval('#manage .mgr-row[data-id="home"] .del', b => b.disabled));
    await p.click(`${row} .del`);
    await settle(p);
    check('an empty category is deleted from disk', !onDisk(root).categories.some(c => c.id === added.id));
    await p.keyboard.press('Escape');
    await settle(p);
    check('Esc closes the list', await p.$eval('#manage', m => m.hidden));
    await p.dblclick('.chip[data-cat="acme"]');
    await p.fill('.chip.editing input', 'Acme Co');
    await p.keyboard.press('Enter');
    await settle(p);
    check('double-clicking a button still renames it on disk', onDisk(root).categories.find(c => c.id === 'acme').name === 'Acme Co');
    await p.keyboard.press('Escape');
    await settle(p);

    const before = readFileSync(join(root, '_categories.json'), 'utf8');
    const foreign = await fetch(url + 'api/categories', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: 'http://evil.example' },
      body: JSON.stringify({ action: 'move', task: '03.gamma', category: 'home' }),
    });
    const plain = await fetch(url + 'api/categories', {
      method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ action: 'delete', id: 'acme' }),
    });
    check('another website cannot change categories', foreign.status === 403 && plain.status === 403 &&
      readFileSync(join(root, '_categories.json'), 'utf8') === before, [foreign.status, plain.status]);

    await p.fill('#q', 'extra');
    await settle(p);
    check('searching a page\'s title opens its task at that step',
      JSON.stringify(await p.$$eval('.row:not([hidden])', rs => rs.filter(r => r.isConnected).map(r => r.dataset.id))) === '["tasks/01.alpha"]' &&
      await p.$eval('.row[data-id="tasks/01.alpha"]', r => r.classList.contains('open')));
    await p.fill('#q', '');
    await settle(p);

    await p.click('.chip[data-cat="home"]');
    await settle(p);
    check('clicking a category shows only its tasks, full width', (await p.$$('.card')).length === 2 && p.url().endsWith('#cat=home'));
    await p.keyboard.press('Escape');
    await settle(p);
    await p.click('.row[data-id="tasks/01.alpha"] button.tw');
    await p.keyboard.press('ArrowDown');
    const target = await p.$eval('.row.on .tl', a => a.getAttribute('href')).catch(() => null);
    await Promise.all([p.waitForURL(u => u.pathname === target, { timeout: 4000 }), p.keyboard.press('Enter')]).catch(() => {});
    check('Enter opens the highlighted task even after a button was clicked',
      target && new URL(p.url()).pathname === target, { target, now: p.url() });

    const phone = await open(url, { viewport: { width: 390, height: 844 } });
    check('no sideways scrolling on a phone', await phone.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth));
  } finally {
    proc.kill();
    rmSync(root, { recursive: true, force: true });
  }
}

// ------------------------------------------------ no _categories.json yet
{
  const root = workspace();
  const { proc, url } = await serve(root);
  try {
    const p = await open(url);
    check('with no file, every task is under Not sorted', (await idsIn(p, '#unsorted')).length === 3);
    await p.click('.chip.manage');
    await p.fill('#manage .mgr-add .nm', 'First');
    await p.click('#manage .mgr-add [data-side="work"]');
    await p.click('#manage .mgr-add .go');
    await settle(p);
    check('the first category creates the file', existsSync(join(root, '_categories.json')) &&
      onDisk(root).categories.length === 1 && onDisk(root).sides.length === 2);
    await p.keyboard.press('Escape');
    await settle(p);
    await p.dragAndDrop('.row[data-id="tasks/02.beta"]', '.chip[data-cat="first"]');
    await settle(p);
    check('and a task can then be dragged into it', onDisk(root).tasks['02.beta']?.category === 'first');
  } finally {
    proc.kill();
    rmSync(root, { recursive: true, force: true });
  }
}

// ------------------------------------ tasks with no page yet, and their status
{
  const root = workspace(CATEGORIES, write => {
    write('tasks/04.delta/CLAUDE.md', '# Delta\n\n## Where this stands\n\nReading the **sources** now.\n' +
      'Nothing is written yet.\n- first open point\n\n## Decisions\n\nnot for the page\n');
    write('tasks/04.delta/_task.json', '{"status": "in progress"}');
    write('tasks/05.epsilon/CLAUDE.md', '# Epsilon\n');
    write('tasks/01.alpha/_task.json', '{"status": "done"}');
  });
  const { proc, url } = await serve(root);
  try {
    const p = await open(url);
    const ids = await p.$$eval('.row', rs => rs.map(r => r.dataset.id));
    check('a task with no page yet is on the index', ids.includes('tasks/04.delta') && ids.includes('tasks/05.epsilon'), ids);
    check('its line says it has no page yet',
      await p.$eval('.row[data-id="tasks/04.delta"] .latest', e => e.textContent) === 'No page yet');
    check('its status from _task.json is on its line, in plain words', await p.$eval('.row[data-id="tasks/04.delta"] .task-status',
      e => e.dataset.status === 'in-progress' && e.textContent === 'In progress'));
    check('a task with pages shows its status too',
      await p.$eval('.row[data-id="tasks/01.alpha"] .task-status', e => e.textContent) === 'Done');
    check('a task with no status shows none', (await p.$$('.row[data-id="tasks/05.epsilon"] .task-status')).length === 0);
    check('the line under the search box keeps its own look', await p.$eval('.search .status', e => {
      const st = getComputedStyle(e);
      return /mono/i.test(st.fontFamily) && st.backgroundColor === 'rgba(0, 0, 0, 0)';
    }));
    await p.fill('#q', 'in progress');
    await settle(p);
    check('searching for a status finds its tasks', JSON.stringify(await p.$$eval('.row:not([hidden])',
      rs => rs.filter(r => r.isConnected).map(r => r.dataset.id))) === '["tasks/04.delta"]');
    await p.fill('#q', '');
    await settle(p);

    const href = await p.$eval('.row[data-id="tasks/04.delta"] .tl', a => a.getAttribute('href'));
    await p.goto(new URL(href, url).href);
    const text = await p.$eval('body', b => b.innerText);
    check('it opens a page with its status and where it stands', href === '/task/tasks/04.delta/' &&
      text.includes('In progress') && text.includes('Reading the sources now. Nothing is written yet.') &&
      text.includes('first open point') && !text.includes('not for the page'), text.slice(0, 300));
    check('bold in its notes is drawn as bold', await p.$eval('.tk-stand strong', e => e.textContent) === 'sources');
    check('that page has the top bar', (await p.$$('#askai-crumb')).length === 1);
    writeFileSync(join(root, 'tasks/04.delta/_task.json'), '{"status": "waiting"}');
    await p.reload();
    check('it shows a new status as soon as the file says so', await p.$eval('.task-status', e => e.textContent) === 'Waiting on you');
    const bare = await (await fetch(url + 'task/tasks/05.epsilon/')).text();
    check('a task with no status or notes says so', bare.includes('No status yet') && bare.includes('no "Where this stands" section'));

    mkdirSync(join(root, 'tasks/04.delta/04-01.first'), { recursive: true });
    writeFileSync(join(root, 'tasks/04.delta/04-01.first/index.html'), '<!doctype html><title>Delta first</title><p>Delta</p>');
    await p.goto(url);
    await settle(p);
    check('once it has a page, its line opens that page', await p.$eval('.row[data-id="tasks/04.delta"] .tl',
      a => a.getAttribute('href')) === '/page/tasks/04.delta/04-01.first/index.html');
    await p.goto(url + 'task/tasks/01.alpha/');
    check('a task\'s own page shows its status', await p.$eval('.tk-h1 .task-status', e => e.textContent) === 'Done');
  } finally {
    proc.kill();
    rmSync(root, { recursive: true, force: true });
  }
}

// ------------------------------------ a change is committed by the proxy itself
// Only where the post-commit hook runs bin/sync; here the hook stands in for it.
{
  const root = workspace(CATEGORIES);
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' });
  git('init', '-q', '-b', 'main');
  git('config', 'user.name', 'Test');
  git('config', 'user.email', 'test@example.invalid');
  git('config', 'commit.gpgsign', 'false');
  git('add', '-A');
  git('commit', '-q', '-m', 'start');
  writeFileSync(join(root, '.git/hooks/post-commit'), '#!/bin/sh\n# Stands in for bin/sync.\n', { mode: 0o755 });
  writeFileSync(join(root, 'tasks/02.beta/index.html'), '<!doctype html><title>Beta page</title><p>An unsaved edit</p>');
  const { proc, url } = await serve(root);
  try {
    const p = await open(url);
    const start = git('rev-parse', 'HEAD');
    await p.dragAndDrop('.row[data-id="tasks/01.alpha"]', '.chip[data-cat="home"]');
    for (let i = 0; i < 50 && git('rev-parse', 'HEAD') === start; i++) { await p.waitForTimeout(100); }
    const subject = git('log', '-1', '--format=%s').trim();
    check('a drag is committed by the proxy, saying what moved', subject === 'Categories: moved 01.alpha from Acme to Home', subject);
    check('that commit holds _categories.json and nothing else', git('show', '--name-only', '--format=', 'HEAD').trim() === '_categories.json');
    check('an unsaved edit elsewhere is left out of it', git('status', '--porcelain').trim() === 'M tasks/02.beta/index.html', git('status', '--porcelain'));
  } finally {
    proc.kill();
    rmSync(root, { recursive: true, force: true });
  }
}

// ---------------------------------------------- a file that does not parse
{
  const root = workspace('{ this is not json');
  const { proc, url } = await serve(root);
  try {
    const p = await open(url);
    check('an unreadable file is named on the page', await p.$eval('#notice', n => !n.hidden && n.textContent.includes('could not be read')));
    await p.click('.row[data-id="tasks/01.alpha"] .cat');
    await p.waitForTimeout(150);
    check('and nothing is written over it', readFileSync(join(root, '_categories.json'), 'utf8') === '{ this is not json');
  } finally {
    proc.kill();
    rmSync(root, { recursive: true, force: true });
  }
}

check('no console errors', errors.length === 0, errors);
await browser.close();
const failed = results.filter(r => !r.ok);
for (const r of results) { console.log(`${r.ok ? 'ok  ' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ' + JSON.stringify(r.detail)}`); }
console.log(`\n${results.length - failed.length} of ${results.length} checks pass`);
process.exit(failed.length ? 1 : 0);
