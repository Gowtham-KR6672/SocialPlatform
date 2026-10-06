/* ============================================================
   Push notifications (V39)
   - Browsers: Web Push through the service worker at /sw.js.
   - Android / iOS app: Firebase Cloud Messaging through the Capacitor
     PushNotifications plugin (needs the Firebase setup, see mobile/README.md).
   Each device is switched on from the Notifications page; which kinds
   (notifications / chat messages) arrive is a per-user choice.
   ============================================================ */
const Push = (function(){
  const isNative = ()=> !!(window.Capacitor && Capacitor.isNativePlatform && Capacitor.isNativePlatform());
  const PN = ()=> isNative() && window.Capacitor.Plugins ? (Capacitor.Plugins.PushNotifications || null) : null;
  const webOk = ()=> 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  const isIOS = ()=> /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
  const standalone = ()=> (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
  let cfg = null, reg = null, nativeHooked = false;

  const keyBytes = b64=>{ const s = (b64 + '='.repeat((4 - b64.length % 4) % 4)).replace(/-/g,'+').replace(/_/g,'/');
    const raw = atob(s); return Uint8Array.from([...raw].map(c=>c.charCodeAt(0))); };
  async function config(force){ if(!cfg || force){ cfg = await api('/api/push/config'); } return cfg; }
  async function swReg(){
    if(reg) return reg;
    reg = await navigator.serviceWorker.register('/sw.js', {scope:'/'});
    await navigator.serviceWorker.ready;
    return reg;
  }

  /* ---- the app (FCM) ---- */
  function hookNative(){
    const pn = PN(); if(!pn || nativeHooked) return; nativeHooked = true;
    pn.addListener('registration', async t=>{
      try{ localStorage.setItem('pmFcmToken', t.value); }catch(e){}
      try{ await api('/api/push/subscribe', {method:'POST', body:{kind:'fcm', token:t.value, platform:Capacitor.getPlatform()}}); }catch(e){}
      if(typeof window.renderPushCard === 'function') renderPushCard();
    });
    pn.addListener('registrationError', e=>{ console.warn('push registration failed', e && e.error); });
    pn.addListener('pushNotificationActionPerformed', a=>{       // the user tapped a notification
      const d = (a && a.notification && a.notification.data) || {};
      if(App.user && typeof openLinkTarget === 'function') openLinkTarget(d.link || 'notifications');
      else try{ sessionStorage.setItem('pmOpenLink', d.link || 'notifications'); }catch(e){}
    });
  }

  /* 'on' | 'off' | 'blocked' | 'unsupported' | 'ios-install' | 'app-update' | 'app-setup' */
  async function state(){
    if(isNative()){
      const pn = PN(); if(!pn) return 'app-update';
      const c = await config(); if(!c.fcm_ready) return 'app-setup';
      const p = await pn.checkPermissions();
      if(p.receive === 'denied') return 'blocked';
      let tok = ''; try{ tok = localStorage.getItem('pmFcmToken') || ''; }catch(e){}
      return p.receive === 'granted' && tok ? 'on' : 'off';
    }
    if(!webOk()) return isIOS() && !standalone() ? 'ios-install' : 'unsupported';
    if(Notification.permission === 'denied') return 'blocked';
    if(Notification.permission !== 'granted') return 'off';
    const r = await navigator.serviceWorker.getRegistration('/');
    const sub = r && await r.pushManager.getSubscription();
    return sub ? 'on' : 'off';
  }

  async function enable(){
    if(isNative()){
      const pn = PN(); if(!pn) throw new Error('Update the app to get push notifications.');
      const c = await config(true); if(!c.fcm_ready) throw new Error('Push in the app isn’t set up yet (the SuperAdmin adds the Firebase key).');
      hookNative();
      let p = await pn.checkPermissions();
      if(p.receive !== 'granted') p = await pn.requestPermissions();
      if(p.receive !== 'granted') throw new Error('Notifications are blocked for the app in Android settings.');
      await pn.register();                        // the token arrives in the 'registration' listener
      return;
    }
    if(!webOk()) throw new Error('This browser can’t receive push notifications.');
    const perm = await Notification.requestPermission();
    if(perm !== 'granted') throw new Error(perm === 'denied'
      ? 'Notifications are blocked for this site. Allow them in the browser’s site settings, then try again.'
      : 'Notifications weren’t allowed.');
    const c = await config(true), r = await swReg();
    let sub = await r.pushManager.getSubscription();
    if(!sub) sub = await r.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:keyBytes(c.vapid_public)});
    await api('/api/push/subscribe', {method:'POST', body:{kind:'web', subscription:sub.toJSON()}});
  }

  async function disable(){
    if(isNative()){
      let tok = ''; try{ tok = localStorage.getItem('pmFcmToken') || ''; localStorage.removeItem('pmFcmToken'); }catch(e){}
      if(tok) await api('/api/push/unsubscribe', {method:'POST', body:{token:tok}});
      try{ const pn = PN(); if(pn && pn.unregister) await pn.unregister(); }catch(e){}
      return;
    }
    const r = webOk() && await navigator.serviceWorker.getRegistration('/');
    const sub = r && await r.pushManager.getSubscription();
    if(sub){ try{ await api('/api/push/unsubscribe', {method:'POST', body:{endpoint:sub.endpoint}}); }catch(e){} await sub.unsubscribe(); }
  }

  /* after login: keep this device linked to whoever is signed in (no prompts) */
  async function sync(){
    try{
      if(isNative()){
        hookNative();
        const pn = PN(); if(!pn) return;
        const c = await config(true); if(!c.fcm_ready) return;
        const p = await pn.checkPermissions();
        if(p.receive === 'granted' && localStorage.getItem('pmFcmToken')) await pn.register();
        return;
      }
      if(!webOk() || Notification.permission !== 'granted') return;
      const r = await navigator.serviceWorker.getRegistration('/');
      const sub = r && await r.pushManager.getSubscription();
      if(sub){ reg = r; await api('/api/push/subscribe', {method:'POST', body:{kind:'web', subscription:sub.toJSON()}}); }
    }catch(e){}
  }

  /* before logout: this device stops receiving the signed-out user's pushes */
  async function forget(){ try{ await disable(); }catch(e){} cfg = null; }

  // a tapped notification while the site is open (sent by the service worker)
  if('serviceWorker' in navigator){
    navigator.serviceWorker.addEventListener('message', e=>{
      if(e.data && e.data.type === 'push-open' && App.user && typeof openLinkTarget === 'function') openLinkTarget(e.data.link || 'notifications');
    });
  }
  if(isNative()) hookNative();
  return {state, enable, disable, sync, forget, config, isNative};
})();
window.Push = Push;

/* ---------- the card on the Notifications page ---------- */
const PUSH_STATE_TEXT = {
  'on': 'On for this device.',
  'off': 'Off on this device. Turn it on to get alerts even when the site is closed.',
  'blocked': 'Blocked for this site. Allow notifications in the browser (or app) settings, then try again.',
  'unsupported': 'This browser can’t receive push notifications. Try Chrome, Edge, Firefox or Safari.',
  'ios-install': 'On iPhone and iPad: tap Share → Add to Home Screen, open the site from there, then turn this on.',
  'app-update': 'This version of the app can’t receive push notifications yet. Update the app.',
  'app-setup': 'Push in the app isn’t set up yet. The SuperAdmin adds the Firebase key below (or in the web version).',
};
async function renderPushCard(){
  const box = $('#pushCard'); if(!box) return;
  let st = 'unsupported', c = null;
  try{ c = await Push.config(true); st = await Push.state(); }catch(e){}
  if(!$('#pushCard')) return;
  const prefs = (c && c.prefs) || {notifications:true, chat:true};
  const canToggle = st === 'on' || st === 'off';
  box.innerHTML = `<div class="push-row">
      <span class="push-ic ${st==='on'?'on':''}">${ic('bell',20)}</span>
      <div class="push-txt"><b>Push notifications</b><small>${esc(PUSH_STATE_TEXT[st]||'')}</small></div>
      ${canToggle?`<button class="btn ${st==='on'?'ghost':''} sm" id="pushToggle">${st==='on'?'Turn off':'Turn on'}</button>`:''}
    </div>
    <div class="push-prefs">
      <label class="push-sw"><input type="checkbox" id="pushPrefN" ${prefs.notifications?'checked':''}><span></span> New notifications</label>
      <label class="push-sw"><input type="checkbox" id="pushPrefC" ${prefs.chat?'checked':''}><span></span> Chat messages</label>
      ${st==='on'?`<button class="btn ghost sm" id="pushTest">${ic('send',13)} Send a test</button>`:''}
    </div>
    ${c && c.is_super ? `<div class="push-fcm">${ic('phone',15)}
      <span>${c.fcm_ready ? `Android / iOS app: Firebase project <b>${esc(c.fcm_project||'')}</b> connected.`
                          : 'Android / iOS app: not set up. Upload the Firebase service-account key (.json).'}</span>
      <label class="btn ghost sm push-up">${c.fcm_ready?'Replace key':'Upload key'}<input type="file" accept=".json,application/json" id="pushFcmFile" hidden></label>
      ${c.fcm_ready?`<button class="btn ghost sm" id="pushFcmDel">${ic('trash',13)} Remove</button>`:''}</div>` : ''}`;
  const t = $('#pushToggle');
  if(t) t.onclick = async ()=>{ t.disabled = true;
    try{ if(st === 'on'){ await Push.disable(); toast('Push turned off on this device'); }
         else { await Push.enable(); toast(Push.isNative() ? 'Push turned on for the app' : 'Push turned on for this device','good'); } }
    catch(e){ toast(e.message || 'Couldn’t change push notifications','warn',6000); }
    renderPushCard(); };
  const save = async ()=>{ try{ await api('/api/push/prefs', {method:'POST', body:{notifications:$('#pushPrefN').checked, chat:$('#pushPrefC').checked}}); toast('Saved','good'); }
    catch(e){ toast(e.message,'warn'); } };
  $('#pushPrefN').onchange = save; $('#pushPrefC').onchange = save;
  if($('#pushTest')) $('#pushTest').onclick = async ()=>{ try{ await api('/api/push/test', {method:'POST'}); toast('Test sent. It should appear in a few seconds.','good'); }catch(e){ toast(e.message,'warn'); } };
  const f = $('#pushFcmFile');
  if(f) f.onchange = async ()=>{ const file = f.files && f.files[0]; if(!file) return;
    try{ const d = await api('/api/push/fcm', {method:'POST', body:{service_account: await file.text()}});
      toast('Firebase connected: ' + d.project, 'good'); }catch(e){ toast(e.message,'warn',7000); }
    renderPushCard(); };
  if($('#pushFcmDel')) $('#pushFcmDel').onclick = ()=>confirmBox('Remove the Firebase key?', 'Push to the Android and iOS app stops until a key is uploaded again. Browser push keeps working.',
    async ()=>{ await api('/api/push/fcm', {method:'DELETE'}); renderPushCard(); }, 'Remove');
}
window.renderPushCard = renderPushCard;
