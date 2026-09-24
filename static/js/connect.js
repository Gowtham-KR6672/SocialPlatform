/* ============================================================
   Social Media Production Dashboard — Version 23
   Connect panel (Instagram / Google Drive OAuth),
   List of Users (presence), heartbeat, and the global
   Running Tasks bar + live user stats in the header.
   ============================================================ */

/* ---------- friendly label for what the user is doing now ---------- */
const PAGE_ACTIVITY = {
  input:'Input board', calendar:'Calendar', published:'Published',
  content:'Content Writing', connect:'Connect', users:'List of Users',
};
function currentActivity(){ return PAGE_ACTIVITY[App.page] || 'Dashboard'; }

/* ============================================================
   CONTENT-TYPE PICKER  (Reel / Post / Story) — shown before publishing
   ============================================================ */
function chooseContentType(onPick){
  const opts = [
    {id:'reel',  icon:ic('film',22), name:'Reel',  desc:'Full-screen vertical video in Reels.'},
    {id:'post',  icon:ic('image',22), name:'Post',  desc:'Video in the main feed / grid.'},
    {id:'story', icon:ic('zap',22), name:'Story', desc:'24-hour vertical Story.'},
  ];
  const m = el(`<div class="modal" style="max-width:520px">
    <div class="modal-head"><h3>Publish to Instagram</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">Confirm how this should be published. The saved
        (connected) Instagram account is used automatically.</p>
      <div class="ctype-grid">
        ${opts.map(o=>`<button class="ctype" data-ct="${o.id}">
            <div class="ct-ico">${o.icon}</div><div class="ct-name">${o.name}</div>
            <div class="ct-desc">${o.desc}</div></button>`).join('')}
      </div>
    </div></div>`);
  openModal(m);
  m.querySelectorAll('[data-ct]').forEach(b=>b.onclick=()=>{ closeModal(); onPick(b.dataset.ct); });
}
window.chooseContentType = chooseContentType;

/* ============================================================
   HEARTBEAT  (presence) — keeps this user marked "online"
   ============================================================ */
let _hbTimer = null;
async function beat(){
  if(!App.user) return;
  try{ await api('/api/heartbeat', {method:'POST', body:{activity: currentActivity()}}); }catch(e){}
}
function startHeartbeat(){ stopHeartbeat(); beat(); _hbTimer = setInterval(beat, 30000); }
function stopHeartbeat(){ if(_hbTimer){ clearInterval(_hbTimer); _hbTimer=null; } }
window.startHeartbeat = startHeartbeat; window.stopHeartbeat = stopHeartbeat;

/* ============================================================
   RUNNING TASKS BAR + LIVE USER STATS  (polled on every page)
   ============================================================ */
let _tasksTimer = null;
function startTasksPolling(){ stopTasksPolling(); pollTasks(); _tasksTimer = setInterval(pollTasks, 4000); }
function stopTasksPolling(){ if(_tasksTimer){ clearInterval(_tasksTimer); _tasksTimer=null; } }
window.startTasksPolling = startTasksPolling; window.stopTasksPolling = stopTasksPolling;

async function pollTasks(){
  if(!App.user) return;
  // header user stats
  try{
    const p = await api('/api/presence');
    App._presence = p;
    setStat('#hsTotal', p.total_users);
    setStat('#hsOnline', p.online);
    setStat('#hsOffline', p.offline);
    setLbl('#hsTotalL',  p.total_users, 'User', 'Users');
    if(App.page==='users' && $('#usersGrid')) fillUsers(p);   // live-refresh the panel
    const ub=$('#navUserCount'); if(ub) ub.textContent=p.total_users;
  }catch(e){}
  // running tasks
  try{
    const d = await api('/api/tasks');
    App._tasks = d;
    const spin=$('#tasksSpin'), lbl=$('#tasksLabel');
    if(spin) spin.classList.toggle('hidden', d.running_count===0);
    if(lbl) lbl.textContent = d.running_count>0 ? `${d.running_count} running` : 'Tasks';
    const btnEl=$('#tasksBtn'); if(btnEl) btnEl.classList.toggle('busy', d.running_count>0);
    if($('#tasksPanel')) fillTasksPanel(d);
  }catch(e){}
}

/* update a header stat number with a small "bump" animation when it changes */
function setStat(sel, val){
  const e = $(sel); if(!e) return;
  if(e.textContent !== String(val)){
    e.textContent = val;
    e.classList.remove('bump'); void e.offsetWidth; e.classList.add('bump');
  }
}
function setLbl(sel, n, singular, plural){
  const e = $(sel); if(!e) return;
  e.textContent = (n === 1) ? singular : (plural || singular);
}

function toggleTasksPanel(){
  const wrap = $('.tasks-wrap'); if(!wrap) return;
  const ex = $('#tasksPanel'); if(ex){ ex.remove(); return; }
  const panel = el(`<div class="tasks-panel" id="tasksPanel">
      <h4>Running tasks</h4><div id="tasksList"></div></div>`);
  wrap.appendChild(panel);
  fillTasksPanel(App._tasks || {running:[],recent:[]});
}
window.toggleTasksPanel = toggleTasksPanel;

function fillTasksPanel(d){
  const list = $('#tasksList'); if(!list) return;
  const running = (d.running||[]).map(t=>`
    <div class="trow">
      <div class="tr-top"><span class="tr-label">${esc(t.label)}</span>
        <button class="btn ghost xs" data-cancel="${esc(t.id)}">Cancel</button></div>
      <div class="tr-bar"><span style="width:${t.percent||0}%"></span></div>
      <div class="tr-msg">${esc(t.message||'')} · ${t.percent||0}%</div>
    </div>`).join('');
  const label = (s)=> s==='failed'?'Failed':(s==='cancelled'?'Cancelled':'Completed');
  const recent = (d.recent||[]).map(t=>`
    <div class="trow done ${t.status}">
      <div class="tr-top"><span class="tr-label">${esc(t.label)}</span>
        <span class="tr-badge ${t.status}">${label(t.status)}</span></div>
      <div class="tr-msg">${esc(t.message||'')}</div>
    </div>`).join('');
  list.innerHTML = (running||recent) ? (running+recent) : '<div class="empty">No background tasks running.</div>';
  list.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=async()=>{
    try{ await api(`/api/tasks/${b.dataset.cancel}/cancel`,{method:'POST'}); toast('Cancelling…','warn'); pollTasks(); }catch(e){}
  });
}

/* ============================================================
   CONNECT PANEL  (Instagram + Google Drive)
   ============================================================ */
async function renderConnect(){
  const c = $('#pageContent'); if(!c) return;
  const isAdmin = App.user && App.user.is_admin;   // admin + superadmin
  const isSuper = App.user && App.user.is_super;    // only the SuperAdmin connects accounts
  const sub = isSuper
    ? `Connect the workspace's Instagram and Google Drive here. These accounts are
       shared across the whole workspace — admins and users see them as connected
       and publish through them.`
    : `These are the workspace's Instagram and Google Drive accounts, connected by
       the SuperAdmin. They're shared with the whole team.`;
  c.innerHTML = `<div class="panel-head"><h2>Connect</h2>
      <p class="sub">${sub}</p></div>
    <div id="connCards" class="conn-cards"><div class="loading">Loading…</div></div>
    ${isAdmin ? `<div class="da-entry">
        <div><b>Video download access</b><div class="sub">Choose which users can download videos from the Drive folder. All users can see the list; only granted users can download.</div></div>
        <button class="btn sm" id="mgrDownload">Manage download access</button>
      </div>
      <div class="da-entry">
        <div><b>Content approval access</b><div class="sub">Approving content is admin-only. Grant approval access here to specific users when they request it.</div></div>
        <button class="btn sm" id="mgrApprove">Manage approval access</button>
      </div>` : ''}
    <div id="oauthCfg"></div>`;
  await refreshConnCards();
  if(isAdmin && $('#mgrDownload')) $('#mgrDownload').onclick = ()=>openAccessManager('download');
  if(isAdmin && $('#mgrApprove')) $('#mgrApprove').onclick = ()=>openAccessManager('approve');
  loadOAuthConfig();
}
window.renderConnect = renderConnect;

async function refreshConnCards(){
  const box = $('#connCards'); if(!box) return;
  let s;
  try{ s = await api('/api/connections'); }catch(e){ box.innerHTML=`<div class="err">${esc(e.message)}</div>`; return; }
  box.innerHTML = `
    ${connCard('instagram','Instagram','Publish approved Reels straight to the workspace Instagram.',s.instagram)}
    ${connCard('google','Google Drive','Store project videos in the workspace Drive folder with shareable links.',s.google)}`;
  box.querySelectorAll('[data-connect]').forEach(b=>b.onclick=()=>connectProvider(b.dataset.connect));
  box.querySelectorAll('[data-disc]').forEach(b=>b.onclick=()=>disconnectProvider(b.dataset.disc));
}

function connCard(id, name, desc, st){
  const u = App.user || {};
  const canManage = !!u.is_super;    // ONLY the SuperAdmin connects/disconnects
  const isAdmin = !!u.is_admin;
  const connected = st && st.connected;
  const badge = connected
    ? `<span class="conn-badge on"><span class="pdot on"></span> Connected</span>`
    : `<span class="conn-badge off"><span class="pdot off"></span> Not connected</span>`;
  const acct = connected && st.account
    ? `<div class="conn-acct">${id==='instagram'?'':ic('mail',12)+' '}${esc(st.account)}</div>` : '';
  // Drive folder link is useful to admins (open the shared folder); hidden from
  // regular users.
  const folder = (id==='google' && connected && st.folder_link && isAdmin)
    ? `<div class="conn-folder">Project folder:
         <a href="${esc(st.folder_link)}" target="_blank" rel="noopener">Open in Drive ${ic('external',12)}</a></div>` : '';
  if(!canManage){
    // Admins + regular users: status only. No connect/disconnect (only the
    // SuperAdmin manages the shared accounts), no demo/OAuth note.
    return `<div class="conn-card ${id}">
        <div class="cc-top"><div class="cc-ico ${id}">${id==='instagram'?pi('instagram',22):ic('folder',20)}</div>
          <div><div class="cc-name">${esc(name)}</div>${badge}</div></div>
        <p class="cc-desc">${esc(desc)}</p>
        ${acct}${folder}
      </div>`;
  }
  // SuperAdmin: full control.
  const mode = connected && st.mode==='demo'
    ? `<div class="conn-mode">Demo connection — add OAuth credentials below to go live.</div>` : '';
  const action = connected
    ? `<button class="btn ghost sm" data-disc="${id}">Disconnect</button>`
    : `<button class="btn sm" data-connect="${id}">Connect ${esc(name)}</button>`;
  return `<div class="conn-card ${id}">
      <div class="cc-top"><div class="cc-ico ${id}">${id==='instagram'?pi('instagram',22):ic('folder',20)}</div>
        <div><div class="cc-name">${esc(name)}</div>${badge}</div></div>
      <p class="cc-desc">${esc(desc)}</p>
      ${acct}${folder}${mode}
      <div class="cc-act">${action}</div>
    </div>`;
}

async function connectProvider(provider){
  try{
    const r = await api(`/api/connect/${provider}/start`, {method:'POST', body:{}});
    if(r.mode === 'live' && r.auth_url){
      // open the official OAuth login in a popup and wait for it to finish
      const w = window.open(r.auth_url, 'sdb_oauth', 'width=520,height=680');
      toast('Complete the sign-in in the popup window…');
      const onMsg = (ev)=>{
        if(ev.data && ev.data.sdb_oauth){
          window.removeEventListener('message', onMsg);
          setTimeout(()=>{ refreshConnCards(); toast(ev.data.ok?'Connected':'Connection cancelled', ev.data.ok?'good':'warn'); }, 400);
        }
      };
      window.addEventListener('message', onMsg);
      // fallback: poll connections in case the popup was closed manually
      const iv = setInterval(async ()=>{ if(w && w.closed){ clearInterval(iv); refreshConnCards(); } }, 1500);
    }else{
      // demo mode — connected immediately
      await refreshConnCards();
      toast(`${provider==='google'?'Google Drive':'Instagram'} connected`, 'good');
    }
  }catch(e){ toast(e.message,'warn'); }
}

function disconnectProvider(provider){
  const name = provider==='google'?'Google Drive':'Instagram';
  confirmBox(`Disconnect ${name}?`, `This removes your ${name} connection from your account only.`,
    async ()=>{ try{ await api(`/api/connect/${provider}/disconnect`,{method:'POST'}); await refreshConnCards(); toast(`${name} disconnected`); }catch(e){ toast(e.message,'warn'); } },
    'Disconnect');
}

/* ---- Credentials area (SuperAdmin / granted users only) ----
   OAuth app credentials (Google + Instagram) AND the Claude API key + model +
   content-writing guidelines all live here. Hidden entirely from anyone the
   SuperAdmin hasn't granted "Can view credentials". Non-secret fields are
   pre-filled from the server so they never look blank after saving; secrets
   show a "set" indicator and are only overwritten when you type a new value. */
async function loadOAuthConfig(){
  const box = $('#oauthCfg'); if(!box) return;
  let cfg; try{ cfg = await api('/api/oauth/config'); }catch(e){ return; }
  // Only credential-holders see this area at all. (`allowed` is the new gate;
  // `is_admin` kept for backward compatibility with older servers.)
  const allowed = (cfg.allowed !== undefined) ? cfg.allowed : !!cfg.is_admin;
  if(!allowed){ box.innerHTML = ''; return; }
  box.innerHTML = `<details class="oauth-cfg"><summary>Credentials · sign-in &amp; AI (SuperAdmin)</summary>
    <div class="ocfg-body">
      <p class="sub">Register a Google Cloud OAuth client and a Meta/Instagram app, then paste the IDs/secrets here.
      These are set once for the whole app — users never type tokens. Add redirect URIs:
      <code>&lt;base&gt;/oauth/google/callback</code> and <code>&lt;base&gt;/oauth/instagram/callback</code>.</p>
      <label class="f">Redirect base URL</label>
      <input class="f" id="oc-base" placeholder="http://127.0.0.1:5000" value="${esc(cfg.oauth_redirect_base||'')}">
      <div class="ocfg-grid">
        <div><label class="f">Google client ID</label>
          <input class="f" id="oc-gid" value="${esc(cfg.google_client_id||'')}" placeholder="…apps.googleusercontent.com"></div>
        <div><label class="f">Google client secret ${cfg.google_secret_set?'(set — blank keeps it)':''}</label>
          <input class="f" id="oc-gsec" type="password" placeholder="${cfg.google_secret_set?'••••••••':'GOCSPX-…'}"></div>
        <div><label class="f">Instagram app ID</label>
          <input class="f" id="oc-igid" value="${esc(cfg.ig_app_id||'')}" placeholder="Meta app id"></div>
        <div><label class="f">Instagram app secret ${cfg.ig_secret_set?'(set — blank keeps it)':''}</label>
          <input class="f" id="oc-igsec" type="password" placeholder="${cfg.ig_secret_set?'••••••••':'app secret'}"></div>
      </div>

      <hr class="ocfg-sep">
      <p class="sub"><b>AI (Claude API)</b> — powers Caption &amp; Hashtags and Content Writing.
      The key is required for AI generation and is never shown to users.</p>
      <div class="ocfg-grid">
        <div><label class="f">Claude API key ${cfg.claude_key_set?'(set — blank keeps it)':''}</label>
          <input class="f" id="oc-ckey" type="password" placeholder="${cfg.claude_key_set?'••••••••':'sk-ant-…'}"></div>
        <div><label class="f">Model</label>
          <input class="f" id="oc-cmodel" value="${esc(cfg.claude_model||'')}" placeholder="claude-3-5-sonnet-latest"></div>
      </div>
      <label class="f">Content-writing guidelines</label>
      <textarea class="f" id="oc-cguide" rows="4" placeholder="Tone, voice, brand rules, do/don't… applied to captions and written content.">${esc(cfg.content_guidelines||'')}</textarea>

      <div class="err" id="oc-err"></div>
      <button class="btn sm" id="oc-save">Save credentials</button>
    </div></details>`;
  $('#oc-save').onclick = async ()=>{
    const body = {
      oauth_redirect_base: $('#oc-base').value.trim(),
      google_client_id: $('#oc-gid').value.trim(),
      ig_app_id: $('#oc-igid').value.trim(),
      claude_model: $('#oc-cmodel').value.trim(),
      content_guidelines: $('#oc-cguide').value,
    };
    const gs=$('#oc-gsec').value.trim(); if(gs) body.google_client_secret=gs;
    const is=$('#oc-igsec').value.trim(); if(is) body.ig_app_secret=is;
    const ck=$('#oc-ckey').value.trim(); if(ck) body.claude_api_key=ck;
    try{
      await api('/api/oauth/config',{method:'POST', body});
      toast('Credentials saved','good');
      // reload so the saved (non-secret) values show and secrets read "set"
      loadOAuthConfig();
      if(window.loadAiStatus) loadAiStatus();   // refresh the top-bar AI chip
    }
    catch(e){ $('#oc-err').textContent=e.message; }
  };
}

/* ============================================================
   LIST OF USERS  (presence)
   ============================================================ */
async function renderUsers(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="panel-head"><h2>List of Users</h2>
      <p class="sub">Everyone registered on this workspace, with live online status.</p></div>
    <div class="user-stats" id="userStats"></div>
    <div class="users-grid" id="usersGrid"><div class="loading">Loading…</div></div>`;
  try{ fillUsers(await api('/api/presence')); }catch(e){ $('#usersGrid').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
}
window.renderUsers = renderUsers;

function fillUsers(p){
  const stats = $('#userStats');
  if(stats) stats.innerHTML = `
    <div class="ustat"><b>${p.total_users}</b><span>Registered</span></div>
    <div class="ustat"><b>${p.active}</b><span>Active</span></div>
    <div class="ustat green"><b>${p.online}</b><span>Online</span></div>
    <div class="ustat gray"><b>${p.offline}</b><span>Offline</span></div>`;
  const grid = $('#usersGrid'); if(!grid) return;
  const meId = App.user && App.user.id;
  // V28: only the SuperAdmin manages other users (delete / reset password).
  const canManage = !!p.can_manage;
  grid.innerHTML = p.users.map(u=>{
    const initials = (u.display_name||u.username||'?').trim().slice(0,2).toUpperCase();
    // Profile photos are never shown on the user cards — always show initials.
    const av = `<span class="uav ph">${esc(initials)}</span>`;
    const svc = [
      u.google_connected?'<span class="usvc g">Drive</span>':'',
      u.instagram_connected?'<span class="usvc i">Instagram</span>':'',
    ].join('') || '<span class="usvc none">No connections</span>';
    const last = u.online ? 'Online now'
      : (u.last_seen ? 'Last active '+fmtTime(u.last_seen) : 'Never signed in');
    const act = (u.online && u.activity) ? `<div class="uact">${esc(u.activity)}</div>` : '';
    const isSelf = (u.id === meId);
    // Self: change own password + delete own account.
    // SuperAdmin (canManage): reset any user's password + delete any account
    // (except the SuperAdmin account, which the server refuses to delete).
    const btns = [];
    if(isSelf){
      btns.push(`<button class="btn ghost xs" data-pw="${u.id}">Change password</button>`);
      btns.push(`<button class="btn danger xs" data-del="${u.id}" data-self="1">Delete my account</button>`);
    }else{
      // call another user (voice/video) — enabled when they're online
      btns.push(`<button class="btn ghost xs" data-callvoice="${u.id}" data-name="${esc(u.username)}" ${u.online?'':'disabled'} title="${u.online?'Voice call':'User is offline'}">${ic('phone',12)} Voice</button>`);
      btns.push(`<button class="btn ghost xs" data-callvid="${u.id}" data-name="${esc(u.username)}" ${u.online?'':'disabled'} title="${u.online?'Video call':'User is offline'}">${ic('camera',12)} Video</button>`);
      if(canManage){
        btns.push(`<button class="btn ghost xs" data-reset="${u.id}" data-name="${esc(u.username)}">Reset password</button>`);
        if(u.role!=='superadmin') btns.push(`<button class="btn danger xs" data-del="${u.id}">Delete</button>`);
      }
    }
    const actions = btns.length ? `<div class="uc-actions">${btns.join('')}</div>` : '';
    const roleBadge = `<span class="urole-badge role-${esc((u.role||'user'))}">${esc(u.role_label||roleLabel(u.role))}</span>`;
    return `<div class="user-card${isSelf?' me':''}">
        <div class="uc-top">${av}
          <div class="uc-id"><div class="uc-name">${esc(u.display_name||u.username)}
            ${isSelf?'<span class="you-tag">You</span>':''}
            <span class="pdot ${u.online?'on':'off'}"></span></div>
            <div class="uc-role">${roleBadge} · @${esc(u.username)}</div></div></div>
        <div class="uc-last ${u.online?'on':''}">${esc(last)}</div>
        ${act}
        <div class="uc-svcs">${svc}</div>
        ${actions}
      </div>`;
  }).join('') || '<div class="empty">No users yet.</div>';

  grid.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>deleteUser(b.dataset.del, b.dataset.self==='1'));
  grid.querySelectorAll('[data-pw]').forEach(b=>b.onclick=()=>changeMyPassword(b.dataset.pw));
  grid.querySelectorAll('[data-reset]').forEach(b=>b.onclick=()=>resetUserPassword(b.dataset.reset, b.dataset.name));
  grid.querySelectorAll('[data-callvoice]').forEach(b=>b.onclick=()=>startCall(Number(b.dataset.callvoice), b.dataset.name, false));
  grid.querySelectorAll('[data-callvid]').forEach(b=>b.onclick=()=>startCall(Number(b.dataset.callvid), b.dataset.name, true));
}

/* SuperAdmin: reset another user's password directly (no current password). */
function resetUserPassword(id, name){
  const m = el(`<div class="modal" style="max-width:420px">
    <div class="modal-head"><h3>Reset password</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub">Set a new password for <b>@${esc(name||'user')}</b>. They can change it later from their profile.</p>
      <label class="f">New password</label><input class="f" id="rp-new" type="password" placeholder="New password">
      <label class="f">Confirm new password</label><input class="f" id="rp-new2" type="password" placeholder="Re-enter new password">
      <div class="err" id="rp-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="rp-go">Reset password</button></div></div>`);
  openModal(m);
  const go = async ()=>{
    $('#rp-err',m).textContent='';
    const n=$('#rp-new',m).value, n2=$('#rp-new2',m).value;
    const pe=(typeof checkPassword==='function')?checkPassword(n):''; if(pe){ $('#rp-err',m).textContent=pe; return; }
    if(n!==n2){ $('#rp-err',m).textContent='Passwords do not match.'; return; }
    try{
      await api(`/api/users/${id}/password`, {method:'POST', body:{password:n}});
      closeModal(); toast('Password reset','good');
    }catch(e){ $('#rp-err',m).textContent=e.message; }
  };
  $('#rp-go',m).onclick = go;
  m.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();go();} }));
  setTimeout(()=>$('#rp-new',m)&&$('#rp-new',m).focus(),40);
}
window.resetUserPassword = resetUserPassword;
window.fillUsers = fillUsers;

function deleteUser(id, isSelf){
  const title = isSelf ? 'Delete your account?' : 'Delete this user account?';
  const body  = isSelf ? 'This permanently removes your account and logs you out. This cannot be undone.'
                       : 'This permanently removes the user account. This cannot be undone.';
  confirmBox(title, body, async ()=>{
    try{
      const r = await api(`/api/users/${id}`, {method:'DELETE'});
      if(r.self_deleted){
        stopHeartbeat(); stopTasksPolling();
        App.user = null; renderTopbar(); renderLanding(); toast('Your account was deleted');
      }else{
        toast('User deleted','good');
        try{ fillUsers(await api('/api/presence')); }catch(e){}
      }
    }catch(e){ toast(e.message,'warn'); }
  }, isSelf?'Delete my account':'Delete user');
}

function changeMyPassword(id){
  const m = el(`<div class="modal" style="max-width:420px">
    <div class="modal-head"><h3>Change password</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Current password</label><input class="f" id="pw-cur" type="password" placeholder="Current password">
      <label class="f">New password</label><input class="f" id="pw-new" type="password" placeholder="New password">
      <label class="f">Confirm new password</label><input class="f" id="pw-new2" type="password" placeholder="Re-enter new password">
      <div class="err" id="pw-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="pw-go">Update password</button></div></div>`);
  openModal(m);
  const go = async ()=>{
    $('#pw-err',m).textContent='';
    const n=$('#pw-new',m).value, n2=$('#pw-new2',m).value;
    const pe=(typeof checkPassword==='function')?checkPassword(n):''; if(pe){ $('#pw-err',m).textContent=pe; return; }
    if(n!==n2){ $('#pw-err',m).textContent='New passwords do not match.'; return; }
    try{
      await api(`/api/users/${id}/password`, {method:'POST', body:{current:$('#pw-cur',m).value, password:n}});
      closeModal(); toast('Password updated','good');
    }catch(e){ $('#pw-err',m).textContent=e.message; }
  };
  $('#pw-go',m).onclick = go;
  m.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();go();} }));
  setTimeout(()=>$('#pw-cur',m)&&$('#pw-cur',m).focus(),40);
}
window.deleteUser = deleteUser; window.changeMyPassword = changeMyPassword;

/* ============================================================
   ADMIN · MANAGE ACCESS  (kind = 'download' | 'approve')
   Two columns (No access / Can <kind>). Drag & drop users
   between them, or use the dropdown to grant quickly.
   ============================================================ */
async function openAccessManager(kind){
  const cfg = (kind === 'approve')
    ? {ep:'/api/approval-access', title:'Content approval access', col:'Can approve'}
    : {ep:'/api/download-access', title:'Video download access',   col:'Can download'};
  let data; try{ data = await api(cfg.ep); }catch(e){ toast(e.message,'warn'); return; }
  // admins always have access and are locked into the granted column
  const users = data.users;
  const m = el(`<div class="modal wide" style="max-width:760px">
    <div class="modal-head"><h3>${cfg.title}</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">Drag a user between the columns, or pick from the dropdown to grant access.
        Admins always have access. Click <b>Save</b> to apply.</p>
      <div class="da-quick">
        <label class="f" style="margin:0">Quickly grant:</label>
        <select class="f" id="da-pick" style="max-width:280px"><option value="">Select a user…</option></select>
        <button class="btn sm" id="da-add">Grant access</button>
      </div>
      <div class="da-cols">
        <div class="da-col" id="da-no"><h4>No access</h4><div class="da-list" data-col="no"></div></div>
        <div class="da-col granted" id="da-yes"><h4>${cfg.col}</h4><div class="da-list" data-col="yes"></div></div>
      </div>
      <div class="err" id="da-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="da-save">Save</button></div></div>`);
  openModal(m);

  function chip(u){
    // Admins always have access and are locked. The SuperAdmin is also locked —
    // an admin must not be able to transfer or modify SuperAdmin access.
    const locked = u.role==='admin' || u.role==='superadmin';
    const lockTag = u.role==='superadmin' ? ' <i>(super admin)</i>' : (locked ? ' <i>(admin)</i>' : '');
    const c = el(`<div class="da-chip${locked?' locked':''}" draggable="${!locked}" data-uid="${u.id}" data-role="${u.role}">
        <span class="da-av">${esc((u.display_name||u.username).slice(0,2).toUpperCase())}</span>
        <span class="da-nm">${esc(u.display_name||u.username)}${lockTag}</span>
        ${locked?'':`<button class="da-move" title="Move">${ic('expand',13)}</button>`}
      </div>`);
    if(!locked){
      c.addEventListener('dragstart',e=>{ e.dataTransfer.setData('text/plain', String(u.id)); c.classList.add('dragging'); });
      c.addEventListener('dragend',()=>c.classList.remove('dragging'));
      c.querySelector('.da-move').onclick=()=>{
        const inYes = c.closest('[data-col]').dataset.col==='yes';
        (inYes ? $('#da-no .da-list',m) : $('#da-yes .da-list',m)).appendChild(c);
        refreshPick();
      };
    }
    return c;
  }
  const noList = $('#da-no .da-list', m), yesList = $('#da-yes .da-list', m);
  users.forEach(u=>{
    const granted = u.can_download || u.role==='admin' || u.role==='superadmin';
    (granted ? yesList : noList).appendChild(chip(u));
  });
  [ ['no',noList], ['yes',yesList] ].forEach(([col,listEl])=>{
    const zone = listEl.closest('[data-col]');
    zone.addEventListener('dragover', e=>{ e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', ()=> zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e=>{
      e.preventDefault(); zone.classList.remove('drag-over');
      const uid = e.dataTransfer.getData('text/plain');
      const ch = m.querySelector(`.da-chip[data-uid="${uid}"]`);
      if(ch && ch.dataset.role!=='admin' && ch.dataset.role!=='superadmin'){ listEl.appendChild(ch); refreshPick(); }
    });
  });
  function refreshPick(){
    const sel = $('#da-pick', m);
    const inNo = [...noList.querySelectorAll('.da-chip')].map(c=>({id:c.dataset.uid, nm:c.querySelector('.da-nm').textContent.trim()}));
    sel.innerHTML = '<option value="">Select a user…</option>' + inNo.map(u=>`<option value="${u.id}">${esc(u.nm)}</option>`).join('');
  }
  refreshPick();
  $('#da-add', m).onclick=()=>{
    const id=$('#da-pick',m).value; if(!id) return;
    const ch=m.querySelector(`#da-no .da-chip[data-uid="${id}"]`);
    if(ch){ yesList.appendChild(ch); refreshPick(); }
  };
  $('#da-save', m).onclick=async ()=>{
    const grants=[...yesList.querySelectorAll('.da-chip')].filter(c=>c.dataset.role!=='admin' && c.dataset.role!=='superadmin').map(c=>Number(c.dataset.uid));
    try{ await api(cfg.ep,{method:'POST', body:{grants}}); closeModal();
      toast((kind==='approve'?'Approval':'Download')+' access updated','good');
      if(App.page==='input') loadProduction();
    }catch(e){ $('#da-err',m).textContent=e.message; }
  };
}
window.openAccessManager = openAccessManager;
