/*
 * CortexOne client.
 *
 * The security-relevant rule in this file: text that came from a user or from
 * the model is never concatenated into an HTML string unescaped. User messages
 * go in via textContent. Assistant replies go through renderMarkdown(), which
 * escapes first and only then introduces a fixed set of tags. The old build did
 * `chatBox.innerHTML += '<span>' + userMessage + '</span>'`, which let any
 * message containing markup execute script in the page.
 */
(function () {
  'use strict';

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var CSRF = csrfMeta ? csrfMeta.getAttribute('content') : '';

  var layout = document.querySelector('.layout');
  var thread = document.getElementById('thread');
  var form = document.getElementById('composer-form');
  var input = document.getElementById('composer-input');
  var sendBtn = document.getElementById('send-btn');
  var errorBox = document.getElementById('composer-error');
  var listEl = document.getElementById('conversation-list');

  /* ---------- safe markdown ---------- */

  var ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (ch) { return ESCAPES[ch]; });
  }

  // Operates on already-escaped text, so the only markup in the result is the
  // fixed tags introduced here.
  function renderInline(escaped) {
    return escaped
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, function (match, label, url) {
        // Only absolute http(s) links become anchors; javascript: and friends
        // stay inert literal text.
        if (!/^https?:\/\//i.test(url)) { return match; }
        return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
      });
  }

  function renderProse(chunk) {
    var lines = chunk.split('\n');
    var html = '';
    var para = [];
    var listTag = null;

    function flushPara() {
      if (!para.length) { return; }
      html += '<p>' + renderInline(escapeHtml(para.join('\n'))).replace(/\n/g, '<br>') + '</p>';
      para = [];
    }

    function flushList() {
      if (listTag) { html += '</' + listTag + '>'; listTag = null; }
    }

    function openList(tag) {
      if (listTag !== tag) { flushList(); html += '<' + tag + '>'; listTag = tag; }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var heading = /^(#{1,6})\s+(.*)$/.exec(line);
      var bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
      var numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);

      if (!line.trim()) {
        flushPara(); flushList();
      } else if (heading) {
        flushPara(); flushList();
        var level = Math.min(heading[1].length + 2, 6);
        html += '<h' + level + '>' + renderInline(escapeHtml(heading[2])) + '</h' + level + '>';
      } else if (bullet) {
        flushPara(); openList('ul');
        html += '<li>' + renderInline(escapeHtml(bullet[1])) + '</li>';
      } else if (numbered) {
        flushPara(); openList('ol');
        html += '<li>' + renderInline(escapeHtml(numbered[1])) + '</li>';
      } else {
        flushList(); para.push(line);
      }
    }

    flushPara(); flushList();
    return html;
  }

  function renderMarkdown(raw) {
    var segments = String(raw).split('```');
    var html = '';
    for (var i = 0; i < segments.length; i++) {
      if (i % 2 === 1) {
        var seg = segments[i];
        var nl = seg.indexOf('\n');
        var body = nl === -1 ? seg : seg.slice(nl + 1);
        html += '<pre><code>' + escapeHtml(body.replace(/\n$/, '')) + '</code></pre>';
      } else {
        html += renderProse(segments[i]);
      }
    }
    return html;
  }

  /* ---------- DOM helpers ---------- */

  function conversationId() {
    return layout.getAttribute('data-conversation-id') || '';
  }

  function setConversationId(id) {
    layout.setAttribute('data-conversation-id', id);
  }

  function clearWelcome() {
    var welcome = thread.querySelector('.welcome');
    if (welcome) { welcome.remove(); }
  }

  function formatTime(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return ''; }
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
    });
  }

  function addMessage(role, content) {
    clearWelcome();

    var article = document.createElement('article');
    article.className = 'msg msg-' + role;

    var roleEl = document.createElement('div');
    roleEl.className = 'msg-role';
    roleEl.textContent = role === 'user' ? 'You' : 'CortexOne';

    var body = document.createElement('div');
    body.className = 'msg-body';
    if (role === 'user') {
      body.textContent = content;          // never parsed as markup
    } else {
      body.innerHTML = renderMarkdown(content);
    }

    var time = document.createElement('time');
    time.className = 'msg-time';
    var now = new Date();
    time.dateTime = now.toISOString();
    time.textContent = formatTime(now.toISOString());

    article.appendChild(roleEl);
    article.appendChild(body);
    article.appendChild(time);
    thread.appendChild(article);
    scrollToBottom();
    return body;
  }

  function scrollToBottom() {
    thread.scrollTop = thread.scrollHeight;
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = '';
  }

  function setBusy(busy) {
    sendBtn.disabled = busy;
    input.disabled = busy;
    sendBtn.textContent = busy ? 'Sending…' : 'Send';
  }

  /* ---------- sidebar ---------- */

  function upsertConversation(id, title) {
    var existing = listEl.querySelector('.conv[data-id="' + id + '"]');
    if (existing) {
      if (title) { existing.querySelector('.conv-link').textContent = title; }
      return;
    }

    var hint = listEl.querySelector('.empty-hint');
    if (hint) { hint.remove(); }

    var wrap = document.createElement('div');
    wrap.className = 'conv is-active';
    wrap.setAttribute('data-id', id);

    var link = document.createElement('a');
    link.className = 'conv-link';
    link.href = '/chat/' + encodeURIComponent(id);
    link.textContent = title || 'New chat';

    var actions = document.createElement('div');
    actions.className = 'conv-actions';
    [['rename', 'Rename', ''], ['delete', 'Delete', ' danger']].forEach(function (spec) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'icon-btn' + spec[2];
      btn.setAttribute('data-action', spec[0]);
      btn.textContent = spec[1];
      actions.appendChild(btn);
    });

    wrap.appendChild(link);
    wrap.appendChild(actions);
    listEl.insertBefore(wrap, listEl.firstChild);
  }

  function apiFetch(url, options) {
    var opts = options || {};
    opts.headers = Object.assign(
      { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
      opts.headers || {}
    );
    return fetch(url, opts);
  }

  if (listEl) {
    listEl.addEventListener('click', function (event) {
      var btn = event.target.closest('button[data-action]');
      if (!btn) { return; }
      event.preventDefault();

      var row = btn.closest('.conv');
      var id = row.getAttribute('data-id');
      var linkEl = row.querySelector('.conv-link');

      if (btn.getAttribute('data-action') === 'rename') {
        var next = window.prompt('Rename conversation', linkEl.textContent.trim());
        if (!next || !next.trim()) { return; }
        apiFetch('/api/conversations/' + encodeURIComponent(id), {
          method: 'PATCH',
          body: JSON.stringify({ title: next.trim() })
        }).then(function (res) {
          if (res.ok) { linkEl.textContent = next.trim(); }
          else { showError('Could not rename that conversation.'); }
        });
      } else {
        if (!window.confirm('Delete this conversation and all of its messages?')) { return; }
        apiFetch('/api/conversations/' + encodeURIComponent(id), { method: 'DELETE' })
          .then(function (res) {
            if (!res.ok) { showError('Could not delete that conversation.'); return; }
            row.remove();
            if (id === conversationId()) { window.location.href = '/chat'; }
          });
      }
    });
  }

  /* ---------- streaming ---------- */

  function streamReply(message, bodyEl) {
    var raw = '';
    var pending = false;

    function paint() {
      pending = false;
      bodyEl.innerHTML = renderMarkdown(raw);
      scrollToBottom();
    }

    function schedulePaint() {
      // Coalesce repaints so a fast stream doesn't re-render per token.
      // requestAnimationFrame is suspended entirely while a tab is hidden, so
      // fall back to a timer there — otherwise a backgrounded chat would show
      // nothing until the response finished.
      if (pending) { return; }
      pending = true;
      if (document.hidden) { window.setTimeout(paint, 100); }
      else { window.requestAnimationFrame(paint); }
    }

    return apiFetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        message: message,
        conversation_id: conversationId() || null
      })
    }).then(function (res) {
      if (!res.ok || !res.body) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          throw new Error(data.error || 'The request failed. Please try again.');
        });
      }

      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      function handleEvent(payload) {
        if (payload.type === 'start') {
          if (!conversationId()) {
            setConversationId(payload.conversation_id);
            upsertConversation(payload.conversation_id, null);
            window.history.replaceState({}, '', '/chat/' + payload.conversation_id);
          }
        } else if (payload.type === 'delta') {
          raw += payload.text;
          schedulePaint();
        } else if (payload.type === 'error') {
          showError(payload.message);
        } else if (payload.type === 'done') {
          if (payload.title) { upsertConversation(payload.conversation_id, payload.title); }
          paint();
        }
      }

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) { paint(); return; }

          buffer += decoder.decode(result.value, { stream: true });
          var frames = buffer.split('\n\n');
          buffer = frames.pop();

          frames.forEach(function (frame) {
            var line = frame.trim();
            if (line.indexOf('data:') !== 0) { return; }
            var json = line.slice(5).trim();
            if (!json) { return; }
            try { handleEvent(JSON.parse(json)); }
            catch (err) { /* ignore a partial or malformed frame */ }
          });

          return pump();
        });
      }

      return pump();
    });
  }

  /* ---------- composer ---------- */

  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 220) + 'px';
  }

  if (form) {
    input.addEventListener('input', autoGrow);

    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var message = input.value.trim();
      if (!message) { return; }

      clearError();
      setBusy(true);
      addMessage('user', message);
      input.value = '';
      autoGrow();

      var bodyEl = addMessage('assistant', '');
      bodyEl.classList.add('is-streaming');

      streamReply(message, bodyEl)
        .catch(function (err) { showError(err.message); })
        .then(function () {
          bodyEl.classList.remove('is-streaming');
          setBusy(false);
          input.focus();
        });
    });
  }

  /* ---------- initial render ---------- */

  // Server-rendered history arrives as plain text (Jinja-escaped). Upgrade it to
  // markdown here so it matches live messages, reading from textContent so no
  // untrusted markup is ever parsed.
  document.querySelectorAll('[data-markdown]').forEach(function (el) {
    var article = el.closest('.msg');
    if (article && article.classList.contains('msg-user')) { return; }
    el.innerHTML = renderMarkdown(el.textContent);
  });

  document.querySelectorAll('[data-timestamp]').forEach(function (el) {
    el.textContent = formatTime(el.getAttribute('data-timestamp'));
  });

  if (thread) { scrollToBottom(); }
  if (input) { autoGrow(); }
})();
