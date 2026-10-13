/* Project X chat client */
var chatId = null;
var $ = function(id){ return document.getElementById(id); };

function esc(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* small markdown renderer: code blocks, inline code, bold, italic, headers, lists, links */
function md(src){
  var blocks = [];
  src = src.replace(/```(\w*)\n([\s\S]*?)```/g, function(m, lang, code){
    blocks.push('<pre><code>' + esc(code.replace(/\n$/,'')) + '</code></pre>');
    return '\u0000' + (blocks.length-1) + '\u0000';
  });
  var html = esc(src);
  html = html
    .replace(/^### (.*)$/gm, '<h3>$1</h3>')
    .replace(/^## (.*)$/gm, '<h2>$1</h2>')
    .replace(/^# (.*)$/gm, '<h1>$1</h1>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  var lines = html.split('\n'), out = [], inList = false;
  lines.forEach(function(ln){
    var m = ln.match(/^\s*[-*] (.*)$/);
    if(m){ if(!inList){ out.push('<ul>'); inList = true; } out.push('<li>'+m[1]+'</li>'); }
    else { if(inList){ out.push('</ul>'); inList = false; } out.push(ln.trim() ? '<p>'+ln+'</p>' : ''); }
  });
  if(inList) out.push('</ul>');
  html = out.join('\n');
  html = html.replace(/\u0000(\d+)\u0000/g, function(m, i){ return blocks[+i]; });
  return html;
}

function addMsg(role, content, isHtml){
  var d = document.createElement('div');
  d.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  d.innerHTML = isHtml ? content : esc(content).replace(/\n/g,'<br>');
  $('messages').appendChild(d);
  $('messages').scrollTop = $('messages').scrollHeight;
  return d;
}

function loadChats(){
  fetch('/api/chats').then(function(r){ return r.json(); }).then(function(data){
    var list = $('chat-list'); list.innerHTML = '';
    data.chats.forEach(function(c){
      var item = document.createElement('div');
      item.className = 'chat-item' + (c.id === chatId ? ' active' : '');
      var t = document.createElement('span');
      t.className = 'title'; t.textContent = c.title; t.title = 'Double-click to rename';
      t.ondblclick = function(e){
        e.stopPropagation();
        var nt = prompt('Rename chat:', c.title);
        if(nt){ fetch('/api/chats/'+c.id, {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title: nt})}).then(loadChats); }
      };
      var del = document.createElement('button');
      del.className = 'del'; del.textContent = '✕'; del.title = 'Delete';
      del.onclick = function(e){
        e.stopPropagation();
        if(confirm('Delete this chat?')){
          fetch('/api/chats/'+c.id, {method:'DELETE'}).then(function(){
            if(chatId === c.id){ chatId = null; $('messages').innerHTML=''; }
            loadChats();
          });
        }
      };
      item.appendChild(t); item.appendChild(del);
      item.onclick = function(){ selectChat(c.id); $('sidebar').classList.remove('open'); };
      list.appendChild(item);
    });
  });
}

function selectChat(id){
  chatId = id;
  $('messages').innerHTML = '';
  fetch('/api/chats/'+id).then(function(r){ return r.json(); }).then(function(data){
    data.messages.forEach(function(m){
      addMsg(m.role, m.role === 'assistant' ? md(m.content) : m.content, m.role === 'assistant');
    });
    loadChats();
  });
}

function send(){
  var text = $('input').value.trim();
  if(!text) return;
  $('input').value = '';
  addMsg('user', text, false);
  var botDiv = addMsg('bot', '<span class="typing">X is thinking…</span>', true);
  var raw = '';
  fetch('/api/send', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({chat_id: chatId, message: text})
  }).then(function(resp){
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buf = '';
    function pump(){
      return reader.read().then(function(res){
        if(res.done){ finish(); return; }
        buf += decoder.decode(res.value, {stream:true});
        var parts = buf.split('\n\n');
        buf = parts.pop();
        parts.forEach(function(p){
          if(p.indexOf('data: ') === 0){
            try{
              var ev = JSON.parse(p.slice(6));
              if(ev.t){ raw += ev.t; botDiv.innerHTML = esc(raw).replace(/\n/g,'<br>'); $('messages').scrollTop = $('messages').scrollHeight; }
              if(ev.error){ botDiv.innerHTML = '<span class="err">'+esc(ev.error)+'</span>'; }
              if(ev.chat_id && !chatId){ chatId = ev.chat_id; loadChats(); }
              if(ev.done){ finish(); }
            }catch(e){}
          }
        });
        return pump();
      });
    }
    var finished = false;
    function finish(){
      if(finished) return; finished = true;
      if(raw) botDiv.innerHTML = md(raw);
      if(chatId) loadChats();
    }
    return pump();
  }).catch(function(){
    botDiv.innerHTML = '<span class="err">Connection lost — try again.</span>';
  });
}

$('send').onclick = send;
$('input').addEventListener('keydown', function(e){
  if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
});
$('input').addEventListener('input', function(){
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 140) + 'px';
});
$('new-chat').onclick = function(){
  fetch('/api/chats', {method:'POST'}).then(function(r){ return r.json(); }).then(function(d){
    selectChat(d.id);
  });
};
$('menu-btn').onclick = function(){ $('sidebar').classList.toggle('open'); };

fetch('/api/me').then(function(r){ return r.json(); }).then(function(me){
  $('persona-label').textContent = me.persona || 'X';
  $('model-label').textContent = (me.model || '').split('/').pop();
  if(!me.key_set) $('key-warning').hidden = false;
});
loadChats();
