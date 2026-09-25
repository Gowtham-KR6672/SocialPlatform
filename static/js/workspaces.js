/* ============================================================
   Workspaces (SuperAdmin only)
   One isolated workspace per client, each with its own Client Admin
   login. The Client Admin then adds users and connects the social
   accounts — centrally, or letting each user connect their own.
   ============================================================ */
const SOCIAL_MODE_LABEL = {central:'Managed by the admin', individual:'Each user connects their own'};

async function renderWorkspaces(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="page-head"><h2>Workspaces</h2><div class="spacer"></div>
      <button class="btn" id="wsNew">${ic('plus',16)} New workspace</button></div>
    <div class="tiles" id="wsTiles"></div>
    <div id="wsBody"><div class="loading">Loading…</div></div>`;
  $('#wsNew').onclick = ()=>openWorkspaceModal(null);
  let d; try{ d = await api('/api/workspaces'); }
  catch(e){ $('#wsBody').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const list = d.workspaces || [];
  const sum = k => list.reduce((s,w)=>s+(w[k]||0),0);
  $('#wsTiles').innerHTML = `
    <div class="tile"><div class="n">${list.length}</div><div class="l">Workspaces</div></div>
    <div class="tile processing"><div class="n">${sum('users')+list.length}</div><div class="l">Logins</div></div>
    <div class="tile completed"><div class="n">${sum('accounts')}</div><div class="l">Social accounts</div></div>
    <div class="tile red"><div class="n">${list.filter(w=>w.disabled).length}</div><div class="l">Suspended</div></div>`;
  if(!list.length){
    $('#wsBody').innerHTML = `<div class="empty-state">${ic('building',34)}<h3>No client workspaces yet</h3>
      <p class="sub">Click <b>New workspace</b> to create one for your first client, with its own admin login.</p></div>`;
    return;
  }
  const when = s => s ? fmtTime(String(s).slice(0,19)) : 'Never';
  $('#wsBody').innerHTML = `<div class="ws-grid">${list.map(w=>`
    <div class="ws-card ${w.disabled?'is-off':''}" data-ws="${w.id}">
      <div class="ws-top"><span class="ws-av">${esc((w.company_name||'?').slice(0,2).toUpperCase())}</span>
        <div class="ws-id"><b>${esc(w.company_name)}</b><span>Admin: @${esc(w.admin_username)}${w.email?' · '+esc(w.email):''}</span></div>
        ${w.disabled?`<span class="chip danger">${ic('lock',11)} Suspended</span>`:`<span class="chip completed">Active</span>`}</div>
      <div class="ws-stats">
        <div><b>${w.users+1}</b><span>Logins</span></div>
        <div><b>${w.accounts}</b><span>Social accounts</span></div>
        <div><b>${w.posts}</b><span>Posts</span></div></div>
      <div class="ws-meta">
        <div>${ic('link',13)} ${esc(SOCIAL_MODE_LABEL[w.social_mode]||w.social_mode)}</div>
        <div class="ws-plats">${w.platforms.length?w.platforms.map(p=>pi(p,16)).join(''):'<span class="muted">No accounts connected yet</span>'}</div>
        <div class="muted">${ic('clock',12)} Last active ${esc(when(w.last_active))} · created ${esc((w.created_at||'').slice(0,10))}</div></div>
      <div class="ws-actions">
        <button class="btn ghost sm" data-edit="${w.id}">${ic('edit',14)} Edit</button>
        <button class="btn ghost sm" data-pw="${w.id}">${ic('key',14)} Password</button>
        <button class="btn ghost sm" data-susp="${w.id}">${ic(w.disabled?'check':'lock',14)} ${w.disabled?'Activate':'Suspend'}</button>
        <button class="btn danger sm" data-del="${w.id}" title="Delete workspace">${ic('trash',14)}</button></div>
    </div>`).join('')}</div>`;
  const byId = Object.fromEntries(list.map(w=>[String(w.id), w]));
  const body = $('#wsBody');
  body.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>openWorkspaceModal(byId[b.dataset.edit]));
  body.querySelectorAll('[data-pw]').forEach(b=>b.onclick=()=>workspacePassword(byId[b.dataset.pw]));
  body.querySelectorAll('[data-susp]').forEach(b=>b.onclick=()=>{
    const w = byId[b.dataset.susp];
    confirmBox(w.disabled?`Activate ${w.company_name}?`:`Suspend ${w.company_name}?`,
      w.disabled ? 'Its admin and users can log in again.' : 'Its admin and every user in the workspace are signed out and can\'t log in until you activate it. Nothing is deleted.',
      async ()=>{ try{ await api('/api/workspaces/'+w.id,{method:'PATCH', body:{disabled:!w.disabled}});
          toast(w.disabled?'Workspace activated':'Workspace suspended','good'); renderWorkspaces(); }catch(e){ toast(e.message,'warn'); } },
      w.disabled?'Activate':'Suspend');
  });
  body.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>deleteWorkspace(byId[b.dataset.del]));
}
window.renderWorkspaces = renderWorkspaces;

function genPassword(){
  const a = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ', n = '23456789', s = '!@#$%&*';
  const pick = (set,k)=>Array.from(crypto.getRandomValues(new Uint32Array(k)), x=>set[x % set.length]).join('');
  return (pick(a,6) + pick(n,3) + pick(s,1)).split('').sort(()=>Math.random()-.5).join('');
}

function modeChooser(cur){
  return `<div class="mode-pick">${['central','individual'].map(m=>`
    <label class="mode-opt"><input type="radio" name="wsmode" value="${m}" ${cur===m?'checked':''}>
      <span><b>${m==='central'?'Managed by the Client Admin':'Each user connects their own'}</b>
      <small>${m==='central'
        ? 'Only the admin connects the social accounts; every post in the workspace publishes from them. Recommended for agencies.'
        : 'Every user connects their own social accounts and their posts publish from them.'}</small></span></label>`).join('')}</div>`;
}

function openWorkspaceModal(w){
  const editing = !!w;
  const m = el(`<div class="modal" style="max-width:560px">
    <div class="modal-head"><h3>${ic('building',18)} ${editing?'Edit workspace':'New client workspace'}</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f" for="ws-co">Client / company name</label>
      <input class="f" id="ws-co" value="${esc(editing?w.company_name:'')}" placeholder="e.g. Acme Foods">
      ${editing?'':`<div class="ws-cred-box">
        <div class="pt-scope big">${ic('key',13)} Client Admin login — share these with the client</div>
        <label class="f" for="ws-user">Admin user ID</label>
        <input class="f" id="ws-user" placeholder="e.g. acme.admin" autocomplete="off">
        <div class="hint">No spaces · letters, numbers, . _ -</div>
        <label class="f" for="ws-pass">Admin password</label>
        <div class="ai-model-row"><input class="f" id="ws-pass" type="text" autocomplete="new-password" value="${esc(genPassword())}">
          <button class="btn ghost sm" type="button" id="ws-gen">${ic('refresh',13)} New</button></div>
        <div class="hint">At least 6 characters with a number and a symbol. The client can change it later in My profile.</div></div>`}
      <label class="f" for="ws-name">Admin's name <span class="muted">(optional)</span></label>
      <input class="f" id="ws-name" value="${esc(editing?w.admin_name:'')}" placeholder="Person who manages this client">
      <label class="f" for="ws-mail">Admin email <span class="muted">(optional — used for password resets and reports)</span></label>
      <input class="f" id="ws-mail" type="email" value="${esc(editing?w.email:'')}" placeholder="admin@client.com">
      <label class="f">Social media accounts</label>
      ${modeChooser(editing?w.social_mode:'central')}
      <div class="hint">The Client Admin can change this later in Setup.</div>
      <div class="err" id="ws-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="ws-save">${ic(editing?'save':'plus',15)} ${editing?'Save':'Create workspace'}</button></div></div>`);
  openModal(m);
  if($('#ws-gen',m)) $('#ws-gen',m).onclick = ()=>{ $('#ws-pass',m).value = genPassword(); };
  $('#ws-save',m).onclick = async ()=>{
    $('#ws-err',m).textContent = '';
    const body = {company_name:$('#ws-co',m).value.trim(), admin_name:$('#ws-name',m).value.trim(),
                  email:$('#ws-mail',m).value.trim(), social_mode:(m.querySelector('[name=wsmode]:checked')||{}).value};
    if(!body.company_name){ $('#ws-err',m).textContent = 'Enter the client / company name.'; return; }
    try{
      if(editing){
        await api('/api/workspaces/'+w.id,{method:'PATCH', body}); closeModal(); toast('Workspace saved','good'); renderWorkspaces();
      }else{
        body.username = $('#ws-user',m).value.trim(); body.password = $('#ws-pass',m).value;
        const ue = checkUsername(body.username); if(ue){ $('#ws-err',m).textContent = ue; return; }
        const pe = checkPassword(body.password); if(pe){ $('#ws-err',m).textContent = pe; return; }
        await api('/api/workspaces',{method:'POST', body}); closeModal(); renderWorkspaces();
        showWorkspaceCreds(body.company_name, body.username, body.password);
      }
    }catch(e){ $('#ws-err',m).textContent = e.message; }
  };
}

function showWorkspaceCreds(company, user, pass){
  showLoginDetails('Workspace created', company, user, pass, `Your ${company} workspace on Social Platform`,
                   'Send these sign-in details to the client. The password isn\'t shown again.');
}

/* Sign-in details with a copy button (new workspaces, new users, password resets) */
function showLoginDetails(title, name, user, pass, heading, note){
  const site = location.origin;
  const text = `${heading || ('Your Social Platform login, ' + name)}\nSign in: ${site}\nUser ID: ${user}\nPassword: ${pass}\nPlease change your password after your first login (My profile).`;
  const m = el(`<div class="modal" style="max-width:480px">
    <div class="modal-head"><h3>${ic('check',18)} ${esc(title)}</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">${esc(note || 'Send these sign-in details to the person. They sign in with the User ID below — not their display name. The password isn\'t shown again.')}</p>
      <div class="ws-creds"><div><span>Sign in at</span><b>${esc(site)}</b></div><div><span>User ID</span><b>${esc(user)}</b></div>
        <div><span>Password</span><b>${esc(pass)}</b></div></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Done</button>
      <button class="btn" id="wsc-copy">${ic('copy',15)} Copy details</button></div></div>`);
  openModal(m);
  $('#wsc-copy',m).onclick = ()=>{ try{ navigator.clipboard.writeText(text); toast('Copied','good'); }catch(e){ toast(text); } };
}

function workspacePassword(w){
  const m = el(`<div class="modal" style="max-width:440px">
    <div class="modal-head"><h3>${ic('key',18)} New password for ${esc(w.company_name)}</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><p class="sub" style="margin-top:0">Sets a new password for the Client Admin <b>@${esc(w.admin_username)}</b>.</p>
      <div class="ai-model-row"><input class="f" id="wp-pass" type="text" value="${esc(genPassword())}" autocomplete="new-password">
        <button class="btn ghost sm" type="button" id="wp-gen">${ic('refresh',13)} New</button></div>
      ${w.totp_enabled?`<label class="cred-toggle" style="margin-top:10px"><input type="checkbox" id="wp-2fa"> <span>Also reset two-factor login</span></label>`:''}
      <div class="err" id="wp-err"></div></div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="wp-save">Set password</button></div></div>`);
  openModal(m);
  $('#wp-gen',m).onclick = ()=>{ $('#wp-pass',m).value = genPassword(); };
  $('#wp-save',m).onclick = async ()=>{
    const pw = $('#wp-pass',m).value, pe = checkPassword(pw); if(pe){ $('#wp-err',m).textContent = pe; return; }
    try{
      await api('/api/workspaces/'+w.id,{method:'PATCH', body:{password:pw}});
      if($('#wp-2fa',m) && $('#wp-2fa',m).checked) await api(`/api/users/${w.id}/2fa/reset`,{method:'POST'});
      closeModal(); showWorkspaceCreds(w.company_name, w.admin_username, pw); renderWorkspaces();
    }catch(e){ $('#wp-err',m).textContent = e.message; }
  };
}

function deleteWorkspace(w){
  const m = el(`<div class="modal" style="max-width:460px">
    <div class="modal-head"><h3>${ic('trash',18)} Delete ${esc(w.company_name)}?</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">This permanently removes the workspace's <b>${w.users+1} login(s)</b>, its <b>${w.accounts} social connection(s)</b>
        and its <b>${w.posts} post(s)</b>, videos, library, brand kit and links. It can't be undone.
        To keep the data but block access, use <b>Suspend</b> instead.</p>
      <label class="f" for="wd-name">Type <b>${esc(w.company_name)}</b> to confirm</label>
      <input class="f" id="wd-name" autocomplete="off">
      <div class="err" id="wd-err"></div></div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn danger" id="wd-go" disabled>Delete workspace</button></div></div>`);
  openModal(m);
  const inp = $('#wd-name',m), go = $('#wd-go',m);
  inp.oninput = ()=>{ go.disabled = inp.value.trim().toLowerCase() !== w.company_name.trim().toLowerCase(); };
  go.onclick = async ()=>{
    try{ await api('/api/workspaces/'+w.id,{method:'DELETE', body:{confirm:inp.value}}); closeModal(); toast('Workspace deleted','good'); renderWorkspaces(); }
    catch(e){ $('#wd-err',m).textContent = e.message; }
  };
}
