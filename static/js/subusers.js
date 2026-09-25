/* ============================================================
   Sub-Users  (primary User manages the accounts working under them)
   The primary User is the admin of its Sub-Users and defines, per
   Sub-User: which sections they can open, whether they can edit/
   update/manage videos, and which videos they may work on.
   ============================================================ */
let _suMeta = {controllable_tabs:[], videos:[]};

async function renderSubusers(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="panel-head"><h2>Sub-Users</h2>
      <p class="sub">Create and manage the people working under your account, and control exactly what each can access.</p></div>
    <div class="row" style="margin-bottom:12px"><button class="btn" id="suAdd">${ic('plus',14)} Create Sub-User</button></div>
    <div id="suBody"><div class="loading">Loading…</div></div>`;
  $('#suAdd').onclick = ()=>openSubuserModal(null);
  await loadSubusers();
}
window.renderSubusers = renderSubusers;

async function loadSubusers(){
  let d;
  try{ d = await api('/api/subusers'); }
  catch(e){ $('#suBody').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  _suMeta = {controllable_tabs:d.controllable_tabs||[], videos:d.videos||[]};
  const list = d.subusers||[];
  if(!list.length){ $('#suBody').innerHTML = `<div class="empty">No Sub-Users yet. Create one to delegate work on your projects.</div>`; return; }
  const tabLabel = (k)=>{ const t=_suMeta.controllable_tabs.find(x=>x.key===k); return t?t.label:k; };
  $('#suBody').innerHTML = `<div class="users-grid">` + list.map(su=>{
    const tabs = (su.access_tabs==null) ? 'All sections' : (su.access_tabs.length? su.access_tabs.map(tabLabel).join(', ') : 'No sections');
    const vids = (su.allowed_videos==='all'||su.allowed_videos==null) ? 'All videos'
      : (Array.isArray(su.allowed_videos)? (su.allowed_videos.length+' selected video(s)') : 'Selected videos');
    return `<div class="user-card">
        <div class="uc-top"><span class="uav ph">${esc((su.display_name||su.username).slice(0,2).toUpperCase())}</span>
          <div class="uc-id"><div class="uc-name">${esc(su.display_name||su.username)} <span class="pdot ${su.online?'on':'off'}"></span></div>
            <div class="uc-role"><span class="urole-badge role-subuser">Sub-User</span></div></div></div>
        <div class="su-login">${ic('key',13)} Login ID: <b>${esc(su.username)}</b>
          <button class="icon-btn sm" data-copyid="${esc(su.username)}" title="Copy login ID">${ic('copy',12)}</button></div>
        <div class="uc-svcs" style="flex-direction:column;align-items:flex-start;gap:4px">
          <span class="usvc">Sections: ${esc(tabs)}</span>
          <span class="usvc">Editing: ${su.can_edit?'Allowed':'View only'} · Approving: ${su.can_approve?'Yes':'No'}</span>
          <span class="usvc">Videos: ${esc(vids)}</span></div>
        <div class="uc-actions">
          <button class="btn ghost xs" data-edit="${su.id}">Edit permissions</button>
          <button class="btn ghost xs" data-pw="${su.id}">Reset password</button>
          <button class="btn danger xs" data-del="${su.id}">Delete</button>
        </div></div>`;
  }).join('') + `</div>`;
  const byId = Object.fromEntries(list.map(s=>[String(s.id), s]));
  $('#suBody').querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>openSubuserModal(byId[b.dataset.edit]));
  $('#suBody').querySelectorAll('[data-pw]').forEach(b=>b.onclick=()=>resetSubuserPw(b.dataset.pw));
  $('#suBody').querySelectorAll('[data-copyid]').forEach(b=>b.onclick=()=>{ try{ navigator.clipboard.writeText(b.dataset.copyid); toast('Login ID copied','good'); }catch(e){} });
  $('#suBody').querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>{
    confirmBox('Delete this Sub-User?','This permanently removes the Sub-User account.',
      async ()=>{ try{ await api('/api/subusers/'+b.dataset.del,{method:'DELETE'}); toast('Sub-User deleted','good'); loadSubusers(); }
        catch(e){ toast(e.message,'warn'); } }, 'Delete');
  });
}

function openSubuserModal(su){
  const editing = !!su;
  const tabs = _suMeta.controllable_tabs;
  const curTabs = editing ? (su.access_tabs==null ? tabs.map(t=>t.key) : su.access_tabs) : tabs.map(t=>t.key);
  const tabChecks = tabs.map(t=>`<label class="cred-toggle" style="display:inline-flex;margin:2px 10px 2px 0">
      <input type="checkbox" data-tab="${t.key}" ${curTabs.includes(t.key)?'checked':''}> <span>${esc(t.label)}</span></label>`).join('');
  const curEdit = editing ? su.can_edit!==false : true;
  const curApprove = editing ? !!su.can_approve : false;
  const allVideos = !editing || su.allowed_videos==='all' || su.allowed_videos==null;
  const selVids = (editing && Array.isArray(su.allowed_videos)) ? su.allowed_videos.map(String) : [];
  const vidOpts = _suMeta.videos.map(v=>`<label class="cred-toggle" style="display:flex;margin:3px 0">
      <input type="checkbox" data-vid="${v.id}" ${selVids.includes(String(v.id))?'checked':''}> <span>${esc(v.title||('#'+v.id))}</span></label>`).join('')
      || '<div class="sub">No videos in the workspace yet.</div>';
  const m = el(`<div class="modal">
    <div class="modal-head"><h3>${editing?'Edit Sub-User':'Create Sub-User'}</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      ${editing?'':`<label class="f">Login ID <span class="muted">(they sign in with this — not the display name)</span></label>
      <input class="f" id="su-user" placeholder="e.g. manoj.editor" autocomplete="off">
      <div class="hint">No spaces · letters, numbers, . _ -</div>
      <label class="f">Password</label>
      <div class="ai-model-row"><input class="f" id="su-pass" type="text" autocomplete="new-password" value="${esc(typeof genPassword==='function'?genPassword():'')}">
        <button class="btn ghost sm" type="button" id="su-gen">${ic('refresh',13)} New</button></div>`}
      <label class="f">Display name</label><input class="f" id="su-name" value="${editing?esc(su.display_name||su.username):''}" placeholder="Full name">
      <label class="f">Sections they can access</label>
      <div style="margin:2px 0 6px">${tabChecks}</div>
      <label class="cred-toggle" style="margin:6px 0"><input type="checkbox" id="su-edit" ${curEdit?'checked':''}> <span>Can edit / update / manage videos (unchecked = view only)</span></label>
      <label class="cred-toggle" style="margin:6px 0"><input type="checkbox" id="su-approve" ${curApprove?'checked':''}> <span>Can approve posts for publishing</span></label>
      <label class="f" style="margin-top:8px">Videos they may work on</label>
      <label class="cred-toggle" style="margin:2px 0"><input type="checkbox" id="su-allvid" ${allVideos?'checked':''}> <span>All videos</span></label>
      <div id="su-vidlist" class="${allVideos?'hidden':''}" style="max-height:160px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px;margin-top:6px">${vidOpts}</div>
      <div class="err" id="su-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="su-save">${editing?'Save permissions':'Create Sub-User'}</button></div></div>`);
  openModal(m);
  if($('#su-gen',m)) $('#su-gen',m).onclick = ()=>{ $('#su-pass',m).value = genPassword(); };
  $('#su-allvid',m).onchange = ()=>{ $('#su-vidlist',m).classList.toggle('hidden', $('#su-allvid',m).checked); };
  $('#su-save',m).onclick = async ()=>{
    const access_tabs = [...m.querySelectorAll('[data-tab]:checked')].map(x=>x.dataset.tab);
    const can_edit = $('#su-edit',m).checked, can_approve = $('#su-approve',m).checked;
    const allowed_videos = $('#su-allvid',m).checked ? 'all'
      : [...m.querySelectorAll('[data-vid]:checked')].map(x=>Number(x.dataset.vid));
    try{
      if(editing){
        await api('/api/subusers/'+su.id,{method:'PATCH', body:{
          access_tabs, can_edit, can_approve, allowed_videos,
          display_name: $('#su-name',m).value.trim()}});
        toast('Permissions updated','good');
      }else{
        const body = {username:$('#su-user',m).value.trim(), password:$('#su-pass',m).value,
          display_name:$('#su-name',m).value.trim(), access_tabs, can_edit, can_approve, allowed_videos};
        await api('/api/subusers',{method:'POST', body});
        closeModal(); loadSubusers();
        if(typeof showLoginDetails==='function') showLoginDetails('User created', body.display_name||body.username, body.username, body.password);
        return;
      }
      closeModal(); loadSubusers();
    }catch(e){ $('#su-err',m).textContent = e.message; }
  };
}

function resetSubuserPw(id){
  const m = el(`<div class="modal"><div class="modal-head"><h3>Reset Sub-User password</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><label class="f">New password</label><input class="f" id="su-np" type="password" placeholder="New password">
      <div class="err" id="su-npe"></div></div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="su-npsave">Set password</button></div></div>`);
  openModal(m);
  $('#su-npsave',m).onclick = async ()=>{
    try{ await api('/api/subusers/'+id,{method:'PATCH', body:{password:$('#su-np',m).value}}); toast('Password updated','good'); closeModal(); }
    catch(e){ $('#su-npe',m).textContent=e.message; }
  };
}
