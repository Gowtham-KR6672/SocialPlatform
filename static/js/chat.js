/* ============================================================
   Chat window — floating Messenger-style panel for a conversation
   (used for video discussions, e.g. "Chat updates" on Processing cards).
   Backend: /api/chat/*  — polls for new messages while open.
   ============================================================ */
const ChatWin = { cid: null, timer: null, lastId: 0, node: null };

function closeChatWindow(){
  if(ChatWin.timer) clearInterval(ChatWin.timer);
  if(ChatWin.node) ChatWin.node.remove();
  ChatWin.cid = null; ChatWin.timer = null; ChatWin.node = null; ChatWin.lastId = 0;
  // refresh unread badges on the board
  if(App.page==='input' && typeof loadProduction==='function' && $('#prodBoard')) loadProduction();
}
window.closeChatWindow = closeChatWindow;

function chatFmtText(t){
  return esc(t||'').replace(/@([A-Za-z0-9_.\-]+)/g, '<span class="chat-at">@$1</span>');
}

function chatMsgHtml(m){
  const me = App.user && m.author_id===App.user.id;
  const canDel = me || (App.user && ['admin','superadmin'].includes(App.user.role));
  const files = (m.files||[]).map(u=>{
    const isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(u);
    return isImg ? `<a href="${esc(u)}" target="_blank"><img class="att-img" src="${esc(u)}" style="max-width:100%;border-radius:8px;margin-top:4px"></a>`
                 : `<a class="att-file" href="${esc(u)}" target="_blank" download>${ic('clip',12)} ${esc(u.split('/').pop())}</a>`;
  }).join('');
  return `<div class="mw-msg ${me?'me':''}" data-mid="${m.id}">
      <div class="mw-bubble">
        ${me?'':`<div class="mw-auth">${esc(m.author)}</div>`}
        ${m.text?`<div class="mw-text">${chatFmtText(m.text)}</div>`:''}
        ${files}
        <div class="mw-time">${fmtTime(m.created_at)}${canDel?` · <span class="mw-del" data-del="${m.id}">delete</span>`:''}</div>
      </div></div>`;
}

async function loadChatMessages(force){
  if(!ChatWin.cid || !ChatWin.node) return;
  let d; try{ d = await api('/api/chat/conversations/'+ChatWin.cid+'/messages'); }
  catch(e){ toast(e.message,'warn'); closeChatWindow(); return; }
  const msgs = d.messages||[];
  const last = msgs.length ? msgs[msgs.length-1].id : 0;
  if(!force && last===ChatWin.lastId) return;       // nothing new
  ChatWin.lastId = last;
  const title = $('.msgr-win-title', ChatWin.node);
  if(title && d.conversation) title.textContent = d.conversation.title;
  const box = $('.msgr-msgs', ChatWin.node);
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  box.innerHTML = msgs.length ? msgs.map(chatMsgHtml).join('')
    : `<div class="empty" style="padding:20px 6px;text-align:center">No updates yet — post the first progress update.</div>`;
  box.querySelectorAll('[data-del]').forEach(x=>x.onclick=async ()=>{
    try{ await api('/api/chat/messages/'+x.dataset.del,{method:'DELETE'}); loadChatMessages(true); }
    catch(e){ toast(e.message,'warn'); }
  });
  if(atBottom || force) box.scrollTop = box.scrollHeight;
}

/* Open (or focus) the chat window for a conversation id */
function openChatWindow(cid){
  if(!cid) return;
  if(ChatWin.cid===cid && ChatWin.node){
    ChatWin.node.classList.remove('flash'); void ChatWin.node.offsetWidth; ChatWin.node.classList.add('flash');
    return;
  }
  if(ChatWin.node) closeChatWindow();
  const w = el(`<div class="msgr-window chat-win" style="right:22px">
      <div class="msgr-win-head">
        <div class="msgr-win-title">Chat</div>
        <button class="msgr-win-x" title="Close" aria-label="Close">${ic('x',16)}</button>
      </div>
      <div class="msgr-msgs"><div class="loading">Loading…</div></div>
      <div class="mw-attp"></div>
      <div class="msgr-inbar">
        <label class="att-btn" title="Attach files / screenshots" style="cursor:pointer">${ic('clip',16)}
          <input type="file" multiple style="display:none" class="mw-files"></label>
        <div style="flex:1;position:relative">
          <input class="f mw-in" placeholder="Type an update… use @ to tag" autocomplete="off" style="width:100%">
          <div class="mention-pop hidden mw-ment" style="bottom:100%;top:auto"></div>
        </div>
        <button class="btn sm mw-send">Send</button>
      </div>
    </div>`);
  document.body.appendChild(w);
  ChatWin.cid = cid; ChatWin.node = w; ChatWin.lastId = -1;
  $('.msgr-win-x', w).onclick = closeChatWindow;

  const inp = $('.mw-in', w), files = $('.mw-files', w), attp = $('.mw-attp', w);
  const refreshAtt = ()=>{ attp.innerHTML = [...(files.files||[])].map(f=>`<span class="att-file">${ic('clip',12)} ${esc(f.name)}</span>`).join(''); };
  files.onchange = refreshAtt;
  // @-mention autocomplete needs the user list — fetch it once if not loaded yet
  (async ()=>{
    if(!App._presence){ try{ App._presence = await api('/api/presence'); }catch(e){} }
    if(typeof setupMention==='function') setupMention(inp, $('.mw-ment', w));
  })();
  const sendBtn = $('.mw-send', w);
  const send = async ()=>{
    const text = inp.value.trim(); const hasFiles = files.files && files.files.length;
    if(!text && !hasFiles) return;
    sendBtn.disabled = true;
    try{
      if(hasFiles){
        const fd = new FormData(); fd.append('text', text);
        for(const f of files.files) fd.append('files', f);
        await api('/api/chat/conversations/'+cid+'/messages',{method:'POST', body:fd});
      }else{
        await api('/api/chat/conversations/'+cid+'/messages',{method:'POST', body:{text}});
      }
      inp.value=''; files.value=''; refreshAtt();
      await loadChatMessages(true);
    }catch(e){ toast(e.message,'warn'); }
    sendBtn.disabled = false; inp.focus();
  };
  sendBtn.onclick = send;
  inp.addEventListener('keydown', e=>{
    const pop = $('.mw-ment', w);
    if(e.key==='Enter' && !(pop && pop.classList.contains('mention-open'))){ e.preventDefault(); send(); }
  });

  loadChatMessages(true);
  ChatWin.timer = setInterval(()=>{
    if(!document.body.contains(w)){ clearInterval(ChatWin.timer); return; }
    loadChatMessages(false);
  }, 4000);
  setTimeout(()=>inp.focus(), 60);
}
window.openChatWindow = openChatWindow;

/* Open the discussion chat for a video (creates it on first use) */
async function openVideoChat(videoId){
  try{ const r = await api('/api/chat/video/'+videoId); openChatWindow(r.id); }
  catch(e){ toast(e.message,'warn'); }
}
window.openVideoChat = openVideoChat;
