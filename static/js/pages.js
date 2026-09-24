/* ============================================================
   V31 pages: Analytics · Inbox · Queue · Team & Brands · Activity
   ============================================================ */
const fmtN = n => (Number(n)||0).toLocaleString();
const fmtK = n => { n = Number(n)||0; return n>=1e6 ? (n/1e6).toFixed(1).replace(/\.0$/,'')+'M' : n>=1e4 ? (n/1e3).toFixed(1).replace(/\.0$/,'')+'K' : n.toLocaleString(); };

/* ---------- tiny inline-SVG bar charts (single series, hover tooltip) ---------- */
function vbarChart(host, rows, opts){
  // rows: [{label, value, tip}]  — vertical bars over time
  const W = Math.max(320, host.clientWidth || 640), H = opts.height || 190;
  const pad = {l:44, r:10, t:10, b:24};
  const iw = W-pad.l-pad.r, ih = H-pad.t-pad.b;
  const max = Math.max(1, ...rows.map(r=>r.value));
  const nice = niceMax(max), ticks = 4;
  const bw = iw / rows.length, barW = Math.max(2, Math.min(28, bw-2));
  let g = '';
  for(let i=0;i<=ticks;i++){
    const y = pad.t + ih - ih*i/ticks, v = nice*i/ticks;
    g += `<line x1="${pad.l}" x2="${W-pad.r}" y1="${y}" y2="${y}" class="viz-grid"/>
          <text x="${pad.l-6}" y="${y+4}" class="viz-axis" text-anchor="end">${fmtK(v)}</text>`;
  }
  const every = Math.ceil(rows.length/7);
  rows.forEach((r,i)=>{
    const h = r.value ? Math.max(2, ih*r.value/nice) : 0, x = pad.l + i*bw + (bw-barW)/2, y = pad.t+ih-h;
    if(h) g += `<path d="${roundedTop(x, y, barW, h, Math.min(4, barW/2))}" class="viz-bar" style="fill:${opts.color||'var(--viz-1)'}"/>`;
    g += `<rect x="${pad.l+i*bw}" y="${pad.t}" width="${bw}" height="${ih}" class="viz-hit" data-i="${i}"/>`;
    if(i%every===0) g += `<text x="${pad.l+i*bw+bw/2}" y="${H-6}" class="viz-axis" text-anchor="middle">${esc(r.label)}</text>`;
  });
  host.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.title||'chart')}">${g}</svg><div class="viz-tip hidden"></div>`;
  bindTips(host, rows);
}
function hbarChart(host, rows, opts){
  // rows: [{label, icon, value, display, tip}] — horizontal comparison bars
  const max = Math.max(1, ...rows.map(r=>r.value));
  host.innerHTML = `<div class="hbars">${rows.map((r,i)=>`<div class="hb-row viz-hit" data-i="${i}">
      <div class="hb-lab">${r.icon||''} ${esc(r.label)}</div>
      <div class="hb-track"><div class="hb-bar" style="width:${Math.max(r.value?1.5:0, 100*r.value/max)}%;background:${opts.color||'var(--viz-1)'}"></div></div>
      <div class="hb-val">${esc(r.display!=null?r.display:fmtN(r.value))}</div></div>`).join('')}</div><div class="viz-tip hidden"></div>`;
  bindTips(host, rows);
}
function bindTips(host, rows){
  const tip = host.querySelector('.viz-tip');
  host.querySelectorAll('.viz-hit').forEach(h=>{
    h.addEventListener('mousemove', e=>{
      const r = rows[Number(h.dataset.i)]; if(!r) return;
      tip.innerHTML = r.tip || `${esc(r.label)}: <b>${fmtN(r.value)}</b>`;
      tip.classList.remove('hidden');
      const box = host.getBoundingClientRect();
      let x = e.clientX-box.left+12, y = e.clientY-box.top-10;
      if(x+tip.offsetWidth > box.width) x = e.clientX-box.left-tip.offsetWidth-12;
      tip.style.left = x+'px'; tip.style.top = Math.max(0,y-tip.offsetHeight)+'px';
      h.classList.add('hover');
    });
    h.addEventListener('mouseleave', ()=>{ tip.classList.add('hidden'); h.classList.remove('hover'); });
  });
}
function niceMax(v){ const p = Math.pow(10, Math.floor(Math.log10(v))); const n = v/p; return (n<=1?1:n<=2?2:n<=5?5:10)*p; }
function roundedTop(x, y, w, h, r){
  r = Math.min(r, h);
  return `M${x},${y+h} V${y+r} Q${x},${y} ${x+r},${y} H${x+w-r} Q${x+w},${y} ${x+w},${y+r} V${y+h} Z`;
}

/* ============================================================ ANALYTICS */
async function renderAnalytics(){
  const c = $('#pageContent'); if(!c) return;
  App._an = App._an || {days:30, platform:'', metric:'views'};
  c.innerHTML = `<div class="page-head"><h2>Analytics</h2><div class="spacer"></div>
      <select class="f sel-sm" id="anDays">${[7,30,90].map(d=>`<option value="${d}" ${App._an.days===d?'selected':''}>Last ${d} days</option>`).join('')}</select>
      <select class="f sel-sm" id="anPlat"><option value="">All platforms</option>${PLAT_ORDER.map(p=>`<option value="${p}" ${App._an.platform===p?'selected':''}>${platLabel(p)}</option>`).join('')}</select>
      <button class="btn ghost sm" id="anRefresh">${ic('refresh',14)} Refresh stats</button>
      <a class="btn ghost sm" id="anPdf">${ic('download',14)} PDF report</a>
      <button class="btn ghost sm" id="anMail">${ic('mail',14)} Email report</button></div>
    <div id="anBody"><div class="loading">Loading…</div></div>`;
  $('#anDays').onchange = e=>{ App._an.days=Number(e.target.value); renderAnalytics(); };
  $('#anPlat').onchange = e=>{ App._an.platform=e.target.value; renderAnalytics(); };
  $('#anPdf').href = `/api/analytics/report.pdf?days=${App._an.days}`;
  $('#anRefresh').onclick = async ()=>{ const b=$('#anRefresh'); b.disabled=true;
    try{ const r=await api('/api/analytics/refresh',{method:'POST'}); toast(`Updated ${r.refreshed} post(s)`,'good'); renderAnalytics(); }
    catch(e){ toast(e.message,'warn'); b.disabled=false; } };
  $('#anMail').onclick = ()=>{
    const m = el(`<div class="modal" style="max-width:420px"><div class="modal-head"><h3>${ic('mail',18)} Email report</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
      <div class="modal-body"><label class="f">Send to</label><input class="f" id="em-to" placeholder="you@company.com">
      <div class="hint">A PDF for the last ${App._an.days} days is attached. Needs the SMTP server set in Setup.</div><div class="err" id="em-err"></div></div>
      <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="em-go">${ic('send',14)} Send</button></div></div>`);
    openModal(m);
    $('#em-go',m).onclick = async ()=>{ try{ await api('/api/analytics/report/email',{method:'POST', body:{to:$('#em-to',m).value, days:App._an.days}}); closeModal(); toast('Report sent','good'); }
      catch(e){ $('#em-err',m).textContent=e.message; } };
  };
  let d; try{ d = await api(`/api/analytics?days=${App._an.days}${App._an.platform?'&platform='+App._an.platform:''}`); }
  catch(e){ $('#anBody').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const s = d.sum, er = s.views ? (100*(s.likes+s.comments+s.shares)/s.views).toFixed(2) : '0';
  const body = $('#anBody');
  if(!d.post_count){ body.innerHTML = `<div class="empty-state">${ic('analytics',34)}<h3>No published posts in this period</h3>
      <p class="sub">Connect your accounts in Setup and publish from the Calendar. Views, likes, comments and shares appear here.</p></div>`; return; }
  body.innerHTML = `
    ${d.simulated_count?`<div class="note warn-note">${ic('info',14)} ${d.simulated_count} of ${d.post_count} posts came from an earlier demo version, so their numbers aren't real.</div>`:''}
    <div class="kpis">
      ${kpi('Posts', fmtN(s.posts), 'send')}${kpi('Views', fmtK(s.views), 'eye')}${kpi('Likes', fmtK(s.likes), 'heart')}
      ${kpi('Comments', fmtK(s.comments), 'message')}${kpi('Shares', fmtK(s.shares), 'share')}${kpi('Engagement rate', er+'%', 'trending')}
    </div>
    <div class="viz-grid2">
      <div class="card glass viz-card"><h4>Views by publish date</h4><div class="viz" id="vzViews"></div></div>
      <div class="card glass viz-card"><h4>Engagements by publish date <span class="muted">(likes + comments + shares)</span></h4><div class="viz" id="vzEng"></div></div>
    </div>
    <div class="card glass viz-card"><h4>Platform comparison
        <span class="seg sm" id="anMetric" style="margin-left:auto">${[['views','Views'],['engagement','Engagements'],['engagement_rate','Engagement rate'],['posts','Posts']].map(([k,l])=>
          `<button data-k="${k}" class="${App._an.metric===k?'on':''}">${l}</button>`).join('')}</span></h4>
      <div class="viz" id="vzPlat"></div>
      <details class="tbl-toggle"><summary>${ic('list',13)} Show as table</summary>
        <table class="rep-table"><thead><tr><th>Platform</th><th>Posts</th><th>Views</th><th>Likes</th><th>Comments</th><th>Shares</th><th>Eng. rate</th></tr></thead>
        <tbody>${d.totals.map(t=>`<tr><td>${pi(t.platform,14)} ${esc(t.label)}${t.simulated?` <span class="tc-sim">${t.simulated} sim</span>`:''}</td><td>${t.posts}</td><td>${fmtN(t.views)}</td><td>${fmtN(t.likes)}</td><td>${fmtN(t.comments)}</td><td>${fmtN(t.shares)}</td><td>${t.engagement_rate}%</td></tr>`).join('')}</tbody></table></details>
    </div>
    <div class="viz-grid2">
      <div class="card glass viz-card"><h4>${ic('trending',15)} Top posts</h4>
        <div class="top-list">${d.top.map((t,i)=>`<div class="top-row"><span class="rank">${i+1}</span>
          <div class="tl-main"><b>${esc(t.title||'Untitled')}</b>${t.simulated?' <span class="tc-sim">sim</span>':''}
            <div class="muted">${Object.keys(t.platforms).map(p=>pi(p,13)).join(' ')} · ${fmtN(t.views)} views · ${fmtN(t.engagement)} engagements</div></div></div>`).join('')}</div></div>
      <div class="card glass viz-card"><h4>${ic('layers',15)} Same post, different platforms</h4>
        ${d.compare.length?`<div class="rep-table-wrap"><table class="rep-table cmp"><thead><tr><th>Post</th>${PLAT_ORDER.filter(p=>d.compare.some(c=>c.platforms[p])).map(p=>`<th>${pi(p,14)}</th>`).join('')}</tr></thead>
          <tbody>${d.compare.map(cmp=>`<tr><td class="rep-name">${esc(cmp.title||'Untitled')}</td>${PLAT_ORDER.filter(p=>d.compare.some(c=>c.platforms[p])).map(p=>{
            const v=cmp.platforms[p]; if(!v) return '<td class="muted">—</td>';
            return `<td class="${cmp.best===p?'best':''}">${fmtK(v.views)} <span class="muted">views</span><br>${fmtK(v.likes+v.comments+v.shares)} <span class="muted">eng.</span>${cmp.best===p?`<div class="best-tag">${ic('check',11)} Best</div>`:''}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div>`
          :'<div class="empty">Publish the same post to 2+ platforms to compare where it performs best.</div>'}</div>
    </div>`;
  const lab = s=>{ const [y,m,dd]=s.split('-'); return `${Number(dd)} ${MONTHS[Number(m)-1].slice(0,3)}`; };
  vbarChart($('#vzViews'), d.series.map(r=>({label:lab(r.date), value:r.views, tip:`${lab(r.date)}<br><b>${fmtN(r.views)}</b> views · ${r.posts} post(s)`})), {title:'Views by day'});
  vbarChart($('#vzEng'), d.series.map(r=>({label:lab(r.date), value:r.engagement, tip:`${lab(r.date)}<br><b>${fmtN(r.engagement)}</b> engagements`})), {title:'Engagements by day'});
  const drawPlat = ()=>{
    const k = App._an.metric;
    const rows = d.totals.map(t=>({label:t.label, icon:pi(t.platform,15), value: k==='engagement'?t.engagement:t[k],
      display: k==='engagement_rate' ? t.engagement_rate+'%' : fmtN(k==='engagement'?t.engagement:t[k]),
      tip:`${esc(t.label)}<br>${fmtN(t.views)} views · ${fmtN(t.engagement)} engagements · ${t.engagement_rate}% rate · ${t.posts} post(s)`}))
      .sort((a,b)=>b.value-a.value);
    hbarChart($('#vzPlat'), rows, {});
  };
  drawPlat();
  body.querySelectorAll('#anMetric button').forEach(b=>b.onclick=()=>{ App._an.metric=b.dataset.k;
    body.querySelectorAll('#anMetric button').forEach(x=>x.classList.toggle('on',x===b)); drawPlat(); });
}
function kpi(label, value, icon){ return `<div class="kpi"><div class="kpi-ic">${ic(icon,16)}</div><div class="kpi-n">${value}</div><div class="kpi-l">${label}</div></div>`; }
window.renderAnalytics = renderAnalytics;

/* ============================================================ INBOX */
async function renderInbox(){
  const c = $('#pageContent'); if(!c) return;
  App._ib = App._ib || {status:'new', platform:'', sentiment:''};
  const f = App._ib;
  c.innerHTML = `<div class="page-head"><h2>Inbox</h2><div class="spacer"></div>
      <div class="seg" id="ibStatus">${[['new','New'],['replied','Replied'],['done','Done'],['','All']].map(([k,l])=>`<button data-s="${k}" class="${f.status===k?'on':''}">${l}</button>`).join('')}</div>
      <select class="f sel-sm" id="ibPlat"><option value="">All platforms</option>${PLAT_ORDER.map(p=>`<option value="${p}" ${f.platform===p?'selected':''}>${platLabel(p)}</option>`).join('')}</select>
      <select class="f sel-sm" id="ibSent"><option value="">Any sentiment</option>${['negative','neutral','positive'].map(s=>`<option ${f.sentiment===s?'selected':''}>${s}</option>`).join('')}</select>
      <button class="btn ghost sm" id="ibSync">${ic('refresh',14)} Sync</button>
</div>
    <p class="sub" style="margin:-6px 0 12px">Comments from every connected platform in one place. Reply here and the reply is posted on the platform
      (Instagram, Facebook, YouTube, X, Threads, LinkedIn). Negative comments trigger an alert.</p>
    <div id="ibBody"><div class="loading">Loading…</div></div>`;
  c.querySelectorAll('#ibStatus button').forEach(b=>b.onclick=()=>{ f.status=b.dataset.s; renderInbox(); });
  $('#ibPlat').onchange = e=>{ f.platform=e.target.value; renderInbox(); };
  $('#ibSent').onchange = e=>{ f.sentiment=e.target.value; renderInbox(); };
  $('#ibSync').onclick = async ()=>{ try{ const r=await api('/api/inbox/sync',{method:'POST'}); toast(`${r.new} new comment(s)`,'good'); renderInbox(); }catch(e){ toast(e.message,'warn'); } };
  const qs = new URLSearchParams(Object.entries(f).filter(([k,v])=>v)).toString();
  let d; try{ d = await api('/api/inbox'+(qs?'?'+qs:'')); }catch(e){ $('#ibBody').innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  if(typeof loadInboxBadge==='function') loadInboxBadge();
  const body = $('#ibBody');
  if(!d.comments.length){ body.innerHTML = `<div class="empty-state">${ic('inbox',34)}<h3>Inbox zero</h3><p class="sub">No comments match these filters.</p></div>`; return; }
  const sentChip = s => s==='negative' ? `<span class="chip danger">${ic('alert',11)} Negative</span>` : s==='positive' ? `<span class="chip completed">${ic('heart',11)} Positive</span>` : `<span class="chip draft">Neutral</span>`;
  body.innerHTML = d.comments.map(cm=>`<div class="ib-item ${cm.sentiment==='negative'?'neg':''}" data-id="${cm.id}">
      <div class="ib-head">${pi(cm.platform,18)} <b>${esc(cm.author||'someone')}</b> ${sentChip(cm.sentiment)}
        <span class="muted">on “${esc(cm.post_title||'post')}” · ${fmtTime((cm.created_at||'').replace('Z','').slice(0,19))}</span>
        ${cm.permalink?`<a href="${esc(cm.permalink)}" target="_blank" rel="noopener" class="muted">${ic('external',13)}</a>`:''}</div>
      <div class="ib-text">${esc(cm.text)}</div>
      ${cm.reply_text?`<div class="ib-reply">${ic('send',12)} <b>${esc(cm.replied_by||'You')}</b>: ${esc(cm.reply_text)}</div>`:''}
      ${cm.reply_error?`<div class="pf-err">${ic('alert',12)} ${esc(cm.reply_error)}</div>`:''}
      <div class="ib-actions">
        <div class="ib-sugg" id="sg-${cm.id}"></div>
        <div class="row" style="gap:6px">
          <input class="f" id="rp-${cm.id}" placeholder="Write a reply…">
          <button class="btn sm" data-send="${cm.id}">${ic('send',13)} Reply</button>
          <button class="btn ghost sm" data-sugg="${cm.id}">${ic('sparkles',13)} Suggest</button>
          ${cm.status!=='done'?`<button class="btn ghost sm" data-done="${cm.id}">${ic('check',13)} Done</button>`:''}
          <button class="btn ghost sm" data-hide="${cm.id}" title="Hide">${ic('x',13)}</button>
        </div></div></div>`).join('');
  body.querySelectorAll('[data-sugg]').forEach(b=>b.onclick=async ()=>{
    const id=b.dataset.sugg; b.disabled=true;
    try{ const r = await api(`/api/inbox/${id}/suggest`,{method:'POST'});
      $('#sg-'+id).innerHTML = r.replies.map(t=>`<button class="sugg">${esc(t)}</button>`).join('') + `<span class="muted">${r.source==='ai'?'AI suggestions':'Templates (add an AI key for tailored replies)'}</span>`;
      $('#sg-'+id).querySelectorAll('.sugg').forEach(s=>s.onclick=()=>{ $('#rp-'+id).value = s.textContent; $('#rp-'+id).focus(); });
    }catch(e){ toast(e.message,'warn'); }
    b.disabled=false;
  });
  body.querySelectorAll('[data-send]').forEach(b=>b.onclick=async ()=>{
    const id=b.dataset.send, text=$('#rp-'+id).value.trim(); if(!text) return;
    b.disabled=true;
    try{ const r = await api(`/api/inbox/${id}/reply`,{method:'POST', body:{text}});
      toast(r.simulated?'Reply saved (this post was not published to a platform)':'Reply posted','good',4000); renderInbox(); }
    catch(e){ toast(e.message,'warn',6000); b.disabled=false; }
  });
  body.querySelectorAll('[data-done]').forEach(b=>b.onclick=async ()=>{ await api(`/api/inbox/${b.dataset.done}/status`,{method:'POST', body:{status:'done'}}); renderInbox(); });
  body.querySelectorAll('[data-hide]').forEach(b=>b.onclick=async ()=>{ await api(`/api/inbox/${b.dataset.hide}/status`,{method:'POST', body:{status:'hidden'}}); renderInbox(); });
}
window.renderInbox = renderInbox;

/* ============================================================ QUEUE */
async function renderQueue(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="page-head"><h2>Posting queue</h2><div class="spacer"></div>
      <button class="btn ghost sm" id="qBulk">${ic('layers',14)} Bulk upload</button>
      <button class="btn sm" id="qFill">${ic('zap',14)} Fill queue with approved posts</button></div>
    <p class="sub" style="margin:-6px 0 14px">Set weekly time slots. <b>Add to queue</b> on a post (or <b>Fill queue</b>) drops it into the next free slot,
      in your time zone (${esc(userTz()||'local')}).</p>
    <div class="viz-grid2">
      <div class="card glass"><h4>${ic('clock',15)} Weekly slots</h4>
        <div class="row" style="gap:8px;margin:8px 0 12px">
          <select class="f sel-sm" id="qDow">${DOW_MON.map((d,i)=>`<option value="${i}">${d}</option>`).join('')}</select>
          <input class="f sel-sm" type="time" id="qTime" value="10:00">
          <button class="btn sm" id="qAdd">${ic('plus',14)} Add slot</button>
          <button class="btn ghost sm" id="qPreset" title="Mon/Wed/Fri 10:00 and Tue/Thu 18:00">Use a starter schedule</button>
        </div>
        <div id="qSlots" class="slot-week"><div class="loading">Loading…</div></div></div>
      <div class="card glass"><h4>${ic('target',15)} Best times to post</h4><div id="qBest"><div class="loading">Loading…</div></div></div>
    </div>
    <div class="card glass"><h4>${ic('list',15)} Upcoming</h4><div id="qUp"><div class="loading">Loading…</div></div></div>`;
  $('#qBulk').onclick = ()=>openBulkUpload();
  const tzq = {tz:userTz(), offset:tzOffset()};
  $('#qFill').onclick = async ()=>{ try{ const r=await api('/api/queue/fill',{method:'POST', body:tzq});
      toast(r.placed.length ? `Queued ${r.placed.length} post(s)${r.remaining?` — ${r.remaining} didn't fit, add more slots`:''}` : 'No approved, unscheduled posts to queue','good',5000); renderQueue(); }
    catch(e){ toast(e.message,'warn'); } };
  const addSlot = (dow,time)=>api('/api/queue/slots',{method:'POST', body:{dow, time}});
  $('#qAdd').onclick = async ()=>{ try{ await addSlot(Number($('#qDow').value), $('#qTime').value); renderQueue(); }catch(e){ toast(e.message,'warn'); } };
  $('#qPreset').onclick = async ()=>{ try{ for(const [d,t] of [[0,'10:00'],[2,'10:00'],[4,'10:00'],[1,'18:00'],[3,'18:00']]) await addSlot(d,t); renderQueue(); }catch(e){ toast(e.message,'warn'); } };
  // slots
  try{
    const s = (await api('/api/queue/slots')).slots;
    $('#qSlots').innerHTML = DOW_MON.map((d,i)=>`<div class="sw-day"><div class="sw-h">${d}</div>${s.filter(x=>x.dow===i).map(x=>
      `<span class="slot">${esc(x.time)}<button data-del="${x.id}" title="Remove">${ic('x',11)}</button></span>`).join('') || '<span class="muted">—</span>'}</div>`).join('');
    $('#qSlots').querySelectorAll('[data-del]').forEach(b=>b.onclick=async ()=>{ await api('/api/queue/slots/'+b.dataset.del,{method:'DELETE'}); renderQueue(); });
  }catch(e){ $('#qSlots').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
  // best times
  try{
    const bt = (await api(`/api/schedule/best-times?tz=${encodeURIComponent(userTz())}&offset=${tzOffset()}`)).best;
    $('#qBest').innerHTML = `<table class="rep-table"><thead><tr><th>Platform</th><th>Suggested slots</th><th>Based on</th></tr></thead><tbody>${PLAT_ORDER.map(p=>
      `<tr><td>${pi(p,14)} ${platLabel(p)}</td><td>${(bt[p]||[]).map(x=>`<span class="bt-chip static">${DOW_MON[x.dow]} ${String(x.hour).padStart(2,'0')}:00</span>`).join(' ')}</td>
       <td class="muted">${(bt[p]||[{}])[0].source||''}</td></tr>`).join('')}</tbody></table>
      <div class="hint">Suggestions switch to your own engagement data once a platform has 5+ real published posts.</div>`;
  }catch(e){ $('#qBest').innerHTML=''; }
  // upcoming
  try{
    const cal = await api('/api/calendar');
    const now = new Date();
    const up = (cal.items||[]).filter(i=>i.state!=='published' && (localFromUtc(i.publish_at) || new Date(i.date+'T23:59')) >= now)
      .sort((a,b)=>((localFromUtc(a.publish_at)||new Date(a.date))-(localFromUtc(b.publish_at)||new Date(b.date)))).slice(0,25);
    $('#qUp').innerHTML = up.length ? `<div class="up-list">${up.map(i=>`<div class="up-row" data-open="${i.date}">
        <span class="up-when">${esc(fmtSchedule(i))}</span><b>${esc(i.title||'Untitled')}</b> ${stateBadge(i)}
        <span class="up-plats">${(i.platforms||[]).map(p=>pi(p,14)).join('')}</span></div>`).join('')}</div>`
      : '<div class="empty">Nothing scheduled yet.</div>';
    $('#qUp').querySelectorAll('[data-open]').forEach(r=>r.onclick=()=>{ App.page='calendar'; const [y,m]=r.dataset.open.split('-').map(Number);
      App.calMonth={y,m:m-1}; renderDashboard(App.readonly); setTimeout(()=>openDay(r.dataset.open), 400); });
  }catch(e){ $('#qUp').innerHTML=''; }
}
window.renderQueue = renderQueue;

/* ============================================================ TEAM & BRANDS */
async function renderTeam(){
  const c = $('#pageContent'); if(!c) return;
  const u = App.user || {};
  c.innerHTML = `<div class="panel-head"><h2>Team &amp; Brands</h2>
      <p class="sub">Manage brands (client workspaces), who may publish where, and your Sub-Users.</p></div>
    <div class="card glass"><h4>${ic('building',15)} Brands</h4>
      <p class="sub">Each brand keeps its own posts and can have its own connected accounts: switch brand in the top bar, then connect accounts in Setup.</p>
      ${u.is_subuser?'':`<div class="row" style="gap:8px;margin:10px 0"><input class="f" id="brName" placeholder="Brand / client name" style="max-width:260px">
        <input type="color" id="brColor" value="#2f7bff" title="Colour"><button class="btn sm" id="brAdd">${ic('plus',14)} Add brand</button></div>`}
      <div id="brList"><div class="loading">Loading…</div></div></div>
    ${u.is_admin?`<div class="card glass"><h4>${ic('shield',15)} Publishing permissions</h4>
      <p class="sub">Choose which platforms each person may publish to. Everyone can still draft posts.</p>
      <div id="permBody"><div class="loading">Loading…</div></div></div>`:''}
    ${u.is_primary_user?`<div class="card glass"><h4>${ic('users',15)} Sub-Users</h4>
      <div class="row" style="margin-bottom:12px"><button class="btn sm" id="suAdd">${ic('plus',14)} Create Sub-User</button></div>
      <div id="suBody"><div class="loading">Loading…</div></div></div>`:''}`;
  // brands
  const loadBrands = async ()=>{
    const d = await api('/api/brands');
    $('#brList').innerHTML = d.brands.length ? d.brands.map(b=>`<div class="br-row"><span class="br-dot" style="background:${esc(b.color||'#2f7bff')}"></span>
        <b>${esc(b.name)}</b> ${String(b.id)===String(d.active_brand_id)?'<span class="chip completed">active</span>':''}
        <span class="spacer"></span>
        <button class="btn ghost xs" data-use="${b.id}">Switch to</button>
        ${u.is_subuser?'':`<button class="btn ghost xs" data-ren="${b.id}" data-name="${esc(b.name)}">${ic('edit',12)} Rename</button>
        <button class="btn danger xs" data-bdel="${b.id}">${ic('trash',12)}</button>`}</div>`).join('')
      : '<div class="empty">No brands yet. You can work without brands; add them when you manage several clients.</div>';
    $('#brList').querySelectorAll('[data-use]').forEach(b=>b.onclick=async ()=>{ await api('/api/brands/active',{method:'POST', body:{brand_id:b.dataset.use}});
      App.user.active_brand_id=Number(b.dataset.use); toast('Switched brand','good'); renderTopbar(); renderDashboard(App.readonly); });
    $('#brList').querySelectorAll('[data-ren]').forEach(b=>b.onclick=async ()=>{ const n=prompt('Brand name', b.dataset.name); if(!n) return;
      await api('/api/brands/'+b.dataset.ren,{method:'PATCH', body:{name:n}}); loadBrands(); loadBrandSwitch(); });
    $('#brList').querySelectorAll('[data-bdel]').forEach(b=>b.onclick=()=>confirmBox('Delete this brand?','Its posts stay and move to "no brand".',
      async ()=>{ await api('/api/brands/'+b.dataset.bdel,{method:'DELETE'}); await refreshMe(); renderTopbar(); renderTeam(); }, 'Delete brand'));
  };
  loadBrands().catch(e=>$('#brList').innerHTML=`<div class="err">${esc(e.message)}</div>`);
  if($('#brAdd')) $('#brAdd').onclick = async ()=>{ const n=$('#brName').value.trim(); if(!n) return;
    try{ await api('/api/brands',{method:'POST', body:{name:n, color:$('#brColor').value}}); $('#brName').value=''; loadBrands(); loadBrandSwitch(); }
    catch(e){ toast(e.message,'warn'); } };
  // permissions
  if($('#permBody')){
    try{
      const d = await api('/api/team/permissions');
      $('#permBody').innerHTML = d.users.length ? `<div class="rep-table-wrap"><table class="rep-table perm"><thead><tr><th>User</th><th>All</th>${d.platforms.map(p=>`<th title="${esc(p.label)}">${pi(p.key,15)}</th>`).join('')}<th></th></tr></thead>
        <tbody>${d.users.map(x=>{ const all = x.platforms===null; return `<tr data-uid="${x.id}"><td>${esc(x.name_with_role)}</td>
          <td><input type="checkbox" class="pm-all" ${all?'checked':''}></td>
          ${d.platforms.map(p=>`<td><input type="checkbox" class="pm-p" value="${p.key}" ${all||(x.platforms||[]).includes(p.key)?'checked':''} ${all?'disabled':''}></td>`).join('')}
          <td><button class="btn sm pm-save">${ic('save',13)} Save</button></td></tr>`; }).join('')}</tbody></table></div>`
        : '<div class="empty">No other users to manage yet — create Sub-Users below.</div>';
      $('#permBody').querySelectorAll('tr[data-uid]').forEach(tr=>{
        const allCb = tr.querySelector('.pm-all');
        allCb.onchange = ()=> tr.querySelectorAll('.pm-p').forEach(x=>{ x.disabled = allCb.checked; if(allCb.checked) x.checked=true; });
        tr.querySelector('.pm-save').onclick = async ()=>{
          const plats = allCb.checked ? null : [...tr.querySelectorAll('.pm-p:checked')].map(x=>x.value);
          try{ await api('/api/team/permissions',{method:'POST', body:{user_id:Number(tr.dataset.uid), platforms:plats}}); toast('Permissions saved','good'); }
          catch(e){ toast(e.message,'warn'); }
        };
      });
    }catch(e){ $('#permBody').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
  }
  if($('#suBody') && typeof loadSubusers==='function'){ $('#suAdd').onclick = ()=>openSubuserModal(null); loadSubusers(); }
}
window.renderTeam = renderTeam;

/* ============================================================ ACTIVITY LOG */
const ACTION_LABEL = {
  uploaded:'Uploaded', created:'Created', edited:'Edited', submitted:'Sent for review', approved:'Approved',
  scheduled:'Scheduled', queued:'Queued', queue_fill:'Filled queue', publish_now:'Publish now', published:'Published',
  retry:'Retried publish', deleted:'Deleted', convert:'Converted video', thumbnail:'Set cover', captions_adapted:'Adapted captions',
  review_link:'Created review link', client_approve:'Client approved', client_changes:'Client requested changes',
  connected:'Connected account', disconnected:'Disconnected account', credentials_saved:'Saved credentials',
  brand_created:'Created brand', brand_deleted:'Deleted brand', permissions_changed:'Changed permissions',
  replied:'Replied to comment', bulk_upload:'Bulk upload', report_emailed:'Emailed report', queue_slot_added:'Added queue slot',
};
async function renderActivity(){
  const c = $('#pageContent'); if(!c) return;
  App._act = App._act || {q:'', action:''};
  c.innerHTML = `<div class="page-head"><h2>Activity log</h2><div class="spacer"></div>
      <input class="f sel-sm" id="acQ" placeholder="Search user or detail…" value="${esc(App._act.q)}">
      <select class="f sel-sm" id="acA"><option value="">All actions</option>${Object.entries(ACTION_LABEL).map(([k,l])=>`<option value="${k}" ${App._act.action===k?'selected':''}>${l}</option>`).join('')}</select>
      <button class="btn ghost sm" id="acCsv">${ic('download',14)} CSV</button></div>
    <div id="acBody"><div class="loading">Loading…</div></div>`;
  let t; $('#acQ').oninput = e=>{ clearTimeout(t); t=setTimeout(()=>{ App._act.q=e.target.value; loadActivity(); }, 300); };
  $('#acA').onchange = e=>{ App._act.action=e.target.value; loadActivity(); };
  $('#acCsv').onclick = ()=>{
    const rows=[['Time','User','Action','Detail']].concat((App._actRows||[]).map(a=>[a.created_at, a.username, ACTION_LABEL[a.action]||a.action, a.detail]));
    const csv=rows.map(r=>r.map(x=>`"${String(x||'').replace(/"/g,'""')}"`).join(',')).join('\n');
    const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'})); a.download='activity-log.csv'; a.click();
  };
  loadActivity();
}
async function loadActivity(){
  const qs = new URLSearchParams(Object.entries(App._act).filter(([k,v])=>v)).toString();
  let d; try{ d = await api('/api/activity'+(qs?'?'+qs:'')); }catch(e){ $('#acBody').innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  App._actRows = d.activity;
  $('#acBody').innerHTML = d.activity.length ? `<div class="rep-table-wrap"><table class="rep-table"><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead>
    <tbody>${d.activity.map(a=>`<tr><td class="muted" style="white-space:nowrap">${fmtTime(a.created_at)}</td><td>${esc(a.username||'system')}</td>
      <td><span class="act-chip act-${esc(a.action)}">${esc(ACTION_LABEL[a.action]||a.action)}</span></td>
      <td>${esc(a.detail||'')}${a.target_type==='item'&&a.target_id?` <a href="#" data-item="${a.target_id}">${ic('external',12)}</a>`:''}</td></tr>`).join('')}</tbody></table></div>`
    : '<div class="empty">No activity yet.</div>';
  $('#acBody').querySelectorAll('[data-item]').forEach(a=>a.onclick=e=>{ e.preventDefault(); openLinkTarget('calendar:'+a.dataset.item); });
}
window.renderActivity = renderActivity;
