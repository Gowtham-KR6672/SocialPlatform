/* ============================================================
   Loan Reminders (V38)
   Customers, groups, loans with payment schedules, automatic
   due-date reminders and one-off messages by SMS, WhatsApp and
   email. Switched on per workspace by the SuperAdmin.
   ============================================================ */
const LR = {tab:'overview', meta:null};
const LR_TABS = [['overview','Overview','gauge'],['customers','Customers','users'],['groups','Groups','layers'],
                 ['send','Send message','send'],['rules','Reminder rules','clock'],['log','Message log','list']];
const LR_CH = {sms:'SMS', whatsapp:'WhatsApp', email:'Email'};
const LR_CH_IC = {sms:'phone', whatsapp:'message', email:'mail'};
const lrMoney = v => '$' + Number(v||0).toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2});
const lrDate = s => { if(!s) return ''; const d = new Date(String(s).slice(0,10)+'T12:00:00');
  return isNaN(d) ? s : d.toLocaleDateString('en-US',{month:'short', day:'numeric', year:'numeric'}); };
const lrDays = s => { const d = new Date(String(s).slice(0,10)+'T12:00:00'), t = new Date(); t.setHours(12,0,0,0);
  return Math.round((d - t) / 86400000); };
const lrDueChip = s => { if(!s) return '<span class="muted">—</span>'; const n = lrDays(s);
  const cls = n < 0 ? 'danger' : n <= 3 ? 'gold' : 'draft';
  const when = n < 0 ? `${-n}d overdue` : n === 0 ? 'today' : `in ${n}d`;
  return `<span class="chip ${cls}">${esc(lrDate(s))} · ${when}</span>`; };

async function lrMeta(force){
  if(!LR.meta || force){ LR.meta = await api('/api/loans/meta'); }
  return LR.meta;
}

/* On phones the tab strip scrolls sideways: keep where it was and bring the chosen tab into view */
function lrKeepTabVisible(strip, prevLeft){
  if(!strip) return;
  if(prevLeft) strip.scrollLeft = prevLeft;
  const on = strip.querySelector('.lr-tab.on'); if(!on) return;
  const l = on.offsetLeft - strip.offsetLeft, r = l + on.offsetWidth;
  if(l < strip.scrollLeft + 8 || r > strip.scrollLeft + strip.clientWidth - 8)
    strip.scrollTo({left: Math.max(0, l - (strip.clientWidth - on.offsetWidth) / 2), behavior: prevLeft ? 'smooth' : 'auto'});
}
async function lrShowBody(){
  try{ await lrMeta(); }catch(e){ const b = $('#lrBody'); if(b) b.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const body = $('#lrBody'); if(!body) return;
  ({overview:lrOverview, customers:lrCustomers, groups:lrGroups, send:lrSend, rules:lrRules, log:lrLog}[LR.tab]||lrOverview)(body);
}
async function renderLoans(){
  const c = $('#pageContent'); if(!c) return;
  const oldStrip = c.querySelector('.lr-tabs'), prevLeft = oldStrip ? oldStrip.scrollLeft : 0;
  c.innerHTML = `<div class="page-head"><h2>Loan Reminders</h2><div class="spacer"></div>
      <button class="btn ghost" id="lrAddCust">${ic('plus',15)} Customer</button>
      <button class="btn" id="lrQuickSend">${ic('send',15)} Send message</button></div>
    <div class="lr-tabs" role="tablist">${LR_TABS.map(([k,l,i])=>
      `<button role="tab" class="lr-tab ${LR.tab===k?'on':''}" aria-selected="${LR.tab===k}" data-lrtab="${k}">${ic(i,14)} ${l}</button>`).join('')}</div>
    <div id="lrBody"><div class="loading">Loading…</div></div>`;
  const strip = c.querySelector('.lr-tabs');
  // switching tabs only swaps the content below, so the strip stays where the user left it
  const select = k=>{
    LR.tab = k;
    strip.querySelectorAll('[data-lrtab]').forEach(t=>{ const on = t.dataset.lrtab===k;
      t.classList.toggle('on', on); t.setAttribute('aria-selected', String(on)); });
    lrKeepTabVisible(strip, strip.scrollLeft);
    $('#lrBody').innerHTML = '<div class="loading">Loading…</div>';
    lrShowBody();
  };
  strip.querySelectorAll('[data-lrtab]').forEach(b=>b.onclick=()=>select(b.dataset.lrtab));
  $('#lrAddCust').onclick = ()=>lrCustomerModal(null);
  $('#lrQuickSend').onclick = ()=>select('send');
  lrKeepTabVisible(strip, prevLeft);
  lrShowBody();
}
window.renderLoans = renderLoans;

/* ---------- Overview ---------- */
async function lrOverview(box){
  let d; try{ d = await api('/api/loans/overview'); }catch(e){ box.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const ch = LR.meta.channels;
  const chChip = k => ch[k] && ch[k].provider ? `<span class="chip completed">${ic('check',11)} ${LR_CH[k]}</span>`
                                              : `<span class="chip draft">${LR_CH[k]} not set up</span>`;
  box.innerHTML = `
    <div class="tiles">
      <div class="tile"><div class="n">${d.customers}</div><div class="l">Customers</div></div>
      <div class="tile processing"><div class="n">${d.active_loans}</div><div class="l">Active loans</div></div>
      <div class="tile completed"><div class="n">${d.due_week}</div><div class="l">Due in 7 days</div></div>
      <div class="tile red"><div class="n">${d.overdue}</div><div class="l">Overdue · ${lrMoney(d.overdue_amount)}</div></div>
      <div class="tile"><div class="n">${d.sent_30d}</div><div class="l">Sent (30 days)${d.failed_30d?` · <b class="red-t">${d.failed_30d} failed</b>`:''}</div></div>
    </div>
    <div class="card glass lr-status">
      <div>${d.reminders_on
          ? `${ic('check',16)} <b>Automatic reminders are on.</b> <span class="muted">They go out at the time set in Reminder rules.</span>`
          : `${ic('alert',16)} <b>Automatic reminders are off.</b> <span class="muted">Turn them on and choose the days in Reminder rules.</span>`}</div>
      <div class="lr-chips">${['sms','whatsapp','email'].map(chChip).join('')}
        ${LR.meta.can_manage?`<button class="link-btn" id="lrGoSetup">${ic('gear',13)} Messaging channels</button>`:''}
        ${LR.meta.can_manage?`<button class="link-btn" id="lrGoRules">${ic('clock',13)} Reminder rules</button>`:''}</div>
    </div>
    <div class="card glass"><div class="sc-title">${ic('calendar',16)} <b>Overdue and due in the next 7 days</b></div>
      ${d.upcoming.length ? `<div class="rep-table-wrap"><table class="rep-table lr-table"><thead><tr>
        <th>Due</th><th>Customer</th><th>Loan</th><th>Payment</th><th>Amount</th><th></th></tr></thead><tbody>
        ${d.upcoming.map(u=>`<tr><td>${lrDueChip(u.due_date)}</td>
          <td><button class="link-btn" data-cust="${u.customer_id}">${esc(u.name)}</button></td>
          <td>${esc(u.loan_ref||'—')}</td><td>#${u.seq}</td><td><b>${lrMoney(u.amount)}</b></td>
          <td class="r"><button class="btn ghost sm" data-paid="${u.id}">${ic('check',13)} Mark paid</button></td></tr>`).join('')}
        </tbody></table></div>` : `<div class="empty-state sm">${ic('check',26)}<p class="sub">Nothing overdue or due this week.</p></div>`}
    </div>`;
  const gs = $('#lrGoSetup'); if(gs) gs.onclick = ()=>{ App.page='setup'; renderDashboard(); };
  const gr = $('#lrGoRules'); if(gr) gr.onclick = ()=>{ LR.tab='rules'; renderLoans(); };
  box.querySelectorAll('[data-cust]').forEach(b=>b.onclick=()=>lrCustomerView(+b.dataset.cust));
  box.querySelectorAll('[data-paid]').forEach(b=>b.onclick=()=>lrMarkPaid(+b.dataset.paid, ()=>lrOverview(box)));
}

function lrMarkPaid(iid, after){
  confirmBox('Mark this payment as paid?', 'No more reminders are sent for it. You can undo this from the customer\'s loan.',
    async ()=>{ try{ await api('/api/loans/installments/'+iid,{method:'PATCH', body:{status:'paid'}});
      toast('Payment marked as paid','good'); after && after(); }catch(e){ toast(e.message,'warn'); } }, 'Mark paid');
}

/* ---------- Customers ---------- */
async function lrCustomers(box){
  let groups = []; try{ groups = (await api('/api/loans/groups')).groups; }catch(e){}
  box.innerHTML = `<div class="lr-toolbar">
      <div class="lr-search">${ic('search',15)}<input class="f" id="lrQ" placeholder="Search name, phone or email" value="${esc(LR.q||'')}"></div>
      <select class="f" id="lrG"><option value="">All groups</option>${groups.map(g=>
        `<option value="${g.id}" ${String(LR.g||'')===String(g.id)?'selected':''}>${esc(g.name)} (${g.count})</option>`).join('')}</select>
      <div class="spacer"></div>
      <button class="btn ghost sm" id="lrImport">${ic('upload',14)} Import CSV</button>
      <button class="btn sm" id="lrNew">${ic('plus',14)} Add customer</button></div>
    <div id="lrCustList"><div class="loading">Loading…</div></div>`;
  $('#lrNew').onclick = ()=>lrCustomerModal(null);
  $('#lrImport').onclick = lrImportModal;
  let t; $('#lrQ').oninput = e=>{ clearTimeout(t); t = setTimeout(()=>{ LR.q = e.target.value; load(); }, 250); };
  $('#lrG').onchange = e=>{ LR.g = e.target.value; load(); };
  async function load(){
    const list = $('#lrCustList'); if(!list) return;
    let d; try{ d = await api(`/api/loans/customers?q=${encodeURIComponent(LR.q||'')}&group=${encodeURIComponent(LR.g||'')}`); }
    catch(e){ list.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    if(!d.customers.length){
      list.innerHTML = `<div class="empty-state">${ic('users',34)}<h3>${LR.q||LR.g?'No matching customers':'No customers yet'}</h3>
        <p class="sub">Add customers one by one, or import a CSV file with their details and loans.</p></div>`; return;
    }
    list.innerHTML = `<div class="rep-table-wrap"><table class="rep-table lr-table"><thead><tr>
      <th>Customer</th><th>Mobile</th><th>Email</th><th>Groups</th><th>Next payment</th><th></th></tr></thead><tbody>
      ${d.customers.map(c=>`<tr>
        <td><button class="link-btn strong" data-cust="${c.id}">${esc(c.name)}</button>
          ${c.opt_out.length?`<span class="chip draft" title="Opted out of ${esc(c.opt_out.map(x=>LR_CH[x]).join(', '))}">opted out</span>`:''}</td>
        <td>${esc(c.phone||'—')}</td><td>${esc(c.email||'—')}</td>
        <td>${c.groups.map(g=>`<span class="lr-gchip">${esc(g.name)}</span>`).join('')||'<span class="muted">—</span>'}</td>
        <td>${c.open?lrDueChip(c.next_due):'<span class="muted">No open loans</span>'}</td>
        <td class="r"><button class="btn ghost sm" data-cust="${c.id}">${ic('edit',13)} Open</button></td></tr>`).join('')}
      </tbody></table></div><div class="hint">${d.customers.length} customer(s)</div>`;
    list.querySelectorAll('[data-cust]').forEach(b=>b.onclick=()=>lrCustomerView(+b.dataset.cust));
  }
  load();
}

async function lrCustomerModal(cust, after){
  let groups = []; try{ groups = (await api('/api/loans/groups')).groups; }catch(e){}
  const has = id => cust && cust.groups.some(g=>g.id===id);
  const m = el(`<div class="modal" style="max-width:520px">
    <div class="modal-head"><h3>${ic('users',18)} ${cust?'Edit customer':'Add customer'}</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <label class="f" for="lc-name">Full name</label><input class="f" id="lc-name" value="${esc(cust?cust.name:'')}" placeholder="e.g. Ann Lee">
      <div class="cred-grid">
        <div><label class="f" for="lc-phone">Mobile (SMS)</label><input class="f" id="lc-phone" value="${esc(cust?cust.phone:'')}" placeholder="(415) 555-0134"></div>
        <div><label class="f" for="lc-wa">WhatsApp <span class="muted">(if different)</span></label><input class="f" id="lc-wa" value="${esc(cust?cust.whatsapp:'')}" placeholder="Same as mobile"></div>
      </div>
      <label class="f" for="lc-mail">Email</label><input class="f" id="lc-mail" type="email" value="${esc(cust?cust.email:'')}" placeholder="ann@example.com">
      <div class="hint">US numbers can be typed any way; numbers outside the US need a + and country code.</div>
      <label class="f">Groups</label>
      <div class="lr-checks">${groups.length?groups.map(g=>`<label class="lr-check"><input type="checkbox" value="${g.id}" data-g ${has(g.id)?'checked':''}> ${esc(g.name)}</label>`).join('')
        :'<span class="muted">No groups yet — create them in the Groups tab.</span>'}</div>
      <label class="f">Don't send this customer</label>
      <div class="lr-checks">${['sms','whatsapp','email'].map(k=>`<label class="lr-check"><input type="checkbox" value="${k}" data-oo ${cust&&cust.opt_out.includes(k)?'checked':''}> ${LR_CH[k]}</label>`).join('')}</div>
      <div class="hint">Tick a channel if the customer asked not to be contacted that way (for example they replied STOP).</div>
      <label class="f" for="lc-notes">Notes</label><textarea class="f" id="lc-notes" rows="2">${esc(cust?cust.notes:'')}</textarea>
      <div class="err" id="lc-err"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="lc-save">${ic('save',15)} ${cust?'Save':'Add customer'}</button></div></div>`);
  openModal(m);
  setTimeout(()=>$('#lc-name',m).focus(), 40);
  $('#lc-save',m).onclick = async ()=>{
    const body = {name:$('#lc-name',m).value, phone:$('#lc-phone',m).value, whatsapp:$('#lc-wa',m).value,
      email:$('#lc-mail',m).value, notes:$('#lc-notes',m).value,
      group_ids:[...m.querySelectorAll('[data-g]:checked')].map(x=>+x.value),
      opt_out:[...m.querySelectorAll('[data-oo]:checked')].map(x=>x.value)};
    try{
      if(cust){ await api('/api/loans/customers/'+cust.id,{method:'PATCH', body}); closeModal(); toast('Customer saved','good'); after ? after() : renderLoans(); }
      else{ const r = await api('/api/loans/customers',{method:'POST', body}); closeModal(); toast('Customer added','good');
            lrCustomerView(r.id, true); }
    }catch(e){ $('#lc-err',m).textContent = e.message; }
  };
}

async function lrCustomerView(cid, offerLoan){
  let d; try{ d = await api('/api/loans/customers/'+cid); }catch(e){ toast(e.message,'warn'); return; }
  const c = d.customer;
  const loanHTML = l => `<div class="lr-loan ${l.status==='closed'?'closed':''}">
      <div class="lr-loan-h"><b>${esc(l.loan_ref||'Loan')}</b> <span class="muted">${esc(l.plan_label)}</span>
        <span class="chip ${l.status==='closed'?'completed':'processing'}">${l.status==='closed'?'Paid off':'Active'}</span>
        <span class="spacer"></span><span class="lr-bal">Balance <b>${lrMoney(l.balance)}</b> · ${l.paid}/${l.installments.length} paid</span>
        <button class="icon-btn sm" data-dloan="${l.id}" title="Delete loan">${ic('trash',14)}</button></div>
      <div class="rep-table-wrap"><table class="rep-table lr-table sm"><thead><tr><th>#</th><th>Due</th><th>Amount</th><th>Status</th><th></th></tr></thead><tbody>
      ${l.installments.map(i=>`<tr class="${i.status==='paid'?'paid':''}"><td>${i.seq}</td>
        <td>${i.status==='paid'?esc(lrDate(i.due_date)):lrDueChip(i.due_date)}</td>
        <td>${lrMoney(i.amount)}${i.kind==='interest'?' <span class="muted">interest</span>':i.kind==='final'?' <span class="muted">final</span>':''}</td>
        <td>${i.status==='paid'?`<span class="chip completed">${ic('check',11)} Paid${i.paid_at?' '+esc(lrDate(i.paid_at)):''}</span>`:'<span class="chip draft">Due</span>'}</td>
        <td class="r"><button class="btn ghost sm" data-inst="${i.id}" data-to="${i.status==='paid'?'due':'paid'}">${i.status==='paid'?'Undo':ic('check',13)+' Paid'}</button></td></tr>`).join('')}
      </tbody></table></div>${l.notes?`<div class="hint">${esc(l.notes)}</div>`:''}</div>`;
  const m = el(`<div class="modal" style="max-width:780px">
    <div class="modal-head"><h3>${ic('users',18)} ${esc(c.name)}</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <div class="lr-contact">
        ${c.phone?`<span>${ic('phone',14)} ${esc(c.phone)}</span>`:''}
        ${c.whatsapp?`<span>${ic('message',14)} ${esc(c.whatsapp)}</span>`:''}
        ${c.email?`<span>${ic('mail',14)} ${esc(c.email)}</span>`:''}
        ${c.groups.map(g=>`<span class="lr-gchip">${esc(g.name)}</span>`).join('')}
        ${c.opt_out.length?`<span class="chip draft">No ${esc(c.opt_out.map(x=>LR_CH[x]).join(' / '))}</span>`:''}
      </div>
      ${c.notes?`<p class="sub">${esc(c.notes)}</p>`:''}
      <div class="sc-title lr-sect" style="margin-top:14px">${ic('card',16)} <b>Loans</b><span class="spacer"></span>
        <button class="btn sm" id="lv-addloan">${ic('plus',14)} Add loan</button></div>
      ${d.loans.length?d.loans.map(loanHTML).join(''):`<div class="empty-state sm"><p class="sub">No loans yet. Add one to start due-date reminders.</p></div>`}
      <details class="lr-hist" ${d.messages.length?'':'hidden'}><summary>${ic('list',14)} Messages sent (${d.messages.length})</summary>
        ${d.messages.map(x=>`<div class="lr-msg"><span class="chip ${x.status==='sent'?'completed':x.status==='failed'?'danger':'draft'}">${esc(x.status)}</span>
          ${ic(LR_CH_IC[x.channel]||'send',13)} <span class="muted">${esc(fmtTime(String(x.created_at).slice(0,19)))}</span>
          <div>${esc(x.body)}</div>${x.error?`<div class="pf-err">${esc(x.error)}</div>`:''}</div>`).join('')}</details>
    </div>
    <div class="modal-foot"><button class="btn danger ghost" id="lv-del">${ic('trash',14)} Delete customer</button>
      <div class="spacer"></div><button class="btn ghost" id="lv-edit">${ic('edit',14)} Edit details</button>
      <button class="btn" id="lv-msg">${ic('send',14)} Message</button></div></div>`);
  openModal(m);
  const reload = ()=>{ closeModal(); lrCustomerView(cid); };
  $('#lv-addloan',m).onclick = ()=>{ closeModal(); lrLoanModal(c, ()=>lrCustomerView(cid)); };
  $('#lv-edit',m).onclick = ()=>{ closeModal(); lrCustomerModal(c, ()=>lrCustomerView(cid)); };
  $('#lv-msg',m).onclick = ()=>{ closeModal(); LR.tab='send'; LR.preCustomers=[c.id]; renderLoans(); };
  $('#lv-del',m).onclick = ()=>confirmBox(`Delete ${c.name}?`, 'Their loans, payment schedule and reminders are removed. Sent-message history stays in the log.',
    async ()=>{ try{ await api('/api/loans/customers/'+cid,{method:'DELETE'}); closeModal(); toast('Customer deleted','good'); renderLoans(); }
               catch(e){ toast(e.message,'warn'); } }, 'Delete');
  m.querySelectorAll('[data-inst]').forEach(b=>b.onclick=async ()=>{
    try{ await api('/api/loans/installments/'+b.dataset.inst,{method:'PATCH', body:{status:b.dataset.to}}); reload(); }
    catch(e){ toast(e.message,'warn'); } });
  m.querySelectorAll('[data-dloan]').forEach(b=>b.onclick=()=>confirmBox('Delete this loan?', 'Its payment schedule is removed and no more reminders are sent for it.',
    async ()=>{ try{ await api('/api/loans/loans/'+b.dataset.dloan,{method:'DELETE'}); reload(); }catch(e){ toast(e.message,'warn'); } }, 'Delete'));
  if(offerLoan && !d.loans.length){ setTimeout(()=>{ closeModal(); lrLoanModal(c, ()=>lrCustomerView(cid)); }, 60); }
}

/* ---------- Add loan (any payment plan) ---------- */
function lrLoanModal(cust, after){
  const plans = LR.meta.plans;
  const today = new Date(); today.setDate(today.getDate()+30);
  const iso = d => d.toISOString().slice(0,10);
  const m = el(`<div class="modal" style="max-width:620px">
    <div class="modal-head"><h3>${ic('card',18)} New loan for ${esc(cust.name)}</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <div class="cred-grid">
        <div><label class="f" for="ln-plan">How is it paid?</label>
          <select class="f" id="ln-plan">${plans.map(([k,l])=>`<option value="${k}">${esc(l)}</option>`).join('')}</select></div>
        <div><label class="f" for="ln-ref">Loan number <span class="muted">(optional)</span></label><input class="f" id="ln-ref" placeholder="e.g. L-1042"></div>
      </div>
      <div id="ln-fields"></div>
      <label class="f" for="ln-notes">Notes <span class="muted">(optional)</span></label><input class="f" id="ln-notes">
      <div class="err" id="ln-err"></div>
      <div id="ln-prev"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn ghost" id="ln-preview">${ic('eye',15)} Preview schedule</button>
      <button class="btn" id="ln-save">${ic('save',15)} Create loan</button></div></div>`);
  openModal(m);
  const F = (id,label,ph,type='text',val='') => `<div><label class="f" for="${id}">${label}</label><input class="f" id="${id}" type="${type}" placeholder="${ph}" value="${val}"></div>`;
  const custom = [{due_date:iso(today), amount:''}];
  const draw = ()=>{
    const p = $('#ln-plan',m).value, box = $('#ln-fields',m);
    if(p==='custom'){
      box.innerHTML = `<label class="f">Payments</label><div id="ln-rows">${custom.map((r,i)=>`<div class="lr-crow">
          <input class="f" type="date" data-cd="${i}" value="${r.due_date}"><input class="f" data-ca="${i}" placeholder="Amount ($)" value="${r.amount}">
          <button class="icon-btn sm" data-cx="${i}" title="Remove">${ic('x',14)}</button></div>`).join('')}</div>
        <button class="btn ghost sm" id="ln-addrow">${ic('plus',13)} Add payment</button>`;
      box.querySelectorAll('[data-cd]').forEach(x=>x.onchange=()=>custom[x.dataset.cd].due_date=x.value);
      box.querySelectorAll('[data-ca]').forEach(x=>x.oninput=()=>custom[x.dataset.ca].amount=x.value);
      box.querySelectorAll('[data-cx]').forEach(x=>x.onclick=()=>{ if(custom.length>1){ custom.splice(+x.dataset.cx,1); draw(); } });
      $('#ln-addrow',m).onclick = ()=>{ const last = custom[custom.length-1]; const d = new Date((last.due_date||iso(today))+'T12:00:00');
        d.setMonth(d.getMonth()+1); custom.push({due_date:iso(d), amount:last.amount}); draw(); };
      return;
    }
    if(p==='one_time'){
      box.innerHTML = `<div class="cred-grid">${F('ln-amount','Amount due ($)','1,000.00')}${F('ln-first','Due date','','date',iso(today))}</div>`; return;
    }
    const unit = p==='weekly'?'weeks':p==='biweekly'?'payments (every 2 weeks)':'months';
    box.innerHTML = `<div class="cred-grid">
        ${F('ln-principal','Loan amount / principal ($)','10,000.00')}
        ${F('ln-rate','Annual interest rate (%)','12','number')}
        ${F('ln-count', p==='interest_only'?'Number of months':'Number of '+unit, '12','number')}
        ${F('ln-first','First due date','','date',iso(today))}
        ${p==='interest_only'?'':F('ln-amount','Payment amount ($) — leave blank to calculate','')}
      </div><div class="hint">${p==='interest_only'
        ? 'Each month the customer pays interest only (principal × rate ÷ 12); the last payment adds the principal.'
        : 'Leave the payment amount blank and it\'s calculated from the principal, rate and number of payments.'}</div>`;
  };
  draw();
  $('#ln-plan',m).onchange = ()=>{ draw(); $('#ln-prev',m).innerHTML=''; };
  const body = ()=>{ const v = id=>{ const x=$('#'+id,m); return x?x.value:''; };
    return {customer_id:cust.id, plan:$('#ln-plan',m).value, loan_ref:v('ln-ref'), notes:v('ln-notes'),
      principal:v('ln-principal'), annual_rate:v('ln-rate'), count:v('ln-count'), first_due:v('ln-first'),
      amount:v('ln-amount'), custom: custom.filter(r=>r.due_date && r.amount!=='')}; };
  $('#ln-preview',m).onclick = async ()=>{
    $('#ln-err',m).textContent='';
    try{ const r = await api('/api/loans/schedule-preview',{method:'POST', body:body()});
      $('#ln-prev',m).innerHTML = `<div class="lr-prev"><b>${r.schedule.length} payment(s) · total ${lrMoney(r.total)}</b>
        <div class="rep-table-wrap"><table class="rep-table lr-table sm"><tbody>${r.schedule.slice(0,60).map(s=>
          `<tr><td>#${s.seq}</td><td>${esc(lrDate(s.due_date))}</td><td>${lrMoney(s.amount)}</td><td class="muted">${s.kind==='payment'?'':esc(s.kind)}</td></tr>`).join('')}
        </tbody></table></div></div>`;
    }catch(e){ $('#ln-err',m).textContent = e.message; }
  };
  $('#ln-save',m).onclick = async ()=>{
    $('#ln-err',m).textContent='';
    try{ await api('/api/loans/loans',{method:'POST', body:body()}); closeModal(); toast('Loan created — reminders will follow its schedule','good'); after && after(); }
    catch(e){ $('#ln-err',m).textContent = e.message; }
  };
}

/* ---------- CSV import ---------- */
function lrImportModal(){
  const sample = 'name,phone,email,group,plan,amount,principal,rate,payments,first_due,loan_ref\n'+
                 'Ann Lee,(415) 555-0134,ann@example.com,Gold,monthly,250,,,12,2026-11-05,L-1001\n'+
                 'Bob Ray,212-555-0199,,Gold;New,interest_only,,5000,9,6,2026-11-01,L-1002';
  const m = el(`<div class="modal" style="max-width:640px">
    <div class="modal-head"><h3>${ic('upload',18)} Import customers</h3><button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body">
      <p class="sub" style="margin-top:0">Upload a CSV (Excel → Save as CSV). Columns, in any order: <b>name</b>, phone, whatsapp, email,
        group (several separated by <code>;</code>), notes. To add a loan on the same row also fill <b>plan</b>
        (monthly, biweekly, weekly, interest_only, one_time), amount or principal + rate, payments and <b>first_due</b> (YYYY-MM-DD).</p>
      <input type="file" id="im-file" accept=".csv,text/csv" class="f">
      <details class="smtp"><summary>${ic('file',14)} Example</summary><pre class="lr-pre">${esc(sample)}</pre>
        <button class="btn ghost sm" id="im-dl">${ic('download',13)} Download example</button></details>
      <div class="err" id="im-err"></div><div id="im-res"></div>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Close</button>
      <button class="btn" id="im-go">${ic('upload',15)} Import</button></div></div>`);
  openModal(m);
  $('#im-dl',m).onclick = ()=>{ const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([sample],{type:'text/csv'})); a.download = 'customers-example.csv'; a.click(); };
  $('#im-go',m).onclick = async ()=>{
    const f = $('#im-file',m).files[0]; $('#im-err',m).textContent='';
    if(!f){ $('#im-err',m).textContent = 'Choose a CSV file.'; return; }
    try{ const r = await api('/api/loans/customers/import',{method:'POST', body:{csv: await f.text()}});
      $('#im-res',m).innerHTML = `<div class="ok-msg">${ic('check',14)} Added ${r.added} customer(s) and ${r.loans} loan(s).</div>
        ${r.errors.length?`<div class="pf-err" style="margin-top:8px">${r.errors.map(esc).join('<br>')}</div>`:''}`;
      toast(`Imported ${r.added} customer(s)`,'good'); if(LR.tab==='customers') lrCustomers($('#lrBody'));
    }catch(e){ $('#im-err',m).textContent = e.message; }
  };
}

/* ---------- Groups ---------- */
async function lrGroups(box){
  let d; try{ d = await api('/api/loans/groups'); }catch(e){ box.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  box.innerHTML = `<div class="lr-toolbar"><p class="sub" style="margin:0">Put customers into groups (for example by branch, loan type or risk)
      and send a message to a whole group at once.</p><div class="spacer"></div>
      <button class="btn sm" id="lrNewG">${ic('plus',14)} New group</button></div>
    ${d.groups.length?`<div class="lr-ggrid">${d.groups.map(g=>`<div class="card glass lr-gcard">
        <div class="lr-gname">${ic('layers',16)} <b>${esc(g.name)}</b></div>
        <div class="lr-gcount">${g.count} customer(s)</div>
        <div class="row" style="gap:6px;flex-wrap:wrap">
          <button class="btn ghost sm" data-gm="${g.id}">${ic('users',13)} Members</button>
          <button class="btn ghost sm" data-gs="${g.id}">${ic('send',13)} Message</button>
          <button class="btn ghost sm" data-gr="${g.id}">${ic('edit',13)}</button>
          <button class="btn ghost sm" data-gd="${g.id}">${ic('trash',13)}</button></div></div>`).join('')}</div>`
      :`<div class="empty-state">${ic('layers',34)}<h3>No groups yet</h3><p class="sub">Create a group, then tick the customers who belong in it.</p></div>`}`;
  const byId = Object.fromEntries(d.groups.map(g=>[String(g.id), g]));
  $('#lrNewG').onclick = ()=>lrGroupName(null, ()=>lrGroups(box));
  box.querySelectorAll('[data-gr]').forEach(b=>b.onclick=()=>lrGroupName(byId[b.dataset.gr], ()=>lrGroups(box)));
  box.querySelectorAll('[data-gm]').forEach(b=>b.onclick=()=>lrGroupMembers(byId[b.dataset.gm], ()=>lrGroups(box)));
  box.querySelectorAll('[data-gs]').forEach(b=>b.onclick=()=>{ LR.tab='send'; LR.preGroups=[+b.dataset.gs]; renderLoans(); });
  box.querySelectorAll('[data-gd]').forEach(b=>b.onclick=()=>confirmBox(`Delete the group "${byId[b.dataset.gd].name}"?`,
    'Only the group is removed — its customers stay.', async ()=>{ try{ await api('/api/loans/groups/'+b.dataset.gd,{method:'DELETE'}); lrGroups(box); }
      catch(e){ toast(e.message,'warn'); } }, 'Delete'));
}

function lrGroupName(g, after){
  const m = el(`<div class="modal" style="max-width:400px"><div class="modal-head"><h3>${g?'Rename group':'New group'}</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><label class="f" for="gn">Group name</label><input class="f" id="gn" value="${esc(g?g.name:'')}" placeholder="e.g. Downtown branch">
      <div class="err" id="gn-err"></div></div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="gn-go">${ic('save',15)} Save</button></div></div>`);
  openModal(m); setTimeout(()=>$('#gn',m).focus(),40);
  $('#gn-go',m).onclick = async ()=>{
    try{ if(g) await api('/api/loans/groups/'+g.id,{method:'PATCH', body:{name:$('#gn',m).value}});
         else{ const r = await api('/api/loans/groups',{method:'POST', body:{name:$('#gn',m).value}}); closeModal();
               lrGroupMembers({id:r.id, name:$('#gn',m).value}, after); return; }
         closeModal(); after && after(); }
    catch(e){ $('#gn-err',m).textContent = e.message; }
  };
}

async function lrGroupMembers(g, after){
  let all, mine;
  try{ all = (await api('/api/loans/customers')).customers; mine = new Set((await api('/api/loans/customers?group='+g.id)).customers.map(c=>c.id)); }
  catch(e){ toast(e.message,'warn'); return; }
  const m = el(`<div class="modal" style="max-width:520px"><div class="modal-head"><h3>${ic('users',18)} ${esc(g.name)} — members</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><div class="lr-search">${ic('search',15)}<input class="f" id="gm-q" placeholder="Filter customers"></div>
      <div class="lr-pick" id="gm-list">${all.map(c=>`<label class="lr-check row-check" data-n="${esc(c.name.toLowerCase())}">
        <input type="checkbox" value="${c.id}" ${mine.has(c.id)?'checked':''}> <b>${esc(c.name)}</b> <span class="muted">${esc(c.phone||c.email||'')}</span></label>`).join('')
        ||'<span class="muted">Add customers first.</span>'}</div></div>
    <div class="modal-foot"><span class="muted" id="gm-n"></span><div class="spacer"></div><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="gm-save">${ic('save',15)} Save members</button></div></div>`);
  openModal(m);
  const count = ()=>{ $('#gm-n',m).textContent = m.querySelectorAll('#gm-list input:checked').length + ' selected'; };
  count(); m.querySelectorAll('#gm-list input').forEach(x=>x.onchange=count);
  $('#gm-q',m).oninput = e=>{ const q = e.target.value.toLowerCase();
    m.querySelectorAll('#gm-list [data-n]').forEach(r=>r.style.display = r.dataset.n.includes(q)?'':'none'); };
  $('#gm-save',m).onclick = async ()=>{
    const now = new Set([...m.querySelectorAll('#gm-list input:checked')].map(x=>+x.value));
    const add = [...now].filter(x=>!mine.has(x)), remove = [...mine].filter(x=>!now.has(x));
    try{ await api('/api/loans/groups/'+g.id,{method:'PATCH', body:{add, remove}}); closeModal(); toast('Group saved','good'); after && after(); }
    catch(e){ toast(e.message,'warn'); }
  };
}

/* ---------- Send message ---------- */
async function lrSend(box){
  let groups = [], custs = [], camps = [];
  try{ [groups, custs, camps] = await Promise.all([api('/api/loans/groups').then(r=>r.groups),
        api('/api/loans/customers').then(r=>r.customers), api('/api/loans/campaigns').then(r=>r.campaigns)]); }
  catch(e){ box.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const preG = new Set(LR.preGroups||[]), preC = new Set(LR.preCustomers||[]); LR.preGroups = LR.preCustomers = null;
  const ch = LR.meta.channels, ph = LR.meta.placeholders;
  const mode = preC.size ? 'pick' : preG.size ? 'groups' : 'all';
  box.innerHTML = `<div class="lr-send">
    <div class="card glass">
      <div class="sc-title">${ic('users',16)} <b>Who</b></div>
      <div class="seg" id="ls-mode">${[['all','All customers'],['groups','Groups'],['pick','Choose customers']].map(([k,l])=>
        `<button class="${mode===k?'on':''}" data-mode="${k}">${l}</button>`).join('')}</div>
      <div id="ls-groups" class="lr-checks" style="margin-top:10px">${groups.map(g=>`<label class="lr-check"><input type="checkbox" value="${g.id}" data-sg ${preG.has(g.id)?'checked':''}> ${esc(g.name)} <span class="muted">(${g.count})</span></label>`).join('')||'<span class="muted">No groups yet.</span>'}</div>
      <div id="ls-pick" style="margin-top:10px"><div class="lr-search">${ic('search',15)}<input class="f" id="ls-q" placeholder="Filter customers"></div>
        <div class="lr-pick">${custs.map(c=>`<label class="lr-check row-check" data-n="${esc(c.name.toLowerCase())}"><input type="checkbox" value="${c.id}" data-sc ${preC.has(c.id)?'checked':''}>
          <b>${esc(c.name)}</b> <span class="muted">${esc(c.phone||c.email||'')}</span></label>`).join('')||'<span class="muted">No customers yet.</span>'}</div></div>
      <div class="hint" id="ls-count"></div>
      <div class="sc-title" style="margin-top:16px">${ic('send',16)} <b>How</b></div>
      <div class="lr-checks">${['sms','whatsapp','email'].map(k=>{ const ok = ch[k] && ch[k].provider;
        return `<label class="lr-check ${ok?'':'off'}" title="${ok?'':LR_CH[k]+' isn\'t set up — add it in Setup → Messaging channels'}">
          <input type="checkbox" value="${k}" data-ch ${ok&&k==='sms'?'checked':''} ${ok?'':'disabled'}> ${ic(LR_CH_IC[k],14)} ${LR_CH[k]}</label>`; }).join('')}</div>
      <div id="ls-subj-w"><label class="f" for="ls-subj">Email subject</label><input class="f" id="ls-subj" placeholder="A message from {company}"></div>
      <label class="f" for="ls-body">Message</label>
      <textarea class="f" id="ls-body" rows="5" placeholder="Hi {first_name}, …"></textarea>
      <div class="lr-ph">${ph.map(([k,l])=>`<button class="lr-phb" data-ph="${k}" title="${esc(l)}">{${k}}</button>`).join('')}</div>
      <div class="hint" id="ls-len"></div>
      <div class="sc-title" style="margin-top:14px">${ic('clock',16)} <b>When</b></div>
      <div class="lr-checks"><label class="lr-check"><input type="radio" name="ls-when" value="now" checked> Send now</label>
        <label class="lr-check"><input type="radio" name="ls-when" value="later"> Schedule</label>
        <input class="f" type="datetime-local" id="ls-at" style="max-width:240px;display:none"></div>
      <div class="err" id="ls-err"></div>
      <button class="btn grad-btn" id="ls-go">${ic('send',15)} Send</button>
      <div class="hint">Loan placeholders such as {amount} and {due_date} use each customer's next unpaid payment.
        Business-initiated WhatsApp messages only reach customers who messaged you in the last 24 hours — use reminders with an approved template for the rest.</div>
    </div>
    <div class="card glass"><div class="sc-title">${ic('list',16)} <b>Recent messages</b></div>
      ${camps.length?camps.slice(0,15).map(x=>`<div class="lr-camp">
        <div><b>${esc(x.name)}</b> <span class="chip ${x.status==='done'?'completed':x.status==='scheduled'?'gold':x.status==='cancelled'?'draft':'processing'}">${esc(x.status)}</span></div>
        <div class="muted">${x.channels.map(k=>LR_CH[k]).join(', ')} · ${x.status==='scheduled'?'for '+esc(fmtTime(new Date(x.send_at+'Z').toISOString().slice(0,19))):esc(fmtTime(String(x.created_at).slice(0,19)))}
          · ${x.sent} sent${x.failed?`, <span class="red-t">${x.failed} failed</span>`:''} / ${x.total}</div>
        ${x.status==='scheduled'?`<button class="link-btn" data-cancel="${x.id}">${ic('x',12)} Cancel</button>`:''}</div>`).join('')
        :'<p class="sub">Nothing sent yet.</p>'}</div>
  </div>`;
  const setMode = k=>{ box.querySelectorAll('#ls-mode button').forEach(b=>b.classList.toggle('on', b.dataset.mode===k));
    $('#ls-groups').style.display = k==='groups'?'':'none'; $('#ls-pick').style.display = k==='pick'?'':'none'; count(); };
  const count = ()=>{ const k = box.querySelector('#ls-mode .on').dataset.mode;
    const n = k==='all' ? custs.length : k==='groups' ? groups.filter(g=>box.querySelector(`[data-sg][value="${g.id}"]:checked`)).reduce((s,g)=>s+g.count,0)
            : box.querySelectorAll('[data-sc]:checked').length;
    $('#ls-count').textContent = k==='groups' ? `About ${n} customer(s) (people in two groups get it once)` : `${n} customer(s)`; };
  box.querySelectorAll('#ls-mode button').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
  box.querySelectorAll('[data-sg],[data-sc]').forEach(x=>x.onchange=count);
  setMode(mode);
  $('#ls-q').oninput = e=>{ const q = e.target.value.toLowerCase(); box.querySelectorAll('#ls-pick [data-n]').forEach(r=>r.style.display = r.dataset.n.includes(q)?'':'none'); };
  const subjW = ()=>{ $('#ls-subj-w').style.display = box.querySelector('[data-ch][value="email"]:checked')?'':'none'; };
  box.querySelectorAll('[data-ch]').forEach(x=>x.onchange=subjW); subjW();
  const ta = $('#ls-body');
  const len = ()=>{ const n = ta.value.length; $('#ls-len').textContent = n ? `${n} characters · about ${Math.max(1,Math.ceil(n/153))} SMS segment(s) per customer (placeholders change the length)` : ''; };
  ta.oninput = len;
  box.querySelectorAll('[data-ph]').forEach(b=>b.onclick=()=>{ const t = '{'+b.dataset.ph+'}', s = ta.selectionStart||ta.value.length;
    ta.value = ta.value.slice(0,s)+t+ta.value.slice(ta.selectionEnd||s); ta.focus(); ta.selectionStart = ta.selectionEnd = s+t.length; len(); });
  box.querySelectorAll('[name=ls-when]').forEach(r=>r.onchange=()=>{ $('#ls-at').style.display = r.value==='later'&&r.checked?'':'none'; });
  box.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=async ()=>{ try{ await api('/api/loans/campaigns/'+b.dataset.cancel,{method:'DELETE'}); lrSend(box); }catch(e){ toast(e.message,'warn'); } });
  $('#ls-go').onclick = async ()=>{
    $('#ls-err').textContent = '';
    const k = box.querySelector('#ls-mode .on').dataset.mode;
    const later = box.querySelector('[name=ls-when][value=later]').checked;
    const at = $('#ls-at').value;
    if(later && !at){ $('#ls-err').textContent = 'Pick the date and time to send.'; return; }
    const body = {all:k==='all', group_ids:k==='groups'?[...box.querySelectorAll('[data-sg]:checked')].map(x=>+x.value):[],
      customer_ids:k==='pick'?[...box.querySelectorAll('[data-sc]:checked')].map(x=>+x.value):[],
      channels:[...box.querySelectorAll('[data-ch]:checked')].map(x=>x.value), subject:$('#ls-subj').value, body:ta.value,
      send_at: later ? new Date(at).toISOString().slice(0,19) : ''};
    try{ const r = await api('/api/loans/send',{method:'POST', body});
      toast(r.status==='scheduled' ? `Scheduled for ${r.customers} customer(s)` : `Sending to ${r.customers} customer(s)…`,'good');
      setTimeout(()=>lrSend(box), r.status==='scheduled'?100:2500);
    }catch(e){ $('#ls-err').textContent = e.message; }
  };
}

/* ---------- Reminder rules ---------- */
const LR_PRESETS = [
  {offset:-3, channels:['sms'], subject:'Payment due {due_date}', template:'Hi {first_name}, a friendly reminder from {company}: your payment of {amount} for loan {loan_ref} is due on {due_date}. Reply STOP to opt out.'},
  {offset:0, channels:['sms'], subject:'Payment due today', template:'Hi {first_name}, your payment of {amount} to {company} is due today ({due_date}). Thank you!'},
  {offset:1, channels:['sms','email'], subject:'Payment overdue', template:'Hi {first_name}, we haven\'t received your payment of {amount} that was due on {due_date}. Please pay as soon as possible or contact {company}.'},
];
async function lrRules(box){
  let st; try{ st = await api('/api/loans/settings'); }catch(e){ box.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const can = LR.meta.can_manage, ch = LR.meta.channels;
  let rules = (st.rules||[]).map(r=>Object.assign({},r));
  const whenLabel = o => o<0 ? `${-o} day(s) before` : o===0 ? 'On the due date' : `${o} day(s) after (overdue)`;
  const draw = ()=>{
    box.innerHTML = `<div class="card glass">
      <label class="cred-toggle big"><input type="checkbox" id="rr-on" ${st.enabled?'checked':''} ${can?'':'disabled'}>
        <span><b>Send automatic payment reminders</b><br><span class="muted">Each rule below runs every day for every unpaid payment on an active loan.</span></span></label>
      <div class="cred-grid" style="margin-top:10px">
        <div><label class="f" for="rr-time">Send at (local time)</label><input class="f" type="time" id="rr-time" value="${esc(st.send_time||'09:00')}" ${can?'':'disabled'}></div>
        <div><label class="f" for="rr-tz">Time zone</label><select class="f" id="rr-tz" ${can?'':'disabled'}>${LR.meta.timezones.map(([k,l])=>`<option value="${k}" ${st.timezone===k?'selected':''}>${esc(l)} (${esc(k)})</option>`).join('')}</select></div>
        <div><label class="f" for="rr-co">Company name in messages <code>{company}</code></label><input class="f" id="rr-co" value="${esc(st.company||'')}" ${can?'':'disabled'}></div>
      </div></div>
    <div class="lr-rules">${rules.map((r,i)=>`<div class="card glass lr-rule">
      <div class="lr-rule-h">
        <select class="f" data-dir="${i}" ${can?'':'disabled'}>${[['before','Before the due date'],['on','On the due date'],['after','After the due date']].map(([k,l])=>
          `<option value="${k}" ${(r.offset<0&&k==='before')||(r.offset===0&&k==='on')||(r.offset>0&&k==='after')?'selected':''}>${l}</option>`).join('')}</select>
        <input class="f lr-days" type="number" min="1" max="60" data-days="${i}" value="${Math.abs(r.offset)||1}" ${r.offset===0?'style="display:none"':''} ${can?'':'disabled'}>
        <span class="muted" data-dl="${i}" ${r.offset===0?'style="display:none"':''}>day(s)</span>
        <span class="spacer"></span>
        <div class="lr-checks">${['sms','whatsapp','email'].map(k=>`<label class="lr-check ${ch[k]&&ch[k].provider?'':'off'}"><input type="checkbox" data-rc="${i}" value="${k}" ${r.channels.includes(k)?'checked':''} ${can?'':'disabled'}> ${LR_CH[k]}</label>`).join('')}</div>
        ${can?`<button class="icon-btn sm" data-rdel="${i}" title="Remove rule">${ic('trash',14)}</button>`:''}</div>
      <input class="f" data-rs="${i}" placeholder="Email subject" value="${esc(r.subject||'')}" ${r.channels.includes('email')?'':'style="display:none"'} ${can?'':'disabled'}>
      <textarea class="f" rows="3" data-rt="${i}" ${can?'':'disabled'}>${esc(r.template||'')}</textarea>
      <div class="hint">${whenLabel(r.offset)} · placeholders: ${LR.meta.placeholders.map(([k])=>'{'+k+'}').join(' ')}</div></div>`).join('')
      || `<div class="empty-state sm"><p class="sub">No reminder rules yet. Add one, or start from a suggestion below.</p></div>`}</div>
    ${can?`<div class="row" style="gap:8px;flex-wrap:wrap;margin:10px 0">
        <button class="btn ghost sm" id="rr-add">${ic('plus',14)} Add rule</button>
        ${LR_PRESETS.map((p,i)=>`<button class="btn ghost sm" data-preset="${i}">${ic('sparkles',13)} ${whenLabel(p.offset)}</button>`).join('')}</div>
      <div class="err" id="rr-err"></div>
      <button class="btn grad-btn" id="rr-save">${ic('save',15)} Save reminder rules</button>`
      :'<div class="hint">Only the workspace admin can change reminder rules.</div>'}
    <div class="hint" style="margin-top:12px">${ic('info',13)} WhatsApp reminders use the approved template set in Setup → Messaging channels
      (WhatsApp doesn't allow free-text messages to customers who haven't messaged you in the last 24 hours). SMS to US numbers needs a
      registered A2P 10DLC campaign or a verified toll-free number with your provider.</div>`;
    if(!can) return;
    const sync = ()=>{ rules.forEach((r,i)=>{
      const dir = box.querySelector(`[data-dir="${i}"]`).value, days = Math.max(1, +box.querySelector(`[data-days="${i}"]`).value||1);
      r.offset = dir==='on' ? 0 : dir==='before' ? -days : days;
      r.channels = [...box.querySelectorAll(`[data-rc="${i}"]:checked`)].map(x=>x.value);
      r.subject = box.querySelector(`[data-rs="${i}"]`).value; r.template = box.querySelector(`[data-rt="${i}"]`).value; });
      st.enabled = $('#rr-on').checked; st.send_time = $('#rr-time').value; st.timezone = $('#rr-tz').value; st.company = $('#rr-co').value; };
    box.querySelectorAll('[data-dir]').forEach(s=>s.onchange=()=>{ sync(); draw(); });
    box.querySelectorAll('[data-rc]').forEach(s=>s.onchange=()=>{ sync(); draw(); });
    box.querySelectorAll('[data-rdel]').forEach(b=>b.onclick=()=>{ sync(); rules.splice(+b.dataset.rdel,1); draw(); });
    $('#rr-add').onclick = ()=>{ sync(); rules.push({offset:-1, channels:['sms'], subject:'', template:'Hi {first_name}, your payment of {amount} is due on {due_date}.'}); draw(); };
    box.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>{ sync(); rules.push(Object.assign({}, LR_PRESETS[+b.dataset.preset])); draw(); });
    $('#rr-save').onclick = async ()=>{
      sync(); $('#rr-err').textContent = '';
      const bad = rules.findIndex(r=>!r.channels.length || !r.template.trim());
      if(bad>=0){ $('#rr-err').textContent = `Rule ${bad+1} needs at least one channel and a message.`; return; }
      try{ st = await api('/api/loans/settings',{method:'POST', body:Object.assign({}, st, {rules})}); rules = st.rules.map(r=>Object.assign({},r));
        toast(st.enabled ? 'Saved — reminders are on' : 'Saved — reminders are off','good'); draw(); }
      catch(e){ $('#rr-err').textContent = e.message; }
    };
  };
  draw();
}

/* ---------- Message log ---------- */
async function lrLog(box){
  LR.lf = LR.lf || {status:'', channel:'', kind:''};
  box.innerHTML = `<div class="lr-toolbar">
      <select class="f" id="lf-s"><option value="">Any status</option>${['sent','failed','skipped'].map(s=>`<option ${LR.lf.status===s?'selected':''}>${s}</option>`).join('')}</select>
      <select class="f" id="lf-c"><option value="">Any channel</option>${['sms','whatsapp','email'].map(s=>`<option value="${s}" ${LR.lf.channel===s?'selected':''}>${LR_CH[s]}</option>`).join('')}</select>
      <select class="f" id="lf-k"><option value="">Reminders and messages</option><option value="auto" ${LR.lf.kind==='auto'?'selected':''}>Automatic reminders</option><option value="manual" ${LR.lf.kind==='manual'?'selected':''}>Messages I sent</option></select>
      <div class="spacer"></div><button class="btn ghost sm" id="lf-r">${ic('refresh',14)} Refresh</button></div>
    <div id="lf-list"><div class="loading">Loading…</div></div>`;
  ['s','c','k'].forEach(x=>$('#lf-'+x).onchange=()=>{ LR.lf = {status:$('#lf-s').value, channel:$('#lf-c').value, kind:$('#lf-k').value}; lrLog(box); });
  $('#lf-r').onclick = ()=>lrLog(box);
  let d; try{ d = await api(`/api/loans/messages?status=${LR.lf.status}&channel=${LR.lf.channel}&kind=${LR.lf.kind}`); }
  catch(e){ $('#lf-list').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  $('#lf-list').innerHTML = d.messages.length ? `<div class="rep-table-wrap"><table class="rep-table lr-table"><thead><tr>
      <th>When</th><th>Customer</th><th>Channel</th><th>Status</th><th>Message</th></tr></thead><tbody>
      ${d.messages.map(x=>`<tr><td class="nowrap">${esc(fmtTime(String(x.created_at).slice(0,19)))}</td>
        <td><button class="link-btn" data-cust="${x.customer_id}">${esc(x.name)}</button><div class="muted">${esc(x.to)}</div></td>
        <td>${ic(LR_CH_IC[x.channel]||'send',13)} ${LR_CH[x.channel]||esc(x.channel)}<div class="muted">${x.kind==='auto'?'Reminder':'Message'}</div></td>
        <td><span class="chip ${x.status==='sent'?'completed':x.status==='failed'?'danger':x.status==='skipped'?'draft':'processing'}">${esc(x.status)}</span></td>
        <td class="lr-body" title="${esc(x.body)}">${x.subject?`<b>${esc(x.subject)}</b> · `:''}${esc(x.body)}${x.error?`<div class="pf-err">${esc(x.error)}</div>`:''}</td></tr>`).join('')}
    </tbody></table></div>` : `<div class="empty-state">${ic('list',34)}<h3>No messages yet</h3><p class="sub">Reminders and messages you send appear here with their delivery status.</p></div>`;
  box.querySelectorAll('[data-cust]').forEach(b=>b.onclick=()=>lrCustomerView(+b.dataset.cust));
}

/* ---------- Setup → Messaging channels (workspace admin) ---------- */
async function renderLoanChannels(host){
  if(!host) return;
  let d; try{ d = await api('/api/loans/channels'); }catch(e){ host.innerHTML = ''; return; }
  const tile = k=>{ const c = d.channels[k]||{}, prov = c.provider && d.providers[k][c.provider];
    return `<div class="pf-tile ${prov?'is-live':''}">
      <div class="pt-top"><span class="pf-ic lr-ic">${ic(LR_CH_IC[k],22)}</span>
        <div class="pt-name"><b>${LR_CH[k]}</b><span class="sub">${prov?esc(prov.label):({sms:'Twilio, Telnyx, Plivo, Vonage or any HTTP API',whatsapp:'WhatsApp Cloud API or Twilio',email:'SMTP or SendGrid'})[k]}</span></div>
        <div class="pt-chips">${prov?`<span class="chip completed">${ic('check',12)} Set up</span>`:'<span class="chip draft">Not set up</span>'}</div></div>
      <div class="pt-actions">
        <button class="btn sm ${prov?'ghost':'grad-btn'}" data-lrset="${k}">${ic(prov?'edit':'plus',14)} ${prov?'Edit':'Set up'}</button>
        ${prov?`<button class="btn ghost sm" data-lrtest="${k}">${ic('send',14)} Send test</button>
        <button class="btn ghost sm" data-lrrm="${k}">${ic('x',14)} Remove</button>`:''}</div></div>`; };
  host.innerHTML = `<div class="sc-sub" style="margin:22px 0 10px">${ic('send',15)} <b>Messaging channels</b>
      <span class="muted">Used by Loan Reminders for due-date reminders and messages to your customers.</span></div>
    <div class="pf-tiles">${['sms','whatsapp','email'].map(tile).join('')}</div>`;
  host.querySelectorAll('[data-lrset]').forEach(b=>b.onclick=()=>lrChannelModal(b.dataset.lrset, d, ()=>renderLoanChannels(host)));
  host.querySelectorAll('[data-lrrm]').forEach(b=>b.onclick=()=>confirmBox(`Remove the ${LR_CH[b.dataset.lrrm]} channel?`,
    'Reminders and messages on this channel stop until you set it up again.', async ()=>{
      try{ await api('/api/loans/channels',{method:'POST', body:{channel:b.dataset.lrrm, provider:''}}); LR.meta=null; renderLoanChannels(host); }
      catch(e){ toast(e.message,'warn'); } }, 'Remove'));
  host.querySelectorAll('[data-lrtest]').forEach(b=>b.onclick=()=>lrChannelTest(b.dataset.lrtest));
}
window.renderLoanChannels = renderLoanChannels;

// most common provider first (the server's JSON comes back alphabetically sorted)
const LR_PROV_ORDER = {sms:['twilio','telnyx','plivo','vonage','custom'], whatsapp:['meta','twilio'], email:['smtp','sendgrid']};
function lrChannelModal(k, d, after){
  const cur = d.channels[k]||{}, raw = d.providers[k];
  const order = (LR_PROV_ORDER[k]||[]).filter(x=>raw[x]).concat(Object.keys(raw).filter(x=>!(LR_PROV_ORDER[k]||[]).includes(x)));
  const provs = Object.fromEntries(order.map(x=>[x, raw[x]]));
  const first = cur.provider || order[0];
  const m = el(`<div class="modal" style="max-width:560px"><div class="modal-head"><h3>${ic(LR_CH_IC[k],18)} ${LR_CH[k]} provider</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><label class="f" for="cp-p">Provider</label>
      <select class="f" id="cp-p">${Object.entries(provs).map(([pk,p])=>`<option value="${pk}" ${pk===first?'selected':''}>${esc(p.label)}</option>`).join('')}</select>
      <div id="cp-f"></div>
      <div class="hint" id="cp-hint"></div>
      <div class="err" id="cp-err"></div></div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn" id="cp-save">${ic('save',15)} Save</button></div></div>`);
  openModal(m);
  const HINT = {
    sms:{twilio:'Twilio Console → Account info shows the SID and token. US numbers must be registered for A2P 10DLC (or use a verified toll-free number).',
         telnyx:'Telnyx Portal → API Keys. Assign your number to a messaging profile with 10DLC registration.',
         plivo:'Plivo Console → Overview shows the Auth ID and token.', vonage:'Vonage API Dashboard → API key and secret.',
         custom:'Any provider with an HTTP API. The JSON body is sent as written with {to}, {from} and {message} filled in.'},
    whatsapp:{meta:'Meta for Developers → your app → WhatsApp → API Setup shows the Phone number ID. Create a permanent token with a System User in Business Settings. Reminders use the approved template; its body parameters are filled in this order.',
              twilio:'Twilio Console → Messaging → WhatsApp senders. For reminders, create an approved Content template and paste its SID; variables are filled in this order.'},
    email:{smtp:'Any mail server (Google Workspace, Microsoft 365, your host). Port 587 uses STARTTLS, 465 uses SSL.',
           sendgrid:'SendGrid → Settings → API Keys (Mail Send permission). The sender must be verified in SendGrid.'}};
  const draw = ()=>{ const p = $('#cp-p',m).value, same = p===cur.provider;
    $('#cp-f',m).innerHTML = provs[p].fields.map(([key,label,ph])=>{ const secret = key.endsWith('_secret');
      const val = same && !secret ? (cur[key]||'') : '';
      const setNote = secret && same && cur[key+'_set'] ? ' <span class="muted">(saved — leave blank to keep)</span>' : '';
      return `<label class="f" for="cpf-${key}">${esc(label)}${setNote}</label>
        <input class="f" id="cpf-${key}" data-k="${key}" ${secret?'type="password" autocomplete="new-password"':''} placeholder="${esc(ph)}" value="${esc(val)}">`; }).join('');
    $('#cp-hint',m).textContent = (HINT[k]||{})[p]||''; };
  draw(); $('#cp-p',m).onchange = draw;
  $('#cp-save',m).onclick = async ()=>{
    const fields = {}; m.querySelectorAll('[data-k]').forEach(x=>fields[x.dataset.k] = x.value);
    try{ await api('/api/loans/channels',{method:'POST', body:{channel:k, provider:$('#cp-p',m).value, fields}});
      LR.meta = null; closeModal(); toast(`${LR_CH[k]} saved — send a test to check it`,'good'); after && after(); }
    catch(e){ $('#cp-err',m).textContent = e.message; }
  };
}

function lrChannelTest(k){
  const m = el(`<div class="modal" style="max-width:420px"><div class="modal-head"><h3>${ic('send',18)} Send a test ${LR_CH[k]}</h3>
      <button class="x" onclick="closeModal()" aria-label="Close">${ic('x',18)}</button></div>
    <div class="modal-body"><label class="f" for="ct-to">${k==='email'?'Email address':'Mobile number'}</label>
      <input class="f" id="ct-to" placeholder="${k==='email'?'you@company.com':'(415) 555-0134'}">
      ${k==='whatsapp'?'<div class="hint">The number must have messaged your WhatsApp number in the last 24 hours (free-text messages only reach those).</div>':''}
      <div class="err" id="ct-err"></div><div id="ct-ok"></div></div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Close</button><button class="btn" id="ct-go">${ic('send',15)} Send test</button></div></div>`);
  openModal(m); setTimeout(()=>$('#ct-to',m).focus(),40);
  $('#ct-go',m).onclick = async ()=>{ $('#ct-err',m).textContent=''; $('#ct-ok',m).innerHTML='';
    try{ const r = await api('/api/loans/channels/test',{method:'POST', body:{channel:k, to:$('#ct-to',m).value}});
      $('#ct-ok',m).innerHTML = `<div class="ok-msg">${ic('check',14)} ${esc(r.message)}</div>`; }
    catch(e){ $('#ct-err',m).textContent = e.message; } };
}
