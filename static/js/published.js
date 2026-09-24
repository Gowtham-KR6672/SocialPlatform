/* ============================================================
   Published panel
   Every published post with its per-platform links, live stats
   (views / likes / comments / shares) and the latest comments.
   ============================================================ */
async function renderPublished(){
  const c = $('#pageContent');
  c.innerHTML = `<div class="page-head"><h2>Published</h2><div class="spacer"></div>
      <button class="btn ghost sm" id="pubRefresh">${ic('refresh',14)} Refresh stats</button>
      <div class="tiles" id="pubTiles" style="margin:0"></div></div>
    <div id="pubList"></div>`;
  $('#pubRefresh').onclick = async ()=>{
    const b=$('#pubRefresh'); b.disabled=true;
    try{ const r = await api('/api/analytics/refresh',{method:'POST'}); toast(`Updated ${r.refreshed} platform post(s)`,'good'); await loadPublished(); }
    catch(e){ toast(e.message,'warn'); }
    b.disabled=false;
  };
  await loadPublished();
}

async function loadPublished(){
  let data;
  try{ data = await api('/api/published'); }
  catch(e){ $('#pubList').innerHTML = `<div class="empty">Log in to view published posts.</div>`; return; }
  const items = data.published;
  const b=$('#navPubCount'); if(b) b.textContent = items.length;
  const sum = k => items.reduce((s,i)=>s+(i.targets||[]).reduce((a,t)=>a+(t[k]||0),0),0);
  $('#pubTiles').innerHTML = `
    <div class="tile completed"><div class="n">${items.length}</div><div class="l">Published</div></div>
    <div class="tile"><div class="n">${fmtK(sum('views'))}</div><div class="l">Views</div></div>
    <div class="tile"><div class="n">${fmtK(sum('likes'))}</div><div class="l">Likes</div></div>
    <div class="tile new"><div class="n">${fmtK(sum('comments'))}</div><div class="l">Comments</div></div>`;

  const list = $('#pubList');
  if(!items.length){ list.innerHTML = `<div class="empty-state">${ic('send',34)}<h3>Nothing published yet</h3><p class="sub">Approve &amp; publish a post from the Calendar.</p></div>`; return; }
  list.innerHTML='';
  items.forEach(it=> list.appendChild(pubCard(it)));

  if(App.focusPublished){
    const card = list.querySelector(`[data-pub="${App.focusPublished}"]`);
    if(card){ card.scrollIntoView({behavior:'smooth', block:'center'});
      card.classList.add('focus-flash'); setTimeout(()=>card.classList.remove('focus-flash'), 2200); }
    App.focusPublished = null;
  }
}

function pubCard(it){
  const targets = (it.targets||[]);
  const rows = targets.map(t=>`<div class="pt-row tc-${t.status}">
      <span class="pt-plat">${pi(t.platform,16)} ${esc(platLabel(t.platform))}</span>
      <span class="pt-stat">${t.status==='published'
        ? `${ic('eye',12)} ${fmtK(t.views)} &nbsp;${ic('heart',12)} ${fmtK(t.likes)} &nbsp;${ic('message',12)} ${fmtK(t.comments)} &nbsp;${ic('share',12)} ${fmtK(t.shares)}`
        : `<span class="pf-err">${ic('alert',12)} ${esc(t.status)}${t.error?': '+esc(t.error):''}</span>`}</span>
      <span class="pt-act">${t.simulated?'<span class="tc-sim" title="Simulated — connect a live account">sim</span>':''}
        ${t.permalink?`<a class="btn ghost xs" href="${esc(t.permalink)}" target="_blank" rel="noopener">${ic('external',12)} Open</a>`:''}
        ${t.status==='failed'?`<button class="btn ghost xs" data-retry="${t.id}">${ic('refresh',12)} Retry</button>`:''}</span>
    </div>`).join('') || (it.ig_permalink ? `<div class="pt-row"><span class="pt-plat">${pi('instagram',16)} Instagram</span>
      <a class="btn ghost xs" href="${esc(it.ig_permalink)}" target="_blank">${ic('external',12)} Open</a></div>` : '<div class="muted">No per-platform data (published before multi-platform support).</div>');
  const comments = (it.inbox||[]).slice(0,8).map(cm=>`<div class="cmt"><div class="cmt-top">${pi(cm.platform,13)} <b>${esc(cm.author)}</b>
      ${cm.sentiment==='negative'?`<span class="chip danger">${ic('alert',10)}</span>`:''}</div><div class="cmt-text">${esc(cm.text)}</div></div>`).join('')
    || (it.comments||[]).map(cm=>`<div class="cmt"><div class="cmt-top"><b>${esc(cm.commenter)}</b></div><div class="cmt-text">${esc(cm.text)}</div></div>`).join('')
    || `<div class="cmt muted-i" style="color:var(--muted)">No comments yet.</div>`;
  const files = it.media || (it.filename?[it.filename]:[]);
  const card = el(`<div class="pubcard" data-pub="${it.id}">
     <div class="pub-main">
       <div class="t">${esc(it.title)} <span class="chip ${it.publish_state==='partial'?'gold':'completed'}">${it.publish_state==='partial'?'Partly published':'Published'}</span></div>
       <div class="cap">${esc(it.caption||'—')}</div>
       <div class="tags">${esc(it.hashtags||'')}</div>
       <div class="meta">Published ${esc(it.published_date||it.date||'—')} · by ${esc(it.owner||'—')}</div>
       <div class="pt-list">${rows}</div>
       <div class="row" style="margin-top:8px">${files.length?`<button class="btn ghost sm" data-pv="1">${ic('eye',14)} Preview</button>`:''}
         <button class="btn ghost sm" data-inbox="1">${ic('inbox',14)} Open inbox</button></div>
     </div>
     <div class="pub-side">
       <div class="cmt-head">Latest comments</div>
       <div class="cmt-list">${comments}</div>
     </div>
   </div>`);
  const pv = card.querySelector('[data-pv]'); if(pv) pv.onclick = ()=>previewItem(it);
  card.querySelector('[data-inbox]').onclick = ()=>{ App.page='inbox'; renderDashboard(App.readonly); };
  card.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async ()=>{
    try{ await api('/api/targets/'+b.dataset.retry+'/retry',{method:'POST'}); toast('Retrying…','good'); setTimeout(loadPublished, 2500); }
    catch(e){ toast(e.message,'warn'); }
  });
  return card;
}
window.renderPublished = renderPublished;
