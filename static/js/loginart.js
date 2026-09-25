/* ============================================================
   Login page illustration, built from the app's own screens
   (no image file): floating cards for the content calendar,
   publishing status, analytics, the AI caption writer and the
   connected platforms. Everything is sized in em against the
   stage width, so it scales cleanly and stays sharp.
   ============================================================ */
(function(){
  const P = (k, s) => (typeof pi === 'function' ? pi(k, s) : '');
  const I = (k, s) => (typeof ic === 'function' ? ic(k, s) : '');

  // calendar: 4 weeks (7 → 30 Sep) with a few scheduled posts
  const POSTS = { 21:['instagram','Reel'], 22:['facebook','Offer'], 23:['youtube','Vlog'], 25:['linkedin','Hiring'],
                  26:['tiktok','Trend'], 28:['twitter','Thread'], 30:['pinterest','Ideas'] };
  const calendar = () => {
    let cells = '';
    for (let d = 21; d <= 34; d++) {
      const n = d > 30 ? d - 30 : d, out = d > 30, p = !out && POSTS[n];
      cells += `<div class="ls-day${out ? ' out' : ''}${n === 25 && !out ? ' today' : ''}">
        <span class="ls-dn">${n}</span>${p ? `<span class="ls-pill ls-${p[0]}" title="${p[1]}">${P(p[0], 9)}<i></i></span>` : ''}</div>`;
    }
    return cells;
  };
  const bars = [38, 52, 44, 60, 56, 72, 64, 82, 76, 96]
    .map((h, i) => `<i style="height:${h}%;animation-delay:${.08 * i}s"></i>`).join('');
  const status = () => [['instagram', 'Published', 'ok'], ['youtube', 'Published', 'ok'],
                  ['linkedin', 'Published', 'ok'], ['tiktok', 'Scheduled · 6:00 PM', 'wait']]
    .map(([k, t, c]) => `<div class="ls-srow">${P(k, 14)}<b>${platLabelSafe(k)}</b><span class="ls-chip ${c}">${c === 'ok' ? I('check', 10) : I('clock', 10)} ${t}</span></div>`).join('');
  const platLabelSafe = k => (typeof platLabel === 'function' ? platLabel(k) : k);

  window.loginScene = () => `
  <div class="ls-stage">
    <div class="ls-card ls-conn ls-f1">
      <div class="ls-glyphs">${['instagram','facebook','youtube','twitter','linkedin','threads','tiktok','pinterest']
        .map(k => `<span>${P(k, 13)}</span>`).join('')}</div>
      <b>8 platforms connected</b>
    </div>

    <div class="ls-card ls-cal ls-f2">
      <div class="ls-cal-h">
        <span class="ls-ic">${I('calendar', 13)}</span><b>Content calendar</b>
        <span class="ls-sp"></span><span class="ls-btn">${I('plus', 10)} New post</span>
      </div>
      <div class="ls-wk">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(w => `<span>${w}</span>`).join('')}</div>
      <div class="ls-grid">${calendar()}</div>
    </div>

    <div class="ls-card ls-pub ls-f3">
      <div class="ls-eye">${I('send', 11)} Publishing status</div>
      <div class="ls-pt"><b>Summer launch reel</b><span class="ls-chip ok">Published</span></div>
      ${status()}
      <div class="ls-prog"><i></i></div>
    </div>

    <div class="ls-card ls-ana ls-f4">
      <div class="ls-eye">${I('bars', 11)} Total reach</div>
      <div class="ls-big">128.4K <span>${I('arrowUp', 10)} 24%</span></div>
      <div class="ls-bars">${bars}</div>
      <small>vs previous 30 days</small>
    </div>

    <div class="ls-card ls-ai ls-f5">
      <div class="ls-ai-h"><span class="ls-spark">${I('sparkles', 13)}</span><b>AI caption</b><span class="ls-chip ai">Generated</span></div>
      <p>Watch the legend weave pure magic with every touch ✨ Drop your favourite memory in the comments 👇</p>
      <div class="ls-tags"><span>#Football</span><span>#Skills</span><span>#Reels</span><span>#GOAT</span></div>
    </div>
  </div>`;
})();
