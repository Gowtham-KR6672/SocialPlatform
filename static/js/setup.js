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
  const isSuper = !!(App.user||{}).is_super;
  c.innerHTML = `<div class="panel-head"><h2>Setup</h2>
      <p class="sub">${isSuper
        ? 'Enter <b>one approved app per platform</b> (click <b>Guide</b> for the steps). Every client connects through these apps, so clients only click <b>Connect</b> and sign in.'
        : 'Click <b>Connect</b> next to a platform and sign in to link your account. Your accounts and data are visible only to your workspace.'}</p></div>
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
      </div>
      <div class="sc-sub">${ic('sparkles',15)} <b>AI provider</b>
        <span class="muted">Used for captions, content writing, per-platform captions and reply suggestions.</span></div>
      <div id="sc-ai">${cfg.ai?aiSettingsHTML(cfg.ai):''}</div>
      <button class="btn sm grad-btn" id="sc-savecred">${ic('save',14)} Save credentials</button>
      <div class="err" id="sc-crederr"></div>
      <details class="smtp review-urls"><summary>${ic('shield',14)} URLs for App Review &amp; webhooks (Meta, Google, TikTok…)</summary>
        <p class="sub">Paste these into each platform's developer console. Meta asks for the first three before an app can go Live.</p>
        ${[['Privacy Policy URL','/privacy'],['Terms of Service URL','/terms'],['Data deletion instructions URL','/data-deletion'],
           ['Data deletion request callback (Meta)','/data-deletion/callback'],['Deauthorize callback (Meta)','/deauthorize/callback'],
           ['Webhook callback URL (Instagram / Facebook)','/webhooks/meta']].map(([l,p])=>{
            const u = (cfg.oauth_redirect_base||d.redirect_base||location.origin).replace(/\/$/,'') + p;
            return `<div class="pf-redirect big" style="margin-top:6px"><span style="min-width:230px">${l}</span><code>${esc(u)}</code>
              <button class="icon-btn sm" data-copy="${esc(u)}" title="Copy">${ic('copy',14)}</button></div>`; }).join('')}
        <div class="hint" style="margin-top:8px">Webhook verify token: the value of <code>INSTAGRAM_WEBHOOK_VERIFY_TOKEN</code> in Render → Environment.
          Subscribe to the <b>comments</b> field (Instagram) and <b>feed</b> field (Facebook Page). Webhooks are delivered only to Live apps.</div>
      </details>
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
  const hasDetails = p => !!(p.app_id && p.secret_set);
  const scopeNote = (p)=>{
    if(p.is_super) return `${ic('building',12)} Platform app — used by every client`;
    if(p.source==='own') return `${ic('key',12)} Using your own app`;
    if(p.platform_ready) return `${ic('check',12)} Ready — set up by your administrator`;
    return `${ic('info',12)} Not set up yet — ask your administrator, or add your own app`;
  };
  const credChip = (p)=>{
    if(p.is_super) return p.installed?`<span class="chip completed">App set</span>`:`<span class="chip gold">App needed</span>`;
    if(p.installed) return '';
    return `<span class="chip gold">Not available yet</span>`;
  };
  const rows = d.platforms.map(p=>`
    <div class="pf-tile ${p.connected&&p.status!=='expired'?'is-live':''}" data-plat="${p.key}">
      <div class="pt-top"><span class="pf-ic">${pi(p.key, 26)}</span>
        <div class="pt-name"><b>${esc(p.label)}</b>
          <span class="sub">${p.connected?esc(p.account||'Connected'):'Supports: '+esc(p.supports.join(', '))}</span></div>
        <div class="pt-chips">${statusChip(p)}${credChip(p)}</div></div>
      <div class="pt-meta">
        <div class="pt-scope">${scopeNote(p)}</div>
        ${p.last_error?`<div class="pf-err">${ic('alert',12)} ${esc(p.last_error)}</div>`:''}
        ${!p.allowed?`<div class="pf-err">${ic('lock',12)} You don't have publishing rights here</div>`:''}
        ${optionPicker(p)}
        ${p.connected?`<div class="pt-import"><button class="link-btn" data-import="${p.key}" title="Bring in posts you published before, with their comments and stats">${ic('download',13)} Import past posts</button>
          ${p.imported_at?`<span class="muted">· last ${esc(fmtTime(String(p.imported_at).slice(0,19)))}</span>`:''}</div>`:''}
      </div>
      <div class="pt-actions">
        <button class="btn ghost sm" data-details="${p.key}">${ic(hasDetails(p)?'edit':'plus',14)} ${hasDetails(p)?'Edit Details':'Add Details'}</button>
        <button class="btn sm ${p.connected?'ghost':'grad-btn'}" data-conn="${p.key}">${ic(p.connected?'x':'link',14)} ${p.connected?'Disconnect':'Connect'}</button>
        <button class="btn ghost sm" data-guide="${p.key}">${ic('file',14)} Guide</button>
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

  let signup = null;
  if(isSuper){ try{ signup = (await api('/api/settings/signup')).allow; }catch(e){} }
  const signupCard = signup===null ? '' : `
    <div class="card glass setup-card">
      <div class="sc-title">${ic('users',16)} <b>Client sign-up</b></div>
      <label class="cred-toggle"><input type="checkbox" id="su-allow" ${signup?'checked':''}>
        <span>Anyone can create an account from the login page</span></label>
      <div class="hint">Turn this off once your clients are set up. You can still create accounts for them yourself.</div>
    </div>`;
  if(!$('#setupBody')) return;          // user left the page while it was loading
  $('#setupBody').innerHTML = credCard + `<div class="pf-tiles">${rows}</div>` + alertsCard + signupCard;
  const sua = $('#su-allow');
  if(sua) sua.onchange = async ()=>{ try{ await api('/api/settings/signup',{method:'POST', body:{allow:sua.checked}});
      toast(sua.checked?'Sign-up is open':'Sign-up is closed','good'); }catch(e){ toast(e.message,'warn'); sua.checked=!sua.checked; } };

  const aiCtl = (cfg.ai && $('#sc-ai')) ? bindAiSettings($('#sc-ai'), cfg.ai) : null;
  const scb = $('#sc-savecred');
  if(scb) scb.onclick = async ()=>{
    const body = Object.assign({oauth_redirect_base:$('#sc-redirect').value.trim()}, aiCtl ? aiCtl.collect() : {});
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
  body.querySelectorAll('[data-details]').forEach(b=>b.onclick=()=>{
    const p = d.platforms.find(x=>x.key===b.dataset.details); if(p) openCredModal(p);
  });
  body.querySelectorAll('[data-opt]').forEach(sel=>sel.onchange=async ()=>{
    const k=sel.dataset.opt, bd = k==='facebook'?{page_id:sel.value}:{board_id:sel.value};
    try{ await api('/api/platforms/'+k+'/option',{method:'POST', body:bd}); toast('Saved','good'); renderSetup(); }
    catch(e){ toast(e.message,'warn'); }
  });
  body.querySelectorAll('[data-import]').forEach(b=>b.onclick=async ()=>{
    const k=b.dataset.import; b.disabled=true; const old=b.innerHTML; b.innerHTML=`${ic('hourglass',14)} Importing…`;
    try{ const r = await api('/api/platforms/'+k+'/import',{method:'POST'});
      toast(`${platLabel(k)}: imported ${r.imported} post(s) (${r.found} found). They appear in Published, Analytics and the Inbox.`,'good',6000); renderSetup(); }
    catch(e){ toast(e.message,'warn',6000); b.disabled=false; b.innerHTML=old; }
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
    if(p.installed){ connectLive(p); return; }
    toast(p.is_super ? `Add the ${p.label} App ID and Secret first`
                     : `${p.label} isn't set up yet — ask your administrator, or add your own app`,'warn',5000);
    openCredModal(p, true);
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

/* ---------- AI provider picker (Setup card + Content Writing "AI settings") ---------- */
const AI_META = {
  claude:     {badge:'Paid',        tone:'paid', note:'Best writing quality. Pay as you go.',
               keyUrl:'https://console.anthropic.com/settings/keys', ph:'sk-ant-…'},
  gemini:     {badge:'Free tier',   tone:'free', note:'Free daily limit. Can read video frames for captions.',
               keyUrl:'https://aistudio.google.com/apikey', ph:'AIza…'},
  groq:       {badge:'Free tier',   tone:'free', note:'Very fast open models (Llama, GPT-OSS) on a free, rate-limited plan.',
               keyUrl:'https://console.groq.com/keys', ph:'gsk_…'},
  openrouter: {badge:'Free models', tone:'free', note:'One key for hundreds of models. Pick one marked free.',
               keyUrl:'https://openrouter.ai/settings/keys', ph:'sk-or-…'},
};
function aiSettingsHTML(ai){
  return `<div class="ai-set">
    <div class="ai-provs" role="radiogroup" aria-label="AI provider">${ai.providers.map(p=>{ const M = AI_META[p.id]||{};
      return `<button type="button" role="radio" class="ai-prov" data-prov="${p.id}" aria-checked="false">
        <span class="ap-top"><b>${esc(p.label)}</b><span class="ap-badge ${M.tone||''}">${esc(M.badge||'')}</span></span>
        <span class="ap-note">${esc(M.note||'')}</span>
        <span class="ap-state">${p.key_set?`${ic('check',12)} Key saved`:'No key yet'}${p.id===ai.provider?' · <b>In use</b>':''}</span></button>`; }).join('')}</div>
    <div class="ai-fields">
      <div><label class="f" for="ai-key">API key <span class="muted ai-keystate"></span>
          <a class="ai-keylink" target="_blank" rel="noopener">Get a key ${ic('external',11)}</a></label>
        <input class="f" id="ai-key" type="password" autocomplete="new-password"></div>
      <div><label class="f" for="ai-model">Model</label>
        <div class="ai-model-row"><input class="f" id="ai-model" list="ai-model-list" autocomplete="off">
          <button class="btn ghost sm" type="button" data-ai="load">${ic('refresh',13)} Load models</button></div>
        <datalist id="ai-model-list"></datalist>
        <div class="hint ai-modelhint"></div>
        <div class="ai-paidwarn hidden">${ic('alert',13)} <span>This is a paid model — it is charged to your OpenRouter credit. Clear the box to use free models only.</span></div></div>
    </div>
    <div class="ai-test-row"><button class="btn ghost sm" type="button" data-ai="test">${ic('zap',13)} Test connection</button>
      <span class="cs-test ai-testres"></span></div>
  </div>`;
}
/* Wires the picker inside `host`. Keys/models typed for several providers are kept
   until Save; collect() returns the fields to POST (blank key = keep the saved one). */
function bindAiSettings(host, ai){
  const byId = Object.fromEntries(ai.providers.map(p=>[p.id, p]));
  const draft = {};                     // id -> {key, model}
  let sel = ai.provider;
  const keyIn = host.querySelector('#ai-key'), modelIn = host.querySelector('#ai-model');
  const list = host.querySelector('#ai-model-list'), hint = host.querySelector('.ai-modelhint');
  const res = host.querySelector('.ai-testres');
  const keep = ()=>{ draft[sel] = {key:keyIn.value, model:modelIn.value}; };
  const paidWarn = ()=>{            // OpenRouter: anything not ending in ":free" costs credit
    const v = modelIn.value.trim();
    host.querySelector('.ai-paidwarn').classList.toggle('hidden', !(sel==='openrouter' && v && !v.endsWith(':free')));
  };
  const show = ()=>{
    const p = byId[sel], M = AI_META[sel]||{}, dr = draft[sel]||{};
    host.querySelectorAll('.ai-prov').forEach(b=>{ const on = b.dataset.prov===sel; b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
    keyIn.value = dr.key || '';
    keyIn.placeholder = p.key_set ? '•••••••• saved — leave blank to keep' : (M.ph || 'Paste the API key');
    host.querySelector('.ai-keystate').textContent = p.key_set ? '(saved)' : '';
    host.querySelector('.ai-keylink').href = M.keyUrl || '#';
    modelIn.value = dr.model != null ? dr.model : (p.model || '');
    modelIn.placeholder = 'Automatic';
    list.innerHTML = '';
    hint.textContent = `Leave empty to pick automatically (${p.default_model}). Click “Load models” to see what your key can use.`
      + (sel==='openrouter' ? ' Free models end in “:free”.' : '');
    res.className = 'cs-test ai-testres'; res.textContent = '';
    paidWarn();
  };
  host.querySelectorAll('.ai-prov').forEach(b=>b.onclick = ()=>{ keep(); sel = b.dataset.prov; show(); });
  host.querySelector('[data-ai="load"]').onclick = async (e)=>{
    const btn = e.currentTarget; btn.disabled = true; hint.textContent = 'Loading models…';
    try{
      const r = await api('/api/settings/ai/models',{method:'POST', body:{provider:sel, api_key:keyIn.value.trim()}});
      list.innerHTML = r.models.map(m=>`<option value="${esc(m.id)}">${esc(m.name)}${m.free?' · free':''}${m.vision?' · reads images':''}</option>`).join('');
      const free = r.models.filter(m=>m.free).length;
      hint.textContent = `${r.models.length} models found${free?` (${free} free)`:''}. Click the Model box to pick one.`;
      modelIn.focus();
    }catch(err){ hint.textContent = err.message; }
    btn.disabled = false;
  };
  host.querySelector('[data-ai="test"]').onclick = async (e)=>{
    const btn = e.currentTarget; btn.disabled = true; res.className = 'cs-test ai-testres'; res.textContent = 'Testing…';
    try{
      const r = await api('/api/settings/content/test',{method:'POST', body:{provider:sel, api_key:keyIn.value.trim(), model:modelIn.value.trim()}});
      res.className = 'cs-test ai-testres '+(r.ok?'ok':'bad'); res.innerHTML = ic(r.ok?'check':'x',13)+' '+esc(r.message);
    }catch(err){ res.className = 'cs-test ai-testres bad'; res.innerHTML = ic('x',13)+' '+esc(err.message); }
    btn.disabled = false;
  };
  modelIn.addEventListener('input', paidWarn);
  show();
  return {
    collect(){
      keep();
      const body = {ai_provider: sel};
      Object.entries(draft).forEach(([id, v])=>{
        if((v.key||'').trim()) body[id+'_api_key'] = v.key.trim();
        body[id+'_model'] = (v.model||'').trim();
      });
      return body;
    },
    selected: ()=>sel, hasKey: ()=> !!(keyIn.value.trim() || byId[sel].key_set),
  };
}
window.aiSettingsHTML = aiSettingsHTML; window.bindAiSettings = bindAiSettings;

/* Add / edit a platform's app details (App ID, Secret) in a popup */
function openCredModal(p, thenConnect){
  const has = !!(p.app_id && p.secret_set);
  const scope = p.is_super
    ? `${ic('building',13)} Platform app — used by every client`
    : p.platform_ready && p.source!=='own'
      ? `${ic('info',13)} Optional: use your own ${esc(p.label)} app. Leave empty to keep using the one your administrator set up.`
      : `${ic('key',13)} Your own ${esc(p.label)} app`;
  const m = el(`<div class="modal" style="max-width:520px">
    <div class="modal-head"><span class="pf-ic sm">${pi(p.key, 20)}</span><h3>${has?'Edit':'Add'} ${esc(p.label)} details</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <div class="pt-scope big">${scope}</div>
      <label class="f" for="cm-id">${esc(p.id_label)}</label>
      <input class="f" id="cm-id" value="${esc(p.app_id||'')}" placeholder="${esc(p.id_label)}" autocomplete="off">
      <label class="f" for="cm-sec">${esc(p.secret_label)}</label>
      <input class="f" id="cm-sec" type="password" autocomplete="new-password"
        placeholder="${p.secret_set?'•••••• saved — leave blank to keep it':esc(p.secret_label)}">
      <label class="f">Redirect URI</label>
      <div class="pf-redirect big"><code>${esc(p.redirect_uri)}</code>
        <button class="icon-btn sm" id="cm-copy" type="button" title="Copy">${ic('copy',14)}</button></div>
      <div class="hint">Register this exact URL in the ${esc(p.label)} developer console. Click <b>Guide</b> on the tile for the steps.</div>
      <div class="err" id="cm-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn ghost" id="cm-save">${ic('save',15)} Save</button>
      ${p.connected?'':`<button class="btn" id="cm-conn">${ic('link',15)} Save &amp; Connect</button>`}</div></div>`);
  openModal(m);
  $('#cm-copy',m).onclick = ()=>{ try{ navigator.clipboard.writeText(p.redirect_uri); toast('Redirect URI copied','good'); }catch(e){ toast(p.redirect_uri); } };
  const save = async ()=>{
    $('#cm-err',m).textContent='';
    const id = $('#cm-id',m).value.trim(), sec = $('#cm-sec',m).value.trim();
    if(!id){ $('#cm-err',m).textContent = `Enter the ${p.id_label}.`; $('#cm-id',m).focus(); return false; }
    if(!sec && !p.secret_set){ $('#cm-err',m).textContent = `Enter the ${p.secret_label}.`; $('#cm-sec',m).focus(); return false; }
    const bd = {app_id:id}; if(sec) bd.app_secret = sec;
    try{ await api('/api/platforms/'+p.key+'/creds',{method:'POST', body:bd}); return true; }
    catch(e){ $('#cm-err',m).textContent = e.message; return false; }
  };
  $('#cm-save',m).onclick = async ()=>{ if(await save()){ closeModal(); toast(p.label+' details saved','good'); renderSetup(); } };
  const cb = $('#cm-conn',m);
  if(cb) cb.onclick = async ()=>{ if(await save()){ closeModal(); connectLive(p); } };
  m.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); (thenConnect && cb ? cb : $('#cm-save',m)).click(); } }));
  setTimeout(()=>$('#cm-id',m) && $('#cm-id',m).focus(), 40);
}
window.openCredModal = openCredModal;

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
