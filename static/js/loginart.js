/* ============================================================
   Login page "concept video", built in code (no video file).
   Seven short scenes walk through how the platform works:
   connect → upload → write with AI → schedule → publish →
   track results → reply. A timeline under the player shows
   the chapters; each chapter's bar filling up is what moves
   the video on (its CSS animation ends → next scene), so
   pausing the animations pauses the whole video.
   Everything is sized in em against the player width, so it
   scales cleanly and stays sharp.
   ============================================================ */
(function(){
  const P = (k, s) => (typeof pi === 'function' ? pi(k, s) : '');
  const I = (k, s) => (typeof ic === 'function' ? ic(k, s) : '');
  const L = k => (typeof platLabel === 'function' ? platLabel(k) : k);
  const PLATS = ['instagram','facebook','youtube','twitter','linkedin','threads','tiktok','pinterest'];
  const SCENE_SECONDS = 5.2;

  const STEPS = [
    {k:'connect',  t:'Connect your accounts',  d:'Link Instagram, Facebook, YouTube, X, LinkedIn, Threads, TikTok and Pinterest once with secure sign-in.'},
    {k:'upload',   t:'Upload your video',      d:'Drop in a file and it is prepared for every format: Reels and Shorts, YouTube and the feed.'},
    {k:'create',   t:'Write it with AI',       d:'Get a caption and hashtags in your brand voice, adapted for each platform.'},
    {k:'schedule', t:'Schedule it',            d:'Drop the post on the calendar, or let the queue pick the best time to post.'},
    {k:'publish',  t:'Publish everywhere',     d:'One click sends it to every platform. Anything that fails can be retried in a tap.'},
    {k:'analyze',  t:'Track the results',      d:'Views, engagement and follower growth, with platforms compared side by side.'},
    {k:'engage',   t:'Reply to your audience', d:'Comments from every platform arrive in one inbox, with AI-suggested replies.'},
  ];
  const label = ['Connect','Upload','Create','Schedule','Publish','Analyze','Engage'];

  /* ---------- scenes ---------- */
  const thumb = (cls='') => `<span class="cv-thumb ${cls}"><span class="cv-play">${I('play', 12)}</span></span>`;

  const s1 = () => `
    <div class="cv-sc s1">
      <div class="s1-ring">
        ${PLATS.map((k,i)=>`<span class="s1-line" style="--a:${i*45}deg;--d:${.2+i*.16}s"></span>`).join('')}
        <span class="s1-hub"><img src="/static/img/logo-160.png" alt=""></span>
        ${PLATS.map((k,i)=>`<span class="s1-node" style="--a:${i*45}deg;--d:${.2+i*.16}s"><span class="s1-pop">${P(k,20)}
          <i class="s1-ok">${I('check',9)}</i></span></span>`).join('')}
      </div>
      <div class="s1-txt">
        <div class="s1-n"><b data-count="8" data-delay="0.2" data-dur="1.3">0</b><span>/8</span></div>
        <div class="s1-l">platforms connected</div>
        <ul class="cv-list">
          <li style="--d:1.6s">${I('lock',12)} Official sign-in, no passwords shared</li>
          <li style="--d:1.9s">${I('refresh',12)} Sign-ins renewed automatically</li>
          <li style="--d:2.2s">${I('building',12)} One workspace per client or brand</li>
        </ul>
      </div>
    </div>`;

  const s2 = () => `
    <div class="cv-sc s2">
      <div class="s2-drop">
        <span class="s2-ic">${I('cloudUpload',24)}</span>
        <b>Drop your video here</b><small>MP4 or MOV, straight from your phone or PC</small>
        <div class="s2-file">
          ${thumb()}
          <div class="s2-meta"><b>Summer launch reel.mp4</b><small>24.6 MB</small><span class="s2-bar"><i></i></span></div>
          <span class="s2-pct"><b data-count="100" data-delay="1.1" data-dur="1.7">0</b>%</span>
          <span class="s2-done">${I('check',11)}</span>
        </div>
      </div>
      <div class="s2-side">
        <div class="cv-eye">Ready for every platform</div>
        ${[['9:16','Reels · TikTok · Shorts','r916'],['16:9','YouTube','r169'],['1:1','Feed posts','r11'],['Cover','Thumbnail picked','rcov']]
          .map(([a,b,c],i)=>`<div class="s2-fmt" style="--d:${2.9+i*.25}s"><span class="s2-ratio ${c}"></span><b>${a}</b><small>${b}</small>
            <span class="cv-ok">${I('check',10)}</span></div>`).join('')}
      </div>
    </div>`;

  const CAPTION = 'Summer is here ☀️ Our new collection drops this Friday. Which look is your favourite? Tell us below 👇';
  const s3 = () => `
    <div class="cv-sc s3">
      <div class="s3-post">${thumb('big')}<b>Summer launch reel</b><small>0:24 · 9:16</small></div>
      <div class="s3-ai">
        <div class="s3-h"><span class="cv-spark">${I('sparkles',14)}</span><b>AI caption writer</b>
          <span class="s3-gen">${I('sparkles',11)} Generate</span></div>
        <div class="s3-tone"><span>Tone</span><b>Friendly</b><b>Short</b><b>Emoji</b></div>
        <p class="s3-cap">${CAPTION.split(' ').map((w,i)=>`<span style="--i:${i}">${w}</span>`).join(' ')}</p>
        <div class="s3-tags">${['#SummerDrop','#NewCollection','#OOTD','#StyleInspo'].map((t,i)=>`<span style="--d:${2.85+i*.14}s">${t}</span>`).join('')}</div>
        <div class="s3-adapt"><small>Adapted for</small>${['instagram','linkedin','twitter','tiktok']
          .map((k,i)=>`<span style="--d:${3.5+i*.16}s">${P(k,12)} ${L(k)}</span>`).join('')}</div>
      </div>
    </div>`;

  // two weeks, Mon 28 Oct → Sun 10 Nov; the new post lands on Fri 1 Nov
  const DATES = [28,29,30,31,1,2,3,4,5,6,7,8,9,10], TARGET = 4;
  const CAL = {1:'instagram',2:'youtube',7:'linkedin',9:'tiktok',11:'facebook',12:'pinterest'};
  const s4 = () => `
    <div class="cv-sc s4">
      <div class="s4-cal">
        <div class="s4-h"><span class="cv-ib">${I('calendar',13)}</span><b>Content calendar</b><span class="cv-sp"></span><small>Week view</small></div>
        <div class="s4-wk">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(w=>`<span>${w}</span>`).join('')}</div>
        <div class="s4-grid">${DATES.map((n,i)=>{ const k=CAL[i];
          return `<div class="s4-day${i===TARGET?' tgt':''}${i<4?' old':''}"><span>${n}</span>${k?`<i class="cv-pill">${P(k,11)}</i>`:''}
            ${i===TARGET?`<i class="cv-pill s4-new">${P('instagram',10)}${P('tiktok',10)}${P('youtube',10)}</i><span class="s4-fly">${thumb()}</span>`:''}</div>`; }).join('')}</div>
      </div>
      <div class="s4-side">
        <div class="cv-eye">Ready to schedule</div>
        <div class="s4-card">${thumb()}<div><b>Summer launch reel</b><small>${P('instagram',10)} ${P('tiktok',10)} ${P('youtube',10)}</small></div></div>
        <div class="s4-best"><span class="cv-ib g">${I('target',13)}</span><div><small>Best time to post</small><b>Fri · 6:00 PM</b></div></div>
        <div class="s4-ok">${I('check',12)} Scheduled for Fri 1 Nov, 6:00 PM</div>
        <div class="s4-q">${I('repeat',12)}<span>Or use <b>Fill queue</b> to slot approved posts in automatically</span></div>
      </div>
    </div>`;

  const PUB = ['instagram','facebook','youtube','linkedin','tiktok'];
  const s5 = () => `
    <div class="cv-sc s5">
      <div class="s5-main">
        <div class="s5-h">${thumb()}<div><b>Summer launch reel</b><small>Fri 1 Nov · 6:00 PM</small></div>
          <span class="cv-sp"></span><span class="s5-btn">${I('send',12)} Publish now</span></div>
        ${PUB.map((k,i)=>`<div class="s5-row" style="--d:${1.1+i*.42}s">${P(k,16)}<b>${L(k)}</b>
          <span class="s5-st"><span class="q">${I('clock',10)} Queued</span><span class="p"><i class="cv-spin"></i> Publishing</span>
            <span class="ok">${I('check',10)} Published</span></span></div>`).join('')}
        <div class="s5-prog"><i></i></div>
      </div>
      <div class="s5-toast">${I('check',14)}<div><b>Live on 5 platforms</b><small>Links and stats are collected automatically</small></div></div>
    </div>`;

  const BARS = [30,42,38,55,50,64,58,74,70,92];
  const SHARE = [['tiktok',41],['instagram',28],['youtube',18],['facebook',13]];
  const s6 = () => `
    <div class="cv-sc s6">
      <div class="s6-kpis">
        <div class="s6-k"><small>${I('eye',11)} Reach</small><b><span data-count="128.4" data-dec="1" data-delay="0.3" data-dur="1.6">0</span>K</b><em>${I('arrowUp',9)} 24%</em></div>
        <div class="s6-k"><small>${I('heart',11)} Engagement</small><b><span data-count="9.8" data-dec="1" data-delay="0.5" data-dur="1.6">0</span>%</b><em>${I('arrowUp',9)} 3.1%</em></div>
        <div class="s6-k"><small>${I('users',11)} New followers</small><b>+<span data-count="2340" data-delay="0.7" data-dur="1.6">0</span></b><em>${I('arrowUp',9)} 18%</em></div>
      </div>
      <div class="s6-row">
        <div class="s6-chart"><div class="cv-eye">Views by day</div>
          <div class="s6-bars">${BARS.map((h,i)=>`<i style="--h:${h}%;--d:${1+i*.08}s"></i>`).join('')}<span class="s6-tip">${I('eye',10)} 15.4K views</span></div></div>
        <div class="s6-cmp"><div class="cv-eye">Platform comparison</div>
          ${SHARE.map(([k,v],i)=>`<div class="s6-pl" style="--w:${v*2.2}%;--d:${1.6+i*.15}s">${P(k,12)}<span><i></i></span><b>${v}%</b>${i===0?'<em>Best</em>':''}</div>`).join('')}
          <div class="s6-pdf">${I('file',11)} Monthly PDF report ready</div></div>
      </div>
    </div>`;

  const CMTS = [['instagram','maya.styles','Obsessed with the yellow one! 😍','pos'],
                ['youtube','Chris D.','When does it ship to Canada?','q'],
                ['tiktok','@leo.fits','Need this for my trip 🔥','pos']];
  const s7 = () => `
    <div class="cv-sc s7">
      <div class="s7-inbox">
        <div class="s7-h"><span class="cv-ib">${I('inbox',13)}</span><b>Unified inbox</b><span class="cv-sp"></span><span class="s7-n">3 new</span></div>
        ${CMTS.map(([k,u,t,s],i)=>`<div class="s7-c${i===1?' sel':''}" style="--d:${.3+i*.35}s">${P(k,15)}<div><b>${u}</b><p>${t}</p></div>
          <span class="s7-tag ${s}">${s==='q'?'Question':'Positive'}</span></div>`).join('')}
      </div>
      <div class="s7-reply">
        <div class="s3-h"><span class="cv-spark">${I('sparkles',13)}</span><b>Suggested reply</b></div>
        <p>Hi Chris! Yes, we ship to Canada. Orders arrive in 3 to 5 days. Thanks for asking! 😊</p>
        <span class="s7-send">${I('send',11)} Send reply</span>
        <div class="s7-ok">${I('check',12)} Replied on YouTube</div>
      </div>
    </div>`;

  window.loginScene = () => {
    setTimeout(initConceptVideo, 0);   // the markup is in the page right after this returns
    return `
  <div class="cv" data-step="0" style="--dur:${SCENE_SECONDS}s">
    <div class="cv-win">
      <div class="cv-bar" aria-hidden="true"><span class="cv-dots"><i></i><i></i><i></i></span>
        <span class="cv-url">${I('lock',10)} socialplatform.app</span><span class="cv-sp"></span><span class="cv-count">1 / ${STEPS.length}</span></div>
      <div class="cv-scr" aria-hidden="true">
        ${[s1,s2,s3,s4,s5,s6,s7].map(f=>f()).join('')}
        <span class="cv-cursor"><svg viewBox="0 0 24 24"><path d="M5 3l13 7.5-5.6 1.4 3.4 6.4-2.6 1.4-3.4-6.4L5.6 17z"/></svg><i></i></span>
      </div>
    </div>
    <div class="cv-cap">
      <div class="cv-cap-txt"><span class="cv-cap-n">Step 1</span><b class="cv-cap-t">${STEPS[0].t}</b><p class="cv-cap-d">${STEPS[0].d}</p></div>
      <button type="button" class="cv-pp" aria-label="Pause the video" title="Pause">
        <svg class="cv-i-pause" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
        <svg class="cv-i-play" viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg></button>
    </div>
    <div class="cv-tl" role="tablist" aria-label="Video chapters">
      ${STEPS.map((s,i)=>`<button type="button" class="cv-seg" role="tab" data-i="${i}" aria-label="${i+1}. ${s.t}" title="${s.t}"><span class="cv-seg-bar"><i></i></span><span class="cv-seg-l">${label[i]}</span></button>`).join('')}
    </div>
  </div>`;
  };

  /* ---------- player ---------- */
  function countUp(el, startAt){
    const to = parseFloat(el.dataset.count), dec = +(el.dataset.dec||0);
    const delay = (+el.dataset.delay||0) * 1000, dur = (+el.dataset.dur||1.2) * 1000;
    const fmt = v => dec ? v.toFixed(dec) : Math.round(v).toLocaleString('en-US');
    el.textContent = fmt(0);
    const tick = now => {
      if(el._run !== startAt) return;                       // a newer run took over
      const t = Math.min(1, Math.max(0, (now - startAt - delay) / dur));
      el.textContent = fmt(to * (1 - Math.pow(1 - t, 3)));
      if(t < 1) requestAnimationFrame(tick);
    };
    el._run = startAt; requestAnimationFrame(tick);
  }

  function initConceptVideo(){
    const root = document.querySelector('.cv:not([data-ready])'); if(!root) return;
    root.dataset.ready = '1';
    const scenes = [...root.querySelectorAll('.cv-sc')], segs = [...root.querySelectorAll('.cv-seg')];
    const capN = root.querySelector('.cv-cap-n'), capT = root.querySelector('.cv-cap-t'), capD = root.querySelector('.cv-cap-d');
    const cap = root.querySelector('.cv-cap-txt'), count = root.querySelector('.cv-count'), pp = root.querySelector('.cv-pp');
    const still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    let cur = -1;

    const show = i => {
      cur = (i + STEPS.length) % STEPS.length;
      root.dataset.step = cur;
      // re-adding .on restarts every CSS animation inside the scene (it was display:none)
      scenes.forEach(s => s.classList.remove('on'));
      segs.forEach((s, j) => { s.classList.remove('on'); s.classList.toggle('done', j < cur); s.setAttribute('aria-selected', String(j === cur)); });
      void root.offsetWidth;
      scenes[cur].classList.add('on'); segs[cur].classList.add('on');
      root.classList.remove('swap'); void root.offsetWidth; root.classList.add('swap');
      capN.textContent = 'Step ' + (cur + 1); capT.textContent = STEPS[cur].t; capD.textContent = STEPS[cur].d;
      count.textContent = (cur + 1) + ' / ' + STEPS.length;
      const t0 = performance.now();
      scenes[cur].querySelectorAll('[data-count]').forEach(el => still
        ? (el.textContent = (+el.dataset.dec ? (+el.dataset.count).toFixed(+el.dataset.dec) : (+el.dataset.count).toLocaleString('en-US')))
        : countUp(el, t0));
    };
    const setPaused = p => {
      root.classList.toggle('paused', p);
      pp.setAttribute('aria-label', (p ? 'Play' : 'Pause') + ' the video'); pp.title = p ? 'Play' : 'Pause';
    };

    // the active chapter's bar filling up is the clock: when it ends, go to the next scene
    segs.forEach(s => {
      s.querySelector('.cv-seg-bar i').addEventListener('animationend', () => { if(s.classList.contains('on')) show(cur + 1); });
      s.onclick = () => show(+s.dataset.i);
    });
    pp.onclick = () => setPaused(!root.classList.contains('paused'));
    if(still) setPaused(true);
    show(0);
    cap.addEventListener('animationend', () => root.classList.remove('swap'));
  }
  window.initConceptVideo = initConceptVideo;
})();
