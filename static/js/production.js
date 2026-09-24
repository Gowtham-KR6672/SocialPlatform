/* ============================================================
   Input board (Trello-style):  Input · Processing · Completed
   - drag & drop cards between columns (or use the Move dropdown)
   - live counts at the top
   - Upload (new videos tagged NEW) + Export (CSV)
   - Remove with confirmation; every action notifies all users
   ============================================================ */
const STAT = {
  input:      {col:'Input',      chip:'input'},
  processing: {col:'Processing', chip:'processing'},
  completed:  {col:'Completed',  chip:'completed'},
};

async function renderProduction(){
  const c = $('#pageContent');
  App._prodDays = App._prodDays || 30;
  c.innerHTML = `<div class="page-head">
      <h2>Input</h2><div class="spacer"></div>
      <label class="date-sel">${ic('calendar',17)}<select id="prodDays" aria-label="Period">${[7,30,90].map(d=>
        `<option value="${d}" ${App._prodDays===d?'selected':''}>Last ${d} days</option>`).join('')}</select></label>
      ${App.readonly?'':`<button class="btn ghost" id="expVid">${ic('download',16)} Export</button>
                        <button class="btn" id="addVid">${ic('plus',16)} Upload Video</button>`}
    </div>
    <div class="stat-grid" id="prodTiles"></div>
    <div class="board v2" id="prodBoard"></div>
    <input type="file" id="prodFiles" accept="video/*" multiple style="display:none">`;
  $('#prodDays').onchange = e=>{ App._prodDays = Number(e.target.value); loadProduction(); };
  $('#prodFiles').onchange = e=>{ if(e.target.files.length) uploadFilesToStatus(e.target.files, 'input'); e.target.value=''; };
  if(!App.readonly){
    if($('#addVid')) $('#addVid').onclick = openAddVideo;
    if($('#expVid')) $('#expVid').onclick = exportBoard;
  }
  await loadProduction();
}

async function loadProduction(){
  let data;
  try{ data = await api('/api/videos'); }
  catch(e){
    $('#prodBoard').innerHTML = `<div class="empty">${ic('lock',14)} Log in to view the Input board.</div>`;
    $('#prodTiles').innerHTML=''; return;
  }
  const {videos, counts} = data;
  App._videos = videos;
  App._vidIsAdmin = !!data.is_admin;
  App._vidCanDownload = !!data.can_download;

  const navc = $('#navProdCount'); if(navc) navc.textContent = videos.length;
  const subs = $('#prodSubs');
  if(subs){
    subs.innerHTML = `
      <div class="subitem" data-sub="input"><span class="sdot input"></span> Input <span class="cnt">${counts.input}</span></div>
      <div class="subitem" data-sub="processing"><span class="sdot processing"></span> Processing <span class="cnt">${counts.processing}</span></div>
      <div class="subitem" data-sub="completed"><span class="sdot completed"></span> Completed <span class="cnt">${counts.completed}</span></div>`;
    subs.querySelectorAll('[data-sub]').forEach(s=>s.onclick=()=>{
      document.querySelectorAll('.col').forEach(col=>{
        col.style.display = (s.dataset.sub && col.dataset.status!==s.dataset.sub)?'none':'';
      });
      toast('Filtered: '+STAT[s.dataset.sub].col);
    });
  }

  const days = App._prodDays || 30;
  const sIn   = periodSeries(videos, 'created_at', days);
  const sProc = periodSeries(videos.filter(v=>v.status==='processing'), 'updated_at', days);
  const sDone = periodSeries(videos.filter(v=>v.status==='completed').map(v=>({t:v.completed_at||v.updated_at})), 't', days);
  $('#prodTiles').innerHTML =
    statCard({tone:'violet', icon:'video', n:counts.input, label:'Input', sub:'Videos added', days, ...sIn}) +
    statCard({tone:'blue', icon:'gear', n:counts.processing, label:'Processing', sub:'In progress', days, ...sProc}) +
    statCard({tone:'green', icon:'check', n:counts.completed, label:'Completed', sub:'Successfully processed', days, ...sDone});

  const board = $('#prodBoard'); board.innerHTML='';
  const EMPTY = {
    processing:{art:'gear',  t:'No videos processing', s:'Videos will appear here once processing starts.'},
    completed: {art:'check', t:'No completed videos yet', s:'Processed videos will appear here.'},
  };
  Object.keys(STAT).forEach(status=>{
    const col = el(`<div class="col col-${status}" data-status="${status}">
      <div class="col-h"><span class="col-dot"></span>${STAT[status].col}<span class="col-count">${counts[status]}</span></div>
      <div class="col-body"></div></div>`);
    const body = col.querySelector('.col-body');
    const items = videos.filter(v=>v.status===status);
    items.forEach(v=> body.appendChild(videoCard(v)));
    if(status==='input' && !App.readonly){
      const dz = el(`<div class="in-drop ${items.length?'compact':''}" role="button" tabindex="0" aria-label="Upload videos">
          <div class="in-drop-ic">${ic('cloudUpload',items.length?20:28)}</div>
          <div class="in-drop-t">Drag &amp; drop videos here</div><div class="in-drop-s">or click to upload</div>
          ${items.length?'':`<button class="btn in-drop-btn" type="button">${ic('upload',16)} Upload Videos</button>
          <div class="in-drop-f"><span>MP4</span><span>MOV</span><span>AVI</span><span>WebM</span>
            <span title="Large files may be limited by your storage plan">${ic('info',14)}</span></div>`}</div>`);
      const pick = ()=>$('#prodFiles').click();
      dz.onclick = pick; dz.onkeydown = e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); pick(); } };
      body.appendChild(dz);
    }else if(!items.length){
      const E = EMPTY[status] || {art:'video', t:'Nothing here yet', s:'Drop videos here.'};
      body.innerHTML = `<div class="col-empty">${emptyArt(E.art)}<b>${E.t}</b><span>${E.s}</span></div>`;
    }
    if(!App.readonly) makeDropzone(col, status);
    board.appendChild(col);
  });
  startCountdownTicker();
}

/* empty-column illustration: a video file with a status badge */
function emptyArt(badge){
  const g = 'ea'+Math.random().toString(36).slice(2,7);
  return `<svg class="ea" viewBox="0 0 150 120" width="150" height="120" aria-hidden="true" fill="none">
    <defs><linearGradient id="${g}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--cc-soft2)"/><stop offset="1" style="stop-color:var(--cc-soft)"/></linearGradient></defs>
    <circle cx="22" cy="40" r="2.5" style="fill:var(--cc)" opacity=".3"/><circle cx="128" cy="30" r="2.5" style="fill:var(--cc)" opacity=".3"/>
    <circle cx="136" cy="70" r="2" style="fill:var(--cc)" opacity=".25"/><circle cx="16" cy="78" r="2" style="fill:var(--cc)" opacity=".25"/>
    <circle cx="36" cy="20" r="1.8" style="fill:var(--cc)" opacity=".25"/>
    <path d="M48 14h36l18 18v62a8 8 0 0 1-8 8H48a8 8 0 0 1-8-8V22a8 8 0 0 1 8-8z" fill="url(#${g})"/>
    <path d="M84 14v12a6 6 0 0 0 6 6h12" fill="#fff" opacity=".6"/>
    <rect x="56" y="46" width="30" height="26" rx="6" style="stroke:var(--cc)" stroke-width="3"/>
    <path d="M67 53v12l9-6z" style="fill:var(--cc)"/>
    <circle cx="100" cy="88" r="17" style="fill:${badge==='check'?'var(--cc)':'#fff'}"/>
    ${badge==='check'
      ? '<path d="m92 88 5.5 5.5L108 83" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>'
      : `<g transform="translate(88 76)" style="stroke:var(--cc)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS.gear}</g>`}
  </svg>`;
}

function tile(cls, n, label){
  return `<div class="tile ${cls}"><div class="n">${n}</div><div class="l">${label}</div></div>`;
}

function videoCard(v){
  const readonly = App.readonly;
  const isNew = v.status==='input';
  const del = readonly ? '' : `<button class="btn danger sm" data-del="${v.id}">Remove</button>`;
  const focus = (App.focusVideo && Number(App.focusVideo)===v.id) ? ' focus-flash' : '';
  // deadline date/time + live countdown + completion stamp
  const dueLine = v.deadline ? `<div class="vdue">${ic('calendar',12)} Due: ${fmtLocal(v.deadline)}</div>` : '';
  const cd = v.deadline
    ? `<div class="countdown" data-deadline="${esc(v.deadline)}" ${v.completed_at?`data-done="${esc(v.completed_at)}"`:''}>${ic('hourglass',12)} …</div>` : '';
  const doneInfo = v.completed_at
    ? `<div class="vdone">${ic('check',12)} Completed by ${esc(v.completed_by||'—')} · ${fmtTime(v.completed_at)}</div>` : '';
  const completeBtn = (!readonly && v.status!=='completed')
    ? `<button class="btn green sm" data-complete="${v.id}">${ic('check',14)} Mark Completed</button>` : '';
  // Processing cards get a "Chat updates" button so the team can post progress
  // updates on the video; unread messages show as a badge.
  const unread = v.chat_unread||0;
  const chatBtn = (!readonly && v.status==='processing')
    ? `<button class="btn ghost sm chat-btn" data-chat="${v.id}" title="Discuss progress on this video">${ic('message',14)} Chat updates${
        unread?` <span class="chat-unread">${unread}</span>`:(v.chat_count?` <span class="chat-cnt">${v.chat_count}</span>`:'')}</button>` : '';
  const card = el(`<div class="vcard tcard${focus}" ${readonly?'':'draggable="true"'} data-vid="${v.id}">
     <div class="t">${esc(v.title)} ${isNew?'<span class="chip new">NEW</span>':''}</div>
     <div class="meta">by ${esc(v.owner||'—')} · ${fmtTime(v.updated_at)}</div>
     ${dueLine}${cd}${doneInfo}
     ${v.description?`<div class="vdesc">${esc(v.description)}</div>`:''}
     <div class="row"><span class="chip ${v.status}">${STAT[v.status].col}</span>${chatBtn}${completeBtn}${del}</div>
   </div>`);
  const cb = card.querySelector('[data-complete]'); if(cb) cb.onclick = (e)=>{ e.stopPropagation(); changeTag(v.id, 'completed'); };
  const chb = card.querySelector('[data-chat]'); if(chb) chb.onclick = (e)=>{ e.stopPropagation(); openVideoChat(v.id); };
  // clicking the card body (not a button) opens the edit/detail view
  card.addEventListener('click', (e)=>{ if(!e.target.closest('button')) openVideoDetail(v); });
  if(!readonly){
    card.querySelector('[data-del]').onclick = (e)=>{ e.stopPropagation(); removeVideo(v); };
    card.addEventListener('dragstart', e=>{ e.dataTransfer.setData('text/plain', String(v.id)); card.classList.add('dragging'); });
    card.addEventListener('dragend',   ()=> card.classList.remove('dragging'));
  }
  if(focus){ App.focusVideo=null; setTimeout(()=>{ card.scrollIntoView({behavior:'smooth',block:'center'}); openVideoDetail(v); }, 250); }
  return card;
}

/* ---------- Video detail: description + comments + revise ---------- */
async function openVideoDetail(v){
  const isAdmin = App.user && App.user.role==='admin';
  const preview = v.filename
    ? `<video class="video-preview" src="/uploads/${encodeURIComponent(v.filename)}" controls></video>` : '';
  // Full edit form (admin) — title, description, hashtags, deadline. Users see read-only.
  const editForm = isAdmin ? `
      <label class="f">Title</label>
      <input class="f" id="vd-title" value="${esc(v.title||'')}">
      <label class="f">Description</label>
      <textarea class="f" id="vd-desc" placeholder="Describe this video / required changes…">${esc(v.description||'')}</textarea>
      <label class="f">Hashtags</label>
      <input class="f" id="vd-tags" value="${esc(v.hashtags||'')}" placeholder="#reels #viral …">
      <label class="f">Deadline</label>
      <input class="f" id="vd-deadline" type="datetime-local" value="${esc((v.deadline||'').slice(0,16))}">
      <div style="margin:10px 0 4px"><button class="btn sm" id="vd-save">Save changes</button></div>`
    : `<label class="f">Description</label>
       <div class="vd-desc-ro">${v.description?esc(v.description):'<span class="muted-i">No description yet.</span>'}</div>
       ${v.hashtags?`<label class="f">Hashtags</label><div class="vd-desc-ro">${esc(v.hashtags)}</div>`:''}
       ${v.deadline?`<label class="f">Deadline</label><div class="vd-desc-ro">${fmtLocal(v.deadline)}</div>`:''}`;
  // Download only for access-granted users (no locked button shown otherwise)
  const dl = v.can_download ? `<a class="btn ghost sm" href="/api/videos/${v.id}/download">${ic('download',14)} Download</a>` : '';
  const m = el(`<div class="modal wide" style="max-width:640px">
    <div class="modal-head"><h3>Video details</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <div class="meta" style="margin-bottom:8px">by ${esc(v.owner||'—')} · <span class="chip ${v.status}">${STAT[v.status].col}</span></div>
      ${preview}
      ${editForm}
      <div style="margin:12px 0;display:flex;gap:8px;flex-wrap:wrap">
        ${dl}
        <button class="btn sm" id="vd-chat">${ic('message',14)} Open chat</button>
        <label class="btn ghost sm" style="cursor:pointer">${ic('refresh',14)} Upload revised version
          <input type="file" id="vd-revise" accept="video/*" style="display:none"></label>
      </div>
      <div class="note">Discussion for this video now happens in <b>Chat</b> — click <b>Open chat</b>.</div>
    </div></div>`);
  openModal(m);
  if(isAdmin && $('#vd-save',m)) $('#vd-save',m).onclick = async ()=>{
    const body = {title:$('#vd-title',m).value, description:$('#vd-desc',m).value,
                  hashtags:$('#vd-tags',m).value, deadline:$('#vd-deadline',m).value};
    try{ await api('/api/videos/'+v.id, {method:'PATCH', body});
      Object.assign(v, body); toast('Saved','good'); loadProduction();
    }catch(e){ toast(e.message,'warn'); }
  };
  $('#vd-chat',m).onclick = ()=>{ closeModal(); openVideoChat(v.id); };
  $('#vd-revise',m).onchange = async (e)=>{
    const f = e.target.files[0]; if(!f) return;
    const fd = new FormData(); fd.append('file', f);
    toast('Uploading revised version…');
    try{ await api('/api/videos/'+v.id+'/revise', {method:'POST', body:fd});
      toast('Revised version uploaded — admins notified','good'); closeModal(); loadProduction(); loadNotifCount();
    }catch(err){ toast(err.message,'warn'); }
  };
}
window.openVideoDetail = openVideoDetail;

/* ---------- live deadline countdown ---------- */
function fmtDur(ms){
  const s=Math.floor(Math.abs(ms)/1000);
  const d=Math.floor(s/86400), h=Math.floor(s%86400/3600), m=Math.floor(s%3600/60);
  const parts=[]; if(d)parts.push(d+'d'); if(h||d)parts.push(h+'h'); parts.push(m+'m');
  return parts.join(' ');
}
function tickCountdowns(){
  document.querySelectorAll('.countdown[data-deadline]').forEach(elc=>{
    const dl = new Date(elc.dataset.deadline);
    if(isNaN(dl)){ elc.textContent=''; return; }
    if(elc.dataset.done){
      // completed_at is UTC; deadline is local — parse completed as UTC
      const ds = elc.dataset.done;
      const done = new Date(/[zZ]|[+\-]\d\d:?\d\d$/.test(ds) ? ds : ds+'Z');
      const early = dl - done;                 // +early, -late
      elc.classList.toggle('over', early<0);
      elc.classList.add('done');
      elc.innerHTML = ic('check',12) + (early>=0 ? ` On time (+${fmtDur(early)} early)` : ` Late (-${fmtDur(early)})`);
      return;
    }
    const diff = dl - new Date();
    if(diff>=0){ elc.classList.remove('over'); elc.innerHTML = `${ic('hourglass',12)} ${fmtDur(diff)} left`; }
    else{ elc.classList.add('over'); elc.innerHTML = `${ic('alert',12)} Overdue -${fmtDur(diff)}`; }
  });
}
let _cdTimer=null;
function startCountdownTicker(){ if(_cdTimer) return; tickCountdowns(); _cdTimer=setInterval(tickCountdowns, 1000); }
window.startCountdownTicker = startCountdownTicker;

/* make a column accept dropped cards AND dropped video files (upload) */
function makeDropzone(col, status){
  col.addEventListener('dragover', e=>{ e.preventDefault(); if(e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; col.classList.add('drag-over'); });
  col.addEventListener('dragleave', e=>{ if(!col.contains(e.relatedTarget)) col.classList.remove('drag-over'); });
  col.addEventListener('drop', e=>{
    e.preventDefault(); col.classList.remove('drag-over');
    // 1) files dropped from the desktop -> upload into this column
    const files = e.dataTransfer && e.dataTransfer.files;
    if(files && files.length){ uploadFilesToStatus(files, status); return; }
    // 2) an existing card dragged between columns -> move it
    const id = e.dataTransfer.getData('text/plain');
    if(id) changeTag(Number(id), status);
  });
}

async function uploadFilesToStatus(files, status){
  const vids = [...files].filter(f=> (f.type||'').startsWith('video/') || /\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(f.name));
  if(!vids.length){ toast('Drop a video file','warn'); return; }
  toast(`Uploading ${vids.length} video(s) to ${STAT[status].col}…`);
  for(const f of vids){
    try{
      const fd = new FormData(); fd.append('file', f); fd.append('title', f.name);
      const r = await api('/api/videos', {method:'POST', body:fd});
      if(status!=='input' && r.id) await api('/api/videos/'+r.id, {method:'PATCH', body:{status}});
    }catch(e){ toast('Upload failed: '+e.message,'warn',5000); }
  }
  toast('Uploaded','good'); loadProduction(); loadNotifCount();
}
window.uploadFilesToStatus = uploadFilesToStatus;

async function changeTag(id, status){
  try{
    await api('/api/videos/'+id, {method:'PATCH', body:{status}});
    toast('Moved to '+STAT[status].col, 'good');
    loadProduction(); loadNotifCount();
  }catch(e){ toast(e.message,'warn'); loadProduction(); }
}

function removeVideo(v){
  confirmBox('Remove this video?',
    `"${v.title}" will be removed and everyone will be notified. This can't be undone.`,
    async ()=>{
      await api('/api/videos/'+v.id, {method:'DELETE'});
      toast('Removed — all users notified','warn');
      loadProduction(); loadNotifCount();
    }, 'Yes, remove');
}

/* Export the board as CSV */
function exportBoard(){
  const rows = [['Title','Column','Owner','Updated']];
  (App._videos||[]).forEach(v=> rows.push([v.title, STAT[v.status]?STAT[v.status].col:v.status, v.owner||'', v.updated_at||'']));
  const csv = rows.map(r=> r.map(c=>`"${String(c).replace(/"/g,'""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'input-board.csv';
  document.body.appendChild(a); a.click(); a.remove();
  toast('Board exported to CSV','good');
}

/* upload / add video modal */
function openAddVideo(){
  const m = el(`<div class="modal">
    <div class="modal-head"><h3>Upload video</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Title</label><input class="f" id="av-title" placeholder="e.g. Village Innovation Reel">
      <label class="f">Video file (optional)</label>
      <div class="dropzone" id="av-drop"><div class="dz-ico">${ic('upload',22)}</div>
        <div><b>Drag &amp; drop</b> a video here, or <span class="dz-browse">browse</span></div>
        <input id="av-file" type="file" accept="video/*" style="display:none"></div>
      <label class="f">Deadline (optional)</label>
      <input class="f" id="av-deadline" type="datetime-local" title="When this task is due">
      <div id="av-preview" class="pre-list"></div>
      <div class="err" id="av-err"></div>
      <div class="note">New videos land in the <b>Input</b> column tagged <b>NEW</b> and everyone is notified.
        Set a <b>deadline</b> to show a live countdown on the card. Move cards by <b>drag &amp; drop</b> between columns.</div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="av-go">Add to Input</button></div></div>`);
  openModal(m);
  const fileInput = $('#av-file',m), drop = $('#av-drop',m);
  const showPreview = ()=>{
    const box=$('#av-preview',m); box.innerHTML='';
    const f=fileInput.files[0]; if(!f) return;
    const v=document.createElement('video'); v.src=URL.createObjectURL(f); v.controls=true; v.className='video-preview';
    box.appendChild(v);
  };
  fileInput.onchange = showPreview;
  drop.onclick = ()=> fileInput.click();
  drop.addEventListener('dragover', e=>{ e.preventDefault(); drop.classList.add('drag-over'); });
  drop.addEventListener('dragleave', ()=> drop.classList.remove('drag-over'));
  drop.addEventListener('drop', e=>{ e.preventDefault(); drop.classList.remove('drag-over');
    if(e.dataTransfer.files.length){ fileInput.files=e.dataTransfer.files; showPreview(); } });
  $('#av-go',m).onclick = async ()=>{
    const title = $('#av-title',m).value.trim();
    const file  = fileInput.files[0];
    const deadline = $('#av-deadline',m).value;
    if(!title && !file){ $('#av-err',m).textContent='Enter a title or choose a file.'; return; }
    try{
      if(file){
        const fd = new FormData(); fd.append('file', file); fd.append('title', title||file.name);
        if(deadline) fd.append('deadline', deadline);
        await api('/api/videos', {method:'POST', body:fd});
      }else{
        await api('/api/videos', {method:'POST', body:{title, deadline}});
      }
      closeModal(); toast('Added to Input (NEW) — all users notified','good');
      loadProduction(); loadNotifCount();
    }catch(e){ $('#av-err',m).textContent = e.message; }
  };
}
window.renderProduction = renderProduction;

/* ============================================================
   REPORTS — deadline vs completion performance
   ============================================================ */
function reportDur(sec){
  const s=Math.floor(Math.abs(sec));
  const d=Math.floor(s/86400), h=Math.floor(s%86400/3600), m=Math.floor(s%3600/60);
  const parts=[]; if(d)parts.push(d+'d'); if(h||d)parts.push(h+'h'); if(!d)parts.push(m+'m');
  return parts.join(' ')||'0m';
}
/* Correct on-time delta (seconds, +early / -late):
   deadline is LOCAL time the admin picked; completed_at is UTC. Parse each
   accordingly so the difference is real (fixes the timezone-offset error). */
function reportDeltaSeconds(v){
  if(!v.deadline || !v.completed_at) return null;
  const dl = new Date(v.deadline);                       // local naive -> local
  const cp = new Date(/[zZ]|[+\-]\d\d:?\d\d$/.test(v.completed_at) ? v.completed_at : v.completed_at+'Z'); // UTC -> absolute
  if(isNaN(dl) || isNaN(cp)) return null;
  return (dl.getTime() - cp.getTime())/1000;             // + = finished before deadline
}
async function renderReports(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="page-head"><h2>Reports</h2><div class="spacer"></div>
     <button class="btn ghost sm" id="rep-export">${ic('download',14)} Export CSV</button></div>
     <div id="rep-stats" class="user-stats"></div>
     <div id="rep-body"><div class="loading">Loading…</div></div>`;
  let data; try{ data = await api('/api/reports'); }catch(e){ $('#rep-body').innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  const rows = data.videos;
  const body = $('#rep-body');
  // compute correct on-time deltas + on-time/late tallies
  let onTime=0, late=0;
  rows.forEach(v=>{ v._delta = reportDeltaSeconds(v); if(v._delta!=null){ if(v._delta>=0) onTime++; else late++; } });
  $('#rep-stats').innerHTML = `
     <div class="ustat green"><b>${data.completed_count||0}</b><span>Completed tasks</span></div>
     <div class="ustat"><b>${data.total||rows.length}</b><span>Total videos</span></div>
     <div class="ustat green"><b>${onTime}</b><span>On time / early</span></div>
     <div class="ustat" style="border-top-color:var(--red)"><b>${late}</b><span>Late</span></div>`;
  if(!rows.length){ body.innerHTML='<div class="empty">No videos yet.</div>'; return; }
  const perf = (v)=>{
    if(v._delta===null || v._delta===undefined){
      return v.completed_at ? '<span class="perf none">No deadline</span>'
           : (v.deadline ? '<span class="perf pending">In progress</span>' : '<span class="perf none">—</span>');
    }
    return v._delta>=0
      ? `<span class="perf early">+${reportDur(v._delta)} early</span>`
      : `<span class="perf late">-${reportDur(v._delta)} late</span>`;
  };
  body.innerHTML = `<div class="rep-table-wrap"><table class="rep-table">
    <thead><tr><th>Video</th><th>Uploaded by</th><th>Upload date</th><th>Deadline</th>
      <th>Completed by</th><th>Completed at</th><th>On-time?</th></tr></thead>
    <tbody>${rows.map(v=>`<tr>
       <td class="rep-name">${esc(v.title)}</td>
       <td>${esc(v.owner||'—')}</td>
       <td>${v.created_at?fmtTime(v.created_at):'—'}</td>
       <td>${v.deadline?fmtLocal(v.deadline):'—'}</td>
       <td>${esc(v.completed_by||'—')}</td>
       <td>${v.completed_at?fmtTime(v.completed_at):'—'}</td>
       <td>${perf(v)}</td>
     </tr>`).join('')}</tbody></table></div>`;
  $('#rep-export').onclick = ()=>{
    const head=['Video','Uploaded by','Upload date','Deadline','Completed by','Completed at','On-time'];
    const lines=[head].concat(rows.map(v=>[v.title, v.owner||'', v.created_at||'', v.deadline||'', v.completed_by||'', v.completed_at||'',
       (v._delta==null?'':(v._delta>=0?'+':'-')+reportDur(v._delta)+(v._delta>=0?' early':' late'))]));
    const csv=lines.map(r=>r.map(x=>`"${String(x).replace(/"/g,'""')}"`).join(',')).join('\n');
    const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'})); a.download='reports.csv';
    document.body.appendChild(a); a.click(); a.remove(); toast('Reports exported','good');
  };
}
window.renderReports = renderReports;
function fmtLocal(s){ try{ const d=new Date(s); return isNaN(d)?s:d.toLocaleString(); }catch(e){ return s; } }
