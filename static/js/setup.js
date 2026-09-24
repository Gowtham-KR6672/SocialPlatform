/* ============================================================
   Setup panel — connect every social platform + alerts/reports.
   - Credentials · Sign-in & AI (SuperAdmin): Redirect Base URL, AI key, model.
   - One row per platform (8): App ID / Secret, redirect URI to register,
     connection status (Live / Expiring / Expired), Connect/Disconnect,
     Page / board picker, and a step-by-step guide.
   - Alerts & reports: webhook, alert email, weekly report email, SMTP.
   ============================================================ */
const PLATFORM_GUIDES = {
  instagram:['Switch your Instagram account to Business or Creator (Instagram app → Settings → Account type).',
    'At developers.facebook.com create an app and add the "Instagram" product (Instagram API with Instagram login).',
    'Open Instagram → API setup with Instagram login. Copy the Instagram App ID and Instagram App Secret into this row.',
    'Under "Set up Instagram business login" add the Redirect URI shown in this row.',
    'While the app is in Development mode, add your account under App roles → Instagram Testers and accept the invite in Instagram.',
    'Click Save, then Connect. Publishing needs your videos at a public HTTPS URL (Public Base URL or Supabase Storage).'],
  facebook:['At developers.facebook.com create a Business app and add "Facebook Login for Business".',
    'App settings → Basic: copy the App ID and App Secret into this row.',
    'Facebook Login → Settings → Valid OAuth Redirect URIs: add the Redirect URI shown in this row.',
    'Request pages_manage_posts, pages_read_engagement, pages_read_user_content, pages_manage_engagement and read_insights (app review for public use).',
    'Click Connect and pick the Page to post to. Page tokens don\'t expire.'],
  youtube:['At console.cloud.google.com create a project and enable "YouTube Data API v3".',
    'Configure the OAuth consent screen (add yourself as a test user while in Testing).',
    'Credentials → Create credentials → OAuth client ID → Web application.',
    'Add the Redirect URI shown in this row under "Authorized redirect URIs".',
    'Copy the Client ID and Client Secret into this row, Save, then Connect with the Google account that owns the channel.',
    'Unverified API projects upload as private until Google audits the project.'],
  twitter:['At developer.x.com create a Project and an App (a paid tier is needed for meaningful posting volume).',
    'User authentication settings → OAuth 2.0 → type "Web App", permissions "Read and write".',
    'Add the Redirect URI shown in this row as the Callback URI.',
    'Keys and tokens → copy the OAuth 2.0 Client ID and Client Secret into this row, Save, then Connect.'],
  linkedin:['At linkedin.com/developers create an app linked to your company page.',
    'Products: add "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect".',
    'Auth → add the Redirect URI shown in this row.',
    'Copy the Client ID and Client Secret into this row, Save, then Connect. Tokens last 60 days — you\'ll be reminded to reconnect.'],
  threads:['At developers.facebook.com create an app with the "Access the Threads API" use case.',
    'Threads use case → Settings: add the Redirect URI shown in this row to the callback URLs.',
    'Copy the Threads App ID and Threads App Secret into this row.',
    'Add your Threads account as a Threads Tester (App roles) and accept the invite, then Save and Connect.'],
  tiktok:['At developers.tiktok.com create an app and add the "Login Kit" and "Content Posting API" products.',
    'Enable "Direct Post" and add the scopes user.info.basic, video.publish, video.upload, video.list.',
    'Add the Redirect URI shown in this row, then copy the Client Key and Client Secret into this row.',
    'Unaudited apps can only post as private (visible to you) until TikTok approves the app.'],
  pinterest:['At developers.pinterest.com create an app (request Standard access for public use).',
    'Add the Redirect URI shown in this row under "Redirect URIs".',
    'Copy the App ID and App Secret key into this row, Save, then Connect.',
    'After connecting, choose which board new Pins go to.'],
};

async function renderSetup(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="panel-head"><h2>Setup</h2>
      <p class="sub">Connect your own social accounts. For each platform, add your App ID and Secret
      (click <b>Guide</b> for the steps), save, then click <b>Connect</b> and sign in.</p></div>
    <div id="setupBody"><div class="loading">Loading…</div></div>`;
  let d, cfg = {}, al = {};
  try{ d = await api('/api/platforms'); }
  catch(e){ $('#setupBody').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  if(d.can_view_creds){ try{ cfg = await api('/api/oauth/config'); }catch(e){} }
  try{ al = await api('/api/settings/alerts'); }catch(e){}

  const credCard = d.can_view_creds ? `
    <div class="card glass setup-card">
      <div class="sc-title">${ic('key',16)} <b>Credentials · Sign-in &amp; AI</b></div>
      <div class="cred-grid">
        <div><label class="f">Redirect Base URL</label>
          <input class="f" id="sc-redirect" value="${esc(cfg.oauth_redirect_base||d.redirect_base||'')}" placeholder="https://your-app.com">
          <div class="hint">Your public app address. Every platform's redirect URI is built from it.</div></div>
        <div><label class="f">Public Base URL (media)</label>
          <input class="f" id="sc-public" value="${esc(al.public_base_url||'')}" placeholder="https://your-app.com">
          <div class="hint">${d.supabase_storage?'Supabase Storage is on, so media already has public URLs.':'Instagram and Threads download media from here (HTTPS only).'}</div></div>
        <div><label class="f">AI Key ${cfg.claude_key_set?'(set — blank keeps it)':''}</label>
          <input class="f" id="sc-aikey" type="password" placeholder="${cfg.claude_key_set?'••••••••':'sk-ant-…'}"></div>
        <div><label class="f">Model</label>
          <input class="f" id="sc-model" value="${esc(cfg.claude_model||'')}" placeholder="claude-opus-5"></div>
      </div>
      <button class="btn sm grad-btn" id="sc-savecred">${ic('save',14)} Save credentials</button>
      <div class="err" id="sc-crederr"></div>
    </div>` : '';

  const statusChip = (p)=>{
    if(!p.connected) return `<span class="chip draft">Not connected</span>`;
    if(p.status==='expired') return `<span class="chip danger">${ic('alert',12)} Expired</span>`;
    if(p.status==='expiring') return `<span class="chip gold">${ic('clock',12)} Expiring</span>`;
    return `<span class="chip completed">${ic('check',12)} Live</span>`;
  };
  const optionPicker = (p)=>{
    if(p.key==='facebook' && p.pages && p.pages.length>1)
      return `<label class="pf-opt">Page <select class="f" data-opt="facebook">${p.pages.map(x=>
        `<option value="${esc(x.id)}" ${x.id===p.page_id?'selected':''}>${esc(x.name||x.id)}</option>`).join('')}</select></label>`;
    if(p.key==='pinterest' && p.boards && p.boards.length)
      return `<label class="pf-opt">Board <select class="f" data-opt="pinterest">${p.boards.map(x=>
        `<option value="${esc(x.id)}" ${x.id===p.board_id?'selected':''}>${esc(x.name||x.id)}</option>`).join('')}</select></label>`;
    return '';
  };
  const rows = d.platforms.map(p=>`
    <div class="pf-row glass" data-plat="${p.key}">
      <div class="pf-left"><span class="pf-ic">${pi(p.key, 26)}</span>
        <div><b>${esc(p.label)}</b>
          <div class="sub">${p.connected?esc(p.account||''):'Supports: '+p.supports.join(', ')}</div>
          ${p.last_error?`<div class="pf-err">${ic('alert',12)} ${esc(p.last_error)}</div>`:''}
          ${!p.allowed?`<div class="pf-err">${ic('lock',12)} You don't have publishing rights here</div>`:''}</div></div>
      <div class="pf-right">
        <div class="pf-cred">
          <input class="f" id="pf-id-${p.key}" value="${esc(p.app_id||'')}" placeholder="${esc(p.id_label)}">
          <input class="f" id="pf-sec-${p.key}" type="password" placeholder="${p.secret_set?'•••••• (set)':esc(p.secret_label)}">
          <button class="btn ghost sm" data-savecred="${p.key}">${ic('save',14)} Save</button>
        </div>
        <div class="pf-redirect" title="Register this exact URL in the ${esc(p.label)} developer console">
          <span>Redirect URI</span><code>${esc(p.redirect_uri)}</code>
          <button class="icon-btn sm" data-copy="${esc(p.redirect_uri)}" title="Copy">${ic('copy',14)}</button></div>
        <div class="pf-status">${p.installed?`<span class="chip completed">Credentials set</span>`:`<span class="chip gold">Credentials needed</span>`}
          ${statusChip(p)} ${optionPicker(p)}
          <button class="btn sm ${p.connected?'ghost':'grad-btn'}" data-conn="${p.key}">${p.connected?'Disconnect':'Connect'}</button>
          <button class="btn ghost sm" data-guide="${p.key}">${ic('file',14)} Guide</button>
        </div>
      </div></div>`).join('');

  const alertsCard = `
    <div class="card glass setup-card">
      <div class="sc-title">${ic('bell',16)} <b>Alerts &amp; reports</b></div>
      <p class="sub">You're notified in the app when a post fails, a negative comment arrives, engagement spikes
        or a connection is about to expire. You can also get these alerts by webhook or email.</p>
      <div class="cred-grid">
        <div><label class="f">Webhook URL (Slack, Discord, Teams, Zapier…)</label>
          <input class="f" id="al-hook" value="${esc(al.alert_webhook||'')}" placeholder="https://hooks.slack.com/…"></div>
        <div><label class="f">Alert email</label>
          <input class="f" id="al-mail" value="${esc(al.alert_email||'')}" placeholder="you@company.com"></div>
        <div><label class="f">Weekly report email (Mondays 9:00)</label>
          <input class="f" id="al-report" value="${esc(al.report_email||'')}" placeholder="team@company.com"></div>
      </div>
      ${al.can_edit_smtp?`<details class="smtp"><summary>${ic('mail',14)} Email server (SMTP) ${al.smtp_configured?'<span class="chip completed">configured</span>':'<span class="chip draft">not set</span>'}</summary>
        <div class="cred-grid">
          <div><label class="f">SMTP host</label><input class="f" id="sm-host" value="${esc(al.smtp_host||'')}" placeholder="smtp.gmail.com"></div>
          <div><label class="f">Port</label><input class="f" id="sm-port" value="${esc(al.smtp_port||'')}" placeholder="587"></div>
          <div><label class="f">Username</label><input class="f" id="sm-user" value="${esc(al.smtp_user||'')}"></div>
          <div><label class="f">Password ${al.smtp_pass_set?'(set — blank keeps it)':''}</label><input class="f" id="sm-pass" type="password"></div>
          <div><label class="f">From address</label><input class="f" id="sm-from" value="${esc(al.smtp_from||'')}" placeholder="Social Platform &lt;noreply@…&gt;"></div>
        </div></details>`:(al.smtp_configured?'':'<div class="hint">Email delivery needs an SMTP server; your SuperAdmin can set one up.</div>')}
      <div class="row" style="gap:8px;margin-top:10px">
        <button class="btn sm grad-btn" id="al-save">${ic('save',14)} Save</button>
        <button class="btn ghost sm" id="al-test">${ic('bell',14)} Send test alert</button>
      </div>
    </div>`;

  $('#setupBody').innerHTML = credCard + `<div class="pf-grid">${rows}</div>` + alertsCard;

  const scb = $('#sc-savecred');
  if(scb) scb.onclick = async ()=>{
    const body = {oauth_redirect_base:$('#sc-redirect').value.trim(), claude_model:$('#sc-model').value.trim()};
    const k = $('#sc-aikey').value.trim(); if(k) body.claude_api_key = k;
    try{ await api('/api/oauth/config',{method:'POST', body});
      await api('/api/settings/alerts',{method:'POST', body:{public_base_url:$('#sc-public').value.trim()}});
      toast('Credentials saved','good'); renderSetup(); }
    catch(e){ $('#sc-crederr').textContent = e.message; }
  };
  const body = $('#setupBody');
  body.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{
    try{ navigator.clipboard.writeText(b.dataset.copy); toast('Redirect URI copied','good'); }catch(e){ toast(b.dataset.copy); }
  });
  body.querySelectorAll('[data-guide]').forEach(b=>b.onclick=()=>{
    const p = d.platforms.find(x=>x.key===b.dataset.guide); if(p) openPlatformGuide(p);
  });
  body.querySelectorAll('[data-savecred]').forEach(b=>b.onclick=async ()=>{
    const k=b.dataset.savecred;
    const bd={app_id:$('#pf-id-'+k).value.trim()};
    const s=$('#pf-sec-'+k).value.trim(); if(s) bd.app_secret=s;
    try{ await api('/api/platforms/'+k+'/creds',{method:'POST', body:bd}); toast(platLabel(k)+' credentials saved','good'); renderSetup(); }
    catch(e){ toast(e.message,'warn'); }
  });
  body.querySelectorAll('[data-opt]').forEach(sel=>sel.onchange=async ()=>{
    const k=sel.dataset.opt, bd = k==='facebook'?{page_id:sel.value}:{board_id:sel.value};
    try{ await api('/api/platforms/'+k+'/option',{method:'POST', body:bd}); toast('Saved','good'); renderSetup(); }
    catch(e){ toast(e.message,'warn'); }
  });
  body.querySelectorAll('[data-conn]').forEach(b=>b.onclick=async ()=>{
    const p = d.platforms.find(x=>x.key===b.dataset.conn);
    if(p.connected){
      confirmBox(`Disconnect ${p.label}?`, 'Scheduled posts for this platform will fail until you reconnect it.', async ()=>{
        try{ await api('/api/platforms/'+p.key+'/disconnect',{method:'POST'});
          await refreshMe(); renderSetup(); toast(p.label+' disconnected'); }
        catch(e){ toast(e.message,'warn'); }
      }, 'Disconnect');
      return;
    }
    // save whatever was typed in this row first, so Connect works without a separate Save click
    const id = $('#pf-id-'+p.key).value.trim(), sec = $('#pf-sec-'+p.key).value.trim();
    if(!id || (!sec && !p.secret_set)){
      toast(`Enter your ${p.label} App ID and Secret first (see Guide)`,'warn',5000);
      $(!id ? '#pf-id-'+p.key : '#pf-sec-'+p.key).focus(); return;
    }
    if(id !== (p.app_id||'') || sec){
      const bd = {app_id:id}; if(sec) bd.app_secret = sec;
      try{ await api('/api/platforms/'+p.key+'/creds',{method:'POST', body:bd}); }
      catch(e){ toast(e.message,'warn'); return; }
    }
    connectLive(p);
  });
  $('#al-save').onclick = async ()=>{
    const bd = {alert_webhook:$('#al-hook').value.trim(), alert_email:$('#al-mail').value.trim(),
                report_email:$('#al-report').value.trim()};
    if($('#sm-host')){ Object.assign(bd, {smtp_host:$('#sm-host').value.trim(), smtp_port:$('#sm-port').value.trim(),
       smtp_user:$('#sm-user').value.trim(), smtp_from:$('#sm-from').value.trim()});
       if($('#sm-pass').value.trim()) bd.smtp_pass = $('#sm-pass').value.trim(); }
    try{ await api('/api/settings/alerts',{method:'POST', body:bd}); toast('Alert settings saved','good'); }
    catch(e){ toast(e.message,'warn'); }
  };
  $('#al-test').onclick = async ()=>{
    try{ await api('/api/settings/alerts/test',{method:'POST'}); toast('Test alert sent — check notifications, webhook and email','good',5000); loadNotifCount(); }
    catch(e){ toast(e.message,'warn'); }
  };
}
window.renderSetup = renderSetup;

async function refreshMe(){ try{ const d=await api('/api/me'); App.user=d.user; }catch(e){} }
window.refreshMe = refreshMe;

/* Step-by-step guide for a platform (plus the downloadable PDF where one exists) */
function openPlatformGuide(p){
  const steps = PLATFORM_GUIDES[p.key] || [];
  const m = el(`<div class="modal" style="max-width:640px">
    <div class="modal-head"><h3>${pi(p.key,20)} ${esc(p.label)} — setup guide</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <ol class="guide-steps">${steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ol>
      <label class="f">Redirect URI to register</label>
      <div class="pf-redirect big"><code>${esc(p.redirect_uri)}</code>
        <button class="icon-btn sm" id="gd-copy">${ic('copy',14)}</button></div>
      <div class="note">If the Redirect Base URL changes (e.g. you deploy online), update this URI in the developer console too.</div>
    </div>
    <div class="modal-foot">${p.guide?`<a class="btn ghost" href="${esc(p.guide)}?dl=1" download>${ic('download',14)} Download PDF guide</a>`:''}
      <button class="btn" onclick="closeModal()">Done</button></div></div>`);
  openModal(m);
  $('#gd-copy',m).onclick = ()=>{ try{ navigator.clipboard.writeText(p.redirect_uri); toast('Copied','good'); }catch(e){} };
}
window.openPlatformGuide = openPlatformGuide;

/* Real OAuth in a popup (credentials configured) */
async function connectLive(p){
  try{
    const r = await api('/api/connect/'+p.key+'/start',{method:'POST', body:{}});
    if(r.mode==='live' && r.auth_url){
      const w = window.open(r.auth_url, 'sdb_oauth', 'width=560,height=720');
      toast(`Sign in to ${p.label} in the popup window…`);
      const onMsg = (ev)=>{
        if(ev.data && ev.data.sdb_oauth){
          window.removeEventListener('message', onMsg);
          setTimeout(async ()=>{ await refreshMe(); renderSetup();
            toast(ev.data.ok?`${p.label} connected`:'Connection cancelled', ev.data.ok?'good':'warn'); }, 400);
        }
      };
      window.addEventListener('message', onMsg);
      const iv = setInterval(async ()=>{ if(w && w.closed){ clearInterval(iv); await refreshMe(); renderSetup(); } }, 1500);
    }
  }catch(e){ toast(e.message,'warn'); }
}
async function connectInstagramOwn(){ connectLive({key:'instagram', label:'Instagram'}); }
window.connectInstagramOwn = connectInstagramOwn;

/* kept for older callers */
function openGuideModal(url, label){ window.open(url, '_blank'); }
window.openGuideModal = openGuideModal;
