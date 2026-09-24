/* ============================================================
   Content Writing panel
   Enter a title -> the Claude API writes the full content,
   following the SuperAdmin's content-writing guidelines.
   ============================================================ */
async function renderContent(){
  const c = $('#pageContent');
  let s = {content_provider:'claude', claude_key_set:false, claude_model:'', can_view_creds:false};
  try{ s = await api('/api/settings/content'); }catch(e){}
  App._contentSettings = s;

  // Show a simple green "AI Connected" status (engine name is not exposed).
  const aiStatus = s.claude_key_set
    ? `<span class="ai-connected">${ic('check',13)} AI Connected</span>`
    : `<span class="ai-disconnected">${ic('x',13)} AI Not Connected</span>`;

  c.innerHTML = `<div class="page-head"><h2>Content Writing</h2><div class="spacer"></div>
      ${aiStatus}
      ${s.can_view_creds?`<button class="btn ghost" id="cwSettings" style="margin-left:10px">${ic('sliders',14)} AI settings</button>`:''}</div>

    <div class="cw-input">
      <input class="f" id="cw-title" placeholder="Enter a title, e.g. “5 ways AI is changing real-estate marketing”">
      <button class="btn" id="cw-go">Generate content</button>
    </div>
    <div class="err" id="cw-err"></div>
    <div class="gen-progress hidden" id="cw-prog"><div class="bar"><div class="fill" id="cw-fill"></div></div>
      <div class="gp-msg" id="cw-msg"></div></div>

    <div id="cw-output"></div>

    <h4 class="cw-h">Recent content</h4>
    <div id="cw-history"></div>`;

  const setBtn=$('#cwSettings'); if(setBtn) setBtn.onclick = openContentSettings;
  $('#cw-go').onclick = generateContent;
  $('#cw-title').addEventListener('keydown', e=>{ if(e.key==='Enter') generateContent(); });
  loadContentHistory();

  // RESUME: if a generation is still running (started earlier, kept running in
  // the background while on another page), reconnect its progress. If one just
  // finished while we were away, show its result now.
  if(App._contentJob){
    const prog=$('#cw-prog'); if(prog) prog.classList.remove('hidden');
    const btn=$('#cw-go'); if(btn){ btn.disabled=true; btn.textContent='Generating…'; }
    watchContentJob();
  }else if(App._lastContent){
    renderOutput(App._lastContent); App._lastContent=null;
  }
}

async function generateContent(){
  const title = $('#cw-title').value.trim();
  if(!title){ $('#cw-err').textContent='Enter a title.'; return; }
  $('#cw-err').textContent='';
  const btn = $('#cw-go'); btn.disabled=true; btn.textContent='Generating…';
  App._cwTitle = title; App._cwPct = 8;
  const prog = $('#cw-prog'); if(prog) prog.classList.remove('hidden');
  paintContentProgress('starting…');
  try{
    // start a BACKGROUND job; it keeps running even if you navigate away
    const start = await api('/api/content/generate', {method:'POST', body:{title}});
    App._contentJob = start.job_id;
    watchContentJob();
  }catch(e){
    if(prog) prog.classList.add('hidden');
    $('#cw-err').textContent = e.message;
    btn.disabled=false; btn.textContent='Generate content';
  }
}

/* Draw the progress bar with the provided TITLE and a PERCENTAGE. */
function paintContentProgress(msgText){
  const prog=$('#cw-prog'), fill=$('#cw-fill'), msg=$('#cw-msg');
  if(prog) prog.classList.remove('hidden');
  const pct = Math.round(App._cwPct||0);
  if(fill) fill.style.width = pct+'%';
  if(msg) msg.innerHTML = `<b>${pct}%</b> · AI is writing “${esc(App._cwTitle||'')}”… ${msgText?('· '+esc(msgText)):''}`;
}

/* A single resilient watcher: keeps polling the background job across page
   switches and updates whatever Content-Writing DOM is currently rendered.
   The percentage advances smoothly (the AI call is one long step server-side). */
function watchContentJob(){
  if(App._cwPoll) return;                 // already watching
  App._cwPoll = setInterval(async ()=>{
    const jobId = App._contentJob;
    if(!jobId){ clearInterval(App._cwPoll); App._cwPoll=null; return; }
    let s; try{ s = await api('/api/content/genstatus/'+jobId); }catch(e){ return; }
    const prog=$('#cw-prog'), fill=$('#cw-fill'), msg=$('#cw-msg'), btn=$('#cw-go');
    if(s.status==='running' || s.status==='starting' || !s.status){
      // creep the percentage up to 90% while the model works
      App._cwPct = Math.min(90, Math.max(App._cwPct||8, s.percent||0) + 4);
      paintContentProgress(s.message);
    }
    if(s.status==='done'){
      clearInterval(App._cwPoll); App._cwPoll=null; App._contentJob=null;
      App._cwPct = 100;
      const result={id:s.id, title:s.title, body:s.body, provider:s.provider, hashtags:s.hashtags};
      if($('#cw-output')){ paintContentProgress('done'); renderOutput(result); loadContentHistory();
        if(prog) setTimeout(()=>prog.classList.add('hidden'),700); }
      else{ App._lastContent = result; }   // show it when we return to the page
      if(btn){ btn.disabled=false; btn.textContent='Generate content'; }
      toast('Content ready','good');
    }else if(s.status==='error' || s.status==='cancelled'){
      clearInterval(App._cwPoll); App._cwPoll=null; App._contentJob=null;
      if($('#cw-err')) $('#cw-err').textContent = s.status==='cancelled' ? 'Cancelled.' : (s.message||'Generation failed');
      if(prog) prog.classList.add('hidden');
      if(btn){ btn.disabled=false; btn.textContent='Generate content'; }
    }
  }, 1500);
}
window.watchContentJob = watchContentJob;

let _saveTimer = null;
function renderOutput(it){
  // accept (itemObject) or legacy (title, body, provider)
  if(typeof it === 'string'){ it = {title:arguments[0], body:arguments[1], provider:arguments[2]}; }
  App._curContent = Object.assign({}, it);
  const box = $('#cw-output');
  box.innerHTML = `<div class="cw-card" data-cid="${it.id||''}">
      <div class="cw-card-head">
        <button class="btn ghost sm cw-toggle" id="cw-toggle" title="Collapse / expand">${ic('chevDown',14)}</button>
        <input class="cw-title-in" id="cw-title-edit" value="${esc(it.title||'')}">
        <span class="chip inprogress">AI</span>
        <span class="save-ind" id="cw-save">Saved</span>
        <div style="flex:1"></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn ghost sm" id="cw-editbtn">${ic('edit',14)} Edit</button>
          <button class="btn ghost sm" id="cw-copy">Copy</button>
          <div class="dl-menu">
            <button class="btn sm" id="cw-dlbtn">${ic('download',14)} Download ${ic('chevDown',12)}</button>
            <div class="dl-list hidden" id="cw-dllist">
              <button data-fmt="docx">Word (.docx)</button>
              <button data-fmt="pdf">PDF (.pdf)</button>
              <button data-fmt="md">Markdown (.md)</button>
            </div>
          </div>
        </div>
      </div>
      <div class="cw-collapse" id="cw-collapse">
        <div class="cw-body md" id="cw-view">${mdToHtml(it.body||'')}</div>
        <textarea class="cw-edit hidden" id="cw-edit"></textarea>
        <div class="cw-tags" id="cw-tags">
          <div class="cw-tags-head"><b>Recommended hashtags</b>
            <button class="btn ghost sm" id="cw-tags-copy" title="Copy hashtags">Copy</button></div>
          <div class="cw-tags-chips" id="cw-tags-view"></div>
          <textarea class="cw-edit hidden" id="cw-tags-edit"></textarea>
        </div>
      </div>
    </div>`;
  const view=$('#cw-view',box), edit=$('#cw-edit',box), ind=$('#cw-save',box);
  edit.value = it.body||'';

  // ---- Recommended hashtags (analysed from content + trending on Google) ----
  const tagsWrap=$('#cw-tags',box), tagsView=$('#cw-tags-view',box), tagsEdit=$('#cw-tags-edit',box);
  const renderTags = (str)=>{
    const list=(str||'').split(/\s+/).map(t=>t.trim()).filter(Boolean)
                 .map(t=> t[0]==='#'? t : '#'+t.replace(/[^A-Za-z0-9]/g,''));
    App._curContent.hashtags = list.join(' ');
    tagsEdit.value = App._curContent.hashtags;
    if(!list.length){ tagsWrap.classList.add('hidden'); return; }
    tagsWrap.classList.remove('hidden');
    tagsView.innerHTML = list.map(t=>`<span class="tag-chip">${esc(t)}</span>`).join('');
  };
  renderTags(it.hashtags||'');
  $('#cw-tags-copy',box).onclick = ()=> navigator.clipboard
      .writeText(App._curContent.hashtags||'').then(()=>toast('Hashtags copied','good'));

  // Open / close (collapse / expand) the content body
  const card=box.querySelector('.cw-card'), collapse=$('#cw-collapse',box), tog=$('#cw-toggle',box);
  tog.onclick = ()=>{
    const closed = card.classList.toggle('closed');
    collapse.classList.toggle('hidden', closed);
    tog.innerHTML = closed ? ic('chevRight',14) : ic('chevDown',14);
    tog.title = closed ? 'Expand' : 'Collapse';
  };

  $('#cw-copy',box).onclick = ()=> navigator.clipboard.writeText(App._curContent.body||'').then(()=>toast('Copied','good'));

  // Edit / Preview toggle
  let editing=false;
  $('#cw-editbtn',box).onclick = ()=>{
    editing=!editing;
    edit.classList.toggle('hidden', !editing);
    view.classList.toggle('hidden', editing);
    tagsEdit.classList.toggle('hidden', !editing);
    tagsView.classList.toggle('hidden', editing);
    $('#cw-editbtn',box).innerHTML = editing ? `${ic('eye',14)} Preview` : `${ic('edit',14)} Edit`;
    if(!editing){ view.innerHTML = mdToHtml(App._curContent.body||''); renderTags(tagsEdit.value); }
    else edit.focus();
  };

  // auto-save (title + body), debounced
  const mark = (t)=>{ if(ind){ ind.textContent=t; ind.className='save-ind'+(t==='Saved'?' ok':''); } };
  const scheduleSave = ()=>{
    App._curContent.body = edit.value;
    App._curContent.title = $('#cw-title-edit',box).value;
    App._curContent.hashtags = tagsEdit.value.trim();
    if(!App._curContent.id){ return; }   // only saved items autosave
    mark('Saving…');
    clearTimeout(_saveTimer);
    _saveTimer = setTimeout(async ()=>{
      try{ await api('/api/content/'+App._curContent.id,{method:'PATCH',
             body:{title:App._curContent.title, body:App._curContent.body,
                   hashtags:App._curContent.hashtags}});
        mark('Saved'); loadContentHistory();
      }catch(e){ mark('Save failed'); }
    }, 800);
  };
  edit.addEventListener('input', scheduleSave);
  tagsEdit.addEventListener('input', scheduleSave);
  $('#cw-title-edit',box).addEventListener('input', scheduleSave);

  // download menu
  const dl=$('#cw-dllist',box);
  $('#cw-dlbtn',box).onclick = (e)=>{ e.stopPropagation(); dl.classList.toggle('hidden'); };
  document.addEventListener('click', ()=> dl && dl.classList.add('hidden'), {once:true});
  dl.querySelectorAll('[data-fmt]').forEach(b=>b.onclick=()=>{ dl.classList.add('hidden'); downloadContent(b.dataset.fmt); });

  box.scrollIntoView({behavior:'smooth', block:'nearest'});
}

function downloadContent(fmt){
  const it = App._curContent||{};
  if(fmt==='md'){
    const blob=new Blob([`# ${it.title||''}\n\n${it.body||''}`],{type:'text/markdown'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
    a.download=((it.title||'content').slice(0,40).replace(/[^a-z0-9]+/gi,'_')||'content')+'.md';
    document.body.appendChild(a); a.click(); a.remove(); return;
  }
  if(!it.id){ toast('Generate/save first to export Word or PDF','warn'); return; }
  // server-side docx/pdf — fetch so we can surface a real error (e.g. python-docx
  // missing) instead of navigating the page to a JSON error, and force a proper
  // download with the right filename.
  const ext = fmt==='pdf' ? 'pdf' : 'docx';
  const fname = ((it.title||'content').slice(0,40).replace(/[^a-z0-9]+/gi,'_')||'content')+'.'+ext;
  toast(`Preparing ${ext.toUpperCase()}…`);
  fetch('/api/content/'+it.id+'/download?fmt='+fmt)
    .then(async (r)=>{
      const ct = r.headers.get('content-type')||'';
      if(!r.ok || ct.includes('application/json')){
        let msg = `Could not build the ${ext.toUpperCase()} file.`;
        try{ const j = await r.json(); if(j.error) msg = j.error; }catch(e){}
        throw new Error(msg);
      }
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = fname;
      document.body.appendChild(a); a.click();
      setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 1500);
      toast(`${ext.toUpperCase()} downloaded`,'good');
    })
    .catch(e=>toast(e.message,'warn', 6000));
}

async function loadContentHistory(){
  const box=$('#cw-history'); if(!box) return;
  try{
    const d = await api('/api/content');
    if(!d.items.length){ box.innerHTML=`<div class="empty">No content yet — generate your first piece above.</div>`; return; }
    box.innerHTML='';
    d.items.forEach(it=>{
      const row = el(`<div class="cw-hist">
          <div class="cw-hist-main"><b>${esc(it.title)}</b>
            <span class="cw-meta">AI · ${fmtTime(it.created_at)}</span></div>
          <div style="display:flex;gap:6px">
            <button class="btn ghost sm" data-open>Open</button>
            <button class="btn danger sm" data-del>Delete</button></div>
        </div>`);
      row.querySelector('[data-open]').onclick=()=> renderOutput({id:it.id, title:it.title, body:it.body, provider:it.provider, hashtags:it.hashtags});
      row.querySelector('[data-del]').onclick=async ()=>{ await api('/api/content/'+it.id,{method:'DELETE'}); loadContentHistory(); };
      box.appendChild(row);
    });
  }catch(e){ box.innerHTML=''; }
}

/* AI settings for content (Claude API key + model + writing guidelines).
   Visible only to credential-holders (SuperAdmin or a granted user). */
async function openContentSettings(){
  let s = App._contentSettings || {};
  try{ s = await api('/api/settings/content'); }catch(e){}
  if(!s.can_view_creds){
    toast('Only the SuperAdmin can change AI credentials.','warn'); return;
  }
  // pull the current model + guidelines from the unified credentials endpoint
  let cfg = {};
  try{ cfg = await api('/api/oauth/config'); }catch(e){}
  const m = el(`<div class="modal">
    <div class="modal-head"><h3>AI settings</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">API key ${s.claude_key_set?'(set — leave blank to keep)':''}</label>
      <input class="f" id="cs-ckey" type="password" placeholder="${s.claude_key_set?'••••••••':'Enter your AI API key'}">
      <label class="f">Model</label>
      <input class="f" id="cs-model" value="${esc(cfg.claude_model||s.claude_model||'')}" placeholder="claude-3-5-sonnet-latest">
      <label class="f">Content-writing guidelines</label>
      <textarea class="f" id="cs-guide" rows="5" placeholder="Tone, voice, do/don't, brand rules… applied to captions and written content.">${esc(cfg.content_guidelines||'')}</textarea>
      <div class="note">The API key is stored server-side and used only to call the AI API.
        Guidelines are applied to both Caption &amp; Hashtags and Content Writing.
        Never paste keys into chat or other public places.</div>
      <div id="cs-test-result" class="cs-test"></div>
      <div class="err" id="cs-err"></div>
    </div>
    <div class="modal-foot">
      <button class="btn ghost" id="cs-test">Test connection</button>
      <div style="flex:1"></div>
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="cs-save">Save</button></div></div>`);
  openModal(m);
  const settingsBody = ()=>{
    const body={};
    const k=$('#cs-ckey',m).value.trim(); if(k) body.claude_api_key=k;
    body.claude_model=$('#cs-model',m).value.trim();
    body.content_guidelines=$('#cs-guide',m).value;
    return body;
  };
  $('#cs-test',m).onclick = async ()=>{
    const res=$('#cs-test-result',m); res.className='cs-test'; res.textContent='Testing…';
    const btn=$('#cs-test',m); btn.disabled=true;
    try{
      const b={}; const k=$('#cs-ckey',m).value.trim(); if(k) b.claude_api_key=k;
      b.claude_model=$('#cs-model',m).value.trim();
      const r = await api('/api/settings/content/test',{method:'POST', body:b});
      res.className = 'cs-test '+(r.ok?'ok':'bad');
      res.innerHTML = ic(r.ok?'check':'x',13)+' '+esc(r.message);
    }catch(e){ res.className='cs-test bad'; res.innerHTML=ic('x',13)+' '+esc(e.message); }
    finally{ btn.disabled=false; }
  };
  $('#cs-save',m).onclick = async ()=>{
    try{ await api('/api/settings/content',{method:'POST', body:settingsBody()}); toast('AI settings saved','good');
      closeModal(); renderContent(); if(window.loadAiStatus) loadAiStatus(); }
    catch(e){ $('#cs-err',m).textContent=e.message; }
  };
}

/* minimal Markdown -> HTML (headings, bold, italics, lists, paragraphs) */
function mdToHtml(md){
  const lines = (md||'').split('\n');
  let html='', inList=false;
  const inline = t => esc(t)
    .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>')
    .replace(/(^|[^*])\*(?!\*)(.+?)\*/g,'$1<i>$2</i>')
    .replace(/`(.+?)`/g,'<code>$1</code>');
  for(let raw of lines){
    const line = raw.replace(/\s+$/,'');
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if(h){ if(inList){html+='</ul>';inList=false;} const lvl=h[1].length; html+=`<h${lvl+1}>${inline(h[2])}</h${lvl+1}>`; }
    else if(li){ if(!inList){html+='<ul>';inList=true;} html+=`<li>${inline(li[1])}</li>`; }
    else if(!line.trim()){ if(inList){html+='</ul>';inList=false;} }
    else{ if(inList){html+='</ul>';inList=false;} html+=`<p>${inline(line)}</p>`; }
  }
  if(inList) html+='</ul>';
  return html;
}
window.renderContent = renderContent;
