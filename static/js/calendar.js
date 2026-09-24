/* ============================================================
   Calendar page  (month grid + multi-platform post workflow)
   Flow:  upload (video / image / carousel / text)  →  caption (AI)
          →  review  →  approve  →  schedule / queue / publish now
   Each post targets several platforms; every platform has its own
   caption, status (queued / publishing / published / failed + retry).
   red = past-due & not published;  green = published
   ============================================================ */
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const DOW_MON = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];     // backend weekday(): Mon=0
const CAP_MAX = {instagram:2200, facebook:63206, youtube:5000, twitter:280, linkedin:3000, threads:500, tiktok:2200, pinterest:500};
const SUPPORTS = {
  instagram:['video','image','carousel'], facebook:['video','image','carousel','text'], youtube:['video'],
  twitter:['video','image','carousel','text'], linkedin:['video','image','carousel','text'],
  threads:['video','image','carousel','text'], tiktok:['video'], pinterest:['video','image','carousel'],
};
const CAL_DRAG = 'application/x-cal-item';

/* ---------- time helpers (schedules are stored as a UTC instant) ---------- */
function userTz(){ try{ return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; }catch(e){ return ''; } }
function tzOffset(){ return new Date().getTimezoneOffset(); }
function toUtcIso(date, time){ const d = new Date(`${date}T${time||'00:00'}`); return isNaN(d) ? null : d.toISOString().slice(0,19); }
function localFromUtc(iso){ if(!iso) return null; const d = new Date(/[zZ]$/.test(iso)?iso:iso+'Z'); return isNaN(d)?null:d; }
function fmtSchedule(it){
  const d = localFromUtc(it.publish_at);
  if(d) return `${d.toLocaleDateString(undefined,{weekday:'short', month:'short', day:'numeric'})} · ${d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}`;
  return prettyDate(it.date) + (it.publish_time ? ' · '+it.publish_time : '');
}
function isImg(fn){ return /\.(jpe?g|png|gif|webp)$/i.test(fn||''); }
function connMode(p){ return ((App.user && App.user.platforms) || {})[p] || ''; }
window.userTz = userTz; window.tzOffset = tzOffset;

async function renderCalendar(){
  if(!App.calMonth){ const n=new Date(); App.calMonth={y:n.getFullYear(), m:n.getMonth()}; }
  const c = $('#pageContent');
  c.innerHTML = `<div class="page-head"><h2>Content Calendar</h2><div class="spacer"></div>
      ${App.readonly?'':`<button class="btn ghost sm" id="calText">${ic('file',15)} Text post</button>
      <button class="btn ghost sm" id="calBulk">${ic('layers',15)} Bulk upload</button>`}
      <div class="tiles" id="calTiles" style="margin:0"></div></div>
    <div class="cal-layout">
     <div>
      <div class="cal-head">
        <button class="btn ghost sm" id="calPrev" aria-label="Previous month">${ic('chevLeft',16)}</button>
        <h3 id="calTitle"></h3>
        <button class="btn ghost sm" id="calNext" aria-label="Next month">${ic('chevRight',16)}</button>
        <button class="btn ghost sm" id="calToday">Today</button>
      </div>
      <div class="cal-grid">
        <div class="cal-dow">${DOW.map(d=>`<div>${d}</div>`).join('')}</div>
        <div class="cal-body" id="calBody"></div>
      </div>
      <div class="legend">
        <span><i style="background:var(--gold)"></i> Draft</span>
        <span><i style="background:var(--brand)"></i> In review / approved / scheduled</span>
        <span><i style="background:var(--green)"></i> Published</span>
        <span><i style="background:var(--red)"></i> Past due, not published</span>
        <span class="legend-tip">${ic('info',13)} Drag a post to another day to reschedule it</span>
      </div>
     </div>
     <div class="pub-status" id="pubStatus"><h4>${ic('send',15)} Publishing status</h4><div id="pubStatusList" class="sub">Loading…</div></div>
    </div>`;
  $('#calPrev').onclick = ()=>shiftMonth(-1);
  $('#calNext').onclick = ()=>shiftMonth(1);
  $('#calToday').onclick= ()=>{ const n=new Date(); App.calMonth={y:n.getFullYear(),m:n.getMonth()}; renderCalendar(); };
  if($('#calBulk')) $('#calBulk').onclick = openBulkUpload;
  if($('#calText')) $('#calText').onclick = ()=>openTextPost(App._today || new Date().toISOString().slice(0,10));
  await drawCalendar();
  startPubStatusPoll();
}

/* Right-side publishing status: live per-platform progress, waiting, failed, recent. */
let _pubStatusTimer = null;
function startPubStatusPoll(){
  if(_pubStatusTimer) clearInterval(_pubStatusTimer);
  let lastSig = '';
  const tick = async ()=>{
    const box = $('#pubStatusList');
    if(!box){ clearInterval(_pubStatusTimer); _pubStatusTimer=null; return; }
    let data; try{ data = await api('/api/calendar'); }catch(e){ return; }
    const items = data.items||[];
    const publishing = items.filter(i=>i.publish_state==='publishing');
    const waiting = items.filter(i=>i.state==='scheduled' && !['publishing','published','partial'].includes(i.publish_state));
    const failed = items.filter(i=>(i.targets||[]).some(t=>t.status==='failed'));
    const recent = items.filter(i=>i.state==='published').sort((a,b)=>String(b.published_date).localeCompare(String(a.published_date))).slice(0,3);
    const row = (i, tag, pct, msg)=>`<div class="ps-row">
        <div class="t"><span>${esc(i.title||'Untitled')}</span>${tag}</div>
        <div class="ps-plats">${(i.platforms||[]).map(p=>targetDot(i,p)).join('')}</div>
        <div class="ps-bar"><span style="width:${pct}%"></span></div>
        <div class="ps-msg">${msg}</div></div>`;
    let html='';
    publishing.forEach(i=> html += row(i, `<span class="chip navy">${i.publish_pct||10}%</span>`, i.publish_pct||10, 'Publishing…'));
    waiting.slice(0,6).forEach(i=> html += row(i, `<span class="chip gold">Waiting</span>`, 6, esc(fmtSchedule(i))));
    failed.slice(0,4).forEach(i=> html += row(i, `<span class="chip danger">Failed</span>`, 0, 'Open the day to retry the failed platform.'));
    recent.forEach(i=> html += row(i, `<span class="chip completed">${i.publish_state==='partial'?'Partly published':'Published'}</span>`, 100, 'Done · '+esc(i.published_date||i.date||'')));
    box.innerHTML = html || `<div class="empty" style="padding:10px">Nothing publishing right now.</div>`;
    // while something publishes, keep the grid & open day in sync
    const sig = items.map(i=>i.id+':'+i.publish_state+':'+(i.targets||[]).map(t=>t.status).join(',')).join('|');
    if(lastSig && sig!==lastSig){
      App._cal = data;
      await drawCalendar();
      const dl = $('#dl-list');
      if(dl && App._openDay && !document.querySelector('#modal-root input:focus, #modal-root textarea:focus')) openDay(App._openDay);
    }
    lastSig = sig;
  };
  tick();
  _pubStatusTimer = setInterval(tick, 3000);
}
window.startPubStatusPoll = startPubStatusPoll;

function shiftMonth(d){
  let {y,m}=App.calMonth; m+=d;
  if(m<0){m=11;y--;} if(m>11){m=0;y++;}
  App.calMonth={y,m}; drawCalendar();
}

async function drawCalendar(){
  const {y,m}=App.calMonth;
  if(!$('#calTitle')) return;
  $('#calTitle').textContent = `${MONTHS[m]} ${y}`;
  let data={items:[],by_date:{},today:'',not_uploaded:0,uploaded:0};
  try{ data = await api('/api/calendar'); }
  catch(e){ $('#calBody').innerHTML=`<div class="empty" style="grid-column:1/8;padding:40px">Log in to view the calendar.</div>`;
            $('#calTiles').innerHTML=''; return; }
  App._cal = data; App._today = data.today;

  $('#calTiles').innerHTML = `
    <div class="tile red click" id="jumpRed"><div class="n">${data.not_uploaded}</div><div class="l">Past due</div></div>
    <div class="tile green"><div class="n">${data.uploaded}</div><div class="l">Published</div></div>`;
  const navRed = $('#navCalRed'); if(navRed) navRed.textContent = data.not_uploaded;

  const today = data.today;
  const first = new Date(y,m,1);
  const startDow = first.getDay();
  const daysIn = new Date(y,m+1,0).getDate();
  const prevDays = new Date(y,m,0).getDate();

  const body = $('#calBody'); body.innerHTML='';
  let firstRedCell=null;
  for(let i=0;i<42;i++){
    let dayNum, cellY=y, cellM=m, out=false;
    if(i<startDow){ dayNum = prevDays-startDow+1+i; cellM=m-1; out=true; if(cellM<0){cellM=11;cellY--;} }
    else if(i>=startDow+daysIn){ dayNum=i-startDow-daysIn+1; cellM=m+1; out=true; if(cellM>11){cellM=0;cellY++;} }
    else dayNum=i-startDow+1;

    const ds = `${cellY}-${String(cellM+1).padStart(2,'0')}-${String(dayNum).padStart(2,'0')}`;
    const items = data.by_date[ds]||[];
    const cell = el(`<div class="cal-cell ${out?'out':''} ${ds===today?'today':''}"></div>`);
    cell.dataset.date = ds;

    const hasPub  = items.some(it=>it.state==='published');
    const overdue = !out && ds<today && items.some(it=>it.state!=='published');
    if(hasPub)  cell.classList.add('green');
    if(overdue) cell.classList.add('red');
    if(overdue && !firstRedCell) firstRedCell = ds;

    let inner = `<span class="dnum">${dayNum}</span>`;
    items.slice(0,3).forEach(it=>{
      let cls = it.state;
      if(it.state!=='published' && !out && ds<today) cls='overdue';
      const icon = it.state==='published'?'check':(it.state==='scheduled'?'clock':(it.state==='approved'?'thumbsUp':(it.state==='submitted'?'eye':'edit')));
      const movable = !out && canReschedule(it);
      inner += `<div class="ev ${cls}${movable?' movable':''}" ${movable?`draggable="true" data-cid="${it.id}"`:''}
        title="${esc(it.title)}${movable?' — drag to another date to reschedule':''}">${ic(icon,11)} <span class="ev-t">${esc(it.title)}</span></div>`;
    });
    if(items.length>3) inner += `<div class="more">+${items.length-3} more</div>`;
    cell.innerHTML = inner;

    if(!out){
      cell.onclick = ()=>openDay(ds);
      if(!App.readonly){
        cell.addEventListener('dragover', e=>{
          const types = Array.from((e.dataTransfer && e.dataTransfer.types)||[]);
          if(types.includes('Files') || (types.includes(CAL_DRAG) && ds>=today)){
            e.preventDefault(); cell.classList.add('drop-hot');
          }
        });
        cell.addEventListener('dragleave', e=>{ if(!cell.contains(e.relatedTarget)) cell.classList.remove('drop-hot'); });
        cell.addEventListener('drop', e=>{
          cell.classList.remove('drop-hot');
          const moved = e.dataTransfer && e.dataTransfer.getData(CAL_DRAG);
          if(moved){ e.preventDefault(); e.stopPropagation(); rescheduleItem(Number(moved), ds); return; }
          const files = e.dataTransfer && e.dataTransfer.files;
          if(files && files.length){ e.preventDefault(); e.stopPropagation(); uploadToDate(ds, files); }
        });
      }
    }
    cell.querySelectorAll('.ev.movable').forEach(ev=>{
      ev.addEventListener('dragstart', e=>{
        e.stopPropagation();
        e.dataTransfer.setData(CAL_DRAG, ev.dataset.cid);
        e.dataTransfer.effectAllowed = 'move';
        ev.classList.add('dragging');
      });
      ev.addEventListener('dragend', ()=> ev.classList.remove('dragging'));
    });
    body.appendChild(cell);
  }

  const jr = $('#jumpRed');
  if(jr) jr.onclick = ()=>{
    if(firstRedCell){ const c=$(`.cal-cell[data-date="${firstRedCell}"]`);
      if(c){ c.scrollIntoView({behavior:'smooth',block:'center'}); c.style.outline='2px solid var(--red)';
             setTimeout(()=>c.style.outline='',1500); openDay(firstRedCell); } }
    else toast('No past-due posts','good');
  };
}
window.drawCalendar = drawCalendar;

/* ---------- Reschedule (change the date of a post) ---------- */
function canReschedule(it){
  return !App.readonly && it.state!=='published' && it.publish_state!=='publishing';
}
async function rescheduleItem(cid, newDate, publishTime){
  const it = (App._cal && (App._cal.items||[]).find(x=>x.id==cid)) || null;
  if(it && it.date===newDate && publishTime===undefined) return false;
  if(newDate < (App._today||'')){ toast('Pick today or a future date.','warn'); return false; }
  const body = {date:newDate};
  const t = publishTime!==undefined ? publishTime : (it && it.publish_time) || '';
  if(publishTime!==undefined) body.publish_time = publishTime;
  body.publish_at = t ? toUtcIso(newDate, t) : null; body.tz = userTz();
  try{
    await api('/api/calendar/'+cid, {method:'PATCH', body});
    toast(`Rescheduled to ${prettyDate(newDate)}${t?(' at '+t):''}`,'good',4000);
    await drawCalendar(); loadNotifCount();
    return true;
  }catch(e){ toast(e.message,'warn',5000); return false; }
}
window.rescheduleItem = rescheduleItem;

function openReschedule(cid, fromDs){
  const it = (App._cal.items||[]).find(x=>x.id==cid); if(!it) return;
  const approved = !!it.approved;
  const today = App._today||'';
  const m = el(`<div class="modal" style="max-width:420px">
    <div class="modal-head"><h3>${ic('calendar',18)} Change schedule date</h3><button class="x" id="rs-x" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <div class="meta" style="margin-bottom:8px"><b>${esc(it.title||'Untitled')}</b> · currently ${esc(fmtSchedule(it))}</div>
      <label class="f">New date</label>
      <input class="f" id="rs-date" type="date" min="${esc(today)}" value="${esc(it.date >= today ? it.date : today)}">
      <label class="f">Publish time (your time zone${userTz()?' — '+esc(userTz()):''})</label>
      <input class="f" id="rs-time" type="time" value="${esc(it.publish_time||'')}">
      <div class="hint">Leave the time empty to publish at the start of the day.</div>
      <div class="err" id="rs-err"></div>
      <div class="note">${approved
        ? 'This post is approved — it will auto-publish on the new date/time.'
        : 'The post keeps its current status and simply moves to the new date.'}
        Tip: you can also <b>drag</b> a post onto another date in the calendar.</div>
    </div>
    <div class="modal-foot"><button class="btn ghost" id="rs-cancel">Cancel</button>
      <button class="btn" id="rs-save">Save new date</button></div></div>`);
  openModal(m);
  const back = ()=> openDay(fromDs);
  $('#rs-x',m).onclick = back; $('#rs-cancel',m).onclick = back;
  $('#rs-save',m).onclick = async ()=>{
    const nd = $('#rs-date',m).value, t = $('#rs-time',m).value;
    if(!nd){ $('#rs-err',m).textContent='Choose a date.'; return; }
    if(nd < today){ $('#rs-err',m).textContent='Pick today or a future date.'; return; }
    if(nd===it.date && t===(it.publish_time||'')){ back(); return; }
    const b = $('#rs-save',m); b.disabled=true; b.textContent='Saving…';
    const ok = await rescheduleItem(cid, nd, t);
    if(ok) openDay(nd); else { b.disabled=false; b.textContent='Save new date'; }
  };
}

/* Upload dropped file(s) directly to a date, then open that day */
async function uploadToDate(ds, files, opts){
  const media = [...files].filter(f=>/^(video|image)\//.test(f.type) || /\.(mp4|mov|webm|mkv|avi|m4v|jpe?g|png|gif|webp)$/i.test(f.name));
  if(!media.length){ toast('Drop a video or image file','warn'); return; }
  toast(`Uploading ${media.length} file(s) to ${ds}…`);
  try{
    const fd=new FormData(); fd.append('date',ds);
    media.forEach(f=>fd.append('files', f));
    fd.append('platforms', JSON.stringify((opts&&opts.platforms) || defaultPlatforms()));
    if(opts && opts.carousel) fd.append('as_carousel','1');
    await api('/api/calendar/upload',{method:'POST', body:fd});
    toast('Uploaded — write or generate captions next','good');
    await drawCalendar(); openDay(ds); loadNotifCount();
  }catch(e){ toast('Upload failed: '+e.message,'warn',6000); }
}
window.uploadToDate = uploadToDate;

function defaultPlatforms(){
  const conn = PLAT_ORDER.filter(p=>connMode(p));
  const allowed = (App.user && App.user.publish_platforms) || PLAT_ORDER;
  const pick = (conn.length ? conn : ['instagram']).filter(p=>allowed.includes(p));
  return pick.length ? pick : [allowed[0]||'instagram'];
}

/* platform picker (chips); returns {el, get()} */
function platformPicker(selected, kind, requireLive){
  const allowed = (App.user && App.user.publish_platforms) || PLAT_ORDER;
  const wrap = el(`<div class="plat-pick">${PLAT_ORDER.map(p=>{
      const live = connMode(p)==='live', ok = allowed.includes(p) && (!requireLive || live);
      const on = selected.includes(p) && ok;
      const unsupported = kind && !(SUPPORTS[p]||[]).includes(kind);
      const tip = `${platLabel(p)}${live?' — connected':' — not connected (connect it in Setup)'}${unsupported?' — doesn\'t support this post type':''}${allowed.includes(p)?'':' — no permission'}`;
      return `<button type="button" class="pp ${on?'on':''} ${unsupported?'unsup':''} ${live?'':'off'}" data-p="${p}" ${ok?'':'disabled'} title="${esc(tip)}">
        ${pi(p,16)} <span>${esc(platLabel(p))}</span>${live?`<i class="pp-live"></i>`:''}</button>`;
    }).join('')}</div>`);
  wrap.querySelectorAll('.pp').forEach(b=>b.onclick=()=>b.classList.toggle('on'));
  return {el:wrap, get:()=>[...wrap.querySelectorAll('.pp.on')].map(b=>b.dataset.p)};
}
window.platformPicker = platformPicker;

/* ---------- Day pop-up ---------- */
function openDay(ds){
  App._openDay = ds;
  const items = (App._cal && App._cal.by_date[ds]) || [];
  const readonly = App.readonly;
  const list = items.length ? items.map(it=>dayItem(it)).join('') : `<div class="empty">No posts on this date.</div>`;
  const uploader = readonly ? `<div class="note">Log in to upload.</div>` : `
     <label class="f">Add posts for this date</label>
     <div class="dropzone" id="dl-drop">
       <div class="dz-ico">${ic('upload',22)}</div>
       <div><b>Drag &amp; drop</b> videos or images here, or <span class="dz-browse">browse</span></div>
       <input class="f" id="dl-files" type="file" accept="video/*,image/*" multiple style="display:none">
     </div>
     <div class="pre-list" id="dl-preview"></div>
     <label class="f">Publish to</label>
     <div id="dl-plats"></div>
     <label class="cred-toggle" style="margin-top:8px"><input type="checkbox" id="dl-carousel"> <span>Combine the selected files into one <b>carousel</b> post</span></label>
     <div class="row" style="gap:8px;margin-top:10px">
       <button class="btn" style="flex:1" id="dl-up">${ic('upload',15)} Upload</button>
       <button class="btn ghost" id="dl-text">${ic('file',15)} Text post</button>
     </div>
     <div class="err" id="dl-err"></div>`;
  const m = el(`<div class="modal wide">
     <div class="modal-head"><h3>${ic('calendar',18)} ${prettyDate(ds)}</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
     <div class="modal-body">
       <div id="dl-list">${list}</div>
       <hr class="sep">
       ${uploader}
     </div></div>`);
  openModal(m);
  bindDayItems(m, ds);
  if(readonly) return;
  const picker = platformPicker(defaultPlatforms());
  $('#dl-plats',m).appendChild(picker.el);
  const fileInput = $('#dl-files',m), drop = $('#dl-drop',m);
  const carouselRow = $('#dl-carousel',m).parentElement;
  const preview = ()=>{
    const box = $('#dl-preview',m); box.innerHTML='';
    [...fileInput.files].forEach(f=>{
      const url = URL.createObjectURL(f);
      const item = el(`<div class="pre-item"><div class="pre-name">${ic(isImg(f.name)?'image':'film',13)} ${esc(f.name)} · ${(f.size/1048576).toFixed(1)} MB</div></div>`);
      const media = document.createElement(isImg(f.name)?'img':'video');
      media.src=url; media.className='video-preview'; if(media.tagName==='VIDEO') media.controls=true;
      item.appendChild(media); box.appendChild(item);
    });
    carouselRow.style.display = fileInput.files.length>1 ? '' : 'none';
  };
  carouselRow.style.display='none';
  fileInput.onchange = preview;
  drop.onclick = ()=> fileInput.click();
  drop.addEventListener('dragover', e=>{ e.preventDefault(); drop.classList.add('drag-over'); });
  drop.addEventListener('dragleave', ()=> drop.classList.remove('drag-over'));
  drop.addEventListener('drop', e=>{
    e.preventDefault(); drop.classList.remove('drag-over');
    if(e.dataTransfer.files && e.dataTransfer.files.length){ fileInput.files = e.dataTransfer.files; preview(); }
  });
  $('#dl-text',m).onclick = ()=>openTextPost(ds);
  $('#dl-up',m).onclick = async ()=>{
    const files = fileInput.files;
    if(!files.length){ $('#dl-err',m).textContent='Choose at least one file.'; return; }
    const plats = picker.get();
    if(!plats.length){ $('#dl-err',m).textContent='Choose at least one platform.'; return; }
    const b=$('#dl-up',m); b.disabled=true; b.textContent='Uploading…';
    await uploadToDate(ds, files, {platforms:plats, carousel:$('#dl-carousel',m).checked});
  };
}
window.openDay = openDay;

function stateBadge(it){
  if(it.state==='published') return it.publish_state==='partial' ? `<span class="chip gold">Partly published</span>` : `<span class="chip completed">Published</span>`;
  if(it.publish_state==='publishing') return `<span class="chip navy">Publishing…</span>`;
  if(it.state==='scheduled') return `<span class="chip gold">Scheduled</span>`;
  if(it.state==='approved')  return `<span class="chip inprogress">Approved</span>`;
  if(it.state==='submitted') return `<span class="chip new">Awaiting approval</span>`;
  return `<span class="chip draft">Draft</span>`;
}

/* small status dot for a platform in a post */
function targetDot(it, p){
  const t = (it.targets||[]).find(x=>x.platform===p);
  const st = t ? t.status : 'none';
  const tip = t ? `${platLabel(p)}: ${st}${t.simulated?' (simulated)':''}${t.error?' — '+t.error:''}` : `${platLabel(p)}: not published yet`;
  return `<span class="tdot st-${st}" title="${esc(tip)}">${pi(p,13)}</span>`;
}

/* per-platform status chips (with link / retry) */
function targetChips(it){
  const plats = it.platforms || [];
  return `<div class="tchips">${plats.map(p=>{
    const t = (it.targets||[]).find(x=>x.platform===p);
    let st = 'Not published', cls = 'none', extra = '';
    if(t){
      cls = t.status;
      st = {new:'Ready', pending:'Queued', publishing:'Publishing…', retrying:'Retrying', published:'Published', failed:'Failed'}[t.status] || t.status;
      if(t.status==='published' && t.permalink) extra = `<a href="${esc(t.permalink)}" target="_blank" rel="noopener" title="Open post">${ic('external',12)}</a>`;
      if(t.status==='failed' && !App.readonly) extra = `<button class="tc-retry" data-retry="${t.id}" title="Retry ${esc(platLabel(p))}">${ic('refresh',12)} Retry</button>`;
      if(t.simulated) extra += `<span class="tc-sim" title="Published by an earlier demo version">sim</span>`;
    }
    const err = t && (t.status==='failed' || t.status==='retrying') && t.error ? ` title="${esc(t.error)}"` : '';
    return `<span class="tchip tc-${cls}"${err}>${pi(p,14)} ${esc(platLabel(p))} · ${st} ${extra}</span>`;
  }).join('')}</div>`;
}

function mediaThumb(it){
  const files = it.media || (it.filename ? [it.filename] : []);
  if(!files.length && it.external_thumb) return `<a class="vthumb" href="${esc(it.external_url||'#')}" target="_blank" rel="noopener" title="Imported post — open on the platform"><img src="${esc(it.external_thumb)}" alt="" referrerpolicy="no-referrer"></a>`;
  if(!files.length) return `<div class="vthumb txt">${ic('file',20)}</div>`;
  const f = it.thumbnail || files[0];
  const inner = isImg(f) ? `<img src="/uploads/${encodeURIComponent(f)}" alt="">` : `<video src="/uploads/${encodeURIComponent(f)}#t=0.5" muted preload="metadata"></video>`;
  return `<button class="vthumb" data-preview="${it.id}" title="Preview">${inner}${files.length>1?`<span class="vcount">${ic('layers',11)} ${files.length}</span>`:''}${!isImg(f)?`<span class="vplay">${ic('play',14)}</span>`:''}</button>`;
}

function dayItem(it){
  const overdue = it.state!=='published' && it.date < (App._today||'');
  const hasCaption = (it.caption||'').trim().length>0;
  const ro = App.readonly;
  const kind = it.media_kind || 'video';
  const progress = `<div class="gen-progress hidden" id="gp-${it.id}">
        <div class="bar"><div class="fill" id="gpf-${it.id}"></div></div>
        <div class="gp-msg" id="gpm-${it.id}"></div></div>`;
  const driveLink = it.drive_link
    ? `<div class="vdrive">${ic('folder',13)} Stored in Google Drive — <a href="${esc(it.drive_link)}" target="_blank" rel="noopener">open file</a></div>` : '';
  const review = it.review_note ? `<div class="vreview">${ic('message',13)} ${esc(it.review_note)}</div>` : '';
  const btn = (attr, icon, label, cls='ghost')=>`<button class="btn ${cls} sm" ${attr}>${ic(icon,14)} ${label}</button>`;
  let actions = '';
  if(!ro){
    actions += btn(`data-editor="${it.id}"`, 'edit', 'Edit post');
    if(it.state==='uploaded'){
      if(kind!=='text') actions += btn(`data-gen="${it.id}"`, 'sparkles', hasCaption?'Regenerate with AI':'Generate with AI', 'brand');
      actions += btn(`data-review="${it.id}"`, 'send', 'Push to review', 'green');
    }else if(it.state==='submitted'){
      if(App.user && App.user.can_approve) actions += btn(`data-approve="${it.id}"`, 'thumbsUp', 'Approve', '');
      else actions += `<span class="await-approval">Awaiting admin approval</span>` + btn('data-reqapprove="1"', 'key', 'Request approval access');
    }else if(it.state==='approved' || it.state==='scheduled'){
      const pubng = it.publish_state==='publishing';
      actions += btn(`data-queue="${it.id}"`, 'clock', 'Add to queue');
      actions += btn(`data-publish="${it.id}" ${pubng?'disabled':''}`, 'send', pubng?('Publishing… '+(it.publish_pct||0)+'%'):'Publish now', 'green');
      if(kind==='video') actions += btn(`data-replace="${it.id}"`, 'refresh', 'Replace video');
    }
    if(it.state!=='published') actions += btn(`data-reviewlink="${it.id}"`, 'share', 'Client review link');
    if(canReschedule(it)) actions += btn(`data-resched="${it.id}"`, 'calendar', 'Change date');
    actions += btn(`data-del="${it.id}"`, 'trash', 'Remove', 'danger');
  }
  const capBlock = hasCaption
    ? `<div class="cap">${esc(it.caption.length>220?it.caption.slice(0,220)+'…':it.caption)}</div>
       ${it.description?`<div class="vdesc-sm" title="Description (YouTube, Facebook, LinkedIn, Pinterest)">${esc(it.description)}</div>`:''}
       <div class="tags">${esc(it.hashtags||'')}</div>`
    : `<div class="cap muted-i">${kind==='text'?'No text yet.':'No caption yet — generate one or write it in the editor.'}</div>`;
  const kindIcon = {video:'film', image:'image', carousel:'layers', text:'file'}[kind] || 'film';
  return `<div class="vcard post ${overdue?'overdue':''}" data-item="${it.id}">
     <div class="post-row">
       ${mediaThumb(it)}
       <div class="post-main">
         <div class="t">${ic(kindIcon,14)} ${esc(it.title||'Untitled')} ${stateBadge(it)}
           ${it.recycle_days?`<span class="chip" title="Evergreen: re-shares ${it.recycle_days} days after publishing">${ic('repeat',11)} ${it.recycle_days}d</span>`:''}</div>
         ${capBlock}
         <div class="meta">${ic('user',12)} ${esc(it.owner||'—')} · ${ic('clock',12)} ${esc(fmtSchedule(it))} · ${esc(it.content_type||'reel')}</div>
         ${targetChips(it)}
         ${review}${driveLink}
       </div>
     </div>
     ${progress}
     <div class="row actions">${actions}</div>
   </div>`;
}

/* Preview a post's media (video / image / carousel) */
function previewItem(it){
  const files = it.media && it.media.length ? it.media : (it.filename ? [it.filename] : []);
  const m = el(`<div class="modal wide">
    <div class="modal-head"><h3>${ic('eye',18)} ${esc(it.title||'Preview')}</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><div class="pv-grid">${files.map(f=> isImg(f)
      ? `<img class="video-preview" src="/uploads/${encodeURIComponent(f)}" alt="">`
      : `<video class="video-preview" controls src="/uploads/${encodeURIComponent(f)}"></video>`).join('') || '<div class="empty">Text-only post.</div>'}</div>
      ${it.caption?`<div class="cap" style="margin-top:10px;white-space:pre-wrap">${esc(it.caption)}\n${esc(it.hashtags||'')}</div>`:''}
    </div></div>`);
  openModal(m);
}
function previewVideo(filename, title){ previewItem({title, media:[filename]}); }
window.previewVideo = previewVideo;
window.previewItem = previewItem;

function findItem(id){ return (App._cal && (App._cal.items||[]).find(x=>x.id==id)) || null; }

function bindDayItems(m, ds){
  const refresh = async ()=>{ await drawCalendar(); openDay(ds); loadNotifCount(); };
  m.querySelectorAll('[data-preview]').forEach(b=>b.onclick=()=>{ const it=findItem(b.dataset.preview); if(it) previewItem(it); });
  m.querySelectorAll('[data-gen]').forEach(b=>b.onclick=()=>generateCaption(b.dataset.gen, ds, m));
  resumeGenerating(m, ds);
  m.querySelectorAll('[data-editor]').forEach(b=>b.onclick=()=>openPostEditor(b.dataset.editor, ds));
  m.querySelectorAll('[data-review]').forEach(b=>b.onclick=async ()=>{
    const it = findItem(b.dataset.review);
    if(!it || !((it.caption||'').trim() || (it.hashtags||'').trim())){ toast('Add a caption or hashtags before pushing to review (Edit post).','warn'); return; }
    try{ await api('/api/calendar/'+it.id+'/submit',{method:'POST'}); toast('Pushed to review — awaiting approval','good'); refresh(); }
    catch(e){ toast(e.message,'warn',6000); }
  });
  m.querySelectorAll('[data-approve]').forEach(b=>b.onclick=async ()=>{
    try{ await api('/api/calendar/'+b.dataset.approve+'/approve',{method:'POST', body:{tz:userTz(), offset:tzOffset()}});
      toast('Approved — schedule it, queue it or publish now','good'); refresh(); }
    catch(e){ toast(e.message,'warn',6000); }
  });
  m.querySelectorAll('[data-reqapprove]').forEach(b=>b.onclick=async ()=>{
    try{ await api('/api/request-access',{method:'POST', body:{kind:'approval'}}); toast('Request sent to the admin','good',5000); }
    catch(e){ toast(e.message,'warn'); }
  });
  m.querySelectorAll('[data-publish]').forEach(b=>b.onclick=()=>openPublishModal(findItem(b.dataset.publish), ds));
  m.querySelectorAll('[data-queue]').forEach(b=>b.onclick=async ()=>{
    try{ const r = await api('/api/calendar/'+b.dataset.queue+'/queue',{method:'POST', body:{tz:userTz(), offset:tzOffset()}});
      toast(`Queued for ${prettyDate(r.date)} at ${r.time}`,'good',5000);
      await drawCalendar(); openDay(r.date); loadNotifCount(); }
    catch(e){ toast(e.message,'warn',6000); }
  });
  m.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async (e)=>{
    e.stopPropagation();
    try{ await api('/api/targets/'+b.dataset.retry+'/retry',{method:'POST'}); toast('Retrying…','good'); refresh(); }
    catch(err){ toast(err.message,'warn'); }
  });
  m.querySelectorAll('[data-reviewlink]').forEach(b=>b.onclick=()=>openReviewLink(b.dataset.reviewlink, ds));
  m.querySelectorAll('[data-resched]').forEach(b=>b.onclick=()=>openReschedule(b.dataset.resched, ds));
  m.querySelectorAll('[data-replace]').forEach(b=>b.onclick=()=>{
    const id=b.dataset.replace;
    const inp=el('<input type="file" accept="video/*" style="display:none">');
    document.body.appendChild(inp);
    inp.onchange=async ()=>{
      if(!inp.files||!inp.files[0]){ inp.remove(); return; }
      const fd=new FormData(); fd.append('file', inp.files[0]);
      b.disabled=true; b.textContent='Replacing…';
      try{ await api('/api/calendar/'+id+'/replace',{method:'POST', body:fd}); toast('Video replaced','good'); refresh(); }
      catch(e){ toast(e.message,'warn'); b.disabled=false; }
      inp.remove();
    };
    inp.click();
  });
  m.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>{
    confirmBox('Remove this post?','It will be removed and all users notified.',
      async ()=>{ await api('/api/calendar/'+b.dataset.del,{method:'DELETE'}); toast('Removed','warn'); refresh(); }, 'Yes, remove');
  });
}

/* ---------- Publish now: choose platforms + post type ---------- */
function openPublishModal(it, ds){
  if(!it) return;
  const types = [
    {id:'reel',  icon:'film',  name:'Reel / Short', desc:'Vertical video (Reels, Shorts, TikTok).'},
    {id:'post',  icon:'image', name:'Feed post',    desc:'Standard feed post / video.'},
    {id:'story', icon:'zap',   name:'Story',        desc:'24-hour Story (Instagram, Facebook).'},
  ];
  const cur = it.content_type==='short' ? 'reel' : (it.content_type||'reel');
  const picker = platformPicker(it.platforms||defaultPlatforms(), it.media_kind, true);
  const m = el(`<div class="modal" style="max-width:560px">
    <div class="modal-head"><h3>${ic('send',18)} Publish now</h3><button class="x" id="pm-x" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Platforms</label><div id="pm-plats"></div>
      <div class="hint">Only connected platforms can be published to. Connect more accounts in Setup.</div>
      <label class="f">Post type</label>
      <div class="ctype-grid">${types.map(o=>`<button class="ctype ${o.id===cur?'on':''}" data-ct="${o.id}">
          <div class="ct-ico">${ic(o.icon,22)}</div><div class="ct-name">${o.name}</div><div class="ct-desc">${o.desc}</div></button>`).join('')}</div>
      <div class="err" id="pm-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" id="pm-cancel">Cancel</button>
      <button class="btn green" id="pm-go">${ic('send',15)} Publish</button></div></div>`);
  openModal(m);
  $('#pm-plats',m).appendChild(picker.el);
  let ct = cur;
  m.querySelectorAll('[data-ct]').forEach(b=>b.onclick=()=>{ ct=b.dataset.ct; m.querySelectorAll('[data-ct]').forEach(x=>x.classList.toggle('on', x===b)); });
  const back = ()=>openDay(ds);
  $('#pm-x',m).onclick = back; $('#pm-cancel',m).onclick = back;
  $('#pm-go',m).onclick = async ()=>{
    const plats = picker.get();
    if(!plats.length){ $('#pm-err',m).textContent='Choose at least one platform.'; return; }
    const b=$('#pm-go',m); b.disabled=true; b.textContent='Queuing…';
    try{ const r = await api('/api/calendar/'+it.id+'/publish',{method:'POST', body:{content_type:ct, platforms:plats}});
      toast(r.message||'Publishing…','good',5000); await drawCalendar(); openDay(ds); loadNotifCount(); }
    catch(e){ $('#pm-err',m).textContent=e.message; b.disabled=false; b.innerHTML=`${ic('send',15)} Publish`; }
  };
}

/* ---------- Client review link ---------- */
async function openReviewLink(cid, ds){
  let url='', links=[];
  try{ url = (await api('/api/calendar/'+cid+'/review-link',{method:'POST'})).url;
       links = (await api('/api/calendar/'+cid+'/review-link')).links; }
  catch(e){ toast(e.message,'warn'); return; }
  const m = el(`<div class="modal" style="max-width:540px">
    <div class="modal-head"><h3>${ic('share',18)} Client review link</h3><button class="x" id="rl-x" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">Send this link to your client. They can preview the post and <b>approve</b> it or
        <b>request changes</b> without logging in. You'll be notified of their decision.</p>
      <div class="pf-redirect big"><code>${esc(url)}</code><button class="icon-btn sm" id="rl-copy">${ic('copy',14)}</button></div>
      <label class="f">History</label>
      <div class="rl-list">${links.map(l=>`<div class="rl-row"><span class="chip ${l.status==='approved'?'completed':(l.status==='changes'?'danger':'draft')}">${esc(l.status)}</span>
        ${l.client_name?esc(l.client_name):'—'} ${l.client_note?`<i>“${esc(l.client_note)}”</i>`:''} <span class="muted">${l.decided_at?fmtTime(l.decided_at):'waiting'}</span></div>`).join('')}</div>
    </div>
    <div class="modal-foot"><a class="btn ghost" href="${esc(url)}" target="_blank" rel="noopener">${ic('external',14)} Open</a>
      <button class="btn" id="rl-done">Done</button></div></div>`);
  openModal(m);
  $('#rl-copy',m).onclick = ()=>{ try{ navigator.clipboard.writeText(url); toast('Link copied','good'); }catch(e){} };
  $('#rl-x',m).onclick = ()=>openDay(ds); $('#rl-done',m).onclick = ()=>openDay(ds);
}

/* ============================================================
   POST EDITOR — content, platforms, per-platform captions,
   media checks & conversion, thumbnail, schedule, evergreen
   ============================================================ */
async function openPostEditor(cid, ds){
  const it = findItem(cid); if(!it) return;
  const kind = it.media_kind || 'video';
  const picker = platformPicker(it.platforms||defaultPlatforms(), kind);
  const pc = Object.assign({}, it.platform_captions||{});
  const sched = localFromUtc(it.publish_at);
  const schedDate = sched ? `${sched.getFullYear()}-${String(sched.getMonth()+1).padStart(2,'0')}-${String(sched.getDate()).padStart(2,'0')}` : it.date;
  const schedTime = sched ? `${String(sched.getHours()).padStart(2,'0')}:${String(sched.getMinutes()).padStart(2,'0')}` : (it.publish_time||'');
  const locked = it.state==='published';
  const m = el(`<div class="modal wide editor" style="max-width:860px">
    <div class="modal-head"><h3>${ic('edit',18)} Edit post</h3> ${stateBadge(it)}<button class="x" id="pe-x" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <section class="pe-sec"><h4>${ic('pen',15)} Content</h4>
        <label class="f">Title</label><input class="f" id="pe-title" value="${esc(it.title||'')}">
        <div class="lib-anchor"><label class="f">Master caption <span class="muted">(used for every platform unless customised below)</span>
          <button class="btn ghost xs" id="pe-tpl" type="button" style="float:right">${ic('folder',12)} Insert template</button></label>
        <textarea class="f" id="pe-cap" style="min-height:90px">${esc(it.caption||'')}</textarea></div>
        <label class="f" for="pe-desc">Description <span class="muted">(added on YouTube, Facebook, LinkedIn and Pinterest)</span></label>
        <textarea class="f" id="pe-desc" style="min-height:70px" placeholder="A few sentences about what happens in the video">${esc(it.description||'')}</textarea>
        <div class="lib-anchor"><label class="f">Hashtags
          <button class="btn ghost xs" id="pe-htg" type="button" style="float:right">${ic('folder',12)} Insert hashtags</button></label>
        <input class="f" id="pe-tags" value="${esc(it.hashtags||'')}" placeholder="#reels #brand"></div>
        <div class="pe-grid">
          <div><label class="f">Website link <span class="muted">(tracked per platform)</span></label>
            <input class="f" id="pe-link" type="url" value="${esc(it.link_url||'')}" placeholder="https://yourshop.com/offer"></div>
          <div><label class="f">Campaign name <span class="muted">(utm_campaign)</span></label>
            <input class="f" id="pe-camp" value="${esc(it.link_campaign||'')}" placeholder="Defaults to the post title"></div>
        </div>
        <div class="hint">Put <code>{link}</code> in the caption where the link should go, or it's added at the end. Each platform gets its own short link,
          so Link in bio &rarr; Website clicks shows which post and platform sent visitors. Instagram captions can't hold clickable links, so it's left out there.</div>
      </section>
      <section class="pe-sec"><h4>${ic('send',15)} Platforms &amp; format</h4>
        <div id="pe-plats"></div>
        <div class="pe-grid">
          <div><label class="f">Post type</label>
            <select class="f" id="pe-type">${[['reel','Reel / Short (vertical)'],['post','Feed post'],['story','Story'],['short','YouTube Short']].map(([v,l])=>
              `<option value="${v}" ${(it.content_type||'reel')===v?'selected':''}>${l}</option>`).join('')}</select></div>
          <div class="pe-yt"><label class="f">YouTube title</label><input class="f" id="pe-yttitle" maxlength="100" value="${esc(it.yt_title||'')}" placeholder="Defaults to the post title"></div>
          <div class="pe-yt"><label class="f">YouTube privacy</label>
            <select class="f" id="pe-ytpriv">${['public','unlisted','private'].map(v=>`<option ${ (it.yt_privacy||'public')===v?'selected':''}>${v}</option>`).join('')}</select></div>
        </div>
      </section>
      <section class="pe-sec"><h4>${ic('message',15)} Captions per platform
          <button class="btn brand sm" id="pe-adapt" style="margin-left:auto">${ic('sparkles',14)} Adapt with AI</button></h4>
        <p class="sub">Each platform has its own length limit and style. Leave a box empty to use the master caption.</p>
        <div id="pe-caps"></div>
      </section>
      ${kind!=='text'?`<section class="pe-sec"><h4>${ic('film',15)} Media checks</h4>
        <div id="pe-checks" class="pe-checks"><div class="loading">Checking media…</div></div>
        ${kind==='video'?`<div class="pe-thumb"><div><label class="f">Cover / thumbnail</label>
          <div class="row" style="gap:8px;align-items:center">
            ${it.thumbnail?`<img class="thumb-sm" src="/uploads/${encodeURIComponent(it.thumbnail)}" alt="">`:'<span class="muted">Auto (first frame)</span>'}
            <input class="f" id="pe-at" type="number" min="0" step="0.5" value="1" style="width:90px" title="Seconds into the video">
            <button class="btn ghost sm" id="pe-grab">${ic('camera',14)} Use frame at (s)</button>
            <label class="btn ghost sm" style="cursor:pointer">${ic('upload',14)} Upload image<input type="file" id="pe-thumbfile" accept="image/*" style="display:none"></label>
            ${it.thumbnail?`<button class="btn ghost sm" id="pe-thumbclear">${ic('x',14)} Reset</button>`:''}
          </div></div></div>`:''}
      </section>`:''}
      <section class="pe-sec"><h4>${ic('clock',15)} Schedule</h4>
        <div class="pe-grid">
          <div><label class="f">Date</label><input class="f" id="pe-date" type="date" value="${esc(schedDate)}" ${locked?'disabled':''}></div>
          <div><label class="f">Time <span class="muted">(${esc(userTz()||'local')})</span></label><input class="f" id="pe-time" type="time" value="${esc(schedTime)}" ${locked?'disabled':''}></div>
          <div><label class="f">Evergreen re-share</label>
            <select class="f" id="pe-recycle">${[[0,'Off'],[14,'Every 14 days'],[30,'Every 30 days'],[60,'Every 60 days'],[90,'Every 90 days']].map(([v,l])=>
              `<option value="${v}" ${Number(it.recycle_days||0)===v?'selected':''}>${l}</option>`).join('')}</select></div>
        </div>
        <label class="cred-toggle"><input type="checkbox" id="pe-auto" ${(it.auto_publish==null||it.auto_publish)?'checked':''}> <span>Auto-publish at this time once approved</span></label>
        <div class="best-times" id="pe-best"></div>
      </section>
      <div class="err" id="pe-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" id="pe-cancel">Cancel</button>
      <button class="btn" id="pe-save">${ic('save',15)} Save post</button></div></div>`);
  openModal(m);
  $('#pe-plats',m).appendChild(picker.el);

  // per-platform caption boxes follow the selected platforms
  const renderCaps = ()=>{
    const box = $('#pe-caps',m);
    [...box.querySelectorAll('textarea')].forEach(t=>{ pc[t.dataset.p] = t.value; });
    const sel = picker.get();
    const master = ()=> (($('#pe-cap',m).value||'') + ($('#pe-tags',m).value?'\n\n'+$('#pe-tags',m).value:'')).trim();
    box.innerHTML = sel.map(p=>`<div class="pcap"><div class="pcap-h">${pi(p,15)} <b>${esc(platLabel(p))}</b>
        <span class="pcap-n" id="pcn-${p}"></span></div>
        <textarea class="f" data-p="${p}" placeholder="${esc(master().slice(0,200) || 'Uses the master caption')}">${esc(pc[p]||'')}</textarea></div>`).join('')
      || '<div class="empty">Select at least one platform.</div>';
    const count = (t)=>{ const n=(t.value||master()).length, max=CAP_MAX[t.dataset.p];
      const c=$('#pcn-'+t.dataset.p,m); c.textContent=`${n.toLocaleString()} / ${max.toLocaleString()}`; c.classList.toggle('over', n>max); };
    box.querySelectorAll('textarea').forEach(t=>{ t.oninput=()=>count(t); count(t); });
    m.querySelectorAll('.pe-yt').forEach(x=>x.style.display = sel.includes('youtube') ? '' : 'none');
  };
  picker.el.querySelectorAll('.pp').forEach(b=>b.addEventListener('click', renderCaps));
  $('#pe-tpl',m).onclick = (e)=>pickLibrary('caption', t=>{ const ta=$('#pe-cap',m);
      ta.value = ta.value.trim() ? ta.value.trimEnd()+'\n\n'+t.body : t.body; renderCaps(); ta.focus(); }, e.currentTarget);
  $('#pe-htg',m).onclick = (e)=>pickLibrary('hashtags', t=>{ const inp=$('#pe-tags',m);
      const have = new Set(inp.value.split(/\s+/).filter(Boolean));
      inp.value = [...have, ...t.body.split(/\s+/).filter(x=>x && !have.has(x))].join(' '); renderCaps(); }, e.currentTarget);
  $('#pe-cap',m).addEventListener('input', renderCaps); $('#pe-tags',m).addEventListener('input', renderCaps);
  renderCaps();

  const collect = ()=>{
    [...$('#pe-caps',m).querySelectorAll('textarea')].forEach(t=>{ pc[t.dataset.p] = t.value; });
    const plats = picker.get();
    const body = {title:$('#pe-title',m).value, caption:$('#pe-cap',m).value, hashtags:$('#pe-tags',m).value,
      description:$('#pe-desc',m).value,
      platforms:plats, platform_captions:Object.fromEntries(plats.map(p=>[p, pc[p]||''])),
      content_type:$('#pe-type',m).value, yt_title:$('#pe-yttitle',m).value, yt_privacy:$('#pe-ytpriv',m).value,
      recycle_days:Number($('#pe-recycle',m).value||0), auto_publish:$('#pe-auto',m).checked,
      link_url:$('#pe-link',m).value.trim(), link_campaign:$('#pe-camp',m).value.trim()};
    const nd = $('#pe-date',m).value, nt = $('#pe-time',m).value;
    if(!locked && (nd!==schedDate || nt!==schedTime)){
      body.date = nd; body.publish_time = nt; body.publish_at = nt ? toUtcIso(nd, nt) : null; body.tz = userTz();
    }
    return body;
  };
  const save = async (quiet)=>{
    const body = collect();
    if(!body.platforms.length) throw new Error('Select at least one platform.');
    if(body.date && body.date < (App._today||'')) throw new Error('Pick today or a future date.');
    await api('/api/calendar/'+cid,{method:'PATCH', body});
    if(!quiet) toast('Post saved','good');
    await drawCalendar();
    return body;
  };
  const back = ()=>openDay(ds);
  $('#pe-x',m).onclick = back; $('#pe-cancel',m).onclick = back;
  $('#pe-save',m).onclick = async ()=>{
    const b=$('#pe-save',m); b.disabled=true;
    try{ const body = await save(); openDay(body.date || ds); }
    catch(e){ $('#pe-err',m).textContent=e.message; b.disabled=false; }
  };
  $('#pe-adapt',m).onclick = async ()=>{
    const b=$('#pe-adapt',m); b.disabled=true; b.innerHTML=`${ic('sparkles',14)} Adapting…`;
    try{
      await save(true);
      const r = await api('/api/calendar/'+cid+'/adapt',{method:'POST', body:{platforms:picker.get()}});
      Object.assign(pc, r.captions||{});
      $('#pe-caps',m).querySelectorAll('textarea').forEach(t=>{ t.value = pc[t.dataset.p]||''; });
      renderCaps();
      if(r.yt_title && !$('#pe-yttitle',m).value) $('#pe-yttitle',m).value = r.yt_title;
      toast(r.source==='ai' ? 'Captions adapted by AI — review them before saving' : 'Captions trimmed to each platform\'s limits (no AI key configured)','good',5000);
      loadChecks();
    }catch(e){ toast(e.message,'warn',5000); }
    b.disabled=false; b.innerHTML=`${ic('sparkles',14)} Adapt with AI`;
  };

  // media checks + conversion
  const loadChecks = async ()=>{
    const box = $('#pe-checks',m); if(!box) return;
    let r; try{ r = await api('/api/calendar/'+cid+'/checks'); }catch(e){ box.innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
    const info = r.media_info||{};
    const head = info.duration ? `<div class="muted">${info.width}×${info.height} · ${info.duration}s · ${info.size_mb} MB</div>` : '';
    const rows = (r.checks||[]).map(c=>`<div class="chk chk-${c.level}">${ic(c.level==='ok'?'check':(c.level==='error'?'alert':'info'),14)}
        ${c.platform?pi(c.platform,14):''} <span>${esc(c.msg)}</span>
        ${c.fix==='convert'?`<span class="chk-fix"><button class="btn ghost xs" data-conv="${c.platform}" data-mode="crop">${ic('crop',12)} Crop to fit</button>
          <button class="btn ghost xs" data-conv="${c.platform}" data-mode="pad">Pad</button></span>`:''}
        ${c.fix==='adapt'?`<button class="btn ghost xs" data-fixadapt="1">${ic('sparkles',12)} Adapt caption</button>`:''}
        ${c.level==='ok'?`<button class="btn ghost xs" data-unvar="${c.platform}">${ic('x',12)} Use original</button>`:''}</div>`).join('');
    box.innerHTML = head + (rows || `<div class="chk chk-ok">${ic('check',14)} Looks good for every selected platform.</div>`);
    box.querySelectorAll('[data-conv]').forEach(b=>b.onclick=async ()=>{
      const p=b.dataset.conv;
      try{ await save(true); await api('/api/calendar/'+cid+'/convert',{method:'POST', body:{platform:p, mode:b.dataset.mode}});
        b.closest('.chk').innerHTML = `${ic('refresh',14)} Converting for ${esc(platLabel(p))}… this can take a minute.`;
        const iv = setInterval(async ()=>{
          const s = await api(`/api/calendar/${cid}/convert-status?platform=${p}`).catch(()=>({}));
          if(s.status==='done' || s.status==='error'){ clearInterval(iv); toast(s.message, s.status==='done'?'good':'warn', 6000); loadChecks(); }
        }, 2000);
      }catch(e){ toast(e.message,'warn',6000); }
    });
    box.querySelectorAll('[data-fixadapt]').forEach(b=>b.onclick=()=>$('#pe-adapt',m).click());
    box.querySelectorAll('[data-unvar]').forEach(b=>b.onclick=async ()=>{
      try{ await api(`/api/calendar/${cid}/variant/${b.dataset.unvar}`,{method:'DELETE'}); loadChecks(); }catch(e){ toast(e.message,'warn'); }
    });
  };
  loadChecks();

  // thumbnail
  const reopen = async ()=>{ await drawCalendar(); openPostEditor(cid, ds); };
  if($('#pe-grab',m)) $('#pe-grab',m).onclick = async ()=>{
    try{ await save(true); await api('/api/calendar/'+cid+'/thumbnail',{method:'POST', body:{at:Number($('#pe-at',m).value||1)}}); toast('Cover set','good'); reopen(); }
    catch(e){ toast(e.message,'warn',5000); }
  };
  if($('#pe-thumbfile',m)) $('#pe-thumbfile',m).onchange = async (e)=>{
    const f=e.target.files[0]; if(!f) return;
    const fd=new FormData(); fd.append('file', f);
    try{ await save(true); await api('/api/calendar/'+cid+'/thumbnail',{method:'POST', body:fd}); toast('Cover uploaded','good'); reopen(); }
    catch(err){ toast(err.message,'warn'); }
  };
  if($('#pe-thumbclear',m)) $('#pe-thumbclear',m).onclick = async ()=>{
    try{ await api('/api/calendar/'+cid+'/thumbnail',{method:'DELETE'}); reopen(); }catch(e){ toast(e.message,'warn'); }
  };

  // best-time suggestions → click to fill the next matching date/time
  try{
    const bt = (await api(`/api/schedule/best-times?tz=${encodeURIComponent(userTz())}&offset=${tzOffset()}`)).best;
    const chips = [];
    picker.get().filter(p=>bt[p]).forEach(p=> (bt[p]||[]).slice(0,2).forEach(s=> chips.push({p, ...s})));
    if(chips.length && $('#pe-best',m)){
      $('#pe-best',m).innerHTML = `<span class="muted">${ic('target',13)} Suggested times:</span>` + chips.map((c,i)=>
        `<button class="bt-chip" data-bt="${i}" title="${esc(c.source)}${c.score!=null?' · score '+c.score:''}">${pi(c.p,13)} ${DOW_MON[c.dow]} ${String(c.hour).padStart(2,'0')}:00</button>`).join('');
      $('#pe-best',m).querySelectorAll('[data-bt]').forEach(b=>b.onclick=()=>{
        const c = chips[Number(b.dataset.bt)];
        const base = new Date(); base.setHours(0,0,0,0);
        for(let k=0;k<8;k++){ const dd=new Date(base); dd.setDate(base.getDate()+k);
          const wd=(dd.getDay()+6)%7; const when=new Date(dd); when.setHours(c.hour,0,0,0);
          if(wd===c.dow && when>new Date()){ $('#pe-date',m).value=`${dd.getFullYear()}-${String(dd.getMonth()+1).padStart(2,'0')}-${String(dd.getDate()).padStart(2,'0')}`;
            $('#pe-time',m).value=`${String(c.hour).padStart(2,'0')}:00`; toast('Time filled — Save post to apply','good'); break; } }
      });
    }
  }catch(e){}
}
window.openPostEditor = openPostEditor;

/* ---------- Text-only post ---------- */
function openTextPost(ds){
  const allowed = (App.user&&App.user.publish_platforms)||PLAT_ORDER;
  const picker = platformPicker(['facebook','twitter','linkedin','threads'].filter(p=>allowed.includes(p)), 'text');
  const m = el(`<div class="modal" style="max-width:560px">
    <div class="modal-head"><h3>${ic('file',18)} New text post</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Date</label><input class="f" id="tp-date" type="date" value="${esc(ds)}">
      <label class="f">Title</label><input class="f" id="tp-title" placeholder="Internal name">
      <label class="f">Text</label><textarea class="f" id="tp-cap" style="min-height:100px"></textarea>
      <label class="f">Hashtags</label><input class="f" id="tp-tags">
      <label class="f">Platforms <span class="muted">(text posts work on Facebook, X, LinkedIn and Threads)</span></label><div id="tp-plats"></div>
      <div class="err" id="tp-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="tp-go">${ic('plus',15)} Create</button></div></div>`);
  openModal(m);
  $('#tp-plats',m).appendChild(picker.el);
  $('#tp-go',m).onclick = async ()=>{
    const d = $('#tp-date',m).value;
    try{ await api('/api/calendar/text',{method:'POST', body:{date:d, title:$('#tp-title',m).value, caption:$('#tp-cap',m).value,
        hashtags:$('#tp-tags',m).value, platforms:picker.get()}});
      toast('Text post created','good'); await drawCalendar(); openDay(d); }
    catch(e){ $('#tp-err',m).textContent=e.message; }
  };
}
window.openTextPost = openTextPost;

/* ---------- Bulk upload ---------- */
function openBulkUpload(){
  const picker = platformPicker(defaultPlatforms());
  const today = App._today || new Date().toISOString().slice(0,10);
  const m = el(`<div class="modal wide" style="max-width:640px">
    <div class="modal-head"><h3>${ic('layers',18)} Bulk upload</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Media files</label>
      <div class="dropzone" id="bu-drop"><div class="dz-ico">${ic('upload',22)}</div>
        <div><b>Drop</b> many videos/images, or <span class="dz-browse">browse</span></div>
        <input type="file" id="bu-files" multiple accept="video/*,image/*" style="display:none"></div>
      <div class="muted" id="bu-count"></div>
      <label class="f">Optional CSV <span class="muted">(columns: filename, title, caption, hashtags, date, time, platforms)</span></label>
      <input class="f" type="file" id="bu-csv" accept=".csv,text/csv">
      <label class="f">How to schedule</label>
      <div class="seg" id="bu-mode"><button class="on" data-m="spread">Spread across dates</button><button data-m="queue">Use my queue slots (after approval)</button></div>
      <div class="pe-grid" id="bu-spread">
        <div><label class="f">Start date</label><input class="f" type="date" id="bu-start" value="${esc(today)}" min="${esc(today)}"></div>
        <div><label class="f">One post every</label><select class="f" id="bu-every">${[1,2,3,7].map(n=>`<option value="${n}">${n} day${n>1?'s':''}</option>`).join('')}</select></div>
        <div><label class="f">At time</label><input class="f" type="time" id="bu-time" value="10:00"></div>
      </div>
      <label class="f">Publish to</label><div id="bu-plats"></div>
      <div class="note">Posts are created as drafts. Generate captions, send them for review, and once approved they publish at their time.</div>
      <div class="err" id="bu-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="bu-go">${ic('upload',15)} Upload all</button></div></div>`);
  openModal(m);
  $('#bu-plats',m).appendChild(picker.el);
  const fi = $('#bu-files',m), drop=$('#bu-drop',m);
  const upd = ()=> $('#bu-count',m).textContent = fi.files.length ? `${fi.files.length} file(s) selected` : '';
  drop.onclick = ()=>fi.click(); fi.onchange = upd;
  drop.addEventListener('dragover', e=>{ e.preventDefault(); drop.classList.add('drag-over'); });
  drop.addEventListener('dragleave', ()=>drop.classList.remove('drag-over'));
  drop.addEventListener('drop', e=>{ e.preventDefault(); drop.classList.remove('drag-over'); if(e.dataTransfer.files.length){ fi.files=e.dataTransfer.files; upd(); } });
  let mode='spread';
  m.querySelectorAll('#bu-mode button').forEach(b=>b.onclick=()=>{ mode=b.dataset.m;
    m.querySelectorAll('#bu-mode button').forEach(x=>x.classList.toggle('on',x===b)); $('#bu-spread',m).style.display = mode==='spread'?'':'none'; });
  $('#bu-go',m).onclick = async ()=>{
    const csv = $('#bu-csv',m).files[0];
    if(!fi.files.length && !csv){ $('#bu-err',m).textContent='Add files and/or a CSV.'; return; }
    const fd = new FormData();
    [...fi.files].forEach(f=>fd.append('files', f));
    if(csv) fd.append('csv', csv);
    fd.append('start_date', $('#bu-start',m).value); fd.append('every_days', $('#bu-every',m).value);
    fd.append('time', $('#bu-time',m).value); fd.append('tz', userTz()); fd.append('offset', tzOffset());
    fd.append('platforms', JSON.stringify(picker.get())); fd.append('mode', mode);
    const b=$('#bu-go',m); b.disabled=true; b.textContent='Uploading…';
    try{ const r = await api('/api/calendar/bulk',{method:'POST', body:fd});
      toast(`${r.ids.length} post(s) added to the calendar`,'good',5000); closeModal(); drawCalendar(); loadNotifCount(); }
    catch(e){ $('#bu-err',m).textContent=e.message; b.disabled=false; b.innerHTML=`${ic('upload',15)} Upload all`; }
  };
}
window.openBulkUpload = openBulkUpload;

/* If a caption generation is still running, resume its progress display. */
async function resumeGenerating(m, ds){
  const items = (App._cal && App._cal.by_date[ds]) || [];
  for(const it of items){
    if(it.state!=='uploaded') continue;
    try{
      const s = await api('/api/calendar/'+it.id+'/genstatus');
      if(['running','starting'].includes(s.status)){
        const wrap=$('#gp-'+it.id, m), fill=$('#gpf-'+it.id, m), msg=$('#gpm-'+it.id, m);
        if(wrap) wrap.classList.remove('hidden');
        if(fill) fill.style.width=(s.percent||0)+'%';
        if(msg) msg.textContent=`${s.percent||0}% — ${s.message||''} (running in background)`;
        pollGen(it.id, ds, m);
      }
    }catch(e){}
  }
}
function pollGen(cid, ds, m){
  const fill=$('#gpf-'+cid, m), msg=$('#gpm-'+cid, m);
  const poll=setInterval(async ()=>{
    let s; try{ s=await api('/api/calendar/'+cid+'/genstatus'); }catch(e){ return; }
    if(fill) fill.style.width=(s.percent||0)+'%';
    if(msg) msg.textContent=`${s.percent||0}% — ${s.message||''}`;
    if(['done','error','idle','cancelled'].includes(s.status)){
      clearInterval(poll);
      if(s.status==='error') toast(s.message,'warn',8000);
      else if(s.status==='done' && s.warning) toast('AI couldn\u2019t analyse the video: '+s.warning,'warn',12000);
      else if(s.status==='done') toast('Title, caption, description & hashtags ready','good');
      if($('#dl-list')) { await drawCalendar(); openDay(ds); loadNotifCount(); }
    }
  }, 800);
}

/* ---------- Generate caption with live % ---------- */
async function generateCaption(cid, ds, m){
  const wrap = $('#gp-'+cid, m), msg = $('#gpm-'+cid, m), fill = $('#gpf-'+cid, m);
  const card = m.querySelector(`[data-item="${cid}"]`);
  if(card) card.querySelectorAll('.actions button').forEach(x=>x.disabled=true);
  if(wrap) wrap.classList.remove('hidden');
  const it = findItem(cid);
  let frames = [];
  if(it && (it.media_kind||'video')==='video'){
    if(msg) msg.textContent = 'Reading frames from the video…';
    if(fill) fill.style.width = '4%';
    frames = await captureFrames('/uploads/'+encodeURIComponent((it.media&&it.media[0]) || it.filename), 4);
  }
  try{ await api('/api/calendar/'+cid+'/generate',{method:'POST', body:{frames}}); pollGen(cid, ds, m); }
  catch(e){ toast(e.message,'warn'); if(card) card.querySelectorAll('.actions button').forEach(x=>x.disabled=false); }
}

/* Grab JPEG frames spread across a video in the browser (no server FFmpeg needed).
   Returns [] when the browser can't read the video. */
function captureFrames(url, n){
  return new Promise(resolve=>{
    const v = document.createElement('video'), out = [];
    let done = false;
    const finish = ()=>{ if(done) return; done = true; clearTimeout(timer); v.removeAttribute('src'); v.load(); resolve(out); };
    const timer = setTimeout(finish, 25000);
    v.muted = true; v.playsInline = true; v.preload = 'auto'; v.crossOrigin = 'anonymous';
    v.onerror = finish;
    v.onloadedmetadata = async ()=>{
      const d = v.duration;
      if(!isFinite(d) || d <= 0){ finish(); return; }
      const W = Math.min(768, v.videoWidth || 768), H = Math.round(W * (v.videoHeight || 432) / (v.videoWidth || 768));
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const ctx = c.getContext('2d');
      for(let i=0; i<n && !done; i++){
        const t = Math.min(d - 0.05, d * (0.1 + 0.8 * i / Math.max(1, n-1)));
        await new Promise(r=>{ const h = ()=>{ v.removeEventListener('seeked', h); r(); }; v.addEventListener('seeked', h); v.currentTime = t; setTimeout(h, 6000); });
        try{ ctx.drawImage(v, 0, 0, W, H); out.push(c.toDataURL('image/jpeg', 0.82)); }
        catch(e){ break; }             // e.g. a storage server without CORS: fall back to the server
      }
      finish();
    };
    v.src = url;
  });
}
window.captureFrames = captureFrames;

function prettyDate(ds){ const [y,m,d]=String(ds).split('-').map(Number); if(!y) return ds; return `${DOW[new Date(y,m-1,d).getDay()]}, ${MONTHS[m-1]} ${d}, ${y}`; }
window.renderCalendar = renderCalendar;
window.prettyDate = prettyDate;
