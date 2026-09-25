/* ============================================================
   Social Media Production Dashboard — Version 1
   Core: state, API, routing, topbar, landing, setup, auth, notifications
   ============================================================ */
const App = {
  user: null,
  page: 'input',           // input | calendar | published
  prod: 'all',             // sub filter: all | input | processing | completed
  notifOpen: false,
  calMonth: null,          // {y, m}
  focusPublished: null,    // item id to scroll/highlight in Published
};
window.App = App;

/* ============================================================
   THEMES — Cosmic Purple (default) + 5 more. Choice is saved
   locally and applied on every load before the UI renders.
   ============================================================ */
// Single fixed theme — the cosmic-glass look from the login reference. The
// theme switcher has been removed; the whole app uses this one palette.
const DEFAULT_THEME = 'cosmic';
const THEMES = [{id:'cosmic', name:'Cosmic', c:'#8b5cf6', dark:true}];
function currentTheme(){ return DEFAULT_THEME; }
function applyTheme(){
  document.body.dataset.theme = DEFAULT_THEME;
  try{ localStorage.setItem('pmTheme', DEFAULT_THEME); }catch(e){}
}
// apply immediately so there's no flash of the wrong theme
applyTheme();
try{ App.sidebarCollapsed = localStorage.getItem('pmSidebar')==='1'; }catch(e){}

function openThemePicker(anchor){
  const ex = document.querySelector('#theme-pop'); if(ex){ ex.remove(); return; }
  const cur = currentTheme();
  const pop = el(`<div class="theme-pop" id="theme-pop">
      <div class="tp-head">Choose a theme</div>
      <div class="tp-grid">${THEMES.map(t=>`
        <button class="tp-item ${t.id===cur?'on':''}" data-theme-id="${t.id}">
          <span class="tp-sw" style="background:${t.c}"></span>
          <span class="tp-nm">${t.name}</span>
          ${t.id===cur?`<span class="tp-ck">${ic('check',14)}</span>`:''}
        </button>`).join('')}</div></div>`);
  document.body.appendChild(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.top = (r.bottom+8)+'px';
  pop.style.right = Math.max(10, window.innerWidth - r.right)+'px';
  pop.querySelectorAll('[data-theme-id]').forEach(b=>b.onclick=()=>{
    applyTheme(b.dataset.themeId); pop.remove();
    if(typeof toast==='function') toast('Theme: '+(THEMES.find(t=>t.id===b.dataset.themeId)||{}).name,'good',1600);
  });
  setTimeout(()=>document.addEventListener('mousedown', function h(e){
    if(!pop.contains(e.target) && e.target!==anchor){ pop.remove(); document.removeEventListener('mousedown',h); }
  }),0);
}
function themeButton(){
  const w = el(`<div class="tasks-wrap"><button class="btn ghost onnavy sm" id="themeBtn" title="Change theme">${ic('sliders',15)} Theme</button></div>`);
  w.querySelector('#themeBtn').onclick = ()=>openThemePicker(w.querySelector('#themeBtn'));
  return w;
}
window.openThemePicker = openThemePicker;

/* ---------- tiny helpers ---------- */
const $  = (s, r=document) => r.querySelector(s);
const el = (html) => { const t=document.createElement('template'); t.innerHTML=html.trim(); return t.content.firstElementChild; };
const esc = (s) => (s==null?'':String(s)).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* Roles (V28): superadmin > admin > user. Pretty labels + "Name (Role)" format. */
const ROLE_LABELS = { superadmin:'SuperAdmin', admin:'Admin', user:'User' };
function roleLabel(role){ return ROLE_LABELS[(role||'user').toLowerCase()] || 'User'; }
function nameWithRole(u){
  if(!u) return '';
  if(u.name_with_role) return u.name_with_role;
  const name = u.display_name || u.username || '';
  return `${name} (${roleLabel(u.role)})`;
}
window.roleLabel = roleLabel; window.nameWithRole = nameWithRole;

/* Sidebar tabs + access control (V28.1). SuperAdmin sees everything, including
   the SuperAdmin-only Access & Logins tabs; Admin/User visibility is controlled
   by the SuperAdmin from the Access panel (App.user.allowed_tabs). */
// Social_Platform sidebar — trimmed to the essentials. Notifications, the
// Connect/Access/Logins/List-of-Users panels have been removed; social
// connections now live in the new "Setup" panel.
const NAV_TABS = [
  {key:'input',    label:'Input',           ic:'video',     group:'Workspace', badge:'navProdCount'},
  {key:'calendar', label:'Calendar',        ic:'calendar',  group:'Workspace', badge:'navCalRed'},
  {key:'queue',    label:'Queue',           ic:'clock',     group:'Workspace'},
  {key:'published',label:'Published',       ic:'send',      group:'Workspace', badge:'navPubCount'},
  {key:'analytics',label:'Analytics',       ic:'bars', group:'Workspace'},
  {key:'inbox',    label:'Inbox',           ic:'mail',     group:'Workspace', badge:'navInboxCount'},
  {key:'content',  label:'Content Writing', ic:'pen',       group:'Workspace'},
  {key:'library',  label:'Library',         ic:'folder',    group:'Workspace'},
  {key:'bio',      label:'Link in bio',     ic:'globe',     group:'Workspace'},
  {key:'reports',  label:'Reports',         ic:'fileText',      group:'Workspace'},
  {key:'workspaces', label:'Workspaces',    ic:'building',  group:'Account'},
  {key:'team',     label:'Team & Brands',   ic:'users',     group:'Account'},
  {key:'activity', label:'Activity Log',    ic:'activity',  group:'Account'},
  {key:'notifications', label:'Notifications', ic:'bell',  group:'Account', unread:'unread-notifications'},
  {key:'setup',    label:'Setup',           ic:'gear',      group:'Account'},
];
// V31 tabs are open to every logged-in user (data inside is still scoped per role)
// Everyone has these; a workspace admin has every section; a Sub-User gets the sections
// their Client Admin ticked (Team & Brands → Sub-Users). Workspaces is SuperAdmin-only.
const ALWAYS_TABS = ['setup','team','activity','notifications'];
function tabAllowed(key){
  const u = App.user || {};
  if(key==='workspaces') return !!u.is_super;
  if(u.is_super || ALWAYS_TABS.includes(key)) return true;
  if(!u.is_subuser) return true;                              // Client Admin: whole workspace
  return (u.allowed_tabs || []).includes(key);
}
window.tabAllowed = tabAllowed;

async function api(path, opts={}){
  const o = Object.assign({headers:{}}, opts);
  if(o.body && !(o.body instanceof FormData)){
    o.headers['Content-Type']='application/json';
    o.body = JSON.stringify(o.body);
  }
  const r = await fetch(path, o);
  let data = {};
  try{ data = await r.json(); }catch(e){}
  if(!r.ok) throw new Error(data.error || ('Request failed ('+r.status+')'));
  return data;
}

function toast(msg, kind='', ms=3200){
  const t = el(`<div class="toast ${kind}">${esc(msg)}</div>`);
  $('#toast-root').appendChild(t);
  setTimeout(()=>{ t.style.opacity='0'; t.style.transition='.3s'; setTimeout(()=>t.remove(),300); }, ms);
}

/* ---------- modal ---------- */
function openModal(node){
  closeModal();
  const ov = el('<div class="overlay"></div>');
  ov.appendChild(node);
  ov.addEventListener('mousedown', e=>{ if(e.target===ov) closeModal(); });
  $('#modal-root').appendChild(ov);
}
function closeModal(){ $('#modal-root').innerHTML=''; }
window.closeModal = closeModal;

/* ============================================================
   TOP BAR
   ============================================================ */
function renderTopbar(){
  const box = $('#topbar-actions');
  box.innerHTML='';
  const brand = $('#brand'); if(brand) brand.style.display = App.user ? '' : 'none';
  document.body.classList.toggle('logged-out', !App.user);
  // Clean top bar — theme is fixed; the user stats strip, Tasks, Setup/Install,
  // Notifications and Chatbot have all been removed for a minimal, premium look.
  if(App.user){
    const bs = el(`<div class="brand-switch" id="brandSwitch"></div>`);
    box.appendChild(bs); loadBrandSwitch();
    const bell = el(`<button class="icon-btn notif-wrap" id="bellBtn" title="Notifications">${ic('bell',18)}<span class="bell-dot hidden" id="bellCount">0</span></button>`);
    bell.onclick = ()=>{ App.page='notifications'; renderDashboard(App.readonly); };
    box.appendChild(bell);
    const pill = el(`<button class="pill user-pill" id="userPill" title="My profile"><span class="avatar">${esc(initials(App.user))}</span>
        <span class="up-name">${esc(App.user.name_with_role || nameWithRole(App.user))}</span> ${ic('chevDown',15)}</button>`);
    box.appendChild(pill);
    pill.onclick = openProfile;
    box.appendChild(btn(`${ic('logout',16)} Log out`,'ghost onnavy sm logout-btn', doLogout));
    if(typeof startNotifPolling==='function') startNotifPolling();
  }
  // logged-out: header stays clean (no buttons) — actions live on the login page
  if(typeof initTopSearch==='function') initTopSearch();
}
/* Brand / workspace switcher — filters the calendar, analytics & publishing accounts */
async function loadBrandSwitch(){
  const box = $('#brandSwitch'); if(!box) return;
  let d; try{ d = await api('/api/brands'); }catch(e){ box.innerHTML=''; return; }
  App._brands = d.brands || [];
  if(!App._brands.length){ box.innerHTML=''; return; }
  const cur = d.active_brand_id || '';
  box.innerHTML = `<label class="bs-label">${ic('building',15)}
      <select id="brandSel" title="Active brand">
        <option value="">All brands</option>
        ${App._brands.map(b=>`<option value="${b.id}" ${String(b.id)===String(cur)?'selected':''}>${esc(b.name)}</option>`).join('')}
      </select></label>`;
  $('#brandSel').onchange = async (e)=>{
    try{ await api('/api/brands/active',{method:'POST', body:{brand_id:e.target.value||null}});
      App.user.active_brand_id = e.target.value ? Number(e.target.value) : null;
      toast(e.target.value ? 'Switched brand' : 'Showing all brands','good');
      renderDashboard(App.readonly);
    }catch(err){ toast(err.message,'warn'); }
  };
}
window.loadBrandSwitch = loadBrandSwitch;

function btn(label, cls, on){ const b=el(`<button class="btn ${cls}">${label}</button>`); b.onclick=on; return b; }

/* Reflect Claude AI connection status in the top bar. Available to every
   logged-in user (status only — never the key itself). */
async function loadAiStatus(){
  const chip = $('#aiChip'); if(!chip) return;
  try{
    const s = await api('/api/settings/content');
    const on = !!s.claude_key_set;
    App._aiConnected = on;
    chip.classList.toggle('ai-on', on);
    chip.classList.toggle('ai-off', !on);
    chip.innerHTML = on ? `${ic('sparkles',14)} AI connected` : `${ic('sparkles',14)} AI off`;
    chip.title = on ? 'Claude AI is connected' : 'No AI key configured — open Content Writing';
  }catch(e){ chip.classList.add('hidden'); }
}
window.loadAiStatus = loadAiStatus;

/* ============================================================
   ROUTING
   ============================================================ */
async function boot(){
  try{ const d = await api('/api/me'); App.user = d.user; }catch(e){}
  renderTopbar();
  if(App.user){ renderDashboard(); startHeartbeat(); if(typeof maybeShowOnboarding==='function') maybeShowOnboarding(); }
  else{ renderLanding(); }
  const rt = new URLSearchParams(location.search).get('reset_token');
  if(rt){ history.replaceState(null, '', location.pathname); openResetWithToken(rt); }
}

/* Decorative 3D crystals for the login page (faceted amethyst gem + two glass
   wireframe cubes), drawn as inline SVG so they stay crisp at any size. */
const COSMIC_GEM_SVG = `<svg class="crystal c-gem" viewBox="0 0 200 220" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <linearGradient id="gA" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c8a6ff"/><stop offset="1" stop-color="#7c3aed"/></linearGradient>
    <linearGradient id="gB" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a855f7"/><stop offset="1" stop-color="#4c1d95"/></linearGradient>
    <linearGradient id="gC" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#8b5cf6"/><stop offset="1" stop-color="#3b1d6e"/></linearGradient>
  </defs>
  <g stroke="rgba(214,196,255,.55)" stroke-width="1.2" stroke-linejoin="round">
    <polygon points="100,8 20,54 100,112" fill="url(#gA)"/>
    <polygon points="100,8 180,54 100,112" fill="url(#gB)"/>
    <polygon points="20,54 20,152 100,112" fill="url(#gC)"/>
    <polygon points="180,54 180,152 100,112" fill="url(#gA)" opacity=".85"/>
    <polygon points="20,152 100,212 100,112" fill="url(#gB)"/>
    <polygon points="180,152 100,212 100,112" fill="url(#gC)" opacity=".9"/>
  </g>
</svg>`;
const _CUBE = (cls, o) => `<svg class="crystal ${cls}" viewBox="0 0 160 160" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <g stroke="rgba(206,180,255,.7)" stroke-width="1.4" stroke-linejoin="round">
    <polygon points="80,18 138,50 80,82 22,50" fill="rgba(168,85,247,${0.30*o})"/>
    <polygon points="22,50 80,82 80,146 22,114" fill="rgba(124,58,237,${0.24*o})"/>
    <polygon points="138,50 80,82 80,146 138,114" fill="rgba(99,102,241,${0.26*o})"/>
  </g>
</svg>`;
const COSMIC_CUBE_SVG = _CUBE('c-cube', 1);
const COSMIC_CUBE2_SVG = _CUBE('c-cube2', 0.6);

function renderLanding(){
  $('#readonly-banner').classList.add('hidden');
  const brand = $('#brand'); if(brand) brand.style.display='none';   // no top-left brand on login
  document.body.classList.add('logged-out');
  const v = $('#view');
  const brandHTML = (cls)=>`<div class="lp-brand ${cls}">
      <img src="/static/img/logo.png" alt="" width="512" height="377">
      <div><div class="lp-name">Social <span>Platform</span></div>
        <div class="lp-tag">Plan, produce &amp; schedule your social content.</div></div></div>`;
  v.innerHTML = `
    <div class="lp">
      <section class="lp-hero">
        ${brandHTML('lp-brand-top')}
        <div class="lp-copy">
          <div class="lp-eyebrow">Grow your brand</div>
          <h1 class="lp-h1">All Your<br><span>Social Media Marketing</span><br>in One Place</h1>
          <p class="lp-lead">Plan, create, schedule and analyze your social media content across multiple
            platforms — faster, smarter and more effectively.</p>
          <div class="lp-feats">
            <div class="lp-feat"><span class="lf-ic c1">${ic('calendar',22)}</span><b>Plan</b><small>Organize your content calendar</small></div>
            <div class="lp-feat"><span class="lf-ic c2">${ic('pen',22)}</span><b>Create</b><small>Design engaging content</small></div>
            <div class="lp-feat"><span class="lf-ic c3">${ic('send',22)}</span><b>Schedule</b><small>Publish at the right time</small></div>
            <div class="lp-feat"><span class="lf-ic c4">${ic('bars',22)}</span><b>Analyze</b><small>Track growth and performance</small></div>
          </div>
        </div>
      </section>

      <div class="lp-scene" aria-hidden="true">${typeof loginScene==='function' ? loginScene() : ''}</div>
      <section class="lp-card" aria-label="Sign in">
        <img class="lp-card-logo" src="/static/img/logo.png" alt="Social Platform logo" width="512" height="377">
        <div class="lp-name">Social <span>Platform</span></div>
        <div class="lp-tag">Plan, produce &amp; schedule your social content.</div>
        <h2 class="lp-welcome">Welcome Back</h2>
        <p class="lp-sub">Sign in to your account to continue</p>

        <div class="lp-fld"><span class="lp-fic">${ic('user',18)}</span>
          <input id="lg-user" placeholder="Username or Email" autocomplete="username" aria-label="Username or email"></div>
        <div class="lp-fld"><span class="lp-fic">${ic('lock',18)}</span>
          <input id="lg-pass" type="password" placeholder="Password" autocomplete="current-password" aria-label="Password">
          <button type="button" class="lp-eye" id="lg-eye" aria-label="Show password" title="Show password">${ic('eyeOff',18)}</button></div>

        <div class="lp-row">
          <label class="lp-check"><input type="checkbox" id="lg-remember"> Keep me logged in</label>
          <a href="#" id="lnkForgot">Forgot password?</a>
        </div>
        <div class="err" id="lg-err" role="alert"></div>
        <button class="lp-go" id="lg-go">Log In ${ic('arrowRight',18)}</button>
      </section>
    </div>`;

  // ---- login (single page) ----
  const doLoginSubmit = async ()=>{
    $('#lg-err').textContent='';
    const b = $('#lg-go'); b.disabled = true;
    try{
      const d = await api('/api/login', {method:'POST', body:{username:$('#lg-user').value,
        password:$('#lg-pass').value, remember:$('#lg-remember').checked}});
      if(d.need_2fa){ b.disabled = false; open2faPrompt(); return; }
      App.user = d.user; afterLogin();          // no toast/pop-up on login
    }catch(e){ $('#lg-err').textContent = e.message; b.disabled = false; }
  };
  $('#lg-go').onclick = doLoginSubmit;
  ['lg-user','lg-pass'].forEach(id=>$('#'+id).addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();doLoginSubmit();} }));
  document.querySelectorAll('.lp-fld').forEach(f=>f.addEventListener('mousedown', e=>{   // whole box focuses its input
    if(e.target.closest('button')) return; const i = f.querySelector('input'); if(e.target!==i){ e.preventDefault(); i.focus(); } }));
  $('#lg-eye').onclick = ()=>{
    const p = $('#lg-pass'), show = p.type === 'password';
    p.type = show ? 'text' : 'password';
    const e = $('#lg-eye'); e.innerHTML = ic(show ? 'eye' : 'eyeOff', 18);
    e.setAttribute('aria-label', show ? 'Hide password' : 'Show password'); e.title = e.getAttribute('aria-label');
  };

  $('#lnkForgot').onclick = (e)=>{ e.preventDefault(); openForgot(); };


  setTimeout(()=>{ const u=$('#lg-user'); if(u) u.focus(); }, 120);
}

/* username/password client-side rules (mirrors the server) */
function checkUsername(name){
  if(!name) return 'Choose a username.';
  if(/\s/.test(name)) return 'Username can\'t contain spaces.';
  if(!/^[A-Za-z0-9_.\-]{3,}$/.test(name)) return 'Username: 3+ chars, letters/numbers/. _ - only (no spaces).';
  return '';
}
function checkPassword(pw){
  if((pw||'').length<6) return 'Password must be at least 6 characters.';
  if(!/\d/.test(pw)) return 'Password must contain at least one number.';
  if(!/[^A-Za-z0-9]/.test(pw)) return 'Password must contain at least one special character (e.g. ! @ # $).';
  return '';
}
window.checkUsername=checkUsername; window.checkPassword=checkPassword;

/* Create account (dialog) */
function openCreateAccount(){
  const m = el(`<div class="modal" style="max-width:420px">
    <div class="modal-head"><h3>Create account</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Username</label><input class="f" id="cr-user" placeholder="Choose a username">
      <div class="hint">No spaces · must be unique · letters, numbers, . _ -</div>
      <label class="f">Password</label><input class="f" id="cr-pass" type="password" placeholder="Choose a password">
      <div class="hint">At least 6 characters, with one number and one special character.</div>
      <label class="f">Confirm password</label><input class="f" id="cr-pass2" type="password" placeholder="Re-enter password">
      <div class="err" id="cr-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="cr-go">Create &amp; log in</button></div></div>`);
  openModal(m);
  const go = async ()=>{
    $('#cr-err',m).textContent='';
    const uname=$('#cr-user',m).value.trim(), p=$('#cr-pass',m).value, p2=$('#cr-pass2',m).value;
    const ue=checkUsername(uname); if(ue){ $('#cr-err',m).textContent=ue; return; }
    const pe=checkPassword(p); if(pe){ $('#cr-err',m).textContent=pe; return; }
    if(p!==p2){ $('#cr-err',m).textContent='Passwords do not match.'; return; }
    try{
      const d = await api('/api/register', {method:'POST', body:{username:uname, password:p}});
      App.user = d.user; closeModal(); afterLogin();   // no pop-up on entry
    }catch(e){ $('#cr-err',m).textContent = e.message; }
  };
  $('#cr-go',m).onclick = go;
  m.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();go();} }));
  setTimeout(()=>$('#cr-user',m)&&$('#cr-user',m).focus(),40);
}

/* Forgot password: emails a one-time reset link (30 minutes) */
function openForgot(){
  const m = el(`<div class="modal" style="max-width:420px">
    <div class="modal-head"><h3>Forgot password</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">Enter your username. We'll email a reset link to the address on your profile.</p>
      <label class="f">Username</label><input class="f" id="fg-user" placeholder="Your username" autocomplete="username">
      <div class="err" id="fg-err"></div>
      <div class="ok-msg hidden" id="fg-ok"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Close</button>
      <button class="btn" id="fg-go">${ic('mail',14)} Send reset link</button></div></div>`);
  openModal(m);
  const go = async ()=>{
    $('#fg-err',m).textContent=''; $('#fg-ok',m).classList.add('hidden');
    try{
      const r = await api('/api/reset-password', {method:'POST', body:{username:$('#fg-user',m).value.trim()}});
      $('#fg-ok',m).innerHTML = `${ic('check',14)} ${esc(r.message||'Check your email for the reset link.')}`;
      $('#fg-ok',m).classList.remove('hidden'); $('#fg-go',m).disabled = true;
    }catch(e){ $('#fg-err',m).textContent = e.message; }
  };
  $('#fg-go',m).onclick = go;
  $('#fg-user',m).addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();go();} });
  setTimeout(()=>$('#fg-user',m)&&$('#fg-user',m).focus(),40);
}

/* Opened from the emailed link (/?reset_token=…) */
function openResetWithToken(token){
  const m = el(`<div class="modal" style="max-width:420px">
    <div class="modal-head"><h3>Choose a new password</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">New password</label><input class="f" id="rt-pass" type="password" autocomplete="new-password">
      <div class="hint">At least 6 characters, with one number and one special character.</div>
      <label class="f">Confirm new password</label><input class="f" id="rt-pass2" type="password" autocomplete="new-password">
      <div class="err" id="rt-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="rt-go">Save password</button></div></div>`);
  openModal(m);
  const go = async ()=>{
    $('#rt-err',m).textContent='';
    const p=$('#rt-pass',m).value, p2=$('#rt-pass2',m).value;
    const pe=checkPassword(p); if(pe){ $('#rt-err',m).textContent=pe; return; }
    if(p!==p2){ $('#rt-err',m).textContent='Passwords do not match.'; return; }
    try{ await api('/api/reset-password/confirm', {method:'POST', body:{token, password:p}});
      closeModal(); toast('Password updated — log in with your new password','good',5000); }
    catch(e){ $('#rt-err',m).textContent = e.message; }
  };
  $('#rt-go',m).onclick = go;
  m.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();go();} }));
  setTimeout(()=>$('#rt-pass',m)&&$('#rt-pass',m).focus(),40);
}
window.openResetWithToken = openResetWithToken;

/* Second login step when two-factor authentication is on */
function open2faPrompt(){
  const m = el(`<div class="modal" style="max-width:400px">
    <div class="modal-head"><h3>${ic('shield',18)} Two-factor login</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">Enter the 6-digit code from your authenticator app, or one of your recovery codes.</p>
      <input class="f code-in" id="tf-code" inputmode="numeric" autocomplete="one-time-code" placeholder="123456" maxlength="20">
      <div class="err" id="tf-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="tf-go">Verify</button></div></div>`);
  openModal(m);
  const go = async ()=>{
    $('#tf-err',m).textContent='';
    try{ const d = await api('/api/login/2fa', {method:'POST', body:{code:$('#tf-code',m).value.trim()}});
      App.user = d.user; closeModal(); afterLogin(); }
    catch(e){ $('#tf-err',m).textContent = e.message; $('#tf-code',m).select(); }
  };
  $('#tf-go',m).onclick = go;
  $('#tf-code',m).addEventListener('keydown',e=>{ if(e.key==='Enter'){e.preventDefault();go();} });
  setTimeout(()=>$('#tf-code',m)&&$('#tf-code',m).focus(),40);
}
window.open2faPrompt = open2faPrompt;

/* Dashboard shell (side panel + content) */
function renderDashboard(readonly=false){
  App.readonly = readonly && !(App.user && App.user.fully_connected);
  $('#readonly-banner').classList.toggle('hidden', !App.readonly);
  const v = $('#view');
  if(!App.page) App.page = 'input';
  // enforce tab access: if the current page isn't allowed, jump to the first allowed one
  if(App.user && !tabAllowed(App.page)){
    App.page = NAV_TABS.map(t=>t.key).find(tabAllowed) || 'input';
  }
  const navItem = (t)=>{
    const unread = t.unread ? `<span class="nav-unread hidden" id="${t.unread}"></span>` : '';
    const badge  = t.badge  ? `<span class="badge" id="${t.badge}">0</span>` : '';
    return `<div class="navitem ${App.page===t.key?'active':''}" data-nav="${t.key}" title="${esc(t.label)}">
        <span class="ic">${ic(t.ic, 18)}</span> <span class="nav-txt">${esc(t.label)}</span> ${unread}${badge}</div>`;
  };
  let sideHTML = '';
  const groups = ['Workspace','Account'];
  groups.forEach((g, gi)=>{
    const items = NAV_TABS.filter(t=>t.group===g && tabAllowed(t.key));
    if(items.length) sideHTML += `<h4>${g}</h4>` + items.map(navItem).join('');
  });
  // Collapse control: icon-only in the bottom-right corner; the label slides out on hover.
  sideHTML += `<button class="side-collapse corner" id="sideCollapse" type="button"
      title="${App.sidebarCollapsed?'Expand':'Collapse'} sidebar" aria-label="${App.sidebarCollapsed?'Expand':'Collapse'} sidebar">
      <span class="sc-label">${App.sidebarCollapsed?'Expand':'Collapse'}</span>
      <span class="sc-ic">${ic(App.sidebarCollapsed?'expand':'collapse', 16)}</span></button>`;
  v.innerHTML = `
    <div class="shell">
      <div class="sidepanel ${App.sidebarCollapsed?'collapsed':''}" id="sidepanel">
        ${sideHTML}
      </div>
      <div class="content">
        <div id="pageContent"></div>
      </div>
    </div>`;
  if(typeof watchPage==='function') watchPage();
  v.querySelectorAll('[data-nav]').forEach(n=>n.onclick=()=>{ App.page=n.dataset.nav; renderDashboard(App.readonly); });
  const sc = $('#sideCollapse');
  if(sc) sc.onclick = ()=>{
    App.sidebarCollapsed = !App.sidebarCollapsed;
    const sp = $('#sidepanel'); if(sp) sp.classList.toggle('collapsed', App.sidebarCollapsed);
    const sic = sc.querySelector('.sc-ic'); if(sic) sic.innerHTML = ic(App.sidebarCollapsed ? 'expand' : 'collapse', 16);
    const word = App.sidebarCollapsed ? 'Expand' : 'Collapse';
    sc.querySelector('.sc-label').textContent = word; sc.title = sc.ariaLabel = word + ' sidebar';
    try{ localStorage.setItem('pmSidebar', App.sidebarCollapsed?'1':'0'); }catch(e){}
  };
  if(App.user){ loadPubBadge(); loadInboxBadge(); loadNotifCount(); }
  if(App.page==='input') renderProduction();
  else if(App.page==='calendar') renderCalendar();
  else if(App.page==='published') renderPublished();
  else if(App.page==='reports') renderReports();
  else if(App.page==='setup') renderSetup();
  else if(App.page==='content') renderContent();
  else if(App.page==='analytics') renderAnalytics();
  else if(App.page==='inbox') renderInbox();
  else if(App.page==='queue') renderQueue();
  else if(App.page==='team') renderTeam();
  else if(App.page==='activity') renderActivity();
  else if(App.page==='notifications') renderNotifications();
  else if(App.page==='library') renderLibrary();
  else if(App.page==='workspaces') renderWorkspaces();
  else if(App.page==='bio') renderBio();
  else { App.page='input'; renderProduction(); }
  // reflect subscription state (read-only banner / renewal alert) on every page
  if(typeof applySubscriptionState==='function') applySubscriptionState();
}

async function loadUserBadge(){
  try{ const d=await api('/api/presence'); const b=$('#navUserCount'); if(b) b.textContent=d.total_users; }catch(e){}
}

async function loadInboxBadge(){
  try{ const d=await api('/api/inbox?status=new'); const b=$('#navInboxCount');
    if(b){ b.textContent=d.comments.length; b.classList.toggle('alert', d.negative_new>0); } }catch(e){}
}
window.loadInboxBadge = loadInboxBadge;

async function loadPubBadge(){
  try{ const d=await api('/api/published'); const b=$('#navPubCount'); if(b) b.textContent=d.published.length; }catch(e){}
}

/* ============================================================
   ACCESS  (SuperAdmin only) — control which tabs Admins/Users see
   ============================================================ */
async function renderAccess(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="panel-head"><h2>Access</h2>
      <p class="sub">Choose which side-panel tabs Admins and Users can open. Set a
      default per role, and optionally override individual users. The SuperAdmin
      always sees every tab.</p></div>
    <div id="accessBody"><div class="loading">Loading…</div></div>`;
  let d; try{ d = await api('/api/access'); }
  catch(e){ $('#accessBody').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const tabs = d.tabs;
  const chk = (attrs, key, on, disabled)=>`<label class="acc-chk">
      <input type="checkbox" ${attrs} value="${key}" ${on?'checked':''} ${disabled?'disabled':''}> ${esc(tabs.find(t=>t.key===key).label)}</label>`;
  const roleBlock = (role, allowed)=>`
    <div class="acc-card">
      <h3>${role==='admin'?'Admin':'User'} role — allowed tabs</h3>
      <div class="acc-tabs">${tabs.map(t=>chk(`data-role="${role}"`, t.key, allowed.includes(t.key), false)).join('')}</div>
    </div>`;
  const userBlock = (u)=>{
    const useDef = (u.override === null);
    const allowed = useDef ? [] : u.override;
    return `<div class="acc-user" data-uid="${u.id}">
        <div class="acc-user-head"><b>${esc(u.name_with_role)}</b>
          <label class="acc-chk"><input type="checkbox" class="acc-usedefault" ${useDef?'checked':''}> Use role default</label></div>
        <div class="acc-tabs acc-user-tabs">${tabs.map(t=>chk('class="acc-uch"', t.key, (!useDef && allowed.includes(t.key)), useDef)).join('')}</div>
      </div>`;
  };
  $('#accessBody').innerHTML = `
    <div class="acc-roles">${roleBlock('admin', d.role_defaults.admin)}${roleBlock('user', d.role_defaults.user)}</div>
    <h3 class="acc-h">Per-user overrides</h3>
    <p class="sub">Untick “Use role default” to give a specific user their own set of tabs.</p>
    <div class="acc-users">${d.users.length ? d.users.map(userBlock).join('') : '<div class="empty">No Admins or Users yet.</div>'}</div>
    <div class="err" id="acc-err"></div>
    <button class="btn" id="acc-save" style="margin-top:14px">Save access settings</button>`;
  c.querySelectorAll('.acc-usedefault').forEach(ch=>ch.onchange=()=>{
    const row = ch.closest('.acc-user');
    row.querySelectorAll('.acc-uch').forEach(x=>{ x.disabled = ch.checked; if(ch.checked) x.checked=false; });
  });
  $('#acc-save').onclick = async ()=>{
    $('#acc-err').textContent = '';
    const role_defaults = {admin:[], user:[]};
    c.querySelectorAll('input[data-role]').forEach(x=>{ if(x.checked) role_defaults[x.dataset.role].push(x.value); });
    const user_overrides = {};
    c.querySelectorAll('.acc-user').forEach(row=>{
      const uid = row.dataset.uid;
      if(row.querySelector('.acc-usedefault').checked){ user_overrides[uid] = null; }
      else { const arr=[]; row.querySelectorAll('.acc-uch').forEach(x=>{ if(x.checked) arr.push(x.value); }); user_overrides[uid]=arr; }
    });
    try{ await api('/api/access',{method:'POST', body:{role_defaults, user_overrides}}); toast('Access settings saved','good'); }
    catch(e){ $('#acc-err').textContent = e.message; }
  };
}
window.renderAccess = renderAccess;

/* ============================================================
   LOGINS  (SuperAdmin only) — full account details + actions
   ============================================================ */
async function renderLogins(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="panel-head"><h2>Logins</h2>
      <p class="sub">Every account created on this workspace, with full details.</p></div>
    <div id="loginsBody"><div class="loading">Loading…</div></div>`;
  let d; try{ d = await api('/api/logins'); }
  catch(e){ $('#loginsBody').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const st = (u)=> u.online ? '<span class="pdot on"></span> Online'
    : (u.last_seen ? esc((typeof fmtTime==='function'?fmtTime(u.last_seen):u.last_seen)) : 'Never');
  const conns = (u)=>{
    const ig = u.instagram_connected ? `IG ${u.instagram_account?('@'+esc(u.instagram_account).replace(/^@/,'')):ic('check',12)}` : '';
    const gd = u.google_connected ? `Drive ${u.google_account?esc(u.google_account):ic('check',12)}` : '';
    return [ig, gd].filter(Boolean).join('<br>') || '<span class="sub">—</span>';
  };
  // Per-user "Can view credentials" control. The SuperAdmin always can (fixed);
  // for everyone else it's an on/off toggle wired to /api/users/<id>/creds-access.
  const creds = (u)=> u.role==='superadmin'
    ? '<span class="sub">always</span>'
    : `<label class="cred-toggle"><input type="checkbox" data-creds="${u.id}" ${u.can_view_credentials?'checked':''}> <span>view</span></label>`;
  const rows = d.users.map(u=>`<tr>
      <td>${esc(u.display_name)}</td>
      <td>@${esc(u.username)}</td>
      <td><span class="urole-badge role-${esc(u.role)}">${esc(u.role_label)}</span></td>
      <td>${esc(u.email||'—')}${u.phone?'<br><span class="sub">'+esc(u.phone)+'</span>':''}</td>
      <td>${st(u)}</td>
      <td>${conns(u)}</td>
      <td class="cred-cell">${creds(u)}</td>
      <td>${esc((u.created_at||'').slice(0,10)||'—')}</td>
      <td class="logins-act">${u.role==='superadmin'
        ? '<span class="sub">permanent</span>'
        : `<button class="btn ghost xs" data-reset="${u.id}" data-name="${esc(u.username)}">Reset password</button>
           <button class="btn danger xs" data-del="${u.id}">Delete</button>`}</td>
    </tr>`).join('');
  $('#loginsBody').innerHTML = `<div class="logins-wrap"><table class="logins-tbl">
      <thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Contact</th><th>Status</th><th>Connections</th><th title="Can view the Credentials area (API key + OAuth)">Credentials</th><th>Created</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  c.querySelectorAll('[data-creds]').forEach(cb=>cb.onchange=async ()=>{
    const id=cb.dataset.creds, allow=cb.checked;
    try{ await api(`/api/users/${id}/creds-access`,{method:'POST', body:{allow}});
      toast(allow?'Credential access granted':'Credential access revoked','good'); }
    catch(e){ cb.checked=!allow; toast(e.message,'warn'); }
  });
  c.querySelectorAll('[data-reset]').forEach(b=>b.onclick=()=>resetUserPassword(b.dataset.reset, b.dataset.name));
  c.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>{
    confirmBox('Delete this user account?','This permanently removes the account and cannot be undone.',
      async ()=>{ try{ await api(`/api/users/${b.dataset.del}`,{method:'DELETE'}); toast('User deleted','good'); if(App.page==='logins') renderLogins(); }
        catch(e){ toast(e.message,'warn'); } }, 'Delete user');
  });
}
window.renderLogins = renderLogins;

/* Tools status strip — single row: each tool with a green(installed)/red(not) dot */
async function loadToolsStatus(){
  const box = $('#toolsStatus'); if(!box) return;
  try{
    const s = await api('/api/tools/summary');
    const dots = [
      ...s.connected.map(n=>`<span class="tstat"><i class="dot g"></i>${esc(n)}</span>`),
      ...s.not_connected.map(n=>`<span class="tstat"><i class="dot r"></i>${esc(n)}</span>`),
    ].join('');
    box.innerHTML = `<div class="tools-status">
        <div class="ring" style="--p:${s.percent}"><span>${s.percent}%</span></div>
        <div class="ts-txt">
          <div><b>Required tools installed:</b> ${s.installed_count} of ${s.total}</div>
          <div class="tstat-row">${dots}</div>
        </div>
        <div class="sp"></div>
        <button class="btn sm" id="tsSetup">Open Setup</button>
      </div>`;
    const b=$('#tsSetup',box); if(b) b.onclick=openSetup;
  }catch(e){ box.innerHTML=''; }
}
window.loadToolsStatus = loadToolsStatus;

/* ============================================================
   SETUP / TOOLS WINDOW
   ============================================================ */
async function openSetup(){
  const m = el(`<div class="modal wide">
    <div class="modal-head"><h3>Setup — Required Tools</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p style="color:var(--muted);font-size:13px;margin-top:0">
        Install these before logging in. Click <b>Install</b> to download the official installer
        (live progress, size &amp; speed shown below) and launch it automatically, or use the link for a
        manual download. Installs keep running in the background — you can close this window; press
        <b>Cancel</b> to stop one.</p>
      <div id="toolList"><div class="loading sm">Loading…</div></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Close</button></div>
  </div>`);
  openModal(m);
  try{
    const d = await api('/api/tools');
    const list = $('#toolList', m);
    list.innerHTML='';
    d.tools.forEach(t=>{
      const stateHtml = t.installed===true
        ? `<button class="btn ghost sm" data-check="${t.id}">Check</button>
           <span class="ready"><i class="dot g"></i> Ready for use</span>`
        : `<button class="btn sm" data-inst="${t.id}">Install</button>
           <button class="btn green sm" data-check="${t.id}" title="Re-check after installing">Check</button>
           <button class="btn danger sm hidden" data-cancel="${t.id}">Cancel</button>
           <a class="btn ghost sm" href="${esc(t.url)}" target="_blank">Link</a>`;
      const row = el(`<div class="tool">
        <div class="ti">${esc(t.name[0])}</div>
        <div class="info"><div class="n"><i class="dot ${t.installed?'g':'r'}"></i> ${esc(t.name)}
             <span style="color:var(--muted);font-weight:500"> · ${esc(t.category)}</span></div>
          <div class="d">${esc(t.desc)}</div>
          <div class="st ${t.installed?'ok':'no'}" id="st-${t.id}">${t.installed===true?'Ready for use':(t.installed===false?'Not detected':'')}</div>
          <div class="dl-progress hidden" id="dlp-${t.id}">
             <div class="bar"><div class="fill" id="dlf-${t.id}"></div></div>
          </div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">${stateHtml}</div>
      </div>`);
      list.appendChild(row);
    });
    list.querySelectorAll('[data-inst]').forEach(b=>b.onclick=()=>installTool(b.dataset.inst, b));
    list.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=()=>cancelInstall(b.dataset.cancel));
    list.querySelectorAll('[data-check]').forEach(b=>b.onclick=()=>recheckTool(b.dataset.check, b));
  }catch(e){ $('#toolList',m).innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}

/* Re-analyse a tool now — flips the red dot to green when it's newly detected. */
async function recheckTool(id, btnEl){
  const row = btnEl.closest('.tool'); if(!row) return;
  const label = btnEl.textContent;
  btnEl.disabled = true; btnEl.textContent = 'Checking…';
  try{
    const r = await api(`/api/tools/${id}/detect`);
    const dotName = row.querySelector('.n .dot');
    const st = row.querySelector('.st');
    const actions = btnEl.parentElement;
    if(r.installed === true){
      if(dotName){ dotName.classList.remove('r'); dotName.classList.add('g'); }
      if(st){ st.className = 'st ok'; st.textContent = 'Ready for use'; }
      actions.innerHTML = `<button class="btn ghost sm" data-check="${id}">Check</button>
        <span class="ready"><i class="dot g"></i> Ready for use</span>`;
      actions.querySelector('[data-check]').onclick = (e)=>recheckTool(id, e.target);
      toast('Detected — ready for use','good');
      loadToolsStatus();   // refresh the % ring + strip
    }else{
      if(dotName){ dotName.classList.remove('g'); dotName.classList.add('r'); }
      if(st){ st.className = 'st err'; st.textContent = 'Still not detected — install it, then Check again'; }
      btnEl.disabled = false; btnEl.textContent = label;
      toast('Not detected yet','warn');
    }
  }catch(e){ btnEl.disabled=false; btnEl.textContent=label; toast(e.message,'warn'); }
}
window.recheckTool = recheckTool;

async function cancelInstall(id){
  try{ await api(`/api/tools/${id}/cancel`, {method:'POST'}); toast('Cancelling…','warn'); }
  catch(e){ toast(e.message,'warn'); }
}

async function installTool(id, btnEl){
  const st  = $('#st-'+id);
  const bar = $('#dlp-'+id);
  const fill= $('#dlf-'+id);
  const cancelBtn = document.querySelector(`[data-cancel="${id}"]`);
  if(bar) bar.classList.remove('hidden');
  if(cancelBtn) cancelBtn.classList.remove('hidden');
  btnEl.disabled=true; btnEl.textContent='Starting…';
  try{
    await api(`/api/tools/${id}/install`, {method:'POST'});
    const poll = setInterval(async ()=>{
      const s = await api(`/api/tools/${id}/status`);
      const pct = s.percent||0;
      if(fill) fill.style.width = pct+'%';
      if(st){
        st.className='st busy';
        if(s.status==='downloading' && s.total_mb)
          st.textContent = `Downloading ${pct}%  ·  ${s.downloaded_mb} / ${s.total_mb} MB`
                           + (s.speed?`  ·  ${s.speed}`:'');
        else st.textContent = s.message || s.status;
      }
      if(['done','manual','error','idle','cancelled'].includes(s.status)){
        clearInterval(poll);
        btnEl.disabled=false; btnEl.textContent='Install';
        if(cancelBtn) cancelBtn.classList.add('hidden');
        if(fill) fill.style.width = (s.status==='error'||s.status==='cancelled'?0:100)+'%';
        const kind = (s.status==='error'||s.status==='cancelled')?'warn':'good';
        if(s.status==='done'){
          // the external installer was launched — keep auto-checking until the
          // OS reports the tool installed, then flip it green (no manual Check).
          if(st){ st.className='st busy'; st.textContent='Finishing install — verifying…'; }
          waitForInstalled(id, btnEl);
        }else{
          if(st) st.className = (s.status==='error'||s.status==='cancelled')?'st err':'st ok';
          toast(s.message || 'Installer launched', kind, 5000);
        }
      }
    }, 700);
  }catch(e){ toast(e.message,'warn'); btnEl.disabled=false; btnEl.textContent='Install'; if(cancelBtn) cancelBtn.classList.add('hidden'); }
}

/* Poll detection after an installer is launched. When the tool is detected,
   flip its row green automatically; once EVERY tool is installed, close Setup. */
function waitForInstalled(id, btnEl){
  let tries = 0;
  const poll = setInterval(async ()=>{
    tries++;
    let r; try{ r = await api(`/api/tools/${id}/detect`); }catch(e){ return; }
    if(r.installed === true){
      clearInterval(poll);
      const row = btnEl && btnEl.closest('.tool');
      if(row){
        const dot = row.querySelector('.n .dot'); if(dot){ dot.classList.remove('r'); dot.classList.add('g'); }
        const st = row.querySelector('.st'); if(st){ st.className='st ok'; st.textContent='Ready for use'; }
        const acts = btnEl.parentElement;
        if(acts) acts.innerHTML = `<button class="btn ghost sm" data-check="${id}">Check</button>
          <span class="ready"><i class="dot g"></i> Ready for use</span>`;
        if(acts && acts.querySelector('[data-check]')) acts.querySelector('[data-check]').onclick = (e)=>recheckTool(id, e.target);
      }
      toast('Detected — ready for use','good');
      loadToolsStatus();
      maybeCloseSetupWhenDone();
    }else if(tries > 600){ clearInterval(poll); }   // give up after ~30 min
  }, 3000);
}

/* If all required tools are now installed, auto-close the Setup window. */
async function maybeCloseSetupWhenDone(){
  try{
    const s = await api('/api/tools/summary');
    if(s.percent >= 100){
      if($('#toolList')){ closeModal(); toast('All required tools are installed','good', 4000); }
    }
  }catch(e){}
}
window.maybeCloseSetupWhenDone = maybeCloseSetupWhenDone;

/* ============================================================
   AUTH  — single username / password login (Enter to submit)
   ============================================================ */
function openLogin(){
  const m = el(`<div class="modal" style="max-width:400px">
    <div class="modal-head"><h3>Log in</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Username</label>
      <input class="f" id="li-user" placeholder="Username" autocomplete="username">
      <label class="f">Password</label>
      <input class="f" id="li-pass" type="password" placeholder="Password" autocomplete="current-password">
      <div class="err" id="li-err"></div>
      <button class="btn" style="width:100%;margin-top:12px" id="li-go">Log in</button>
      <div class="note">Log in with your account, or use <b>Create account</b> to register.</div>
    </div>
  </div>`);
  openModal(m);
  const submit = async ()=>{
    $('#li-err',m).textContent='';
    try{
      const d = await api('/api/login', {method:'POST', body:{
        username:$('#li-user',m).value, password:$('#li-pass',m).value}});
      if(d.need_2fa){ open2faPrompt(); return; }
      App.user = d.user; afterLogin();          // no toast/pop-up on login
    }catch(e){ $('#li-err',m).textContent = e.message; }
  };
  $('#li-go',m).onclick = submit;
  const onEnter = (e)=>{ if(e.key==='Enter'){ e.preventDefault(); submit(); } };
  $('#li-user',m).addEventListener('keydown', onEnter);
  $('#li-pass',m).addEventListener('keydown', onEnter);
  setTimeout(()=>{ const u=$('#li-user',m); if(u) u.focus(); }, 40);
}

/* logging in goes straight to the dashboard */
function enterDashboard(){
  closeModal(); renderTopbar(); renderDashboard();
  startHeartbeat();          // presence (kept; silent)
  // No auto pop-ups except the FIRST-TIME onboarding Welcome popup below.
  // Notifications, Tasks, Chatbot and the Setup/Install prompt are all removed.
  if(typeof maybeShowOnboarding==='function') maybeShowOnboarding();
}
function afterLogin(){ enterDashboard(); }

/* On login, automatically check required tools and pop up Setup if any missing. */
async function autoCheckTools(){
  try{
    const s = await api('/api/tools/summary');
    if(s && s.percent < 100 && !$('#toolList')){
      openSetup();
      toast(`Some required tools are missing (${s.installed_count}/${s.total}). Install them to continue.`,'warn',6000);
    }
  }catch(e){}
}
window.autoCheckTools = autoCheckTools;

/* Once the user is connected: if the AI Model is already installed, make sure
   its model is pulled and running in the background — no reinstall. */
let _aiPoll = null;
async function ensureAiModel(){
  try{
    const r = await api('/api/aimodel/ensure', {method:'POST'});
    if(!r || r.installed === false) return;          // not installed → Setup handles it
    if(r.status === 'ready'){ toast('AI Model ready','good'); loadToolsStatus(); return; }
    toast('AI Model: preparing in the background…');
    if(_aiPoll) clearInterval(_aiPoll);
    _aiPoll = setInterval(async ()=>{
      try{
        const s = await api('/api/aimodel/status');
        if(s.status === 'ready'){
          clearInterval(_aiPoll); _aiPoll=null;
          toast('AI Model is running','good'); loadToolsStatus();
        }else if(s.status === 'error'){
          clearInterval(_aiPoll); _aiPoll=null;
          toast(s.message || 'AI Model could not start','bad');
        }
      }catch(e){ clearInterval(_aiPoll); _aiPoll=null; }
    }, 2500);
  }catch(e){ /* silent — dashboard still works without the model */ }
}

/* Instagram Graph API publishing settings */
async function openIgSettings(){
  let s = {ig_user_id:'', public_base_url:'', token_set:false};
  try{ s = await api('/api/settings/instagram'); }catch(e){}
  const m = el(`<div class="modal">
    <div class="modal-head"><h3>Instagram publishing settings</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <div class="note" style="margin-top:0">To publish to the <b>real</b> Instagram, you need a Facebook/Instagram
        <b>Business</b> account, a Graph API <b>access token</b>, your <b>IG user id</b>, and a
        <b>public https URL</b> where your videos are reachable (Instagram cannot read localhost).
        Leave blank if you connect Instagram from Setup.</div>
      <label class="f">Instagram Business account ID</label>
      <input class="f" id="ig-uid" value="${esc(s.ig_user_id||'')}" placeholder="1784xxxxxxxxxxx">
      <label class="f">Public base URL (serves your /uploads)</label>
      <input class="f" id="ig-url" value="${esc(s.public_base_url||'')}" placeholder="https://your-public-host">
      <label class="f">Graph API access token ${s.token_set?'(already set — leave blank to keep)':''}</label>
      <input class="f" id="ig-tok" type="password" placeholder="${s.token_set?'••••••••':'EAAG...'}">
      <div class="err" id="ig-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Close</button>
      <button class="btn" id="ig-save">Save</button></div></div>`);
  openModal(m);
  $('#ig-save',m).onclick = async ()=>{
    const body = {ig_user_id:$('#ig-uid',m).value, public_base_url:$('#ig-url',m).value};
    const tok = $('#ig-tok',m).value.trim(); if(tok) body.ig_token = tok;
    try{ await api('/api/settings/instagram',{method:'POST', body}); toast('Instagram settings saved','good'); closeModal(); }
    catch(e){ $('#ig-err',m).textContent=e.message; }
  };
}
window.openIgSettings = openIgSettings;

/* Profile: display name, email, password and two-factor login */
function openProfile(){
  const u = App.user||{};
  const m = el(`<div class="modal" style="max-width:460px">
    <div class="modal-head"><h3>My profile</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f">Display name</label>
      <input class="f" id="pf-name" value="${esc(u.display_name||u.username||'')}">
      <label class="f">Email <span class="muted">(for password reset links and alerts)</span></label>
      <input class="f" id="pf-email" type="email" value="${esc(u.email||'')}" placeholder="you@company.com">
      <div class="err" id="pf-err"></div>
      <button class="btn sm" id="pf-save" style="margin-top:6px">Save</button>
      <hr class="sep">
      <label class="f">Change password</label>
      <input class="f" id="pf-cur" type="password" placeholder="Current password" style="margin-bottom:8px">
      <input class="f" id="pf-new" type="password" placeholder="New password" style="margin-bottom:8px">
      <input class="f" id="pf-new2" type="password" placeholder="Confirm new password">
      <div class="err" id="pf-perr"></div>
      <button class="btn sm" id="pf-pwsave" style="margin-top:6px">Update password</button>
      <hr class="sep">
      <label class="f">${ic('shield',14)} Two-factor login</label>
      <div id="pf-2fa"></div>
    </div></div>`);
  openModal(m);
  $('#pf-save',m).onclick = async ()=>{
    $('#pf-err',m).textContent='';
    try{ const r = await api('/api/me/profile',{method:'POST', body:{display_name:$('#pf-name',m).value, email:$('#pf-email',m).value}});
      App.user = r.user; renderTopbar(); toast('Profile saved','good');
    }catch(e){ $('#pf-err',m).textContent=e.message; }
  };
  $('#pf-pwsave',m).onclick = async ()=>{
    $('#pf-perr',m).textContent='';
    const n=$('#pf-new',m).value, n2=$('#pf-new2',m).value;
    const pe=checkPassword(n); if(pe){ $('#pf-perr',m).textContent=pe; return; }
    if(n!==n2){ $('#pf-perr',m).textContent='New passwords do not match.'; return; }
    try{ await api(`/api/users/${u.id}/password`,{method:'POST', body:{current:$('#pf-cur',m).value, password:n}});
      toast('Password updated','good'); $('#pf-cur',m).value=$('#pf-new',m).value=$('#pf-new2',m).value='';
    }catch(e){ $('#pf-perr',m).textContent=e.message; }
  };
  const box = $('#pf-2fa',m);
  const draw = ()=>{
    if((App.user||{}).totp_enabled){
      box.innerHTML = `<div class="ok-msg">${ic('check',14)} On — you'll be asked for a code from your authenticator app at each login.</div>
        <details class="tf-off"><summary>Turn off two-factor login</summary>
          <input class="f" id="tf-pw" type="password" placeholder="Your password" style="margin:8px 0">
          <input class="f" id="tf-cd" inputmode="numeric" placeholder="Current 6-digit code">
          <div class="err" id="tf-e"></div><button class="btn danger sm" id="tf-off" style="margin-top:6px">Turn off</button></details>`;
      $('#tf-off',m).onclick = async ()=>{ try{ await api('/api/2fa/disable',{method:'POST', body:{password:$('#tf-pw',m).value, code:$('#tf-cd',m).value.trim()}});
          App.user.totp_enabled = false; toast('Two-factor login turned off'); draw(); }catch(e){ $('#tf-e',m).textContent=e.message; } };
    }else{
      box.innerHTML = `<p class="sub" style="margin:0 0 8px">Protect your account with a code from Google Authenticator, Microsoft Authenticator or 1Password.</p>
        <button class="btn ghost sm" id="tf-start">${ic('lock',14)} Set up two-factor login</button>`;
      $('#tf-start',m).onclick = async ()=>{
        let r; try{ r = await api('/api/2fa/setup',{method:'POST'}); }catch(e){ toast(e.message,'warn'); return; }
        box.innerHTML = `<ol class="tf-steps"><li>Scan this QR code in your authenticator app.</li>
            <li>Enter the 6-digit code it shows.</li></ol>
          <div class="tf-qr">${r.qr_svg}</div>
          <div class="hint">Can't scan? Enter this key: <code>${esc(r.secret)}</code></div>
          <input class="f code-in" id="tf-code" inputmode="numeric" maxlength="6" placeholder="123456" style="margin-top:8px">
          <div class="err" id="tf-e"></div><button class="btn sm" id="tf-en" style="margin-top:6px">Turn on</button>`;
        $('#tf-en',m).onclick = async ()=>{ try{ const d = await api('/api/2fa/enable',{method:'POST', body:{code:$('#tf-code',m).value.trim()}});
            App.user.totp_enabled = true;
            box.innerHTML = `<div class="ok-msg">${ic('check',14)} Two-factor login is on.</div>
              <p class="sub"><b>Save these recovery codes</b> somewhere safe. Each one works once if you lose your phone. They won't be shown again.</p>
              <div class="tf-codes">${d.recovery_codes.map(c=>`<code>${esc(c)}</code>`).join('')}</div>
              <button class="btn ghost sm" id="tf-copy">${ic('copy',14)} Copy codes</button>`;
            $('#tf-copy',m).onclick = ()=>{ try{ navigator.clipboard.writeText(d.recovery_codes.join('\n')); toast('Copied','good'); }catch(e){} };
          }catch(e){ $('#tf-e',m).textContent=e.message; } };
      };
    }
  };
  draw();
}
window.openProfile = openProfile;

async function doLogout(){
  if(typeof stopHeartbeat==='function') stopHeartbeat();
  if(typeof stopTasksPolling==='function') stopTasksPolling();
  await api('/api/logout',{method:'POST'});
  App.user=null; renderTopbar(); renderLanding();
  toast('Logged out');
}

async function deleteTestAccounts(){
  confirmBox('Delete test accounts?',
    'This removes the Admin and User test logins. You can still create real accounts.',
    async ()=>{
      await api('/api/delete-test-accounts',{method:'POST'});
      toast('Test accounts deleted','good');
      // if we were logged in as a test account we are now logged out
      const d = await api('/api/me'); App.user=d.user;
      renderTopbar();
      if(!App.user) renderLanding(); else renderDashboard(App.readonly);
    });
}

/* ============================================================
   CONFIRM BOX
   ============================================================ */
function confirmBox(title, body, onYes, yesLabel='Yes, continue'){
  const m = el(`<div class="modal" style="max-width:420px">
    <div class="modal-head"><h3>${esc(title)}</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><p style="margin:0;color:#374a5e">${esc(body)}</p></div>
    <div class="modal-foot">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn danger" id="cfx">${esc(yesLabel)}</button>
    </div></div>`);
  openModal(m);
  $('#cfx',m).onclick = async ()=>{ closeModal(); await onYes(); };
}
window.confirmBox = confirmBox;

/* ============================================================
   NOTIFICATIONS
   ============================================================ */
function updateNavBadges(sections, unread){
  // Each sidebar shows ONLY its own section's unread count (no duplicate totals).
  // The Notifications sidebar counts only general items not tied to a board.
  ['input','calendar','published','content','notifications'].forEach(sec=>{
    const el2 = $('#unread-'+sec); if(!el2) return;
    const n = (sections && sections[sec]) || 0;
    el2.textContent = n; el2.classList.toggle('hidden', !n);
  });
}
async function loadNotifCount(){
  if(!App.user) return;
  try{
    const d = await api('/api/notifications');
    App._notifs = d.notifications; App._notifUnread = d.unread; App._notifSections = d.sections;
    const dot = $('#bellCount');
    if(dot){ dot.textContent = d.unread; dot.classList.toggle('hidden', d.unread===0); }
    updateNavBadges(d.sections, d.unread);
    if(App.page==='notifications' && $('#notifFeed') && !document.querySelector('.nf-thread:not(.hidden)')) fillNotifFeed();
  }catch(e){}
}
async function markNotifRead(id){
  try{ await api('/api/notifications/'+id+'/read',{method:'POST'}); }catch(e){}
}
async function toggleNotif(){
  const wrap = $('.notif-wrap');
  if(!wrap) return;
  const existing = $('#notifPanel');
  if(existing){ existing.remove(); return; }
  await loadNotifCount();
  const list = (App._notifs||[]).slice(0,20).map(n=>`
    <div class="notif k-${esc(n.kind)} ${n.read?'is-read':'is-unread'} clickable" data-id="${n.id}" ${n.link?`data-link="${esc(n.link)}"`:''}>
      <span class="kd"></span>
      <div><div class="msg">${esc(n.message)}</div>
        <div class="nd">${fmtTime(n.created_at)} · ${esc(n.actor)}${n.reply_count?` · ${ic('message',12)} ${n.reply_count}`:''}</div></div>
    </div>`).join('') || '<div class="empty">No notifications yet</div>';
  const panel = el(`<div class="notif-panel" id="notifPanel">
      <h4>Notifications
        <button class="btn ghost sm" id="allN" style="margin-left:auto">See all</button>
        <button class="btn ghost sm" id="clrN">Mark all read</button></h4>
      ${list}</div>`);
  wrap.appendChild(panel);
  panel.querySelectorAll('.notif').forEach(x=>x.onclick=()=>{
    panel.remove(); markNotifRead(Number(x.dataset.id));
    if(x.dataset.link) openLinkTarget(x.dataset.link); else { App.page='notifications'; renderDashboard(App.readonly); }
  });
  $('#allN',panel).onclick = ()=>{ panel.remove(); App.page='notifications'; renderDashboard(App.readonly); };
  $('#clrN',panel).onclick = async ()=>{ await api('/api/notifications/read-all',{method:'POST'}); panel.remove(); loadNotifCount(); };
}
function fmtTime(iso){
  try{ const d=new Date(iso+'Z'); return d.toLocaleString(); }catch(e){ return iso; }
}
window.loadNotifCount = loadNotifCount;

/* Navigate to a notification's target and open the related item */
function openLinkTarget(link){
  const [kind, id] = (link||'').split(':');
  if(kind==='published'){
    App.page='published'; App.focusPublished = id?Number(id):null;
    renderDashboard(App.readonly);
  }else if(kind==='video'){
    App.page='input'; App.focusVideo = id?Number(id):null;
    renderDashboard(App.readonly);
  }else if(kind==='calendar'){
    App.page='calendar'; renderDashboard(App.readonly);
    if(id) setTimeout(()=>{ const it=(App._cal&&App._cal.items||[]).find(x=>x.id==id);
      if(it){ const [y,m]=it.date.split('-').map(Number); App.calMonth={y, m:m-1}; drawCalendar().then(()=>openDay(it.date)); } }, 500);
  }else if(kind==='inbox'){
    App.page='inbox'; renderDashboard(App.readonly);
  }else if(kind==='setup'){
    App.page='setup'; renderDashboard(App.readonly);
  }else if(kind==='openchat'){
    // open the Messenger chat window for this conversation
    if(typeof openChatWindow==='function') openChatWindow(Number(id));
  }else if(kind==='chat'){
    // legacy: open the notifications page and expand that thread
    App.page='notifications'; App._openChat = Number(id); renderDashboard(App.readonly);
  }else{
    App.page='notifications'; renderDashboard(App.readonly);
  }
}
window.openLinkTarget = openLinkTarget;

/* ============================================================
   NOTIFICATIONS — full sidebar page (with per-user read/unread + chat)
   ============================================================ */
function renderNotifications(){
  const c = $('#pageContent'); if(!c) return;
  App._notifFilter = App._notifFilter || 'all';
  const unread = (App._notifs||[]).filter(n=>!n.read).length;
  c.innerHTML = `<div class="page-head"><h2>Notifications</h2>
      <span class="nf-count" id="nf-count">${unread?`${unread} unread`:'All caught up'}</span><div class="spacer"></div>
      <div class="seg" id="nf-seg">
        <button class="${App._notifFilter==='all'?'on':''}" data-f="all">All</button>
        <button class="${App._notifFilter==='unread'?'on':''}" data-f="unread">Unread</button>
      </div>
      <button class="btn ghost sm" id="nf-readall">${ic('check',14)} Mark all read</button></div>
    <div class="nf-filter">
      <label class="nf-search">${ic('search',15)}<input id="nf-q" placeholder="Search notifications…" value="${esc(App._notifQ||'')}"></label>
      <input class="f nf-date" id="nf-date" type="date" value="${esc(App._notifDate||'')}" title="Filter by date">
      <button class="btn ghost sm" id="nf-clearfil">${ic('x',13)} Clear</button>
      <div class="spacer"></div>
      <label class="nf-selall"><input type="checkbox" id="nf-selall"> Select all</label>
      <button class="btn danger sm hidden" id="nf-bulkdel">${ic('trash',13)} Delete selected</button>
    </div>
    <div id="notifFeed"><div class="loading">Loading…</div></div>`;
  c.querySelectorAll('#nf-seg button').forEach(b=>b.onclick=()=>{ App._notifFilter=b.dataset.f; renderNotifications(); });
  $('#nf-readall').onclick = async ()=>{ await api('/api/notifications/read-all',{method:'POST'}); await loadNotifCount(); fillNotifFeed(); };
  $('#nf-selall').onchange = (e)=>{ document.querySelectorAll('.nf-check').forEach(x=>x.checked=e.target.checked); updateBulkDel(); };
  $('#nf-bulkdel').onclick = async ()=>{
    const ids=[...document.querySelectorAll('.nf-check:checked')].map(x=>Number(x.dataset.id));
    if(!ids.length) return;
    // per-user: removes them from MY list only — other users are unaffected
    confirmBox(`Delete ${ids.length} notification(s) from your list?`,'They are removed from your notifications only — other users still see theirs.',
      async ()=>{ try{ await api('/api/notifications/hide-bulk',{method:'POST', body:{ids}}); toast('Removed from your list','good'); loadNotifCount().then(fillNotifFeed); }catch(e){ toast(e.message,'warn'); } }, 'Delete from my list');
  };
  $('#nf-q').oninput = (e)=>{ App._notifQ=e.target.value; fillNotifFeed(); };
  $('#nf-date').onchange = (e)=>{ App._notifDate=e.target.value; fillNotifFeed(); };
  $('#nf-clearfil').onclick = ()=>{ App._notifQ=''; App._notifDate=''; renderNotifications(); };
  loadNotifCount().then(()=>{ fillNotifFeed();
    if(App._openChat){ const cid=App._openChat; App._openChat=null; setTimeout(()=>toggleThread(cid), 150); }
  });
}
window.renderNotifications = renderNotifications;

function fillNotifFeed(){
  const feed = $('#notifFeed'); if(!feed) return;
  let items = App._notifs||[];
  if(App._notifFilter==='unread') items = items.filter(n=>!n.read);
  // filter by name/text
  const q = (App._notifQ||'').trim().toLowerCase();
  if(q) items = items.filter(n=> (n.message||'').toLowerCase().includes(q) || (n.actor||'').toLowerCase().includes(q));
  // filter by date (created_at is UTC iso; compare local date)
  if(App._notifDate){ items = items.filter(n=>{ try{ const d=new Date((n.created_at||'')+'Z'); return d.toISOString().slice(0,10)===App._notifDate || d.toLocaleDateString('en-CA')===App._notifDate; }catch(e){ return false; } }); }
  const cnt = $('#nf-count'); if(cnt){ const u=(App._notifs||[]).filter(n=>!n.read).length; cnt.textContent = u?`${u} unread`:'All caught up'; }
  if(!items.length){ feed.innerHTML=`<div class="empty-state">${ic('bell',32)}<h3>${App._notifFilter==='unread'?'No unread notifications':'Nothing here'}</h3>
      <p class="sub">${(App._notifQ||App._notifDate)?'Try clearing the filters.':'Updates about uploads, approvals, publishing and comments appear here.'}</p></div>`; return; }
  let lastDay = '';
  feed.innerHTML = items.map(n=>{
    const d = new Date((n.created_at||'')+'Z');
    const day = notifDayLabel(d);
    const head = day!==lastDay ? `<div class="nf-day">${esc(day)}</div>` : '';
    lastDay = day;
    const k = notifKind(n);
    return head + `
    <div class="nf-item ${n.read?'is-read':'is-unread'} k-${k.cls}" data-id="${n.id}">
      <div class="nf-main">
        <input type="checkbox" class="nf-check" data-id="${n.id}" title="Select">
        <span class="nf-ic k-${k.cls}" title="${esc(k.label)}">${ic(k.icon,16)}</span>
        <div class="nf-body">
          <div class="nf-msg">${esc(cleanNotifText(n.message))}</div>
          <div class="nf-meta"><span class="nf-kind">${esc(k.label)}</span> · ${isNaN(d)?'':d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})} · ${esc(n.actor||'system')}
            ${n.link?`· <a href="#" class="nf-open" data-link="${esc(n.link)}" data-id="${n.id}">Open ${ic('chevRight',12)}</a>`:''}</div>
        </div>
        <div class="nf-actions">
          ${!n.read?`<button class="icon-btn sm" data-read="${n.id}" title="Mark as read">${ic('check',14)}</button>`:''}
          <button class="icon-btn sm nf-chat" data-chat="${n.id}" title="Discussion">${ic('message',14)}${n.reply_count?`<span class="nf-rc">${n.reply_count}</span>`:''}</button>
          <button class="icon-btn sm" data-delnotif="${n.id}" title="Delete from my list">${ic('trash',14)}</button>
        </div>
      </div>
      <div class="nf-thread hidden" id="nf-thread-${n.id}"></div>
    </div>`; }).join('');
  feed.querySelectorAll('.nf-open').forEach(a=>a.onclick=(e)=>{ e.preventDefault(); markNotifRead(Number(a.dataset.id)); openLinkTarget(a.dataset.link); });
  feed.querySelectorAll('[data-read]').forEach(b=>b.onclick=async ()=>{ await markNotifRead(Number(b.dataset.read)); await loadNotifCount(); fillNotifFeed(); });
  feed.querySelectorAll('[data-chat]').forEach(b=>b.onclick=()=>toggleThread(Number(b.dataset.chat)));
  // per-user delete: removes it from MY list only (other users keep theirs)
  feed.querySelectorAll('[data-delnotif]').forEach(b=>b.onclick=async ()=>{
    try{ await api('/api/notifications/'+b.dataset.delnotif+'/hide',{method:'POST'}); loadNotifCount().then(fillNotifFeed); toast('Removed from your list'); }catch(e){ toast(e.message,'warn'); }
  });
  feed.querySelectorAll('.nf-check').forEach(x=>x.onchange=updateBulkDel);
}
window.fillNotifFeed = fillNotifFeed;

/* notification type → icon + label (kind first, then message keywords) */
function notifKind(n){
  const m = (n.message||'').toLowerCase(), k = (n.kind||'').toLowerCase();
  if(k==='alert' || m.includes('failed') || m.includes('negative comment')) return {cls:'alert', icon:'alert', label:'Alert'};
  if(k==='publish' || m.includes('published')) return {cls:'publish', icon:'send', label:'Published'};
  if(k==='approval' || m.includes('approved') || m.includes('requested changes')) return {cls:'approval', icon:'thumbsUp', label:'Approval'};
  if(k==='remove' || m.includes('removed')) return {cls:'remove', icon:'trash', label:'Removed'};
  if(k==='comment') return {cls:'comment', icon:'message', label:'Comment'};
  if(k==='calendar' || m.includes('scheduled') || m.includes('evergreen')) return {cls:'calendar', icon:'calendar', label:'Schedule'};
  if(k==='content' || m.includes('caption') || m.includes('content generat')) return {cls:'content', icon:'sparkles', label:'AI content'};
  if(k==='upload' || m.includes('upload')) return {cls:'upload', icon:'upload', label:'Upload'};
  if(k==='subscription') return {cls:'subscription', icon:'card', label:'Billing'};
  return {cls:'info', icon:'info', label:'Update'};
}
/* the type icon replaces the emoji the server puts at the start of a message */
function cleanNotifText(t){
  return String(t||'').replace(/^[\s\u2190-\u2BFF\u2600-\u27BF\uFE0F\u{1F000}-\u{1FAFF}]+/u, '').trim();
}
function notifDayLabel(d){
  if(isNaN(d)) return '';
  const t = new Date(); t.setHours(0,0,0,0);
  const x = new Date(d); x.setHours(0,0,0,0);
  const diff = Math.round((t - x)/86400000);
  if(diff===0) return 'Today';
  if(diff===1) return 'Yesterday';
  return d.toLocaleDateString(undefined, {weekday:'long', day:'numeric', month:'long', year: d.getFullYear()===t.getFullYear()?undefined:'numeric'});
}
function updateBulkDel(){
  const n=document.querySelectorAll('.nf-check:checked').length;
  const b=$('#nf-bulkdel'); if(b){ b.classList.toggle('hidden', n===0); b.innerHTML=`${ic('trash',13)} Delete selected (${n})`; }
}

async function toggleThread(id){
  const box = $('#nf-thread-'+id); if(!box) return;
  if(!box.classList.contains('hidden')){ box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  box.innerHTML = '<div class="loading">Loading…</div>';
  await markNotifRead(id);
  await loadThread(id);
}
function attachFileChip(name){ return `<span class="att-file">${ic('clip',12)} ${esc(name)}</span>`; }
function renderReplyFiles(files){
  if(!files || !files.length) return '';
  return `<div class="nf-atts">${files.map(u=>{
    const isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(u);
    return isImg ? `<a href="${esc(u)}" target="_blank"><img class="att-img" src="${esc(u)}"></a>`
                 : `<a class="att-file" href="${esc(u)}" target="_blank" download>${ic('clip',12)} ${esc(u.split('/').pop())}</a>`;
  }).join('')}</div>`;
}
async function loadThread(id){
  const box = $('#nf-thread-'+id); if(!box) return;
  let replies=[];
  try{ replies = (await api('/api/notifications/'+id+'/replies')).replies; }catch(e){}
  const meId = App.user && App.user.id, meAdmin = App.user && App.user.role==='admin';
  box.innerHTML = `
    <div class="nf-replies">${replies.map(r=>`
        <div class="nf-reply" data-rid="${r.id}"><b>${esc(r.author)}</b> <span class="nf-rt">${fmtTime(r.created_at)}</span>
          ${(r.author_id===meId||meAdmin)?`<button class="nf-del" data-del-reply="${r.id}" title="Delete message">${ic('trash',12)}</button>`:''}
          ${r.text?`<div>${esc(r.text)}</div>`:''}
          ${renderReplyFiles(r.files)}
        </div>`).join('') || '<div class="empty" style="padding:10px 0">No messages yet — start the conversation.</div>'}</div>
    <div class="nf-reply-box">
      <label class="att-btn" title="Attach files/screenshots (no limit)">${ic('clip',16)}
        <input type="file" id="nf-files-${id}" multiple style="display:none"></label>
      <div class="nf-in-wrap" style="flex:1;position:relative">
        <input class="f" id="nf-rin-${id}" placeholder="Message… use @ to tag" autocomplete="off">
        <div class="mention-pop hidden" id="nf-ment-${id}"></div>
      </div>
      <button class="btn sm" data-send="${id}">Send</button>
    </div>
    <div class="nf-att-preview" id="nf-attp-${id}"></div>`;
  const inp = box.querySelector('#nf-rin-'+id);
  const fileInput = box.querySelector('#nf-files-'+id);
  const attp = box.querySelector('#nf-attp-'+id);
  const refreshAtt = ()=>{ attp.innerHTML = [...(fileInput.files||[])].map(f=>attachFileChip(f.name)).join(''); };
  fileInput.onchange = refreshAtt;
  // @-mention autocomplete
  setupMention(inp, box.querySelector('#nf-ment-'+id));
  const send = async ()=>{
    const text=inp.value.trim(); const hasFiles = fileInput.files && fileInput.files.length;
    if(!text && !hasFiles) return;
    try{
      if(hasFiles){
        const fd=new FormData(); fd.append('text', text);
        for(const f of fileInput.files) fd.append('files', f);
        await api('/api/notifications/'+id+'/replies',{method:'POST', body:fd});
      }else{
        await api('/api/notifications/'+id+'/replies',{method:'POST', body:{text}});
      }
      inp.value=''; fileInput.value=''; refreshAtt(); loadThread(id);
    }catch(e){ toast(e.message,'warn'); }
  };
  box.querySelector('[data-send]').onclick = send;
  if(inp) inp.addEventListener('keydown',e=>{ if(e.key==='Enter' && !$('#nf-ment-'+id, box).classList.contains('mention-open')){ e.preventDefault(); send(); } });
  box.querySelectorAll('[data-del-reply]').forEach(b=>b.onclick=async ()=>{
    try{ await api('/api/notifications/'+id+'/replies/'+b.dataset.delReply,{method:'DELETE'}); loadThread(id); }
    catch(e){ toast(e.message,'warn'); }
  });
}

/* @-mention autocomplete: shows users as you type @ */
function setupMention(input, pop){
  if(!input || !pop) return;
  const users = (App._presence && App._presence.users) || [];
  const show = (list, q, atPos)=>{
    if(!list.length){ pop.classList.add('hidden'); pop.classList.remove('mention-open'); return; }
    pop.innerHTML = list.slice(0,6).map(u=>`<div class="ment-item" data-u="${esc(u.username)}">
        <span class="ment-av">${esc((u.display_name||u.username).slice(0,2).toUpperCase())}</span>
        @${esc(u.username)}${(u.role&&u.role!=='user')?` <span class="ment-ad">${esc(u.role_label||roleLabel(u.role))}</span>`:''}</div>`).join('');
    pop.classList.remove('hidden'); pop.classList.add('mention-open');
    pop.querySelectorAll('.ment-item').forEach(it=>it.onclick=()=>{
      const val=input.value; const before=val.slice(0,atPos); const after=val.slice(input.selectionStart);
      input.value = before + '@' + it.dataset.u + ' ' + after;
      pop.classList.add('hidden'); pop.classList.remove('mention-open'); input.focus();
    });
  };
  input.addEventListener('input', ()=>{
    const val=input.value, pos=input.selectionStart;
    const m = val.slice(0,pos).match(/@([A-Za-z0-9_.\-]*)$/);
    if(!m){ pop.classList.add('hidden'); pop.classList.remove('mention-open'); return; }
    const q=m[1].toLowerCase();
    const list=users.filter(u=>u.username.toLowerCase().includes(q) && u.id!==(App.user&&App.user.id));
    show(list, q, pos-m[0].length);
  });
  input.addEventListener('blur', ()=> setTimeout(()=>{ pop.classList.add('hidden'); pop.classList.remove('mention-open'); }, 180));
}

/* ---------- Comment popup polling ---------- */
let _notifPoll = null;
function startNotifPolling(){
  if(_notifPoll) clearInterval(_notifPoll);
  pollNotifs();
  _notifPoll = setInterval(pollNotifs, 12000);
}
async function pollNotifs(){
  if(!App.user){ return; }
  try{
    const d = await api('/api/notifications');
    const items = d.notifications || [];
    App._notifs = items; App._notifUnread = d.unread; App._notifSections = d.sections;
    const maxId = items.length ? items[0].id : 0;
    if(App._lastNotifId === undefined){ App._lastNotifId = maxId; }
    else if(maxId > App._lastNotifId){
      App._lastNotifId = maxId;   // no auto pop-ups — notifications live in the panel
    }
    const dot=$('#bellCount'); if(dot){ dot.textContent=d.unread; dot.classList.toggle('hidden', d.unread===0); }
    updateNavBadges(d.sections, d.unread);
    // don't rebuild the feed while the user has a discussion thread open
    if(App.page==='notifications' && $('#notifFeed') && !document.querySelector('.nf-thread:not(.hidden)')) fillNotifFeed();
  }catch(e){}
}
function showCommentPopup(n){
  const card = el(`<div class="toast comment-pop">
      <div class="cp-head">${ic('message',14)} New comment</div>
      <div class="cp-body">${esc(n.message)}</div>
      <div class="cp-cta">View in Published ${ic('chevRight',13)}</div>
    </div>`);
  card.onclick = ()=>{ card.remove(); openLinkTarget(n.link); };
  $('#toast-root').appendChild(card);
  setTimeout(()=>{ card.style.opacity='0'; card.style.transition='.4s'; setTimeout(()=>card.remove(),400); }, 11000);
}

/* boot */
document.addEventListener('DOMContentLoaded', boot);
