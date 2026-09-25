/* ============================================================
   First-time onboarding
   Shows a Welcome popup on the user's first login, then an
   optional step-by-step setup wizard. Completion is saved in
   the database so it never appears again for that user.
   ============================================================ */
function maybeShowOnboarding(){
  const u = App.user;
  if(!u || u.onboarding_done) return;      // only once, until completed
  // already has accounts connected → setup is effectively done; don't nag
  if(Object.values(u.platforms||{}).some(Boolean)){ markOnboardingDone(); return; }
  // small delay so the dashboard paints first, then the Welcome popup appears
  setTimeout(showWelcomePopup, 350);
}
window.maybeShowOnboarding = maybeShowOnboarding;

/* ---- Welcome popup ---- */
function showWelcomePopup(){
  if(!App.user || App.user.onboarding_done) return;
  const m = el(`<div class="modal ob-welcome">
    <div class="modal-body" style="text-align:center;padding:26px 24px">
      <div class="ob-badge">${ic('sparkles',28)}</div>
      <h2 style="margin:10px 0 6px">Welcome to Social Platform</h2>
      <p class="sub" style="max-width:420px;margin:0 auto 18px">
        Let's get you set up in a couple of minutes — complete your profile and
        connect the social accounts you want to publish to.</p>
      <div class="ob-dl">
        <span class="sub">Setup Guide:</span>
        <a class="btn ghost sm" href="/guides/Social_Platform_Setup_Guide.pdf" download>${ic('download',13)} PDF</a>
        <a class="btn ghost sm" href="/guides/Social_Platform_Setup_Guide.docx" download>${ic('download',13)} Word</a>
      </div>
      <div class="row" style="justify-content:center;gap:10px;margin-top:20px">
        <button class="btn ghost" id="ob-later">Maybe later</button>
        <button class="btn grad-btn" id="ob-start">Start Setup ${ic('chevRight',15)}</button>
      </div>
      <label class="ob-never"><input type="checkbox" id="ob-never"> Don't show this again</label>
    </div></div>`);
  openModal(m, {closeOnBackdrop:false});
  $('#ob-later',m).onclick = ()=>{                 // shows again next login unless ticked
    if($('#ob-never',m).checked) markOnboardingDone();
    closeModal();
  };
  $('#ob-start',m).onclick = ()=>{ closeModal(); startSetupWizard(); };
}

/* ---- Setup wizard ---- */
const OB_STEPS = ['Complete Profile','Connect Instagram','Connect YouTube',
                  'Other accounts','Review','Finish'];

function startSetupWizard(){
  App._obStep = 0;
  openWizard();
}

function openWizard(){
  const m = el(`<div class="modal ob-wizard" style="max-width:620px">
    <div class="modal-head"><h3 id="ob-title"></h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="ob-steps" id="ob-progress"></div>
    <div class="modal-body" id="ob-stepbody"></div>
    <div class="modal-foot">
      <button class="btn ghost" id="ob-back">${ic('chevLeft',15)} Back</button>
      <div style="flex:1"></div>
      <button class="btn ghost" id="ob-skip">Skip</button>
      <button class="btn grad-btn" id="ob-next">Next ${ic('chevRight',15)}</button>
    </div></div>`);
  openModal(m, {closeOnBackdrop:false});
  drawWizardStep(m);
  $('#ob-back',m).onclick = ()=>{ if(App._obStep>0){ App._obStep--; drawWizardStep(m); } };
  $('#ob-skip',m).onclick = ()=>{ nextStep(m); };
  $('#ob-next',m).onclick = ()=>{ handleStepNext(m); };
}

function drawWizardStep(m){
  const i = App._obStep;
  $('#ob-title',m).textContent = `Setup — ${OB_STEPS[i]}`;
  // progress dots
  $('#ob-progress',m).innerHTML = OB_STEPS.map((s,ix)=>`
    <div class="ob-dot ${ix<i?'done':''} ${ix===i?'on':''}"><span>${ix<i?ic('check',12):(ix+1)}</span><i>${esc(s)}</i></div>`).join('');
  const body = $('#ob-stepbody',m);
  const back=$('#ob-back',m), skip=$('#ob-skip',m), next=$('#ob-next',m);
  back.style.visibility = i===0 ? 'hidden' : 'visible';
  skip.style.display = (i>=4) ? 'none' : '';
  next.innerHTML = (i===OB_STEPS.length-1) ? `Finish ${ic('check',15)}` : `Next ${ic('chevRight',15)}`;

  const plat = (App.user.platforms)||{};
  if(i===0){                         // Complete Profile
    body.innerHTML = `
      <label class="f">Display name</label>
      <input class="f" id="ob-name" value="${esc(App.user.display_name||App.user.username||'')}">
      <label class="f">Email (optional)</label>
      <input class="f" id="ob-email" type="email" value="${esc(App.user.email||'')}" placeholder="you@company.com">
      <label class="f">Phone (optional)</label>
      <input class="f" id="ob-phone" value="${esc(App.user.phone||'')}" placeholder="+91…">`;
  }else if(i===1){                   // Instagram
    body.innerHTML = obConnectStep('instagram','Instagram',pi('instagram',22), plat.instagram);
    bindConnectStep(m,'instagram');
  }else if(i===2){                   // YouTube
    body.innerHTML = obConnectStep('youtube','YouTube',pi('youtube',22), plat.youtube);
    bindConnectStep(m,'youtube');
  }else if(i===3){                   // Other accounts (Facebook + Twitter/X)
    body.innerHTML = `<p class="sub" style="margin-top:0">Connect any other accounts you use.</p>
      ${obConnectStep('facebook','Facebook',pi('facebook',22), plat.facebook)}
      <hr class="sep">
      ${obConnectStep('twitter','Twitter / X',pi('twitter',22), plat.twitter)}`;
    bindConnectStep(m,'facebook'); bindConnectStep(m,'twitter');
  }else if(i===4){                   // Review
    const rows = [['Instagram',plat.instagram],['YouTube',plat.youtube],
                  ['Facebook',plat.facebook],['Twitter / X',plat.twitter]];
    body.innerHTML = `<p class="sub" style="margin-top:0">Here's your setup so far — you can change any of it later from the Setup panel.</p>
      <div class="ob-review">
        <div class="obr"><span>Profile</span><b>${esc(App.user.display_name||App.user.username)}</b></div>
        ${rows.map(([n,c])=>`<div class="obr"><span>${n}</span>
          <b class="${c?'ok':'muted-i'}">${c?'Connected':'Not connected'}</b></div>`).join('')}
      </div>`;
  }else{                             // Finish
    body.innerHTML = `<div style="text-align:center;padding:14px 0">
      <div class="ob-badge">${ic('check',28)}</div>
      <h3 style="margin:8px 0 4px">You're all set!</h3>
      <p class="sub">Click Finish to start using Social Platform. You can connect more accounts anytime from the Setup panel.</p></div>`;
  }
}

function obConnectStep(key,label,icon,connected){
  return `<div class="ob-conn" data-plat="${key}">
      <div class="ob-conn-h"><span class="ob-ic">${icon}</span> <b>${label}</b>
        <span class="chip ${connected?'completed':'draft'}" id="ob-st-${key}">${connected?'Connected':'Not connected'}</span></div>
      <div class="row" style="gap:8px;margin-top:8px">
        <button class="btn sm ${connected?'ghost':'grad-btn'}" data-obconn="${key}">${connected?'Disconnect':'Connect with '+label}</button>
        <a class="btn ghost sm" href="/guides/${key}.pdf" download>${ic('download',13)} Guide</a>
      </div></div>`;
}

function bindConnectStep(m, key){
  const b = m.querySelector(`[data-obconn="${key}"]`); if(!b) return;
  b.onclick = async ()=>{
    const connected = (App.user.platforms||{})[key];
    try{
      if(connected){
        await api('/api/platforms/'+key+'/disconnect',{method:'POST'});
      }else{
        // real sign-in only: needs the App ID + Secret saved in Setup first
        const r = await api('/api/connect/'+key+'/start',{method:'POST', body:{}});
        const w = window.open(r.auth_url, 'sdb_oauth', 'width=560,height=720');
        const done = async ()=>{ window.removeEventListener('message', onMsg); clearInterval(iv); await refreshMe(); drawWizardStep(m); };
        const onMsg = (ev)=>{ if(ev.data && ev.data.sdb_oauth) done(); };
        window.addEventListener('message', onMsg);
        const iv = setInterval(()=>{ if(w && w.closed) done(); }, 1500);
        return;
      }
      await refreshMe();
      drawWizardStep(m);     // re-render this step with fresh status
    }catch(e){ toast(e.message,'warn'); }
  };
}

async function handleStepNext(m){
  const i = App._obStep;
  if(i===0){                          // save profile
    const name = ($('#ob-name',m).value||'').trim();
    if(!name){ toast('Enter a display name','warn'); return; }
    try{ await api('/api/me/profile',{method:'POST', body:{
        display_name:name, email:$('#ob-email',m).value, phone:$('#ob-phone',m).value}});
      await refreshMe(); renderTopbar();
    }catch(e){ toast(e.message,'warn'); return; }
  }
  if(i===OB_STEPS.length-1){ finishOnboarding(); return; }
  nextStep(m);
}

function nextStep(m){
  if(App._obStep < OB_STEPS.length-1){ App._obStep++; drawWizardStep(m); }
  else finishOnboarding();
}

async function markOnboardingDone(){
  if(App.user) App.user.onboarding_done = true;
  try{ await api('/api/onboarding/complete',{method:'POST'}); }catch(e){}
}

async function finishOnboarding(){
  await markOnboardingDone();
  closeModal();
  toast('Setup complete — welcome aboard!','good', 3000);
  renderDashboard();
}
