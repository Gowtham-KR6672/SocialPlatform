/* ============================================================
   Native app bridge — runs only inside the Android / iOS app
   (Capacitor, see mobile/). On the normal website it does nothing.
   - Sign-in to Google, Meta, X… opens in the system browser tab:
     those providers block sign-in inside embedded web views.
   - External links open in the system browser.
   - Android back button closes the open dialog, then goes back.
   - Data refreshes when the app comes back to the foreground.
   ============================================================ */
(function(){
  const C = window.Capacitor;
  if(!C || typeof C.isNativePlatform !== 'function' || !C.isNativePlatform()) return;
  const P = C.Plugins || {};
  document.documentElement.classList.add('in-app', 'in-app-' + C.getPlatform());

  // ---- sign-in popups → system browser tab ----------------------------------
  // The site opens sign-in with window.open(url) and waits for the window to close.
  // Here that becomes the in-app browser tab; "closed" flips when the user closes it.
  let current = null;
  if(P.Browser){
    P.Browser.addListener('browserFinished', ()=>{ if(current){ current.closed = true; current = null; } });
  }
  const webOpen = window.open.bind(window);
  window.open = function(url, name, features){
    let u;
    try{ u = new URL(url, location.href); }catch(e){ return webOpen(url, name, features); }
    if(!P.Browser || u.origin === location.origin) return webOpen(url, name, features);
    const handle = {closed:false, location:{href:u.href}, focus(){}, postMessage(){},
                    close(){ try{ P.Browser.close(); }catch(e){} }};
    current = handle;
    P.Browser.open({url:u.href, presentationStyle:'popover'});
    return handle;
  };

  // ---- external links (posts, help pages) → system browser --------------------
  document.addEventListener('click', e=>{
    const a = e.target.closest && e.target.closest('a[href]');
    if(!a || !P.Browser) return;
    let u; try{ u = new URL(a.getAttribute('href'), location.href); }catch(err){ return; }
    if(!/^https?:$/.test(u.protocol) || u.origin === location.origin) return;
    e.preventDefault();
    P.Browser.open({url:u.href});
  }, true);

  // ---- Android back button --------------------------------------------------
  if(P.App){
    P.App.addListener('backButton', ({canGoBack})=>{
      const root = document.getElementById('modal-root');
      if(root && root.children.length && typeof window.closeModal === 'function'){ window.closeModal(); return; }
      if(window.App && App.user && App.page && App.page !== 'input' && typeof window.renderDashboard === 'function'){
        App.page = 'input'; window.renderDashboard(); return;
      }
      if(canGoBack) history.back(); else P.App.minimizeApp();
    });
    // back from the sign-in tab or the background: refresh what's on screen
    P.App.addListener('resume', ()=>{
      try{
        if(window.App && App.user && typeof window.renderDashboard === 'function' && !document.querySelector('#modal-root .modal')){
          window.renderDashboard(App.readonly);
        }
      }catch(e){}
    });
  }
})();
