/* ============================================================
   Application Bundle — MC Tunnel Controller
   Vanilla JS, no framework dependencies.
   Works with both CSS-only and JS-driven patterns.
   ============================================================ */

/* =================================================================
   Module: CSRF Token Management
   ================================================================= */

function getCSRFToken() {
  var meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

async function refreshCSRFToken() {
  try {
    var resp = await fetch('/api/admin/csrf-token');
    if (!resp.ok) return '';
    var data = await resp.json();
    var token = data.csrf_token || '';
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) {
      meta.setAttribute('content', token);
    } else {
      var el = document.createElement('meta');
      el.name = 'csrf-token';
      el.content = token;
      document.head.appendChild(el);
    }
    return token;
  } catch (_e) {
    return '';
  }
}

/* =================================================================
   Module: JWT Auth
   ================================================================= */

function getJWT() {
  try {
    return sessionStorage.getItem('mc_jwt');
  } catch (_e) {
    return null;
  }
}

function setJWT(token) {
  try {
    sessionStorage.setItem('mc_jwt', token);
  } catch (_e) {
    // sessionStorage may be unavailable
  }
}

function clearJWT() {
  try {
    sessionStorage.removeItem('mc_jwt');
  } catch (_e) {
    // ignore
  }
}

function isAuthenticated() {
  return !!getJWT();
}

/* =================================================================
   Module: API Client
   ================================================================= */

async function apiCall(url, method, body, options) {
  if (method === undefined) method = 'GET';
  if (body === undefined) body = null;
  if (options === undefined) options = {};

  var headers = {
    'Accept': 'application/json',
  };

  // Add JWT Authorization header
  var token = getJWT();
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }

  // Add CSRF token for state-changing requests
  if (body && (method === 'POST' || method === 'PUT' || method === 'DELETE')) {
    var csrf = getCSRFToken();
    if (csrf) {
      headers['X-CSRF-Token'] = csrf;
    }
  }

  // Set Content-Type for JSON bodies
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  var fetchOptions = {
    method: method,
    headers: headers,
  };

  if (body) {
    fetchOptions.body = body instanceof FormData ? body : JSON.stringify(body);
  }

  // Merge additional options (signal, etc.)
  if (options.signal) {
    fetchOptions.signal = options.signal;
  }

  try {
    var resp = await fetch(url, fetchOptions);

    // Handle 401 — redirect to login
    if (resp.status === 401) {
      clearJWT();
      if (!window.location.pathname.startsWith('/login')) {
        var returnTo = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = '/login?next=' + returnTo;
      }
      throw new Error('Authentication required');
    }

    // Handle 403 — CSRF token might have expired, refresh and retry once
    if (resp.status === 403 && body && (method === 'POST' || method === 'PUT' || method === 'DELETE')) {
      await refreshCSRFToken();
      headers['X-CSRF-Token'] = getCSRFToken();
      fetchOptions.headers = headers;
      resp = await fetch(url, fetchOptions);
    }

    // Guard: verify content-type is JSON before parsing
    var contentType = resp.headers.get('content-type') || '';
    if (contentType.indexOf('application/json') === -1 && resp.status !== 200) {
      // Non-JSON error response: try to read as text for diagnostics
      var textSample = '';
      try {
        var rawText = await resp.text();
        textSample = rawText.substring(0, 200);
      } catch (_e2) {
        textSample = '(unable to read response body)';
      }
      console.error('[apiCall] Non-JSON response: ' + resp.status + ' ' + resp.statusText +
        ' for ' + method + ' ' + url + '. Content-Type: ' + (contentType || 'none') +
        '. Body preview: ' + textSample);
      throw new Error('Server returned non-JSON response (HTTP ' + resp.status + ') — check server logs');
    }

    var data;
    try {
      data = await resp.json();
    } catch (jsonErr) {
      // Last resort: response claimed JSON but wasn't parseable
      var fallbackText = '';
      try {
        var clone = resp.clone();
        fallbackText = await clone.text();
        fallbackText = fallbackText.substring(0, 300);
      } catch (_e3) {
        fallbackText = '(unable to read body)';
      }
      console.error('[apiCall] JSON parse failed for ' + method + ' ' + url +
        '. Status: ' + resp.status + '. Body preview: ' + fallbackText);
      throw new Error('Server returned invalid JSON (HTTP ' + resp.status + ')');
    }

    if (!resp.ok) {
      var errMsg = data.message || data.error || 'Request failed';
      throw new Error(errMsg);
    }

    return data;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw err;
    }
    if (err.message === 'Failed to fetch' || err.message === 'NetworkError') {
      throw new Error('Network error — please check your connection');
    }
    throw err;
  }
}

/* =================================================================
   Module: Toast Notifications
   ================================================================= */

function showToast(message, type) {
  if (type === undefined) type = 'success';

  var container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  var toast = document.createElement('div');
  toast.className = 'toast';
  if (type === 'error') toast.classList.add('error');
  if (type === 'warning') toast.classList.add('warning');
  toast.textContent = message;
  container.appendChild(toast);

  // Auto-remove after 3 seconds
  setTimeout(function () {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, 3000);
}

/* =================================================================
   Module: Tab Switching
   Supports both JS-driven (.tab-btn) and CSS-radio (.tab-label) patterns.
   ================================================================= */

function switchTab(tabName) {
  // Update tab labels/buttons: check .tab-btn then .tab-label
  var tabs = document.querySelectorAll('.tab-btn, .tab-label');
  for (var i = 0; i < tabs.length; i++) {
    var t = tabs[i];
    var match = false;
    if (t.getAttribute('data-tab') === tabName) match = true;
    if (t.classList.contains('tab-' + tabName)) match = true;
    if (t.getAttribute('for') === 'tab-' + tabName) match = true;
    t.classList.toggle('active', match);
  }

  // Update tab panels
  var panels = document.querySelectorAll('.tab-panel');
  for (var j = 0; j < panels.length; j++) {
    var p = panels[j];
    var match = false;
    if (p.classList.contains('tab-' + tabName)) match = true;
    if (p.id === 'tab-' + tabName || p.id === 'panel-' + tabName) match = true;
    p.classList.toggle('active', match);
  }

  // Check the corresponding radio button (CSS-only pattern)
  var radio = document.getElementById('tab-' + tabName);
  if (radio && radio.type === 'radio') {
    radio.checked = true;
  }
}

/* =================================================================
   Module: Live Poller
   ================================================================= */

function LivePoller(url, interval) {
  if (interval === undefined) interval = 10000;
  this.url = url;
  this.interval = interval;
  this._timer = null;
  this._callbacks = [];
  this._abortController = null;
}

LivePoller.prototype.start = function () {
  var self = this;

  function poll() {
    if (self._stopped) return;

    self._abortController = new AbortController();

    apiCall(self.url, 'GET', null, { signal: self._abortController.signal })
      .then(function (data) {
        for (var i = 0; i < self._callbacks.length; i++) {
          try {
            self._callbacks[i](data);
          } catch (_e) {
            // callback error — don't break the chain
          }
        }
      })
      .catch(function (err) {
        if (err.name === 'AbortError') return;
        // Silently fail on poll errors
      });

    self._timer = setTimeout(poll, self.interval);
  }

  self._stopped = false;
  poll();
};

LivePoller.prototype.stop = function () {
  this._stopped = true;
  if (this._timer) {
    clearTimeout(this._timer);
    this._timer = null;
  }
  if (this._abortController) {
    this._abortController.abort();
    this._abortController = null;
  }
};

LivePoller.prototype.onData = function (callback) {
  if (typeof callback === 'function') {
    this._callbacks.push(callback);
  }
};

/* =================================================================
   Module: Dashboard-specific logic
   ================================================================= */

function updateDashboard(data) {
  if (!data) return;

  var status = data.data || data;

  var onlinePlayers = status.onlinePlayers !== undefined ? status.onlinePlayers : '--';
  var maxPlayers = status.maxPlayers !== undefined ? status.maxPlayers : '--';
  var tps = status.tps !== undefined ? status.tps : '--';
  var uptime = formatUptime(status.uptime);
  var cpu = (status.cpu !== undefined && status.cpu !== null) ? status.cpu + '%' : '--';
  var memory = status.memory || {};
  var memPercent = memory.percent !== undefined ? Math.round(memory.percent * 10) / 10 : 0;
  var memUsed = memory.used || '--';
  var memMax = memory.max || '--';

  setHtml('.stat-card:nth-child(1) .stat-val', onlinePlayers + '<small>/' + maxPlayers + '</small>');
  setHtml('.stat-card:nth-child(2) .stat-val', String(tps));
  setHtml('.stat-card:nth-child(3) .stat-val', memPercent + '%');
  setHtml('.stat-card:nth-child(4) .stat-val', uptime);
  setHtml('.stat-card:nth-child(5) .stat-val', cpu);
  // Tunnel card (6) is updated separately by tunnel poller

  // Update memory progress bar
  var progressCard = document.querySelector('.stat-card:nth-child(3)');
  if (progressCard) {
    var bar = progressCard.querySelector('.progress-bar .fill');
    if (bar) bar.style.width = memPercent + '%';

    var label = progressCard.querySelector('.stat-lbl');
    if (label) label.textContent = '内存 (' + memUsed + '/' + memMax + ')';

    var progBar = progressCard.querySelector('.progress-bar');
    if (progBar) {
      progBar.classList.remove('warn', 'danger');
      if (memPercent >= 85) progBar.classList.add('danger');
      else if (memPercent >= 70) progBar.classList.add('warn');
    }
  }

  // Update server status pill
  var serverStatus = status.status || 'unknown';
  var statusPill = document.querySelector('.topbar-status .pill');
  if (statusPill) {
    statusPill.className = 'pill';
    if (serverStatus === 'running') {
      statusPill.classList.add('pill-success');
      statusPill.innerHTML = '● 服务器运行中';
    } else if (serverStatus === 'stopped' || serverStatus === 'stopping') {
      statusPill.classList.add('pill-danger');
      statusPill.innerHTML = '● 服务器已停止';
    } else if (serverStatus === 'starting') {
      statusPill.classList.add('pill-warning');
      statusPill.innerHTML = '● 服务器启动中';
    } else {
      statusPill.classList.add('pill-warning');
      statusPill.innerHTML = '● ' + serverStatus;
    }
  }

  // Toggle start/stop buttons based on status
  var btnStart = document.getElementById('btn-start');
  var btnStop = document.getElementById('btn-stop');
  var btnRestart = document.getElementById('btn-restart');
  if (serverStatus === 'running') {
    if (btnStart) btnStart.style.display = 'none';
    if (btnStop) btnStop.style.display = '';
    if (btnRestart) btnRestart.style.display = '';
  } else {
    if (btnStart) btnStart.style.display = '';
    if (btnStop) btnStop.style.display = 'none';
    if (btnRestart) btnRestart.style.display = 'none';
  }

  // Update nav badge
  var badge = document.querySelector('.nav-badge');
  if (badge) badge.textContent = String(onlinePlayers);
}

function updateTunnel(data) {
  if (!data || !data.data) return;
  var d = data.data;
  var activeTunnels = d.activeTunnels !== undefined ? d.activeTunnels : '--';

  // Status label for the stat card
  var tStatus;
  if (d.status === 'connected') tStatus = '已连接';
  else if (d.status === 'connecting') tStatus = '连接中…';
  else if (d.status === 'disconnected') tStatus = '未连接';
  else tStatus = (d.status || '--');

  setHtml('.stat-card:nth-child(6) .stat-val', String(activeTunnels));
  var label = document.querySelector('.stat-card:nth-child(6) .stat-lbl');
  if (label) label.textContent = '穿透隧道 · ' + tStatus;

  // Update the server info line below the table
  var serverInfo = document.getElementById('tunnel-server-info');
  if (serverInfo) {
    serverInfo.innerHTML = '穿透服务器: <code>' + escapeHtml(d.server || '--') + '</code> · 连接时长: ' + escapeHtml(d.uptime || '--');
  }

  // Dynamically populate the tunnel mappings table
  var mappings = d.mappings || [];
  var tableContainer = document.getElementById('tunnel-mappings-table');
  if (!tableContainer) return;

  if (mappings.length === 0) {
    tableContainer.innerHTML = '<div class="empty-state"><p>暂无穿透隧道配置</p></div>';
    // Still show start button when no tunnels configured
    updateFrpcButtons(d.status);
    return;
  }

  var rows = '';
  for (var i = 0; i < mappings.length; i++) {
    var m = mappings[i];
    var isActive = m.status === 'active';
    var statusClass = isActive ? 'pill-success' : 'pill-danger';
    var statusLabel = isActive ? '● 活跃' : '● 离线';
    rows += '<tr>' +
      '<td>' + escapeHtml(m.name) + '</td>' +
      '<td class="mono">' + escapeHtml(String(m.localPort)) + '</td>' +
      '<td class="mono">' + escapeHtml(String(m.remotePort)) + '</td>' +
      '<td>' + escapeHtml(m.protocol || 'TCP') + '</td>' +
      '<td><span class="pill ' + statusClass + '">' + statusLabel + '</span></td>' +
      '</tr>';
  }

  tableContainer.innerHTML = '<table class="data-table"><thead><tr><th>隧道名称</th><th>本地端口</th><th>公网端口</th><th>协议</th><th>状态</th></tr></thead><tbody>' + rows + '</tbody></table>';

  updateFrpcButtons(d.status);
}

function updateFrpcButtons(status) {
  var connected = status === 'connected';
  var btnStart = document.getElementById('btn-frp-start');
  var btnStop = document.getElementById('btn-frp-stop');
  var msg = document.getElementById('frpc-action-msg');
  if (btnStart) btnStart.style.display = connected ? 'none' : '';
  if (btnStop) btnStop.style.display = connected ? '' : 'none';
  // Show a hint when connecting
  if (msg && !connected && status === 'connecting') {
    msg.textContent = 'frpc 正在连接樱花节点…';
  } else if (msg && !connected) {
    msg.textContent = '';
  }
}

function _ensureTable(parentSelector, columns) {
  var parent = document.querySelector(parentSelector);
  if (!parent) return null;
  var table = parent.querySelector('.data-table');
  if (!table) {
    // Create table with header
    table = document.createElement('table');
    table.className = 'data-table';
    var thead = '<thead><tr>';
    for (var c = 0; c < columns.length; c++) { thead += '<th>' + columns[c] + '</th>'; }
    thead += '</tr></thead><tbody></tbody>';
    table.innerHTML = thead;
    // Clear parent content and append table
    parent.innerHTML = '';
    parent.appendChild(table);
  }
  return table.querySelector('tbody');
}

function updatePlayers(data) {
  if (!data || !data.players) return;

  var players = data.players;

  // Update online count
  var countEl = document.getElementById('online-count');
  if (countEl) countEl.textContent = String(players.length);

  // Use the player table container
  var container = document.getElementById('panel-players-table');
  if (!container) return;

  if (players.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>没有在线玩家</p></div>';
    return;
  }

  var gamemodeNames = { '0': '🏕 生存', '1': '🎨 创造', '2': '⚔ 冒险', '3': '👁 旁观' };
  var html = '<table class="data-table"><thead><tr><th>玩家名</th><th>所在世界</th><th>坐标</th><th>游戏模式</th><th>在线时长</th><th>操作</th></tr></thead><tbody>';
  // Use the in_whitelist field from the API — always accurate, no race condition
  for (var i = 0; i < players.length; i++) {
    var p = players[i];
    var name = p.name || '';
    var inWl = p.in_whitelist === true;
    var worldIcon = '';
    if (p.world === '地狱') worldIcon = '🔥 ';
    else if (p.world === '末地') worldIcon = '🌑 ';
    else if (p.world === '主世界') worldIcon = '🌍 ';
    var gm = gamemodeNames[p.gamemode] || p.gamemode || '--';

    var actions = '<button class="btn btn-success btn-xs op-btn" data-player="' + encodeAttr(name) + '" data-is-op="' + (p.is_op ? '1' : '0') + '" style="margin-right:4px;">' + (p.is_op ? '撤销OP' : '⚡OP') + '</button>' +
      '<button class="btn btn-danger btn-xs kick-btn" data-player="' + encodeAttr(name) + '">踢出</button>';
    if (!inWl) {
      actions += ' <button class="btn btn-primary btn-xs wl-add-btn" data-player="' + encodeAttr(name) + '" style="margin-left:4px;">📋+白名单</button>';
    }

    html += '<tr>' +
      '<td>' + (inWl ? '✅ ' : '🔓 ') + escapeHtml(name) + '</td>' +
      '<td>' + worldIcon + escapeHtml(p.world || '--') + '</td>' +
      '<td class="mono">' + escapeHtml(p.coords || '--') + '</td>' +
      '<td>' + gm + '</td>' +
      '<td>' + escapeHtml(p.online_time || '--') + '</td>' +
      '<td>' + actions + '</td>' +
      '</tr>';
  }
  html += '</tbody></table>';
  container.innerHTML = html;
}

function updateWhitelist(data) {
  if (!data || !data.whitelist) return;

  var entries = data.whitelist;
  var container = document.getElementById('panel-whitelist-table');
  var countEl = document.getElementById('wl-count');
  if (countEl) countEl.textContent = String(entries.length);

  // Build the global whitelisted names cache for player list cross-reference
  var nameSet = new Set();
  for (var i = 0; i < entries.length; i++) {
    nameSet.add((entries[i].name || '').toLowerCase());
  }
  window._whitelistedNames = nameSet;

  if (!container) return;

  if (entries.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>白名单为空</p><p style="font-size:10px;color:var(--muted);">使用上方的输入框添加玩家</p></div>';
    return;
  }

  var html = '<table class="data-table"><thead><tr><th>状态</th><th>玩家名</th><th>最后在线</th><th>添加日期</th><th>添加人</th><th>操作</th></tr></thead><tbody>';
  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i];
    var name = entry.name || '';
    var onlineDot = entry.online ? '<span style="color:var(--success);" title="在线">🟢</span>' : '<span style="color:var(--muted);" title="离线">◌</span>';
    html += '<tr>' +
      '<td>' + onlineDot + '</td>' +
      '<td>🧑 ' + escapeHtml(name) + '</td>' +
      '<td>' + escapeHtml(entry.last_online || '--') + '</td>' +
      '<td>' + escapeHtml(entry.added_at || '--') + '</td>' +
      '<td>' + escapeHtml(entry.added_by || '--') + '</td>' +
      '<td><button class="btn btn-danger btn-xs wl-remove-btn" data-player="' + encodeAttr(name) + '">移除</button></td>' +
      '</tr>';
  }
  html += '</tbody></table>';
  container.innerHTML = html;
}

function updatePending(data) {
  if (!data || !data.pending) return;

  var pending = data.pending;
  var section = document.getElementById('pending-section');
  var list = document.getElementById('pending-list');
  if (!section || !list) return;

  if (pending.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = '';
  var html = '<table class="data-table"><thead><tr><th>玩家名</th><th>时间</th><th>操作</th></tr></thead><tbody>';
  for (var i = 0; i < pending.length && i < 10; i++) {
    var p = pending[i];
    html += '<tr>' +
      '<td>❌ ' + escapeHtml(p.name || '') + '</td>' +
      '<td class="mono">' + escapeHtml(p.time || '--') + '</td>' +
      '<td><button class="btn btn-primary btn-xs wl-add-btn" data-player="' + encodeAttr(p.name || '') + '">+ 添加</button></td>' +
      '</tr>';
  }
  html += '</tbody></table>';
  list.innerHTML = html;
}

function updateWhitelistStatus(data) {
  // Called by the whitelist toggle API response or by polling
  var enabled = data && data.enabled !== undefined ? data.enabled : null;
  var label = document.getElementById('wl-status-label');
  var btn = document.getElementById('btn-wl-toggle');
  var hint = document.getElementById('wl-toggle-hint');

  if (enabled === true) {
    if (label) label.innerHTML = '🔒 白名单已启用 — 仅白名单玩家可加入';
    if (btn) btn.textContent = '临时关闭';
    if (btn) btn.className = 'btn btn-warning btn-sm';
    if (hint) hint.textContent = '朋友想加入？点"临时关闭"允许任何人连入';
  } else if (enabled === false) {
    if (label) label.innerHTML = '🔓 白名单已关闭 — 任何人可加入';
    if (btn) btn.textContent = '开启白名单';
    if (btn) btn.className = 'btn btn-success btn-sm';
    if (hint) hint.textContent = '所有人都能加入时，在在线列表中一键加入白名单';
  } else {
    if (label) label.innerHTML = '⚠ 服务器未运行，白名单状态未知';
    if (btn) btn.disabled = true;
    if (hint) hint.textContent = '';
  }
}

// ---- Whitelist action functions ----

function refreshWhitelist() {
  var poller = window._whitelistPoller;
  if (poller) { poller.stop(); poller.start(); }
  var pp = window._pendingPoller;
  if (pp) { pp.stop(); pp.start(); }
}

async function toggleWhitelist() {
  var btn = document.getElementById('btn-wl-toggle');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }
  try {
    var data = await apiCall('/api/whitelist/toggle', 'POST', {});
    var result = (data && data.data) ? data.data : {};
    updateWhitelistStatus(result);
    showToast(result.message || '已切换', 'success');
    refreshWhitelist();
  } catch (err) {
    showToast('切换失败: ' + (err.message || '网络错误'), 'error');
  } finally {
    if (btn) { btn.disabled = false; }
  }
}

async function reloadWhitelist() {
  try {
    var data = await apiCall('/api/whitelist/reload', 'POST', {});
    showToast(data.message || '白名单已重载', 'success');
    refreshWhitelist();
  } catch (err) {
    showToast('重载失败: ' + (err.message || '网络错误'), 'error');
  }
}

async function whitelistAddFromInput() {
  var input = document.getElementById('whitelist-name');
  if (!input) return;
  var name = input.value.trim();
  if (!name) { showToast('请输入玩家名', 'error'); return; }
  try {
    var data = await apiCall('/api/whitelist/add', 'POST', { name: name });
    if (data && data.success) {
      showToast(data.message || name + ' 已添加', 'success');
      input.value = '';
      refreshWhitelist();
    } else {
      showToast((data && data.message) || '添加失败', 'error');
    }
  } catch (err) {
    showToast('添加失败: ' + (err.message || '网络错误'), 'error');
  }
}

function showBatchModal() {
  var modal = document.getElementById('modal-batch-add');
  if (modal) modal.classList.add('active');
}

async function batchWhitelistAdd() {
  var textarea = document.getElementById('batch-names');
  if (!textarea) return;
  var raw = textarea.value.trim();
  if (!raw) { showToast('请输入玩家名', 'error'); return; }
  var names = raw.split(/[\n,]+/).map(function (s) { return s.trim(); }).filter(Boolean);
  if (names.length === 0) { showToast('请输入至少一个玩家名', 'error'); return; }

  var added = 0, failed = 0;
  for (var i = 0; i < names.length; i++) {
    try {
      var data = await apiCall('/api/whitelist/add', 'POST', { name: names[i] });
      if (data && data.success) {
        added++;
      } else {
        failed++;
      }
    } catch (_e) {
      failed++;
    }
  }
  showToast('成功添加 ' + added + ' 人' + (failed > 0 ? '，失败 ' + failed + ' 人' : ''), added > 0 ? 'success' : 'error');
  textarea.value = '';
  var modal = document.getElementById('modal-batch-add');
  if (modal) modal.classList.remove('active');
  refreshWhitelist();
}

function updateLogs(data) {
  if (!data || !data.lines) return;

  var lines = data.lines;
  var viewer = document.getElementById('log-viewer') || document.querySelector('.log-viewer');
  if (!viewer) return;

  if (lines.length === 0) {
    viewer.innerHTML = '<div class="empty-state" style="padding:20px;"><p>暂无日志</p><p style="font-size:10px;color:var(--muted);">启动 MC 服务器后将显示日志</p></div>';
    return;
  }

  var html = '';
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    var styled = escapeHtml(line);
    // Highlight chat lines
    if (/<\w{2,16}>\s/.test(line) && !/\[.*(WARN|ERROR|FATAL).*\]/i.test(line)) {
      styled = '<span class="console-chat">' + styled + '</span>';
    } else if (/\[.*(WARN|ERROR|FATAL).*\]/i.test(line)) {
      styled = '<span class="console-error">' + styled + '</span>';
    }
    html += '<div class="log-line console-line">' + styled + '</div>';
  }

  viewer.innerHTML = html;
  viewer.scrollTop = viewer.scrollHeight;
}

function refreshLogs() {
  var poller = window._logsPoller;
  if (poller) {
    poller.stop();
    poller.start();
  } else {
    // Poller not started yet — do a one-shot fetch
    apiCall('/api/logs/recent?limit=500').then(function (data) {
      updateLogs(data);
    }).catch(function () {});
  }
}

async function exportLogs() {
  try {
    var token = getJWT();
    var resp = await fetch('/api/logs/export', {
      headers: {
        'Accept': 'text/plain',
        'Authorization': 'Bearer ' + token,
      },
    });
    if (!resp.ok) {
      var errData = await resp.json().catch(function () { return {}; });
      showToast(errData.message || '导出失败', 'error');
      return;
    }
    var blob = await resp.blob();
    var url = window.URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'server_logs_all.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    showToast('日志已导出', 'success');
  } catch (err) {
    showToast('导出失败: ' + (err.message || '网络错误'), 'error');
  }
}

async function clearLogs() {
  if (!confirm('确定要清空服务器日志吗？')) return;
  try {
    var data = await apiCall('/api/logs/clear', 'POST', {});
    showToast(data.message || '日志已清空', 'success');
    // Clear the display immediately
    var viewer = document.getElementById('log-viewer') || document.querySelector('.log-viewer');
    if (viewer) {
      viewer.innerHTML = '<div class="empty-state" style="padding:20px;"><p>日志已清空</p></div>';
    }
    // Restart the poller so it picks up new entries
    var poller = window._logsPoller;
    if (poller) {
      poller.stop();
      poller.start();
    }
  } catch (err) {
    showToast('清空失败: ' + (err.message || '网络错误'), 'error');
  }
}

function updateConsole(data) {
  if (!data || !data.lines) return;

  var viewer = document.getElementById('console-viewer');
  if (!viewer) return;

  var lines = data.lines;
  var html = '';
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    var styled = escapeHtml(line);
    // Match PaperMC/Vanilla chat format: "[...]: <PlayerName> message"
    if (/<\w{2,16}>\s/.test(line) && !/\[.*(WARN|ERROR|FATAL).*\]/i.test(line)) {
      styled = '<span class="console-chat">' + styled + '</span>';
    } else if (/\[.*(WARN|ERROR|FATAL).*\]/i.test(line)) {
      styled = '<span class="console-error">' + styled + '</span>';
    }
    html += '<div class="log-line console-line">' + styled + '</div>';
  }

  viewer.innerHTML = html;
  viewer.scrollTop = viewer.scrollHeight;
}

async function sendCommand() {
  var input = document.getElementById('console-command');
  var btn = document.getElementById('console-send-btn');
  if (!input || !btn) return;

  var cmd = input.value.trim();
  if (!cmd) return;

  btn.disabled = true;
  btn.textContent = '⏳';

  try {
    var data = await apiCall('/api/mc/command', 'POST', { command: cmd });

    var viewer = document.getElementById('console-viewer');
    if (viewer) {
      var respText = (data && data.response) ? data.response : '(no response)';
      var entry = document.createElement('div');
      entry.className = 'log-line console-cmd-entry';
      entry.innerHTML = '<span class="time">▶ cmd</span>' +
        '<span class="msg">' + escapeHtml(cmd) + ' → ' + escapeHtml(respText) + '</span>';
      viewer.appendChild(entry);
      viewer.scrollTop = viewer.scrollHeight;
    }

    input.value = '';
  } catch (err) {
    showToast('命令执行失败: ' + (err.message || '网络错误'));
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ 发送';
  }
}

/* =================================================================
   Module: Server Center
   ================================================================= */

function updateServerCenter(data) {
  if (!data || !data.data) return;

  var d = data.data;
  var running = d.status === 'running';

  // Server info grid
  setHtml('#sc-status', running
    ? '<span style="color:var(--success);">● 运行中</span>'
    : '<span style="color:var(--danger);">● 已停止</span>');
  setHtml('#sc-ip', d.lan_address || (d.local_ip + ':' + d.port));
  setHtml('#sc-port', String(d.port));
  setHtml('#sc-version', d.version || '--');
  setHtml('#sc-world', d.active_world || '--');
  setHtml('#sc-online', d.online_mode ? '正版验证 ✓' : '离线模式 (局域网可用)');

  // Toggle buttons
  var sStart = document.getElementById('sc-btn-start');
  var sStop = document.getElementById('sc-btn-stop');
  var sRestart = document.getElementById('sc-btn-restart');
  if (running) {
    if (sStart) sStart.style.display = 'none';
    if (sStop) sStop.style.display = '';
    if (sRestart) sRestart.style.display = '';
  } else {
    if (sStart) sStart.style.display = '';
    if (sStop) sStop.style.display = 'none';
    if (sRestart) sRestart.style.display = 'none';
  }

  // Version list
  var versions = d.installed_versions || [];
  var vhtml = '';
  for (var i = 0; i < versions.length; i++) {
    var ver = versions[i];
    var activeBadge = ver.active ? ' <span class="pill pill-success" style="font-size:9px;">活跃</span>' : '';
    vhtml += '<div class="version-item">' +
      '<span class="version-name">' + escapeHtml(ver.file_name) +
      ' (' + ver.size_mb + ' MB)' + activeBadge + '</span>' +
      (ver.active ? '' : '<button class="btn btn-secondary btn-xs" onclick="switchVersion(\'' + escapeHtml(ver.version) + '\')">切换到此版本</button>') +
      '</div>';
  }
  setHtml('#version-list', vhtml || '<div class="empty-state"><p>未检测到已安装版本</p></div>');
}

async function toggleOnlineMode() {
  var el = document.querySelector('#sc-online');
  var current = (el && el.textContent.indexOf('正版验证') >= 0);
  var newVal = !current;
  var label = newVal ? '正版验证' : '离线模式';
  if (!confirm('切换为 "' + label + '"？\\n\\n正版验证 开启 = 仅正版玩家可加入\\n正版验证 关闭 = 任意客户端可加入（局域网友好）\\n\\n需要重启服务器才能生效。')) return;
  try {
    var data = await apiCall('/api/server/settings', 'POST', { online_mode: newVal });
    showToast(data.message || '设置已更新');
    loadServerCenter();
  } catch (err) {
    showToast('设置失败: ' + (err.message || '网络错误'));
  }
}

function loadServerCenter() {
  apiCall('/api/server/info').then(function (data) {
    updateServerCenter(data);
  }).catch(function () {});
}

async function switchVersion(version) {
  if (!confirm('切换到版本 ' + version + '？\n\n切换后需要重启服务器才能生效。')) return;
  try {
    var data = await apiCall('/api/server/versions/switch', 'POST', { version: version });
    showToast(data.message || '版本已切换');
    loadServerCenter();
  } catch (err) {
    showToast('切换失败: ' + (err.message || '网络错误'));
  }
}

function showCreateWorldModal() {
  var modal = document.getElementById('modal-create-world');
  if (modal) modal.classList.add('active');
}

async function createWorld() {
  var nameInput = document.getElementById('new-world-name');
  var name = nameInput ? nameInput.value.trim() : '';
  if (!name) { alert('请输入世界名称'); return; }

  try {
    var data = await apiCall('/api/server/worlds/create', 'POST', { name: name });
    showToast(data.message || '世界已创建');
    var modal = document.getElementById('modal-create-world');
    if (modal) modal.classList.remove('active');
    if (nameInput) nameInput.value = '';
    loadWorlds();
  } catch (err) {
    showToast('创建失败: ' + (err.message || '网络错误'));
  }
}

async function deleteWorld(name) {
  if (!confirm('确定要删除世界 "' + name + '" 吗？此操作不可撤销！')) return;
  try {
    var data = await apiCall('/api/server/worlds/delete', 'POST', { name: name });
    showToast(data.message || '世界已删除');
    loadWorlds();
  } catch (err) {
    showToast('删除失败: ' + (err.message || '网络错误'));
  }
}

async function activateWorld(name) {
  try {
    var data = await apiCall('/api/server/worlds/activate', 'POST', { name: name });
    showToast(data.message || '活跃世界已切换');
    loadWorlds();
    loadServerCenter();
  } catch (err) {
    showToast('切换失败: ' + (err.message || '网络错误'));
  }
}

async function renameWorld(oldName) {
  var newName = prompt('将 "' + oldName + '" 重命名为：', oldName);
  if (!newName || newName === oldName) return;
  try {
    var data = await apiCall('/api/server/worlds/rename', 'POST', { old_name: oldName, new_name: newName });
    showToast(data.message || '重命名成功');
    loadWorlds();
  } catch (err) {
    showToast('重命名失败: ' + (err.message || '网络错误'));
  }
}

function loadWorlds() {
  apiCall('/api/server/worlds').then(function (data) {
    var worlds = data.worlds || [];
    var whtml = '';
    for (var i = 0; i < worlds.length; i++) {
      var w = worlds[i];
      var dims = w.dimensions || {};
      var activeLabel = w.active ? ' <span class="pill pill-success" style="font-size:9px;">活跃</span>' : '';
      // Dimension status dots
      var dimHtml = '<div class="world-dims">' +
        '<span class="dim-dot" title="主世界">' + (dims.overworld ? '🌍' : '◌') + ' 主世界</span>' +
        '<span class="dim-dot" title="地狱">' + (dims.nether ? '🔥' : '◌') + ' 地狱</span>' +
        '<span class="dim-dot" title="末地">' + (dims.end ? '🌑' : '◌') + ' 末地</span>' +
        '</div>';
      whtml += '<div class="world-card' + (w.active ? ' active' : '') + '">' +
        '<div class="world-card-header">' +
        '<span class="world-name">🌍 ' + escapeHtml(w.name) + activeLabel + '</span>' +
        '<span class="world-size">' + escapeHtml(w.size_human) + '</span>' +
        '</div>' +
        dimHtml +
        '<div class="world-card-meta">修改于 ' + escapeHtml(w.modified) + '</div>' +
        '<div class="world-card-actions">' +
        (w.active ? '' : '<button class="btn btn-primary btn-xs" onclick="activateWorld(\'' + escapeHtml(w.name) + '\')">设为活跃</button>') +
        '<button class="btn btn-secondary btn-xs" onclick="renameWorld(\'' + escapeHtml(w.name) + '\')">重命名</button>' +
        (w.active ? '' : '<button class="btn btn-danger btn-xs" onclick="deleteWorld(\'' + escapeHtml(w.name) + '\')">删除</button>') +
        '</div>' +
        '</div>';
    }
    setHtml('#world-grid', whtml || '<div class="empty-state"><p>未检测到世界存档</p><p style="font-size:10px;color:var(--muted);">新建世界后启动服务器将自动生成地狱和末地维度</p></div>');
  }).catch(function () {});
}

async function downloadNewVersion() {
  // Show the modal
  var modal = document.getElementById('modal-download-version');
  if (modal) modal.classList.add('active');

  // Load version list
  var select = document.getElementById('remote-version-select');
  if (!select || select.options.length > 1) return;
  try {
    var resp = await fetch('/api/public/versions');
    var data = await resp.json();
    var versions = data.versions || [];
    select.innerHTML = '';
    for (var i = 0; i < versions.length; i++) {
      var opt = document.createElement('option');
      opt.value = versions[i];
      opt.textContent = versions[i];
      select.appendChild(opt);
    }
  } catch (err) {
    select.innerHTML = '<option value="">加载失败</option>';
  }
}

async function downloadVersion() {
  var select = document.getElementById('remote-version-select');
  var version = select ? select.value : '';
  if (!version) { alert('请选择版本'); return; }

  var btn = document.getElementById('btn-download-version');
  var progressArea = document.getElementById('download-progress-area');
  var progressFill = document.getElementById('download-progress-fill');
  var progressText = document.getElementById('download-progress-text');
  var progressMb = document.getElementById('download-progress-mb');
  var progressPhase = document.getElementById('download-progress-phase');
  var hint = document.getElementById('download-hint');

  if (btn) { btn.disabled = true; btn.textContent = '⏳ 请求中...'; }
  if (hint) hint.textContent = '正在连接 PaperMC API...';

  // Start progress polling immediately
  var progressTimer = setInterval(async function () {
    try {
      var resp = await fetch('/api/public/download-progress');
      var d = await resp.json();
      var p = (d && d.data) ? d.data : d;
      var st = p ? p.status : 'idle';
      if (st === 'downloading') {
        var pct = p.percent || 0;
        if (progressArea) progressArea.style.display = '';
        if (progressFill) progressFill.style.width = pct + '%';
        if (progressText) progressText.textContent = pct + '%';
        if (progressMb) progressMb.textContent = (p.downloaded_mb || 0).toFixed(1) + ' / ' + (p.total_mb || 0).toFixed(1) + ' MB';
        // Show phase label
        if (progressPhase) {
          if (p.phase === 'mojang_jar') {
            progressPhase.textContent = '📦 下载原版 Minecraft ' + (p.version || '') + ' 服务端...';
          } else {
            progressPhase.textContent = '📦 下载 PaperMC ' + (p.version || '') + ' 引导器...';
          }
        }
      } else if (st === 'done') {
        // Download fully completed
        clearInterval(progressTimer);
        if (progressArea) progressArea.style.display = 'none';
        if (progressPhase) progressPhase.textContent = '';
        if (hint) hint.textContent = '下载可能需要几分钟，请耐心等待。';
        if (btn) { btn.disabled = false; btn.textContent = '开始下载'; }
        showToast('版本 ' + version + ' 下载完成，可切换使用');
        var modal = document.getElementById('modal-download-version');
        if (modal) modal.classList.remove('active');
        loadServerCenter();
      } else if (st === 'error') {
        clearInterval(progressTimer);
        if (progressArea) progressArea.style.display = 'none';
        if (progressPhase) progressPhase.textContent = '';
        if (hint) hint.textContent = '下载可能需要几分钟，请耐心等待。';
        if (btn) { btn.disabled = false; btn.textContent = '开始下载'; }
        showToast('下载失败，请检查网络');
      }
    } catch (_) {}
  }, 500);

  // Trigger the background download
  try {
    var result = await apiCall('/api/server/versions/download', 'POST', { version: version });
    // apiCall throws on non-ok; result is already parsed JSON
    showToast(result.message || '下载已启动');
  } catch (err) {
    clearInterval(progressTimer);
    showToast('下载请求失败: ' + (err.message || '网络错误'));
    if (progressArea) progressArea.style.display = 'none';
    if (hint) hint.textContent = '下载可能需要几分钟，请耐心等待。';
    if (btn) { btn.disabled = false; btn.textContent = '开始下载'; }
  }

  // Safety timeout: stop polling after 10 minutes
  setTimeout(function() { clearInterval(progressTimer); }, 600000);
}

/* =================================================================
   Module: Helper functions
   ================================================================= */

function setHtml(selector, html) {
  var el = document.querySelector(selector);
  if (el) el.innerHTML = html;
}

function formatUptime(seconds) {
  if (seconds === undefined || seconds === null || seconds < 0) return '--';
  var s = Math.round(Number(seconds));
  if (s < 60) return s + '秒';
  if (s < 3600) return Math.floor(s / 60) + '分' + (s % 60) + '秒';
  var h = Math.floor(s / 3600);
  var m = Math.floor((s % 3600) / 60);
  return h + '时' + m + '分';
}

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str || '');
  var map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return str.replace(/[&<>"']/g, function (m) { return map[m]; });
}

function encodeAttr(str) {
  return escapeHtml(String(str || '')).replace(/"/g, '&quot;');
}

/* =================================================================
   Module: Server Actions
   ================================================================= */

async function serverAction(action) {
  var endpoint, actionLabel;
  switch (action) {
    case 'start':   endpoint = '/api/mc/start';   actionLabel = '启动'; break;
    case 'stop':    endpoint = '/api/mc/stop';    actionLabel = '停止'; break;
    case 'restart': endpoint = '/api/mc/restart'; actionLabel = '重启'; break;
    default: return;
  }

  var btn = document.querySelector('[data-action="' + action + '"]');
  var origHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
  }

  try {
    var result = await apiCall(endpoint, 'POST', {});
    showToast(result.message || actionLabel + '成功', 'success');
  } catch (err) {
    showToast(err.message || actionLabel + '失败', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

var _frpcActionLock = false;

async function frpcStart() {
  if (_frpcActionLock) return;
  _frpcActionLock = true;
  var btn = document.getElementById('btn-frp-start');
  var msg = document.getElementById('frpc-action-msg');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
  if (msg) msg.textContent = '正在连接樱花节点…';
  try {
    var result = await apiCall('/api/tunnel/start', 'POST', {});
    showToast(result.message || '穿透已启动', 'success');
    // Immediately swap buttons — don't wait for the 10s poll cycle
    if (btn) btn.style.display = 'none';
    var btnStop = document.getElementById('btn-frp-stop');
    if (btnStop) btnStop.style.display = '';
    if (msg) msg.textContent = '已连接 ✓';
    // Clear the "已连接" hint after 5s
    setTimeout(function () { if (msg) msg.textContent = ''; }, 5000);
  } catch (err) {
    showToast(err.message || '启动失败', 'error');
    if (msg) msg.textContent = '启动失败';
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '▶ 启动穿透'; }
    _frpcActionLock = false;
  }
}

async function frpcStop() {
  if (_frpcActionLock) return;
  _frpcActionLock = true;
  var btn = document.getElementById('btn-frp-stop');
  var msg = document.getElementById('frpc-action-msg');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
  if (msg) msg.textContent = '正在断开…';
  try {
    var result = await apiCall('/api/tunnel/stop', 'POST', {});
    showToast(result.message || '穿透已停止', 'success');
    // Immediately swap buttons back
    if (btn) btn.style.display = 'none';
    var btnStart = document.getElementById('btn-frp-start');
    if (btnStart) btnStart.style.display = '';
    if (msg) msg.textContent = '已断开';
    setTimeout(function () { if (msg) msg.textContent = ''; }, 3000);
  } catch (err) {
    showToast(err.message || '停止失败', 'error');
    if (msg) msg.textContent = '停止失败';
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '⏹ 停止穿透'; }
    _frpcActionLock = false;
  }
}

async function kickPlayer(playerName) {
  if (!playerName) return;

  var btn = document.querySelector('.kick-btn[data-player="' + encodeAttr(playerName) + '"]');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
  }

  try {
    await apiCall('/api/mc/kick', 'POST', { name: playerName });
    showToast(playerName + ' 已被踢出', 'success');
    var poller = window._playerPoller;
    if (poller) { poller.stop(); poller.start(); }
  } catch (err) {
    showToast(err.message || '踢出失败', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '踢出';
    }
  }
}

async function toggleOpPlayer(playerName, currentlyOp) {
  if (!playerName) return;
  var endpoint = currentlyOp ? '/api/mc/deop' : '/api/mc/op';
  var actionLabel = currentlyOp ? '撤销管理员' : '设为管理员';
  var confirmMsg = currentlyOp
    ? '确定撤销 ' + playerName + ' 的管理员（OP）权限吗？'
    : '确定将 ' + playerName + ' 设为服务器管理员（OP）吗？';
  if (!confirm(confirmMsg)) return;

  var btn = document.querySelector('.op-btn[data-player="' + encodeAttr(playerName) + '"]');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
  }

  try {
    await apiCall(endpoint, 'POST', { name: playerName });
    showToast(playerName + ' ' + actionLabel + '成功', 'success');
    // Refresh player list so the button toggles
    var poller = window._playerPoller;
    if (poller) { poller.stop(); poller.start(); }
  } catch (err) {
    showToast(err.message || '操作失败', 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = currentlyOp ? '撤销OP' : '⚡OP';
    }
  }
}

async function whitelistAdd(playerName) {
  if (!playerName || !playerName.trim()) {
    showToast('请输入玩家名', 'error');
    return;
  }

  try {
    await apiCall('/api/whitelist/add', 'POST', { name: playerName.trim() });
    showToast(playerName.trim() + ' 已添加到白名单', 'success');
    var poller = window._whitelistPoller;
    if (poller) { poller.stop(); poller.start(); }
  } catch (err) {
    showToast(err.message || '添加失败', 'error');
  }
}

async function whitelistRemove(playerName) {
  if (!playerName) return;

  try {
    await apiCall('/api/whitelist/remove', 'POST', { name: playerName });
    showToast(playerName + ' 已从白名单移除', 'success');
    refreshWhitelist();
  } catch (err) {
    showToast(err.message || '移除失败', 'error');
  }
}

/* =================================================================
   Module: Modal helpers (JS-driven)
   ================================================================= */

function openModal(modalId) {
  var modal = document.getElementById(modalId);
  if (modal) modal.classList.add('active');
}

function closeModal(modalId) {
  var modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('active');
}

/* =================================================================
   Module: Initialization
   ================================================================= */

document.addEventListener('DOMContentLoaded', function () {
  // --- Setup CSRF token ---
  refreshCSRFToken();

  // --- Login page ---
  var loginForm = document.getElementById('login-form');
  if (loginForm) {
    loginForm.addEventListener('submit', async function (e) {
      e.preventDefault();

      var btn = document.getElementById('login-btn');
      var errorEl = document.getElementById('login-error');
      var username = document.getElementById('username').value.trim();
      var password = document.getElementById('password').value;

      errorEl.classList.remove('visible');
      errorEl.textContent = '';
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> 登录中...';

      try {
        await refreshCSRFToken();

        var resp = await fetch('/api/admin/login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRF-Token': getCSRFToken(),
          },
          body: JSON.stringify({ username: username, password: password }),
        });

        var data = await resp.json();

        if (!resp.ok) {
          errorEl.textContent = data.message || '登录失败，请检查用户名和密码';
          errorEl.classList.add('visible');
          return;
        }

        if (data.token) setJWT(data.token);

        if (data.csrf_token) {
          var meta = document.querySelector('meta[name="csrf-token"]');
          if (meta) meta.setAttribute('content', data.csrf_token);
        }

        var params = new URLSearchParams(window.location.search);
        var next = params.get('next') || '/dashboard';
        window.location.href = next;
      } catch (err) {
        errorEl.textContent = '网络错误，请检查服务器连接';
        errorEl.classList.add('visible');
      } finally {
        btn.disabled = false;
        btn.textContent = '登 录';
      }
    });
  }

  // --- Dashboard: start status polling ---
  // Only start on pages that have a dashboard tab panel
  var dashboardPanel = document.querySelector('.tab-panel');
  if (dashboardPanel && isAuthenticated()) {
    // --- Create all pollers ---
    var statusPoller = new LivePoller('/api/mc/status', 10000);
    statusPoller.onData(function (data) { updateDashboard(data); });
    window._statusPoller = statusPoller;

    var playerPoller = new LivePoller('/api/mc/players', 5000);
    playerPoller.onData(function (data) { updatePlayers(data); });
    window._playerPoller = playerPoller;

    var whitelistPoller = new LivePoller('/api/whitelist/list', 15000);
    whitelistPoller.onData(function (data) {
      updateWhitelist(data);
      // Also update whitelist status from the list response
      updateWhitelistStatus(data);
    });
    window._whitelistPoller = whitelistPoller;

    var pendingPoller = new LivePoller('/api/whitelist/pending', 10000);
    pendingPoller.onData(function (data) { updatePending(data); });
    window._pendingPoller = pendingPoller;

    var logsPoller = new LivePoller('/api/logs/recent?limit=500', 10000);
    logsPoller.onData(function (data) { updateLogs(data); });
    window._logsPoller = logsPoller;

    var consolePoller = new LivePoller('/api/mc/console?limit=200', 3000);
    consolePoller.onData(function (data) {
      updateConsole(data);
      // Auto-scroll on new data
    });
    window._consolePoller = consolePoller;

    var serverCenterPoller = new LivePoller('/api/server/info', 15000);
    serverCenterPoller.onData(function (data) { updateServerCenter(data); });
    window._serverCenterPoller = serverCenterPoller;

    var tunnelPoller = new LivePoller('/api/tunnel/status', 10000);
    tunnelPoller.onData(function (data) { updateTunnel(data); });
    window._tunnelPoller = tunnelPoller;

    // Start all pollers (status dashboard needs it immediately; others pre-warm)
    statusPoller.start();
    tunnelPoller.start();
    // Stagger other starts to avoid request flood
    setTimeout(function () { playerPoller.start(); }, 200);
    setTimeout(function () { whitelistPoller.start(); }, 400);
    setTimeout(function () { pendingPoller.start(); }, 300);
    setTimeout(function () { logsPoller.start(); }, 600);
    setTimeout(function () { consolePoller.start(); }, 800);
    setTimeout(function () { serverCenterPoller.start(); }, 1000);

    // Initial data loads
    setTimeout(function () { loadWorlds(); }, 500);
    setTimeout(function () { loadServerCenter(); }, 1200);
  }

  // --- Tab switching ---
  var tabBar = document.querySelector('.tab-bar');
  if (tabBar) {
    tabBar.addEventListener('click', function (e) {
      var target = e.target.closest('.tab-label, .tab-btn');
      if (!target) return;

      // Determine tab name from for attribute, class, or data-tab
      var tabName = target.getAttribute('data-tab');
      if (!tabName) {
        var forAttr = target.getAttribute('for');
        if (forAttr) tabName = forAttr.replace('tab-', '');
      }
      if (!tabName) {
        for (var c = 0; c < target.classList.length; c++) {
          var cls = target.classList[c];
          if (cls.indexOf('tab-') === 0 && cls !== 'tab-bar') {
            tabName = cls.replace('tab-', '');
            break;
          }
        }
      }
      if (!tabName) return;

      switchTab(tabName);
    });
  }

  // --- Tab radio change listeners (catches sidebar labels and direct radio changes) ---
  var tabRadios = document.querySelectorAll('.tab-radio');
  for (var i = 0; i < tabRadios.length; i++) {
    tabRadios[i].addEventListener('change', function () {
      if (!this.checked) return;
      var tabName = this.id.replace('tab-', '');
      switchTab(tabName);

      // Refresh worlds immediately when switching to server center
      if (tabName === 'servercenter') {
        loadWorlds();
        loadServerCenter();
      }
    });
  }

  // --- Server action buttons ---
  var allBtns = document.querySelectorAll('[data-action]');
  for (var i = 0; i < allBtns.length; i++) {
    allBtns[i].addEventListener('click', function (e) {
      e.preventDefault();
      serverAction(this.getAttribute('data-action'));
    });
  }

  // --- Kick player / OP player (delegated) ---
  document.addEventListener('click', function (e) {
    var kickBtn = e.target.closest('.kick-btn');
    if (kickBtn) {
      var playerName = kickBtn.getAttribute('data-player');
      var modal = document.getElementById('modal-kick');
      if (modal) {
        if (!modal.querySelector('.modal-box')) {
          kickPlayer(playerName);
        } else {
          modal.setAttribute('data-kick-player', playerName);
          modal.classList.add('active');
        }
      } else {
        kickPlayer(playerName);
      }
    }

    var opBtn = e.target.closest('.op-btn');
    if (opBtn) {
      var playerName = opBtn.getAttribute('data-player');
      var isOp = opBtn.getAttribute('data-is-op') === '1';
      toggleOpPlayer(playerName, isOp);
    }
  });

  // --- Whitelist add / remove (delegated) ---
  document.addEventListener('click', function (e) {
    var wlRemove = e.target.closest('.wl-remove-btn');
    if (wlRemove) {
      var playerName = wlRemove.getAttribute('data-player');
      // Show confirmation modal
      var modal = document.getElementById('modal-wl-remove');
      var nameSpan = document.getElementById('wl-remove-name');
      var confirmBtn = document.getElementById('btn-wl-remove-confirm');
      if (modal && nameSpan) {
        nameSpan.textContent = playerName;
        if (confirmBtn) confirmBtn.setAttribute('data-player', playerName);
        modal.classList.add('active');
      } else {
        // Fallback: direct remove
        whitelistRemove(playerName);
      }
      return;
    }
    var wlAdd = e.target.closest('.wl-add-btn');
    if (wlAdd) {
      var name = wlAdd.getAttribute('data-player');
      if (name) {
        var btn = wlAdd;
        btn.disabled = true;
        btn.textContent = '...';
        apiCall('/api/whitelist/add', 'POST', { name: name }).then(function (data) {
          if (data && data.success) {
            showToast(data.message || name + ' 已添加到白名单', 'success');
            refreshWhitelist();
          } else {
            showToast((data && data.message) || '添加失败', 'error');
          }
        }).catch(function (err) {
          showToast('添加失败: ' + (err.message || '网络错误'), 'error');
        }).finally(function () {
          btn.disabled = false;
          btn.textContent = '📋+白名单';
        });
      }
    }
  });

  // --- Modal confirm buttons ---
  var confirmBtns = document.querySelectorAll('.modal-confirm');
  for (var j = 0; j < confirmBtns.length; j++) {
    confirmBtns[j].addEventListener('click', function () {
      var modal = this.closest('.modal-overlay');
      if (!modal) return;
      var playerName = this.getAttribute('data-player');
      if (playerName) {
        if (modal.id && modal.id.indexOf('modal-kick') === 0) {
          kickPlayer(playerName);
        } else if (modal.id === 'modal-wl-remove') {
          whitelistRemove(playerName);
          modal.classList.remove('active');
        }
      }
      modal.classList.remove('active');
    });
  }

  // --- Modal close buttons ---
  var closeBtns = document.querySelectorAll('.modal-close');
  for (var k = 0; k < closeBtns.length; k++) {
    closeBtns[k].addEventListener('click', function (e) {
      e.preventDefault();
      var modal = this.closest('.modal-overlay');
      if (modal) modal.classList.remove('active');
    });
  }

  // --- Close modal on overlay click ---
  var overlays = document.querySelectorAll('.modal-overlay');
  for (var l = 0; l < overlays.length; l++) {
    overlays[l].addEventListener('click', function (e) {
      if (e.target === this) this.classList.remove('active');
    });
  }

  // --- Logout buttons ---
  var logoutBtns = document.querySelectorAll('.logout-btn, a[href*=\"/login\"]');
  for (var m = 0; m < logoutBtns.length; m++) {
    (function (btn) {
      btn.addEventListener('click', function (e) {
        // Only intercept logout buttons in sidebar, not the login page link
        if (btn.closest('.sidebar') || btn.classList.contains('logout-btn')) {
          e.preventDefault();
          clearJWT();
          window.location.href = '/login';
        }
      });
    })(logoutBtns[m]);
  }
});
