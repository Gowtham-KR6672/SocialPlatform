/* ============================================================
   Native app bridge — runs only inside the Android / iOS app
   (Capacitor, see mobile/). On the normal website it does nothing.
   - Sign-in to Google, Meta, X… opens in the system browser tab:
     those providers block sign-in inside embedded web views.
   - External links open in the system browser.
   - Android back button closes the open menu / dialog, then goes back.
   - Data refreshes when the app comes back to the foreground.
   - The screen doesn't zoom, so it never slides left and right.
   ============================================================ */
(function(){
  const C = window.Capacitor;
  if(!C || typeof C.isNativePlatform !== 'function' || !C.isNativePlatform()) return;
  const P = C.Plugins || {};
  document.documentElement.classList.add('in-app', 'in-app-' + C.getPlatform());

  // ---- no zoom ----------------------------------------------------------------
  // iOS zooms in when a text box under 16px is tapped (the sign-in fields) and never
  // zooms back out, so every screen after that is a little too wide and slides sideways.
  // iOS: viewport-fit=cover lets the page read the home-bar height, so the phone menu sits above it.
  // Android pads the app around its status and navigation bars itself — cover would turn that off.
  const fit = C.getPlatform() === 'ios' ? ', viewport-fit=cover' : '';
  const vp = document.querySelector('meta[name="viewport"]');
  if(vp) vp.setAttribute('content', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no' + fit);

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
      if(typeof window.closeMobileNav === 'function' && window.closeMobileNav()) return;   // phone menu sheet
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
