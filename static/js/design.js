/* ============================================================
   V34 Studio design
   - every page header gets an eyebrow label, subtitle and an
     illustration in that page's accent colour (not only blue)
   - global search in the top bar (Ctrl/⌘ K)
   - stat cards with a sparkline and period-over-period change
   ============================================================ */
const PAGE_META = {
  input:        {eyebrow:'Dashboard',  accent:'violet',  art:'video',     sub:'Upload and manage your social media videos'},
  calendar:     {eyebrow:'Planning',   accent:'blue',    art:'calendar',  sub:'Schedule posts and see everything going out this month'},
  queue:        {eyebrow:'Planning',   accent:'teal',    art:'clock',     sub:'Weekly posting slots, filled automatically'},
  published:    {eyebrow:'Publishing', accent:'green',   art:'send',      sub:'Everything that went live, with stats and comments'},
  analytics:    {eyebrow:'Insights',   accent:'indigo',  art:'bars',      sub:'Views, engagement and follower growth across platforms'},
  inbox:        {eyebrow:'Engagement', accent:'pink',    art:'mail',      sub:'Comments and messages from every connected platform'},
  content:      {eyebrow:'Create',     accent:'emerald', art:'pen',       sub:'Write captions, scripts and hashtags with AI'},
  library:      {eyebrow:'Create',     accent:'teal',    art:'folder',    sub:'Reusable media, caption templates and hashtag groups'},
  bio:          {eyebrow:'Growth',     accent:'indigo',  art:'globe',     sub:'Your link-in-bio page and click-tracked links'},
  reports:      {eyebrow:'Insights',   accent:'violet',  art:'fileText',  sub:'Production and publishing reports'},
  team:         {eyebrow:'Account',    accent:'pink',    art:'users',     sub:'Brands, brand kits, permissions and people'},
  activity:     {eyebrow:'Account',    accent:'amber',   art:'activity',  sub:'Who did what, and when'},
  notifications:{eyebrow:'Account',    accent:'amber',   art:'bell',      sub:'Alerts about posts, comments and connections'},
  setup:        {eyebrow:'Account',    accent:'blue',    art:'gear',      sub:'Connect platforms, credentials and alerts'},
};
window.PAGE_META = PAGE_META;

let _svgN = 0;
const svgId = p => `${p}${++_svgN}`;

/* Decorative header illustration: floating glass cards around the page icon */
function heroArt(icon){
  const g = svgId('ha'), P = ICON_PATHS[icon] || ICON_PATHS.sparkles;
  const acc = 'style="stroke:var(--acc)"';
  return `<svg viewBox="0 0 420 170" width="420" height="170" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="${g}a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" style="stop-color:var(--acc-2)"/><stop offset="1" style="stop-color:var(--acc)"/></linearGradient>
      <linearGradient id="${g}b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset="1" stop-color="#fff" stop-opacity=".5"/></linearGradient>
      <radialGradient id="${g}c"><stop offset="0" style="stop-color:var(--acc);stop-opacity:.22"/><stop offset="1" style="stop-color:var(--acc);stop-opacity:0"/></radialGradient>
      <filter id="${g}s" x="-40%" y="-40%" width="180%" height="190%"><feDropShadow dx="0" dy="10" stdDeviation="9" flood-color="#2b1f7a" flood-opacity=".16"/></filter>
    </defs>
    <ellipse cx="258" cy="92" rx="200" ry="86" fill="url(#${g}c)"/>
    <path d="M10 160 C 80 160, 105 104, 168 106" ${acc} stroke-width="2" stroke-linecap="round" opacity=".35"/>
    <circle cx="168" cy="106" r="4.5" style="fill:var(--acc)" opacity=".45"/>
    <rect x="222" y="46" width="160" height="104" rx="20" fill="url(#${g}b)" stroke="#fff" transform="rotate(7 302 98)" filter="url(#${g}s)"/>
    <g transform="rotate(-5 252 84)" filter="url(#${g}s)">
      <rect x="172" y="28" width="164" height="110" rx="22" fill="url(#${g}a)"/>
      <rect x="172" y="28" width="164" height="55" rx="22" fill="#fff" opacity=".10"/>
      <circle cx="254" cy="83" r="30" fill="#fff" fill-opacity=".22"/>
      <g transform="translate(237.8 66.8) scale(1.35)" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none">${P}</g>
    </g>
    <g transform="rotate(9 372 40)" filter="url(#${g}s)">
      <rect x="346" y="12" width="54" height="48" rx="13" fill="#fff"/>
      <g transform="translate(361 24)" ${acc} stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none">${ICON_PATHS.image}</g>
    </g>
    <g filter="url(#${g}s)"><rect x="140" y="16" width="42" height="20" rx="10" fill="#34d399"/><circle cx="170" cy="26" r="4.5" fill="#fff" opacity=".85"/></g>
    <g filter="url(#${g}s)"><rect x="304" y="128" width="78" height="32" rx="11" fill="#fff"/>
      <rect x="316" y="146" width="8" height="8" rx="2" style="fill:var(--acc)" opacity=".5"/>
      <rect x="330" y="140" width="8" height="14" rx="2" style="fill:var(--acc)" opacity=".7"/>
      <rect x="344" y="136" width="8" height="18" rx="2" style="fill:var(--acc)"/>
      <rect x="358" y="143" width="8" height="11" rx="2" style="fill:var(--acc)" opacity=".6"/></g>
  </svg>`;
}
window.heroArt = heroArt;

/* Turn a page's plain header into the hero header: eyebrow + title + subtitle
   on the left, actions on the right, illustration behind. Runs whenever a page
   (re)renders its content. */
function decorateHead(pc){
  const head = [...pc.children].find(x=>x.matches && x.matches('.page-head,.panel-head'));
  if(!head || head.dataset.dec) return;
  const h2 = head.querySelector(':scope > h2'); if(!h2) return;
  head.dataset.dec = '1';
  const meta = PAGE_META[App.page] || {};
  const title = el(`<div class="ph-title"><div class="eyebrow"><span class="eb-dot"></span>${esc(meta.eyebrow||'Workspace')}</div></div>`);
  head.insertBefore(title, h2); title.appendChild(h2);
  let sub = head.querySelector(':scope > p.sub');
  const nx = head.nextElementSibling;
  if(!sub && nx && nx.matches('p.sub')) sub = nx;
  if(sub){ sub.removeAttribute('style'); title.appendChild(sub); }
  else if(meta.sub) title.appendChild(el(`<p class="sub">${esc(meta.sub)}</p>`));
  head.querySelectorAll(':scope > .tiles').forEach(t=>{ t.removeAttribute('style'); head.after(t); });
  head.querySelectorAll(':scope > .spacer').forEach(x=>x.remove());
  const rest = [...head.children].filter(x=>x!==title);
  if(rest.length){ const act = el('<div class="ph-actions"></div>'); rest.forEach(x=>act.appendChild(x)); head.appendChild(act); }
  head.classList.add('hero-head');
  head.insertBefore(el(`<div class="ph-art" aria-hidden="true">${heroArt(meta.art)}</div>`), head.firstChild);
  requestAnimationFrame(()=>placeArt(head));
}
/* keep the illustration in the free space between the title and the actions */
function placeArt(head){
  const art = head.querySelector('.ph-art'); if(!art) return;
  const act = head.querySelector('.ph-actions'), title = head.querySelector('.ph-title');
  const aw = act ? act.offsetWidth : 0, tw = title ? title.offsetWidth : 0, W = head.clientWidth;
  const free = W - tw - aw, fits = free >= 300;
  art.classList.toggle('dim', !fits);
  art.style.right = (fits ? Math.max(0, aw - 40) : 0) + 'px';
  const svg = art.querySelector('svg'); if(svg) svg.style.width = (fits ? Math.min(420, free + 70) : 420) + 'px';
}
let _artT = null;
window.addEventListener('resize', ()=>{ clearTimeout(_artT); _artT = setTimeout(()=>document.querySelectorAll('.hero-head').forEach(placeArt), 150); });
function watchPage(){
  const pc = $('#pageContent'); if(!pc) return;
  const meta = PAGE_META[App.page] || {};
  pc.dataset.accent = meta.accent || 'violet';
  pc.dataset.page = App.page;
  const run = ()=>decorateHead(pc);
  new MutationObserver(run).observe(pc, {childList:true});
  run();
}
window.watchPage = watchPage;

/* ---------- stat cards ---------- */
function smoothPath(pts){
  if(pts.length<2) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for(let i=0;i<pts.length-1;i++){
    const p0 = pts[i-1]||pts[i], p1 = pts[i], p2 = pts[i+1], p3 = pts[i+2]||p2;
    const c1 = [p1[0]+(p2[0]-p0[0])/6, p1[1]+(p2[1]-p0[1])/6], c2 = [p2[0]-(p3[0]-p1[0])/6, p2[1]-(p3[1]-p1[1])/6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}
function sparkline(series){
  const W = 220, H = 70, max = Math.max(...series, 0), id = svgId('sp');
  if(!max) return `<svg class="sc-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" x2="${W}" y1="${H-2}" y2="${H-2}" style="stroke:var(--sc)" stroke-width="2" stroke-dasharray="3 5" opacity=".35"/></svg>`;
  const pts = series.map((v,i)=>[W*i/(series.length-1||1), H-4-(H-14)*v/max]);
  const line = smoothPath(pts);
  return `<svg class="sc-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--sc);stop-opacity:.35"/><stop offset="1" style="stop-color:var(--sc);stop-opacity:0"/></linearGradient></defs>
    <path d="${line} L${W},${H} L0,${H} Z" fill="url(#${id})"/>
    <path d="${line}" fill="none" style="stroke:var(--sc)" stroke-width="2" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
}
/* {tone, icon, n, label, sub, series, cur, prev, days} */
function statCard(o){
  let delta = '';
  if(o.prev != null){
    if(!o.prev && !o.cur) delta = `<span class="sc-d flat">${ic('arrowUp',13)} 0%</span>`;
    else if(!o.prev) delta = `<span class="sc-d up">${ic('arrowUp',13)} New</span>`;
    else { const p = Math.round(100*(o.cur-o.prev)/o.prev);
      delta = `<span class="sc-d ${p>=0?'up':'down'}">${ic(p>=0?'arrowUp':'arrowDown',13)} ${Math.abs(p)}%</span>`; }
    delta = `<div class="sc-delta">${delta}<span>vs previous ${o.days} days</span></div>`;
  }
  return `<div class="stat-card tone-${o.tone}">
    <div class="sc-ico">${o.icon==='check'?`<span class="sc-check">${ic('check',22)}</span>`:ic(o.icon,30)}</div>
    <div class="sc-main"><div class="sc-n">${fmtNum(o.n)}</div><div class="sc-l">${esc(o.label)}</div><div class="sc-s">${esc(o.sub||'')}</div></div>
    ${delta}${o.series?sparkline(o.series):''}</div>`;
}
function fmtNum(n){ return (Number(n)||0).toLocaleString(); }
/* per-day counts of rows whose date field falls in the last `days` days, plus the previous period total */
function periodSeries(rows, field, days){
  const DAY = 86400000, now = Date.now(), start = now - days*DAY, prevStart = start - days*DAY;
  const series = new Array(days).fill(0); let cur = 0, prev = 0;
  rows.forEach(r=>{
    const s = r[field]; if(!s) return;
    const t = Date.parse(/Z|[+-]\d\d:?\d\d$/.test(s) ? s : s+'Z'); if(isNaN(t)) return;
    if(t >= start && t <= now){ cur++; series[Math.min(days-1, Math.floor((t-start)/DAY))]++; }
    else if(t >= prevStart && t < start) prev++;
  });
  return {series, cur, prev};
}
window.statCard = statCard; window.periodSeries = periodSeries; window.sparkline = sparkline;

/* ---------- global search (top bar) ---------- */
async function searchData(){
  const c = App._search;
  if(c && Date.now()-c.at < 30000) return c;
  const [v, p] = await Promise.all([api('/api/videos').catch(()=>({videos:[]})), api('/api/calendar').catch(()=>({items:[]}))]);
  return (App._search = {at:Date.now(), videos:v.videos||[], posts:p.items||[]});
}
function initTopSearch(){
  const box = $('#topSearch'); if(!box) return;
  if(!App.user){ box.innerHTML=''; delete box.dataset.ready; box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  if(box.dataset.ready) return; box.dataset.ready = '1';
  const mac = /Mac|iPhone|iPad/.test(navigator.platform||'');
  box.innerHTML = `<span class="ts-ic">${ic('search',17)}</span>
    <input id="tsIn" type="search" placeholder="Search videos, posts, campaigns or pages…" autocomplete="off" aria-label="Search">
    <kbd>${mac?'⌘':'Ctrl'} K</kbd><div class="ts-pop hidden" id="tsPop" role="listbox"></div>`;
  const inp = $('#tsIn'), pop = $('#tsPop');
  let results = [], sel = 0, timer = null;
  const close = ()=>{ pop.classList.add('hidden'); };
  const go = (r)=>{
    close(); inp.value=''; inp.blur();
    if(r.kind==='page'){ App.page = r.key; renderDashboard(App.readonly); }
    else if(r.kind==='video'){ App.focusVideo = r.id; App.page='input'; renderDashboard(App.readonly); }
    else if(r.kind==='post'){
      if(r.state==='published'){ App.focusPublished = r.id; App.page='published'; renderDashboard(App.readonly); return; }
      const [y,m] = r.date.split('-').map(Number); App.calMonth = {y, m:m-1}; App.page='calendar';
      renderDashboard(App.readonly); setTimeout(()=>{ if(typeof openDay==='function') openDay(r.date); }, 600);
    }
  };
  const draw = ()=>{
    if(!results.length){ pop.innerHTML = `<div class="ts-empty">No matches</div>`; pop.classList.remove('hidden'); return; }
    let last = '';
    pop.innerHTML = results.map((r,i)=>{
      const grp = r.group!==last ? `<div class="ts-grp">${esc(r.group)}</div>` : ''; last = r.group;
      return `${grp}<button class="ts-item ${i===sel?'on':''}" data-i="${i}" role="option"><span class="ts-ri">${ic(r.icon,16)}</span>
        <span class="ts-rt"><b>${esc(r.title)}</b>${r.meta?`<span>${esc(r.meta)}</span>`:''}</span></button>`;
    }).join('');
    pop.classList.remove('hidden');
    pop.querySelectorAll('[data-i]').forEach(b=>b.onmousedown = e=>{ e.preventDefault(); go(results[Number(b.dataset.i)]); });
  };
  const run = async ()=>{
    const q = inp.value.trim().toLowerCase();
    if(!q){ close(); return; }
    const d = await searchData();
    const has = (...xs)=>xs.some(x=>(x||'').toString().toLowerCase().includes(q));
    const pages = NAV_TABS.filter(t=>tabAllowed(t.key) && has(t.label, (PAGE_META[t.key]||{}).sub)).slice(0,4)
      .map(t=>({kind:'page', group:'Pages', icon:t.ic, title:t.label, meta:(PAGE_META[t.key]||{}).sub, key:t.key}));
    const vids = d.videos.filter(v=>has(v.title, v.description, v.hashtags)).slice(0,5)
      .map(v=>({kind:'video', group:'Videos', icon:'video', title:v.title, meta:`${(STAT[v.status]||{}).col||v.status} · ${v.owner||''}`, id:v.id}));
    const posts = d.posts.filter(p=>has(p.title, p.caption, p.hashtags, p.link_campaign)).slice(0,6)
      .map(p=>({kind:'post', group:'Posts', icon:p.state==='published'?'send':'calendar', title:p.title||'(untitled post)',
                meta:`${p.state==='published'?'Published':'Scheduled'} · ${p.date}`, id:p.id, date:p.date, state:p.state}));
    results = [...pages, ...vids, ...posts]; sel = 0; draw();
  };
  inp.addEventListener('input', ()=>{ clearTimeout(timer); timer = setTimeout(run, 160); });
  inp.addEventListener('focus', ()=>{ App._search = null; if(inp.value.trim()) run(); });
  inp.addEventListener('blur', ()=>setTimeout(close, 120));
  inp.addEventListener('keydown', e=>{
    if(e.key==='Escape'){ inp.value=''; close(); inp.blur(); }
    else if(e.key==='ArrowDown' && results.length){ e.preventDefault(); sel=(sel+1)%results.length; draw(); }
    else if(e.key==='ArrowUp' && results.length){ e.preventDefault(); sel=(sel-1+results.length)%results.length; draw(); }
    else if(e.key==='Enter' && results[sel]){ e.preventDefault(); go(results[sel]); }
  });
}
document.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){ const i = $('#tsIn'); if(i){ e.preventDefault(); i.focus(); i.select(); } }
});
window.initTopSearch = initTopSearch;

/* initials avatar for the user menu */
function initials(u){
  const n = (u.display_name||u.username||'?').trim();
  const parts = n.split(/\s+/).filter(Boolean);
  return ((parts[0]||'?')[0] + (parts.length>1 ? parts[parts.length-1][0] : (parts[0]||'')[1]||'')).toUpperCase();
}
window.initials = initials;
