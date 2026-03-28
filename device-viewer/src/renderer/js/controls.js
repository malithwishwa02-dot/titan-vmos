document.addEventListener('DOMContentLoaded', async () => {
  /* ─── DOM refs ─── */
  const connBadge = document.getElementById('conn-badge');
  const connLabel = document.getElementById('conn-label');
  const placeholder = document.getElementById('screen-placeholder');
  const retryBtn = document.getElementById('btn-retry');
  const toastContainer = document.getElementById('toast-container');
  const sidebar = document.getElementById('sidebar');
  const modeButtons = Array.from(document.querySelectorAll('[data-display-mode]'));
  const phText = placeholder.querySelector('.ph-text');
  const phSpinner = placeholder.querySelector('.ph-spinner');

  let sidebarHideTimer = null;
  let prevConnState = 'connecting';

  /* ─── Toast system with dedup / throttle / limit ─── */

  const MAX_TOASTS = 3;
  let _lastToastMsg = '';
  let _lastToastTime = 0;

  function showToast(message, type = 'info', duration = 4000) {
    // Dedup: skip identical messages within 3 seconds
    const now = Date.now();
    if (message === _lastToastMsg && now - _lastToastTime < 3000) return;
    _lastToastMsg = message;
    _lastToastTime = now;

    // Enforce max visible toasts — remove oldest if at limit
    const existing = toastContainer.querySelectorAll('.toast');
    if (existing.length >= MAX_TOASTS) {
      const oldest = existing[0];
      oldest.remove();
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast-visible'));
    setTimeout(() => {
      toast.classList.remove('toast-visible');
      toast.addEventListener('transitionend', () => toast.remove(), { once: true });
    }, duration);
  }

  /* ─── Connection state (single source of truth) ─── */

  function setConnectionState(state) {
    prevConnState = state;

    connBadge.className = 'conn-badge ' + state;

    if (state === 'connected') {
      connLabel.textContent = 'Connected';
    } else if (state === 'connecting') {
      connLabel.textContent = 'Connecting';
    } else if (state === 'recovering') {
      connLabel.textContent = 'Reconnecting';
    } else {
      connLabel.textContent = 'Offline';
    }
  }

  /* ─── Display mode ─── */

  function setDisplayMode(mode) {
    modeButtons.forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.displayMode === mode);
    });
  }

  function applyLayout(layout) {
    const s = document.documentElement.style;
    s.setProperty('--screen-w', layout.screenWidth + 'px');
    s.setProperty('--screen-h', layout.screenHeight + 'px');
    s.setProperty('--phone-w', layout.phoneWidth + 'px');
    s.setProperty('--phone-h', layout.phoneHeight + 'px');

    if (layout.bezelRadius != null) s.setProperty('--bezel-radius', layout.bezelRadius + 'px');
    if (layout.screenRadius != null) s.setProperty('--screen-radius', layout.screenRadius + 'px');
    if (layout.bezelTop != null) s.setProperty('--bezel-top', layout.bezelTop + 'px');
    if (layout.bezelBottom != null) s.setProperty('--bezel-bottom', layout.bezelBottom + 'px');
    if (layout.bezelSide != null) s.setProperty('--bezel-side', layout.bezelSide + 'px');

    document.body.classList.remove('mode-phone', 'mode-maximized', 'mode-fullscreen');
    document.body.classList.add('mode-' + (layout.mode || 'phone'));
    setDisplayMode(layout.mode || 'phone');
  }

  /* ─── IPC listeners ─── */

  window.cuttlefish.onLayout(layout => applyLayout(layout));

  window.cuttlefish.onStatus(status => {
    if (status === 'connected') {
      setConnectionState('connected');
      placeholder.style.display = 'none';
      // Only show success toast when recovering from a problem, not on initial connect
      if (prevConnState === 'recovering' || prevConnState === 'disconnected') {
        showToast('Device connected', 'success', 2000);
      }
      return;
    }

    if (status === 'recovering') {
      setConnectionState('recovering');
      placeholder.style.display = '';
      retryBtn.style.display = 'none';
      phSpinner.style.display = '';
      phText.textContent = 'Reconnecting…';
      return;
    }

    // disconnected — permanent
    setConnectionState('disconnected');
    placeholder.style.display = '';
    retryBtn.style.display = '';
    phSpinner.style.display = 'none';
    phText.textContent = 'Device disconnected';
  });

  // Error events — NEVER change connection state, only show toast
  window.cuttlefish.onError(msg => {
    console.error('[scrcpy]', msg);
    showToast(msg, 'error');
  });

  window.cuttlefish.onAppError(err => {
    console.error('[app]', err.detail || err.message);
    showToast(err.message || 'An error occurred', 'error');
  });

  /* ─── Sidebar: auto-show in fullscreen on mouse near right edge ─── */

  document.addEventListener('mousemove', e => {
    if (!document.body.classList.contains('mode-fullscreen') &&
        !document.body.classList.contains('mode-maximized')) return;
    if (e.clientX > window.innerWidth - 96) {
      sidebar.classList.add('sb-visible');
      if (sidebarHideTimer) clearTimeout(sidebarHideTimer);
      sidebarHideTimer = setTimeout(() => sidebar.classList.remove('sb-visible'), 2500);
    }
  });

  /* ─── Button clicks ─── */

  document.querySelectorAll('[data-action]').forEach(el => {
    el.addEventListener('click', e => {
      e.stopPropagation();
      const fn = window.cuttlefish[el.dataset.action];
      if (typeof fn === 'function') {
        fn();
        el.style.transform = 'scale(0.93)';
        el.style.opacity = '0.75';
        setTimeout(() => { el.style.transform = ''; el.style.opacity = ''; }, 120);
      }
    });
  });

  modeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      window.cuttlefish.setDisplayMode(btn.dataset.displayMode);
    });
  });

  /* ─── Window controls ─── */

  document.getElementById('btn-close').addEventListener('click', () => window.cuttlefish.closeWindow());
  document.getElementById('btn-minimize').addEventListener('click', () => window.cuttlefish.minimizeWindow());
  document.getElementById('btn-maximize').addEventListener('click', () => window.cuttlefish.maximizeWindow());

  /* ─── Retry button ─── */

  retryBtn.addEventListener('click', () => {
    retryBtn.style.display = 'none';
    phSpinner.style.display = '';
    phText.textContent = 'Reconnecting to device…';
    setConnectionState('connecting');
    window.cuttlefish.restartScrcpy();
  });

  /* ─── Double-click viewport to fullscreen ─── */

  const screenArea = document.getElementById('screen-area');
  if (screenArea) {
    screenArea.addEventListener('dblclick', () => window.cuttlefish.fullscreenWindow());
  }

  /* ─── Keyboard shortcuts ─── */

  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.key === '1') { e.preventDefault(); window.cuttlefish.setDisplayMode('phone'); return; }
    if (e.ctrlKey && e.key === '2') { e.preventDefault(); window.cuttlefish.setDisplayMode('fullscreen'); return; }

    const map = {
      Escape: 'back',
      Home: 'home',
      F5: 'restartScrcpy',
      F9: 'screenshot',
      F11: 'fullscreenWindow',
    };
    const action = map[e.key];
    if (action && window.cuttlefish[action]) {
      e.preventDefault();
      window.cuttlefish[action]();
    }
  });

  /* ─── Titan API backend status ─── */

  const ftApi    = document.getElementById('ft-api');
  const apiDot   = document.getElementById('api-dot');
  const apiLabel = document.getElementById('api-label');
  const ftDevice = document.getElementById('ft-device');

  function updateApiStatus(health) {
    if (!ftApi) return;
    if (health.connected) {
      const allOk = health.status === 'ok';
      ftApi.className = 'ft-api ' + (allOk ? 'api-ok' : 'api-warn');
      const parts = ['API'];
      if (health.adb?.ok) parts.push(`ADB:${health.adb.devices || 0}`);
      if (health.disk)    parts.push(`Disk:${health.disk.free_gb || '?'}G`);
      if (health.memory)  parts.push(`Mem:${health.memory.available_gb || '?'}G`);
      apiLabel.textContent = parts.join(' · ');
    } else {
      ftApi.className = 'ft-api api-off';
      apiLabel.textContent = 'API Offline';
    }
  }

  // Listen for periodic health broadcasts from main process
  window.cuttlefish.onTitanHealth(health => updateApiStatus(health));

  // Fetch initial health + device info
  window.cuttlefish.titanHealth().then(h => updateApiStatus(h)).catch(() => {});
  window.cuttlefish.titanDevice().then(dev => {
    if (dev && ftDevice) {
      const model = dev.config?.model?.replace(/_/g, ' ') || 'Android 14';
      const serial = dev.adb_target || '0.0.0.0:6520';
      ftDevice.textContent = `${model} · ${serial}`;
    }
  }).catch(() => {});

  /* ─── Initial state ─── */

  setConnectionState('connecting');
  try {
    setDisplayMode(await window.cuttlefish.getDisplayMode());
  } catch {
    setDisplayMode('phone');
  }
});
