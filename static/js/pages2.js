/* ============================================================
   V32 pages: Content Library · Link in bio & tracked links ·
   account analytics · direct messages · brand kit
   ============================================================ */

/* ============================================================ CONTENT LIBRARY */
async function renderLibrary(){
  const c = $('#pageContent'); if(!c) return;
  App._lib = App._lib || 'media';
  c.innerHTML = `<div class="page-head"><h2>Content library</h2><div class="spacer"></div>
      <div class="seg" id="libTabs">${[['media','Media'],['caption','Caption templates'],['hashtags','Hashtag groups']].map(([k,l])=>
        `<button data-k="${k}" class="${App._lib===k?'on':''}">${l}</button>`).join('')}</div></div>
    <p class="sub" style="margin:-6px 0 14px">Save media, caption templates and hashtag groups once and reuse them in any post.
      In the post editor, use <b>Insert template</b> and <b>Insert hashtags</b>.</p>
    <div id="libBody"><div class="loading">Loading…</div></div>`;
  c.querySelectorAll('#libTabs button').forEach(b=>b.onclick=()=>{ App._lib=b.dataset.k; renderLibrary(); });
  const kind = App._lib, body = $('#libBody');
  let d; try{ d = await api('/api/library?kind='+kind); }catch(e){ body.innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  if(kind==='media'){
    body.innerHTML = `<div class="card glass"><div class="row" style="gap:8px;align-items:center">
        <input class="f sel-sm" id="lbTitle" placeholder="Name (optional)">
        <label class="btn sm" style="cursor:pointer">${ic('upload',14)} Upload media<input type="file" id="lbFile" accept="video/*,image/*" style="display:none"></label></div></div>
      <div class="lib-grid">${d.items.map(i=>`<div class="lib-card">
          <div class="lib-thumb">${isImg(i.filename)?`<img src="/uploads/${encodeURIComponent(i.filename)}" alt="">`:`<video src="/uploads/${encodeURIComponent(i.filename)}#t=0.5" muted preload="metadata"></video>`}</div>
          <div class="lib-t">${esc(i.title)}</div>
          <div class="row" style="gap:6px"><button class="btn sm" data-use="${i.id}">${ic('plus',13)} New post</button>
            <button class="icon-btn sm" data-del="${i.id}" title="Delete">${ic('trash',13)}</button></div></div>`).join('')
        || '<div class="empty">No media yet — upload videos or images you reuse often (intros, logos, product shots).</div>'}</div>`;
    $('#lbFile').onchange = async (e)=>{
      const f=e.target.files[0]; if(!f) return;
      const fd=new FormData(); fd.append('file', f); fd.append('title', $('#lbTitle').value || f.name);
      try{ await api('/api/library',{method:'POST', body:fd}); toast('Added to library','good'); renderLibrary(); }catch(err){ toast(err.message,'warn'); }
    };
    body.querySelectorAll('[data-use]').forEach(b=>b.onclick=()=>{
      const picker = platformPicker(defaultPlatforms());
      const m = el(`<div class="modal" style="max-width:480px"><div class="modal-head"><h3>${ic('plus',18)} New post from library</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
        <div class="modal-body"><label class="f">Date</label><input class="f" type="date" id="luDate" value="${esc(App._today||new Date().toISOString().slice(0,10))}">
        <label class="f">Publish to</label><div id="luPlats"></div><div class="err" id="luErr"></div></div>
        <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="luGo">Create draft</button></div></div>`);
      openModal(m); $('#luPlats',m).appendChild(picker.el);
      $('#luGo',m).onclick = async ()=>{ try{ const r = await api(`/api/library/${b.dataset.use}/use`,{method:'POST', body:{date:$('#luDate',m).value, platforms:picker.get()}});
          closeModal(); toast('Draft created in the Calendar','good'); App.page='calendar'; const [y,mo]=r.date.split('-').map(Number); App.calMonth={y,m:mo-1};
          renderDashboard(App.readonly); setTimeout(()=>openDay(r.date), 500); }catch(e){ $('#luErr',m).textContent=e.message; } };
    });
  }else{
    const isTags = kind==='hashtags';
    body.innerHTML = `<div class="card glass"><h4>${ic('plus',15)} New ${isTags?'hashtag group':'caption template'}</h4>
        <input class="f" id="lbT" placeholder="${isTags?'e.g. Fitness, Launch week':'e.g. Product launch'}" style="margin-bottom:8px">
        <textarea class="f" id="lbB" style="min-height:${isTags?60:100}px" placeholder="${isTags?'#fitness #gym #workout':'Write the template. Use {link} where a tracked link should go.'}"></textarea>
        <button class="btn sm" id="lbSave" style="margin-top:8px">${ic('save',14)} Save</button></div>
      <div class="lib-list">${d.items.map(i=>`<div class="lib-row"><div><b>${esc(i.title)}</b><div class="${isTags?'tags':'lib-body'}">${esc(i.body)}</div></div>
        <div class="row" style="gap:6px"><button class="icon-btn sm" data-copy="${esc(i.body)}" title="Copy">${ic('copy',13)}</button>
        <button class="icon-btn sm" data-del="${i.id}" title="Delete">${ic('trash',13)}</button></div></div>`).join('')
        || `<div class="empty">No ${isTags?'hashtag groups':'templates'} yet.</div>`}</div>`;
    $('#lbSave').onclick = async ()=>{ try{ await api('/api/library',{method:'POST', body:{kind, title:$('#lbT').value, body:$('#lbB').value}}); toast('Saved','good'); renderLibrary(); }catch(e){ toast(e.message,'warn'); } };
    body.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{ try{ navigator.clipboard.writeText(b.dataset.copy); toast('Copied','good'); }catch(e){} });
  }
  body.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>confirmBox('Delete this library item?','Posts already using it are not affected.',
    async ()=>{ await api('/api/library/'+b.dataset.del,{method:'DELETE'}); renderLibrary(); }, 'Delete'));
}
window.renderLibrary = renderLibrary;

/* Pickers used by the post editor */
async function pickLibrary(kind, onPick, anchor){
  let d; try{ d = await api('/api/library?kind='+kind); }catch(e){ toast(e.message,'warn'); return; }
  if(!d.items.length){ toast(kind==='hashtags'?'No hashtag groups yet — add them in the Library':'No templates yet — add them in the Library','warn',4000); return; }
  const pop = el(`<div class="lib-pop">${d.items.map(i=>`<button data-id="${i.id}"><b>${esc(i.title)}</b><span>${esc(i.body.slice(0,90))}</span></button>`).join('')}</div>`);
  document.querySelectorAll('.lib-pop').forEach(x=>x.remove());
  const host = (anchor && anchor.closest('.lib-anchor')) || document.querySelector('#modal-root .modal'); if(!host) return;
  host.appendChild(pop);
  pop.querySelectorAll('button').forEach(b=>b.onclick=()=>{ onPick(d.items.find(x=>String(x.id)===b.dataset.id)); pop.remove(); });
  setTimeout(()=>document.addEventListener('mousedown', function h(e){ if(!pop.contains(e.target)){ pop.remove(); document.removeEventListener('mousedown',h); } }), 0);
}
window.pickLibrary = pickLibrary;

/* ============================================================ LINK IN BIO + TRACKED LINKS */
async function renderBio(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="page-head"><h2>Link in bio &amp; tracked links</h2></div>
    <div class="viz-grid2">
      <div class="card glass" id="bioEditor"><div class="loading">Loading…</div></div>
      <div class="card glass"><h4>${ic('analytics',15)} Website clicks (30 days)</h4><div class="viz" id="clkChart"></div>
        <div id="clkPlat" class="clk-plat"></div></div>
    </div>
    <div class="card glass"><h4>${ic('link',15)} Tracked links (UTM)</h4>
      <p class="sub">Add a website link to a post in the post editor and each platform automatically gets its own short link
        with <code>utm_source</code>, <code>utm_medium</code>, <code>utm_campaign</code>, so your analytics show which post and platform sent the visit.
        You can also create a link here for use anywhere.</p>
      <div class="pe-grid"><input class="f" id="lkUrl" placeholder="https://yourshop.com/offer"><input class="f" id="lkLabel" placeholder="Label">
        <input class="f" id="lkSrc" placeholder="utm_source (e.g. newsletter)"><input class="f" id="lkCamp" placeholder="utm_campaign"></div>
      <button class="btn sm" id="lkAdd" style="margin-top:8px">${ic('plus',14)} Create tracked link</button>
      <div id="lkList" style="margin-top:12px"></div></div>`;
  let page = null;
  try{ page = (await api('/api/bio')).page; }catch(e){}
  const links = (page && page.links) || [{label:'',url:''}];
  const ed = $('#bioEditor');
  const drawEditor = ()=>{
    ed.innerHTML = `<h4>${ic('globe',15)} Your link-in-bio page</h4>
      ${page?`<div class="pf-redirect big"><code>${esc(page.url)}</code><button class="icon-btn sm" data-copy="${esc(page.url)}">${ic('copy',14)}</button>
        <a class="icon-btn sm" href="${esc(page.url)}" target="_blank" rel="noopener" title="Open">${ic('external',14)}</a></div>
        <div class="hint">Put this address in your Instagram / TikTok bio.</div>`:'<div class="hint">Save to create your page.</div>'}
      <div class="pe-grid"><div><label class="f">Page address</label><input class="f" id="bSlug" value="${esc(page?page.slug:'')}" placeholder="yourbrand"></div>
        <div><label class="f">Title</label><input class="f" id="bTitle" value="${esc(page?page.title:'')}" placeholder="Your brand"></div>
        <div><label class="f">Accent colour</label><input type="color" class="f" id="bTheme" value="${esc(page?page.theme:'#2f7bff')}"></div></div>
      <label class="f">Short bio</label><textarea class="f" id="bBio" style="min-height:60px">${esc(page?page.bio:'')}</textarea>
      <label class="f">Links</label><div id="bLinks">${links.map((l,i)=>`<div class="row bio-link" style="gap:6px;margin-bottom:6px">
          <input class="f" data-lab="${i}" value="${esc(l.label||'')}" placeholder="Button text"><input class="f" data-url="${i}" value="${esc(l.url||'')}" placeholder="https://…">
          <button class="icon-btn sm" data-rm="${i}" title="Remove">${ic('x',13)}</button></div>`).join('')}</div>
      <button class="btn ghost sm" id="bAdd">${ic('plus',13)} Add link</button>
      <label class="cred-toggle" style="margin-top:8px"><input type="checkbox" id="bPosts" ${(!page||page.show_posts)?'checked':''}> <span>Show my latest posts as a grid</span></label>
      <div class="row" style="gap:8px;margin-top:10px"><button class="btn sm" id="bSave">${ic('save',14)} Save page</button>
        ${page?`<label class="btn ghost sm" style="cursor:pointer">${ic('image',14)} Profile image<input type="file" id="bAvatar" accept="image/*" style="display:none"></label>`:''}</div>
      <div class="err" id="bErr"></div>`;
    const read = ()=>{ ed.querySelectorAll('[data-lab]').forEach(inp=>{ links[inp.dataset.lab].label = inp.value; });
                       ed.querySelectorAll('[data-url]').forEach(inp=>{ links[inp.dataset.url].url = inp.value; }); };
    $('#bAdd').onclick = ()=>{ read(); links.push({label:'',url:''}); drawEditor(); };
    ed.querySelectorAll('[data-rm]').forEach(b=>b.onclick=()=>{ read(); links.splice(Number(b.dataset.rm),1); if(!links.length) links.push({label:'',url:''}); drawEditor(); });
    ed.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{ try{ navigator.clipboard.writeText(b.dataset.copy); toast('Copied','good'); }catch(e){} });
    $('#bSave').onclick = async ()=>{ read();
      try{ page = (await api('/api/bio',{method:'POST', body:{slug:$('#bSlug').value, title:$('#bTitle').value, bio:$('#bBio').value,
            theme:$('#bTheme').value, show_posts:$('#bPosts').checked, links:links.filter(l=>l.url)}})).page;
        toast('Page saved','good'); links.splice(0, links.length, ...(page.links.length?page.links:[{label:'',url:''}])); drawEditor(); loadClicks(); }
      catch(e){ $('#bErr').textContent = e.message; } };
    if($('#bAvatar')) $('#bAvatar').onchange = async (e)=>{ const f=e.target.files[0]; if(!f) return; const fd=new FormData(); fd.append('file', f);
      try{ await api('/api/bio/avatar',{method:'POST', body:fd}); toast('Image updated','good'); }catch(err){ toast(err.message,'warn'); } };
  };
  drawEditor();
  const loadLinks = async ()=>{
    let d; try{ d = await api('/api/links'); }catch(e){ return; }
    $('#lkList').innerHTML = d.links.length ? `<div class="rep-table-wrap"><table class="rep-table"><thead><tr><th>Link</th><th>Goes to</th><th>Source</th><th>Clicks</th><th></th></tr></thead>
      <tbody>${d.links.map(l=>`<tr><td><code>${esc(l.short_url)}</code> <button class="icon-btn sm" data-copy="${esc(l.short_url)}">${ic('copy',12)}</button><div class="muted">${esc(l.label||'')}</div></td>
        <td class="lk-url">${esc(l.url)}</td><td>${l.platform&&l.platform!=='bio'?pi(l.platform,14)+' ':''}${esc(l.utm_source||'')}${l.utm_campaign?' · '+esc(l.utm_campaign):''}</td>
        <td><b>${fmtN(l.clicks)}</b></td><td><button class="icon-btn sm" data-dl="${l.id}" title="Delete">${ic('trash',12)}</button></td></tr>`).join('')}</tbody></table></div>`
      : '<div class="empty">No tracked links yet.</div>';
    $('#lkList').querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{ try{ navigator.clipboard.writeText(b.dataset.copy); toast('Copied','good'); }catch(e){} });
    $('#lkList').querySelectorAll('[data-dl]').forEach(b=>b.onclick=async ()=>{ await api('/api/links/'+b.dataset.dl,{method:'DELETE'}); loadLinks(); });
  };
  const loadClicks = async ()=>{
    let d; try{ d = await api('/api/links/stats?days=30'); }catch(e){ return; }
    const lab = s=>{ const [y,m,dd]=s.split('-'); return `${Number(dd)} ${MONTHS[Number(m)-1].slice(0,3)}`; };
    vbarChart($('#clkChart'), d.series.map(r=>({label:lab(r.date), value:r.clicks, tip:`${lab(r.date)}<br><b>${fmtN(r.clicks)}</b> clicks`})), {title:'Clicks by day', height:160});
    const bp = Object.entries(d.by_platform).sort((a,b)=>b[1]-a[1]);
    $('#clkPlat').innerHTML = `<div class="muted" style="margin:6px 0">${fmtN(d.total)} clicks in 30 days</div>` +
      (bp.length ? bp.map(([p,n])=>`<span class="bt-chip static">${PLAT[p]?pi(p,13):ic('globe',13)} ${esc(PLAT[p]?platLabel(p):p)} · ${fmtN(n)}</span>`).join(' ') : '');
  };
  $('#lkAdd').onclick = async ()=>{ try{ await api('/api/links',{method:'POST', body:{url:$('#lkUrl').value, label:$('#lkLabel').value,
      utm_source:$('#lkSrc').value, utm_medium:'referral', utm_campaign:$('#lkCamp').value}}); $('#lkUrl').value=''; toast('Link created','good'); loadLinks(); }
    catch(e){ toast(e.message,'warn'); } };
  loadLinks(); loadClicks();
}
window.renderBio = renderBio;

/* Line chart for levels such as follower counts: the y-axis fits the data range
   (not zero-based) so day-to-day growth is visible. rows: [{label, value, tip}] */
function lineChart(host, rows, opts){
  const W = Math.max(300, host.clientWidth || 600), H = opts.height || 150;
  const pad = {l:48, r:12, t:12, b:24}, iw = W-pad.l-pad.r, ih = H-pad.t-pad.b;
  const vals = rows.map(r=>r.value);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if(hi===lo){ hi += 1; lo = Math.max(0, lo-1); }
  const span = hi-lo; lo = Math.max(0, lo-span*0.15); hi = hi+span*0.15;
  const X = i => pad.l + (rows.length>1 ? iw*i/(rows.length-1) : iw/2), Y = v => pad.t + ih - ih*(v-lo)/(hi-lo);
  let g = '';
  for(let i=0;i<=3;i++){ const v = lo+(hi-lo)*i/3, y = Y(v);
    g += `<line x1="${pad.l}" x2="${W-pad.r}" y1="${y}" y2="${y}" class="viz-grid"/>${i?`<text x="${pad.l-6}" y="${y+4}" class="viz-axis" text-anchor="end">${fmtK(Math.round(v))}</text>`:''}`; }
  g += `<path d="${rows.map((r,i)=>`${i?'L':'M'}${X(i).toFixed(1)},${Y(r.value).toFixed(1)}`).join(' ')}" fill="none" stroke="${opts.color||'var(--viz-1)'}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  const every = Math.ceil(rows.length/6), step = rows.length>1 ? iw/(rows.length-1) : iw;
  rows.forEach((r,i)=>{
    g += `<circle cx="${X(i)}" cy="${Y(r.value)}" r="${rows.length<=12?3.5:0}" fill="${opts.color||'var(--viz-1)'}" stroke="var(--card)" stroke-width="2"/>`;
    g += `<rect x="${X(i)-step/2}" y="${pad.t}" width="${step}" height="${ih}" class="viz-hit" data-i="${i}"/>`;
    if(i%every===0 || i===rows.length-1) g += `<text x="${X(i)}" y="${H-6}" class="viz-axis" text-anchor="middle">${esc(r.label)}</text>`;
  });
  host.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.title||'chart')}">${g}</svg><div class="viz-tip hidden"></div>`;
  bindTips(host, rows);
}

/* ============================================================ ACCOUNT ANALYTICS (Analytics → Accounts tab) */
async function renderAccountAnalytics(host, days){
  host.innerHTML = '<div class="loading">Loading…</div>';
  let d; try{ d = await api(`/api/analytics/accounts?days=${days}`); }catch(e){ host.innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  if(!d.accounts.length){ host.innerHTML = `<div class="empty-state">${ic('users',32)}<h3>No connected accounts</h3><p class="sub">Connect accounts in Setup to track followers, reach and profile views.</p></div>`; return; }
  host.innerHTML = `<div class="row" style="margin-bottom:10px"><button class="btn ghost sm" id="accRefresh">${ic('refresh',14)} Update now</button>
      <span class="muted" style="margin-left:8px">Snapshots are taken every 6 hours; the chart fills in day by day.</span></div>
    <div class="acc-grid">${d.accounts.map((a,i)=>`<div class="card glass acc-card">
      <div class="acc-h">${pi(a.platform,20)} <b>${esc(a.account||a.label)}</b><span class="muted">${esc(a.label)}</span></div>
      <div class="acc-kpis"><div><div class="kpi-n">${fmtK(a.followers)}</div><div class="kpi-l">Followers</div></div>
        <div><div class="kpi-n ${a.growth>0?'up':(a.growth<0?'down':'')}">${a.growth>0?'+':''}${fmtK(a.growth)}</div><div class="kpi-l">Growth · ${days}d</div></div>
        <div><div class="kpi-n">${fmtK(a.reach)}</div><div class="kpi-l">Reach</div></div>
        <div><div class="kpi-n">${fmtK(a.profile_views)}</div><div class="kpi-l">Profile views</div></div></div>
      <div class="viz" id="accChart${i}"></div>
      ${a.days_tracked<2?'<div class="hint">Tracking started — growth appears after the second daily snapshot.</div>':''}</div>`).join('')}</div>`;
  d.accounts.forEach((a,i)=>{ if(a.series.length) lineChart($('#accChart'+i), a.series.map(r=>{ const [y,m,dd]=r.day.split('-');
      const l=`${Number(dd)} ${MONTHS[Number(m)-1].slice(0,3)}`; return {label:l, value:r.followers, tip:`${l}<br><b>${fmtN(r.followers)}</b> followers · ${fmtN(r.reach)} reach`}; }),
    {title:'Followers by day', height:130}); });
  $('#accRefresh').onclick = async ()=>{ const b=$('#accRefresh'); b.disabled=true;
    try{ await api('/api/analytics/accounts/refresh',{method:'POST'}); toast('Updated','good'); renderAccountAnalytics(host, days); }catch(e){ toast(e.message,'warn'); b.disabled=false; } };
}
window.renderAccountAnalytics = renderAccountAnalytics;

/* ============================================================ DIRECT MESSAGES (Inbox → Messages tab) */
async function renderDMs(host){
  host.innerHTML = '<div class="loading">Loading…</div>';
  let d; try{ d = await api('/api/dms'); }catch(e){ host.innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  if(!d.dm_accounts.length){ host.innerHTML = `<div class="empty-state">${ic('message',32)}<h3>No messaging accounts</h3>
      <p class="sub">Connect Instagram or a Facebook Page in Setup. Direct messages need the messaging permission —
      if you connected before this update, click Disconnect and Connect again to grant it.</p></div>`; return; }
  host.innerHTML = `<div class="dm-wrap"><div class="dm-list">
      <div class="row" style="padding:8px;gap:6px"><button class="btn ghost sm" id="dmSync">${ic('refresh',13)} Sync messages</button></div>
      ${d.conversations.map(cv=>`<button class="dm-conv ${cv.unread?'unread':''}" data-acc="${cv.account_id}" data-conv="${esc(cv.conversation_id)}">
        ${pi(cv.platform,16)}<div class="dm-cmain"><b>${esc(cv.name||'Unknown')}</b><span>${cv.last_dir==='out'?'You: ':''}${esc((cv.last_text||'').slice(0,60))}</span></div>
        ${cv.unread?`<span class="chat-unread">${cv.unread}</span>`:''}</button>`).join('') || '<div class="empty" style="padding:14px">No messages yet. Click Sync.</div>'}</div>
    <div class="dm-thread" id="dmThread"><div class="empty-state">${ic('message',28)}<p class="sub">Choose a conversation.</p></div></div></div>`;
  $('#dmSync').onclick = async ()=>{ const b=$('#dmSync'); b.disabled=true;
    try{ const r = await api('/api/dms/sync',{method:'POST'}); toast(`${r.new} new message(s)`,'good'); renderDMs(host); }catch(e){ toast(e.message,'warn'); b.disabled=false; } };
  host.querySelectorAll('.dm-conv').forEach(b=>b.onclick=()=>{ host.querySelectorAll('.dm-conv').forEach(x=>x.classList.toggle('on', x===b)); b.classList.remove('unread');
    const cu=b.querySelector('.chat-unread'); if(cu) cu.remove(); openDMThread(b.dataset.acc, b.dataset.conv); });
}
async function openDMThread(acc, conv){
  const box = $('#dmThread'); if(!box) return;
  let d; try{ d = await api(`/api/dms/${acc}/${encodeURIComponent(conv)}`); }catch(e){ box.innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  box.innerHTML = `<div class="dm-head">${pi(d.platform,16)} <b>${esc((d.messages.find(m=>m.direction==='in')||d.messages[0]||{}).participant_name||'')}</b>
      <span class="muted">via ${esc(d.account||'')}</span></div>
    <div class="dm-msgs">${d.messages.map(m=>`<div class="dm-msg ${m.direction}"><div class="dm-bubble"><div class="dm-text">${esc(m.text)}</div><div class="dm-time">${fmtTime((m.created_at||'').slice(0,19))}${m.sent_by?' · '+esc(m.sent_by):''}</div></div></div>`).join('')}</div>
    <div class="dm-reply"><input class="f" id="dmText" placeholder="Reply…"><button class="btn sm" id="dmSend">${ic('send',13)} Send</button></div>
    <div class="hint" style="padding:0 10px 8px">Platforms only allow replies within 24 hours of the person's last message.</div>`;
  const msgs = box.querySelector('.dm-msgs'); msgs.scrollTop = msgs.scrollHeight;
  const send = async ()=>{ const t=$('#dmText').value.trim(); if(!t) return; $('#dmSend').disabled=true;
    try{ await api(`/api/dms/${acc}/${encodeURIComponent(conv)}`,{method:'POST', body:{text:t}}); openDMThread(acc, conv); }
    catch(e){ toast(e.message,'warn',6000); $('#dmSend').disabled=false; } };
  $('#dmSend').onclick = send;
  $('#dmText').addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); send(); } });
}
window.renderDMs = renderDMs;

/* ============================================================ BRAND KIT (Team & Brands) */
async function renderBrandKit(host){
  const brands = (App._brands||[]);
  let bid = App._kitBrand || '';
  const draw = async ()=>{
    let d; try{ d = await api('/api/brandkit'+(bid?`?brand_id=${bid}`:'')); }catch(e){ host.innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
    const k = d.kit || {};
    host.innerHTML = `<h4>${ic('sparkles',15)} Brand kit
        ${brands.length?`<select class="f sel-sm" id="bkBrand" style="margin-left:auto"><option value="">Workspace default</option>${brands.map(b=>`<option value="${b.id}" ${String(b.id)===String(bid)?'selected':''}>${esc(b.name)}</option>`).join('')}</select>`:''}</h4>
      <p class="sub">The AI follows this when it writes captions, adapts them per platform and suggests replies. Banned words are flagged in the post editor's checks,
        and the logo and colour brand your monthly PDF report.${k.inherited?' <b>(Showing the workspace default — save to create a kit for this brand.)</b>':''}</p>
      <div class="bk-grid">
        <div class="bk-logo">${k.logo?`<img src="/uploads/${encodeURIComponent(k.logo)}" alt="Logo">`:`<div class="bk-ph">${ic('image',24)}</div>`}
          <label class="btn ghost sm" style="cursor:pointer">${ic('upload',13)} Logo<input type="file" id="bkLogo" accept="image/png,image/jpeg" style="display:none"></label></div>
        <div class="pe-grid" style="flex:1">
          <div><label class="f">Primary colour</label><input type="color" class="f" id="bkC1" value="${esc(k.color_primary||'#2f7bff')}"></div>
          <div><label class="f">Secondary colour</label><input type="color" class="f" id="bkC2" value="${esc(k.color_secondary||'#12b886')}"></div>
          <div><label class="f">Website</label><input class="f" id="bkWeb" value="${esc(k.website||'')}" placeholder="https://…"></div>
        </div></div>
      <label class="f">Tone of voice</label><textarea class="f" id="bkTone" style="min-height:60px" placeholder="e.g. Friendly and upbeat, short sentences, speaks to young professionals, light emoji use">${esc(k.tone||'')}</textarea>
      <div class="pe-grid"><div><label class="f">Default hashtags (always added)</label><input class="f" id="bkTags" value="${esc(k.default_hashtags||'')}" placeholder="#yourbrand #tagline"></div>
        <div><label class="f">Banned words (comma separated)</label><input class="f" id="bkBan" value="${esc(k.banned_words||'')}" placeholder="cheap, guaranteed, free"></div></div>
      <button class="btn sm" id="bkSave" style="margin-top:10px">${ic('save',14)} Save brand kit</button>`;
    if($('#bkBrand')) $('#bkBrand').onchange = e=>{ bid = e.target.value; App._kitBrand = bid; draw(); };
    $('#bkSave').onclick = async ()=>{ try{ await api('/api/brandkit',{method:'POST', body:{brand_id:bid||null, color_primary:$('#bkC1').value,
        color_secondary:$('#bkC2').value, website:$('#bkWeb').value, tone:$('#bkTone').value, default_hashtags:$('#bkTags').value, banned_words:$('#bkBan').value}});
      toast('Brand kit saved','good'); draw(); }catch(e){ toast(e.message,'warn'); } };
    $('#bkLogo').onchange = async (e)=>{ const f=e.target.files[0]; if(!f) return; const fd=new FormData(); fd.append('file', f);
      try{ await api('/api/brandkit/logo'+(bid?`?brand_id=${bid}`:''),{method:'POST', body:fd}); toast('Logo uploaded','good'); draw(); }catch(err){ toast(err.message,'warn'); } };
  };
  draw();
}
window.renderBrandKit = renderBrandKit;
