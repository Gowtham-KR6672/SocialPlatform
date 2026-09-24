/* ============================================================
   Subscription & Billing
   - Primary Users pay a per-seat monthly plan (mock gateway:
     Razorpay / Google Pay — UI + workflow only, no live charge).
   - SuperAdmin sets the per-seat price + payout account.
   - On expiry the account becomes read-only (enforced server-side);
     when renewal is near the dashboard shows an alert style.
   ============================================================ */
async function renderBilling(){
  const c = $('#pageContent'); if(!c) return;
  c.innerHTML = `<div class="panel-head"><h2>Subscription &amp; Billing</h2>
      <p class="sub">Per-seat monthly plan. Payments are credited to the Super Admin's configured account.</p></div>
    <div id="billBody"><div class="loading">Loading…</div></div>`;
  let s, inv;
  try{ s = await api('/api/subscription'); }
  catch(e){ $('#billBody').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  try{ inv = (await api('/api/subscription/invoices')).invoices || []; }catch(e){ inv = []; }

  const statusChip = s.status==='active'
    ? `<span class="chip completed">Active</span>`
    : (s.status==='expired' ? `<span class="chip danger">Expired</span>` : `<span class="chip draft">No plan</span>`);
  const daysTxt = (s.days_left==null) ? '—'
    : (s.days_left>=0 ? `${s.days_left} day(s) left` : `expired ${-s.days_left} day(s) ago`);
  const fmt = (n)=>'₹'+Number(n||0).toLocaleString('en-IN',{maximumFractionDigits:2});

  // ---- SuperAdmin: price + payout account ----
  const superBox = s.can_manage_price ? `
    <div class="card" style="margin-bottom:14px">
      <b>Super Admin — plan settings</b>
      <p class="sub" style="margin:6px 0 10px">Set the per-seat price (applies to all Users) and the payout account that receives payments.</p>
      <div class="ocfg-grid">
        <div><label class="f">Price per seat / month (₹)</label>
          <input class="f" id="bl-price" type="number" min="0" step="1" value="${esc(s.price)}"></div>
        <div><label class="f">Payout account</label>
          <input class="f" id="bl-payout" placeholder="razorpay:acct_… or UPI id" value="${esc(s.payout_account||'')}"></div>
      </div>
      <button class="btn sm" id="bl-savePrice">Save plan settings</button>
    </div>` : '';

  // ---- Primary User: pay ----
  const seats = s.seats||1;
  const payBox = s.can_pay ? `
    <div class="card" style="margin-bottom:14px">
      <div class="row"><b>Renew / extend subscription</b><div class="spacer" style="flex:1"></div>
        <span class="chip navy">${fmt(s.price)}/seat/mo</span></div>
      <hr class="sep">
      <label class="f">Seats</label>
      <input class="f" id="bl-seats" type="number" min="1" step="1" value="${seats}" style="max-width:140px">
      <label class="f" style="margin-top:10px">Payment method</label>
      <div class="pm-grid">
        <div class="pm sel" data-method="razorpay"><span class="pm-tick">${ic('check',12)}</span>
          <div class="pm-logo" style="color:#3B5BFF">Razorpay</div><div class="sub">UPI · Cards · Net-banking</div></div>
        <div class="pm" data-method="gpay"><span class="pm-tick">${ic('check',12)}</span>
          <div class="pm-logo">Google&nbsp;Pay</div><div class="sub">Google Pay · UPI</div></div>
      </div>
      <div id="bl-total" class="sub" style="margin:6px 0 10px"></div>
      <button class="btn" id="bl-pay">Pay &amp; renew</button>
      <p class="note">Design/workflow only — no live payment gateway is wired. This records the
        payment, generates an invoice and extends your plan by one month.</p>
      <div class="err" id="bl-err"></div>
    </div>` : (s.status!=='none' ? `<div class="card" style="margin-bottom:14px"><b>Subscription managed by your primary account.</b>
        <p class="sub" style="margin:6px 0 0">Your access follows your organisation's subscription (${daysTxt}).</p></div>` : '');

  // ---- invoices ----
  const invRows = inv.length ? inv.map(i=>`
      <div class="cw-hist"><div class="cw-hist-main"><b>${esc(i.number)}</b>
        <span class="cw-meta">${esc((i.created_at||'').slice(0,10))} · ${esc((i.method||'').toUpperCase())} · ${i.seats} seat(s) → paid until ${esc(i.period_end)}</span></div>
        <div class="row"><span class="chip completed">${fmt(i.amount)}</span></div></div>`).join('')
    : `<div class="empty">No invoices yet.</div>`;

  $('#billBody').innerHTML = `
    <div class="tiles" style="margin-bottom:14px">
      <div class="tile"><div class="n">${statusChip}</div><div class="l">Status</div></div>
      <div class="tile"><div class="n">${esc(daysTxt)}</div><div class="l">${s.expiry?('Renews '+esc((s.expiry||'').slice(0,10))):'Not started'}</div></div>
      <div class="tile"><div class="n">${seats}</div><div class="l">Seats</div></div>
    </div>
    ${s.renewing_soon ? `<div class="sub-banner warn">${ic('hourglass',14)} Renewal approaching — your plan renews in ${s.days_left} day(s). Renew to avoid interruption.</div>`:''}
    ${s.status==='expired' ? `<div class="sub-banner lock">${ic('lock',14)} Subscription expired — creating, editing &amp; publishing are disabled. Viewing still works. Renew to re-enable.</div>`:''}
    ${superBox}
    ${payBox}
    <div class="card"><b>Invoices</b><hr class="sep">${invRows}</div>`;

  // price save (super)
  const sp = $('#bl-savePrice');
  if(sp) sp.onclick = async ()=>{
    try{ await api('/api/subscription/price',{method:'POST', body:{
        price: Number($('#bl-price').value||0), payout_account: $('#bl-payout').value.trim()}});
      toast('Plan settings saved','good'); renderBilling(); }
    catch(e){ toast(e.message,'warn'); }
  };

  // payment method + total + pay
  let method = 'razorpay';
  const recalc = ()=>{ const seatsN=Math.max(1,parseInt($('#bl-seats').value||'1',10));
    const sub=s.price*seatsN, gst=sub*0.18; const t=$('#bl-total');
    if(t) t.innerHTML = `Subtotal ${fmt(sub)} + GST (18%) ${fmt(gst)} = <b>${fmt(sub+gst)}</b>`; };
  if($('#bl-seats')){ $('#bl-seats').addEventListener('input', recalc); recalc(); }
  c.querySelectorAll('.pm').forEach(p=>p.onclick=()=>{
    c.querySelectorAll('.pm').forEach(x=>x.classList.remove('sel'));
    p.classList.add('sel'); method = p.dataset.method;
  });
  const payBtn = $('#bl-pay');
  if(payBtn) payBtn.onclick = async ()=>{
    payBtn.disabled=true; payBtn.textContent='Processing…';
    try{
      const seatsN = Math.max(1, parseInt($('#bl-seats').value||'1',10));
      const r = await api('/api/subscription/pay',{method:'POST', body:{method, seats:seatsN}});
      toast(`Payment recorded — invoice ${r.invoice_number}. Plan extended to ${r.period_end}.`,'good',6000);
      await refreshMe();               // pick up the new subscription state
      renderBilling();
    }catch(e){ $('#bl-err').textContent=e.message; }
    finally{ payBtn.disabled=false; payBtn.textContent='Pay & renew'; }
  };
}
window.renderBilling = renderBilling;

/* Re-fetch the current user so App.user.subscription is fresh (after paying). */
async function refreshMe(){
  try{ const d = await api('/api/me'); if(d.user){ App.user = d.user; } }catch(e){}
}
window.refreshMe = refreshMe;

/* Reflect the subscription state on every page: a read-only banner when the
   plan has lapsed, and an alert style when renewal is near. */
function applySubscriptionState(){
  const s = (App.user && App.user.subscription) || null;
  document.body.classList.remove('sub-locked','sub-warn');
  const host = $('#pageContent'); if(!host) return;
  const old = document.getElementById('subStateBanner'); if(old) old.remove();
  if(!s) return;
  let html = '';
  if(s.status==='expired'){
    document.body.classList.add('sub-locked');
    html = `<div class="sub-banner lock" id="subStateBanner">${ic('lock',14)} <b>Subscription expired.</b>
      Creating, editing, updating &amp; publishing are disabled — viewing still works.
      <button class="btn sm pale" id="subGoBilling">Renew now</button></div>`;
  }else if(s.renewing_soon){
    document.body.classList.add('sub-warn');
    html = `<div class="sub-banner warn" id="subStateBanner">${ic('hourglass',14)} <b>Renewal approaching</b> — your plan renews in
      ${s.days_left} day(s). <button class="btn sm" id="subGoBilling">Review &amp; renew</button></div>`;
  }
  if(html){
    host.insertAdjacentHTML('afterbegin', html);
    const b=document.getElementById('subGoBilling');
    if(b) b.onclick=()=>{ App.page='billing'; renderDashboard(App.readonly); };
  }
}
window.applySubscriptionState = applySubscriptionState;
