    var VIDEO_ID = "{{VIDEO_ID}}";

    // file:// fallback – YouTube embeds require HTTP; overlay instructions on the left panel
    (function () {
      if (window.location.protocol !== 'file:') return;
      if (window.self !== window.top) return;  // suppress when loaded in iframe

      var rawPath = window.location.pathname;
      var dir = decodeURIComponent(rawPath.replace(/\/[^/]+$/, ''));
      var parts = rawPath.split('/');
      var file = parts[parts.length - 1];
      var parent = parts[parts.length - 2];
      var urlPath = (parent === 'reports') ? 'reports/' + file : file;
      var localUrl = 'http://localhost:8765/' + urlPath;
      var serveDir = (parent === 'reports') ? dir.replace(/\/reports$/, '') : dir;
      var cmd = 'python3 -m http.server 8765 --directory "' + serveDir.replace(/"/g, '\\"') + '"';

      function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

      var notice = document.createElement('div');
      notice.id = 'fl-notice';
      notice.setAttribute('style',
        'position:absolute;inset:0;z-index:100;' +
        'background:var(--left-bg);color:var(--left-text);' +
        'display:flex;flex-direction:column;align-items:center;justify-content:flex-start;overflow-y:auto;' +
        'padding:2rem 1.5rem;' +
        'font-family:"DM Sans",system-ui,sans-serif;'
      );

      notice.innerHTML =
        '<div style="width:100%;max-width:360px;display:flex;flex-direction:column;gap:22px;margin:auto 0;">' +

        // ── Header: icon + title + description ──────────────────────────────────
        '<div style="text-align:center;display:flex;flex-direction:column;align-items:center;gap:14px;">' +
        '<div style="width:46px;height:46px;background:var(--video-bg);border:1px solid var(--left-border);border-radius:10px;display:flex;align-items:center;justify-content:center;">' +
        '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.55">' +
        '<rect x="2" y="2" width="20" height="20" rx="5"/>' +
        '<polygon points="10,7.5 17,12 10,16.5" fill="currentColor" stroke="none"/>' +
        '</svg>' +
        '</div>' +
        '<div>' +
        '<p style="font-size:15px;font-weight:600;color:var(--left-text);margin:0 0 6px;line-height:1.3;">Serve to enable video playback</p>' +
        '<p style="font-size:12px;color:var(--left-meta);line-height:1.65;max-width:290px;margin:0 auto;">' +
        'YouTube blocks embeds opened via\u00a0' +
        '<code style="font-size:10.5px;background:var(--left-border);padding:1px 5px;border-radius:3px;font-family:monospace">file://</code>' +
        '.\u00a0Start a local HTTP server to enable playback.' +
        '</p>' +
        '</div>' +
        '</div>' +

        // ── Step 1: Start server ─────────────────────────────────────────────────
        '<div style="display:flex;flex-direction:column;gap:8px;">' +
        '<p style="font-size:10px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--left-heading);margin:0;">' +
        '\u2460\u00a0Start server' +
        '</p>' +
        '<div style="background:var(--video-bg);border:1px solid var(--left-border);border-radius:8px;padding:10px 12px;display:flex;align-items:flex-start;gap:10px;">' +
        '<code id="fl-cmd" style="flex:1;font-size:11px;font-family:\'SF Mono\',\'Fira Code\',\'Menlo\',monospace;line-height:1.65;word-break:break-all;user-select:all;color:var(--left-text);">' + esc(cmd) + '</code>' +
        '<button id="fl-copy" style="flex-shrink:0;margin-top:2px;padding:5px 11px;font-size:11px;font-family:inherit;font-weight:500;background:var(--toggle-bg);color:var(--toggle-text);border:none;border-radius:5px;cursor:pointer;white-space:nowrap;">Copy</button>' +
        '</div>' +
        '</div>' +

        // ── Step 2: Open report ──────────────────────────────────────────────────
        '<div style="display:flex;flex-direction:column;gap:8px;">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;">' +
        '<p style="font-size:10px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--left-heading);margin:0;">' +
        '\u2461\u00a0Open report' +
        '</p>' +
        '<div style="font-size:10.5px;color:var(--left-meta);display:flex;align-items:center;gap:4px;">' +
        '<span id="fl-dot" style="font-size:8px;line-height:1">\u25cf</span>' +
        '<span id="fl-stxt">Checking\u2026</span>' +
        '</div>' +
        '</div>' +
        '<a id="fl-open" href="' + esc(localUrl) + '" style="display:flex;align-items:center;justify-content:center;padding:11px 16px;background:var(--left-link);color:#fff;text-decoration:none;border-radius:8px;font-size:13px;font-weight:500;opacity:0.3;pointer-events:none;transition:opacity 0.25s ease;">' +
        'Open localhost:8765 \u2197' +
        '</a>' +
        '<div id="fl-cd" style="text-align:center;font-size:11px;color:var(--left-meta);min-height:18px;display:flex;align-items:center;justify-content:center;gap:8px;"></div>' +
        '</div>' +

        '</div>';

      document.querySelector('.video-wrap').appendChild(notice);

      // ── Copy to clipboard ────────────────────────────────────────────────────
      var copyBtn = document.getElementById('fl-copy');
      copyBtn.addEventListener('click', function () {
        function onCopied() {
          copyBtn.textContent = 'Copied \u2713';
          copyBtn.style.background = 'rgba(39,174,96,0.15)';
          copyBtn.style.color = '#27ae60';
          setTimeout(function () {
            copyBtn.textContent = 'Copy';
            copyBtn.style.background = 'var(--toggle-bg)';
            copyBtn.style.color = 'var(--toggle-text)';
          }, 2000);
        }
        if (navigator.clipboard) {
          navigator.clipboard.writeText(cmd).then(onCopied);
        } else {
          var r = document.createRange();
          r.selectNode(document.getElementById('fl-cmd'));
          window.getSelection().removeAllRanges();
          window.getSelection().addRange(r);
          try { document.execCommand('copy'); } catch (e) { }
          onCopied();
        }
      });

      // ── Localhost server detection ───────────────────────────────────────────
      var dotEl = document.getElementById('fl-dot');
      var stxtEl = document.getElementById('fl-stxt');
      var openBtn = document.getElementById('fl-open');
      var cdEl = document.getElementById('fl-cd');
      var serverUp = false, cdTimer = null, pollTimer = null;

      function enableOpen() {
        openBtn.style.opacity = '1';
        openBtn.style.pointerEvents = 'auto';
      }

      function setStatus(up) {
        dotEl.style.color = up ? '#27ae60' : 'var(--left-meta)';
        stxtEl.textContent = up ? 'Running \u2713' : 'Not running';
      }

      function startCountdown() {
        if (cdTimer) return;
        var s = 5;
        function tick() {
          if (s <= 0) { clearInterval(cdTimer); window.location.href = localUrl; return; }
          cdEl.innerHTML =
            'Opening in ' + s + 's\u2026\u00a0' +
            '<button id="fl-stay" style="background:none;border:none;font:inherit;font-size:11px;color:var(--left-link);cursor:pointer;padding:0;text-decoration:underline;">Stay</button>';
          document.getElementById('fl-stay').addEventListener('click', cancelCd);
          s--;
        }
        tick();
        cdTimer = setInterval(tick, 1000);
      }

      function cancelCd() {
        if (cdTimer) { clearInterval(cdTimer); cdTimer = null; }
        cdEl.innerHTML = '';
      }

      function checkServer() {
        fetch('http://localhost:8765/', { mode: 'no-cors', cache: 'no-store' })
          .then(function () {
            if (serverUp) return;
            serverUp = true;
            clearInterval(pollTimer);
            setStatus(true);
            enableOpen();
            startCountdown();
          })
          .catch(function () {
            if (!serverUp) setStatus(false);
          });
      }

      checkServer();
      pollTimer = setInterval(checkServer, 2000);
    })();

    // Theme toggle
    (function () {
      var html = document.documentElement;
      var btn = document.getElementById('theme-toggle');
      var icon = document.getElementById('theme-icon');

      var sunPath = '<circle cx="12" cy="12" r="4.5"/><line x1="12" y1="2" x2="12" y2="4.5"/><line x1="12" y1="19.5" x2="12" y2="22"/><line x1="4.22" y1="4.22" x2="5.87" y2="5.87"/><line x1="18.13" y1="18.13" x2="19.78" y2="19.78"/><line x1="2" y1="12" x2="4.5" y2="12"/><line x1="19.5" y1="12" x2="22" y2="12"/><line x1="4.22" y1="19.78" x2="5.87" y2="18.13"/><line x1="18.13" y1="5.87" x2="19.78" y2="4.22"/>';
      var moonPath = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';

      function applyTheme(dark) {
        if (dark) {
          html.setAttribute('data-theme', 'dark');
          icon.innerHTML = sunPath;
        } else {
          html.removeAttribute('data-theme');
          icon.innerHTML = moonPath;
        }
      }

      // Fall back to the OS preference on a first visit, as the gallery does —
      // otherwise a dark-mode user gets a white report beside a dark gallery.
      var saved = localStorage.getItem('theme');
      applyTheme(saved
        ? saved === 'dark'
        : window.matchMedia('(prefers-color-scheme: dark)').matches);

      btn.addEventListener('click', function () {
        var isDark = html.getAttribute('data-theme') === 'dark';
        var next = !isDark;
        localStorage.setItem('theme', next ? 'dark' : 'light');
        applyTheme(next);
      });
    })();

    // Help modal
    (function () {
      var overlay = document.getElementById('help-overlay');
      var helpBtn = document.getElementById('help-btn');
      var closeBtn = document.getElementById('help-close');

      function openHelp() { overlay.classList.add('open'); }
      function closeHelp() { overlay.classList.remove('open'); }

      helpBtn.addEventListener('click', openHelp);
      closeBtn.addEventListener('click', closeHelp);
      overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeHelp();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeHelp();
      });
    })();

    // Shared meta (parsed once; reused by info modal and markdown export)
    var VL_META = (function () {
      try {
        var raw = document.getElementById('video-lens-meta').textContent;
        return JSON.parse(raw) || {};
      } catch (e) { return {}; }
    })();

    function formatDurationSeconds(s) {
      if (typeof s !== 'number' || !isFinite(s) || s < 0) return null;
      s = Math.round(s);
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      var sec = s % 60;
      if (h > 0) return h + 'h ' + String(m).padStart(2, '0') + 'm ' + String(sec).padStart(2, '0') + 's';
      if (m > 0) return m + 'm ' + String(sec).padStart(2, '0') + 's';
      return sec + 's';
    }

    function formatGeneratedAtLocal(iso) {
      if (!iso) return null;
      var d = new Date(iso);
      if (isNaN(d.getTime())) return null;
      try {
        return d.toLocaleString(undefined, {
          year: 'numeric', month: 'short', day: '2-digit',
          hour: '2-digit', minute: '2-digit'
        });
      } catch (e) { return iso; }
    }

    // Info modal
    (function () {
      var overlay = document.getElementById('info-overlay');
      var infoBtn = document.getElementById('info-btn');
      var closeBtn = document.getElementById('info-close');

      var model = VL_META.agentModel || VL_META.modelName || null;
      var generated = formatGeneratedAtLocal(VL_META.generatedAt);
      var duration = formatDurationSeconds(VL_META.durationSeconds);

      if (model) document.getElementById('info-model').textContent = model;
      if (generated) document.getElementById('info-generated').textContent = generated;
      if (duration) document.getElementById('info-duration').textContent = duration;

      function openInfo() { overlay.classList.add('open'); }
      function closeInfo() { overlay.classList.remove('open'); }

      infoBtn.addEventListener('click', openInfo);
      closeBtn.addEventListener('click', closeInfo);
      overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeInfo();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeInfo();
      });
    })();

    // YT IFrame API
    var ytPlayer;
    var pendingSeek = null;
    var ytControlsVisible = false;
    var ccEnabled = false;

    function toggleFullscreen() {
      var el = document.querySelector('.video-wrap');
      if (document.fullscreenElement || document.webkitFullscreenElement) {
        (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      } else {
        (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
      }
    }

    function syncFullscreenBtn() {
      var active = !!(document.fullscreenElement || document.webkitFullscreenElement);
      // In fullscreen give YouTube native controls; restore custom overlay when exiting
      if (!ytControlsVisible) {
        document.getElementById('yt-overlay').style.display = active ? 'none' : '';
      }
    }
    document.addEventListener('fullscreenchange', syncFullscreenBtn);
    document.addEventListener('webkitfullscreenchange', syncFullscreenBtn);

    function buildIframeSrc() {
      return 'https://www.youtube.com/embed/{{VIDEO_ID}}?enablejsapi=1&rel=0&controls='
        + (ytControlsVisible ? '1' : '0')
        + (ccEnabled ? '&cc_load_policy=1' : '');
    }

    function rebuildIframe(savedTime) {
      var oldIframe = document.getElementById('yt-player');
      var wrap = oldIframe.parentNode;
      var savedAllow = oldIframe.allow;
      if (ytPlayer && ytPlayer.destroy) ytPlayer.destroy();
      var newIframe = document.createElement('iframe');
      newIframe.id = 'yt-player';
      newIframe.allow = savedAllow;
      newIframe.allowFullscreen = true;
      newIframe.src = buildIframeSrc();
      wrap.appendChild(newIframe);
      pendingSeek = savedTime;
      ytPlayer = new YT.Player('yt-player', {
        events: {
          onReady: onPlayerReady,
          onStateChange: onPlayerStateChange,
          onError: onPlayerError
        }
      });
    }

    function toggleCaptions() {
      if (!ytPlayer) return;
      var savedTime = (ytPlayer.getCurrentTime) ? ytPlayer.getCurrentTime() : 0;
      ccEnabled = !ccEnabled;
      rebuildIframe(savedTime);
    }

    function onPlayerReady(e) {
      if (pendingSeek !== null) {
        e.target.seekTo(pendingSeek, true);
        e.target.playVideo();
        pendingSeek = null;
      }
    }

    function onPlayerStateChange(e) {
      document.getElementById('play-pause-btn').innerHTML = e.data === 1
        ? '<svg width="11" height="12" viewBox="0 0 11 12" fill="currentColor"><rect x="0" y="0" width="3.5" height="12" rx="1"/><rect x="7.5" y="0" width="3.5" height="12" rx="1"/></svg>'
        : '<svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor"><polygon points="0,0 10,6 0,12"/></svg>';
      document.body.classList.toggle('is-playing', e.data === 1);
    }

      function onPlayerError(e) {
        if (e.data !== 101 && e.data !== 150) return;  // only handle embed-disabled
        var wrap = document.querySelector('.video-wrap');
        wrap.innerHTML =
          '<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;' +
          'padding:24px;text-align:center;background:var(--video-bg);color:var(--left-text);gap:14px;">' +
          '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">' +
          '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
          '<strong style="font-size:15px;opacity:0.8">Embedding disabled by video owner</strong>' +
          '<span style="font-size:12px;opacity:0.55;max-width:280px">This video cannot be played here. Watch it directly on YouTube.</span>' +
          '<a href="{{VIDEO_URL}}" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:10px 20px;border-radius:6px;' +
          'background:var(--left-link);color:#fff;font-size:13px;font-weight:600;text-decoration:none;">Watch on YouTube</a>' +
          '</div>';
        // Hide controls since they're useless without a player
        document.getElementById('progress-track').style.display = 'none';
        document.querySelector('.ctrl-bar').style.display = 'none';
      }

      function onYouTubeIframeAPIReady() {
        ytPlayer = new YT.Player('yt-player', {
          events: {
            onReady: onPlayerReady,
            onStateChange: onPlayerStateChange,
            onError: onPlayerError
          }
        });
      }

      // Controls toggle
      document.getElementById('controls-toggle-btn').addEventListener('click', function () {
        var savedTime = (ytPlayer && ytPlayer.getCurrentTime) ? ytPlayer.getCurrentTime() : 0;
        ytControlsVisible = !ytControlsVisible;
        document.querySelector('.ctrl-bar').classList.toggle('yt-native', ytControlsVisible);
        document.getElementById('controls-toggle-btn').classList.toggle('active', ytControlsVisible);
        document.getElementById('yt-overlay').style.display = ytControlsVisible ? 'none' : '';
        rebuildIframe(savedTime);
      });

      // Timestamp links — seek via API instead of reloading src
      var links = document.querySelectorAll('a.ts');
      var topicItems = Array.from(links).map(function (a) {
        return { a: a, li: a.closest('li'), t: parseInt(a.getAttribute('data-t'), 10) };
      });

      function setActiveItem(li) {
        topicItems.forEach(function (item) { item.li.classList.remove('active'); });
        if (li) {
          li.classList.add('active');
          li.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      }

      function seekToTimestamp(t, li) {
        if (ytPlayer && ytPlayer.seekTo) {
          ytPlayer.seekTo(t, true);
          ytPlayer.playVideo();
        } else {
          pendingSeek = t;
        }
        setActiveItem(li);
        document.querySelector('.left').scrollIntoView({ behavior: 'smooth', block: 'start' });
      }

      links.forEach(function (a) {
        a.addEventListener('click', function (e) {
          e.preventDefault();
          seekToTimestamp(parseInt(this.getAttribute('data-t'), 10), this.closest('li'));
        });
      });

      function setExpanded(li, on) {
        li.classList.toggle('expanded', on);
        if (li.hasAttribute('aria-expanded')) {
          li.setAttribute('aria-expanded', on ? 'true' : 'false');
        }
      }

      function activateTopic(item) {
        if (item.li.querySelector('.outline-detail')) {
          var wasExpanded = item.li.classList.contains('expanded');
          // Accordion: collapse all manually-expanded items
          document.querySelectorAll('ol.topics li.expanded').forEach(function (li) {
            setExpanded(li, false);
          });
          // Toggle this one (if it was already expanded, it stays collapsed)
          if (!wasExpanded) setExpanded(item.li, true);
        } else {
          seekToTimestamp(item.t, item.li);
        }
      }

      topicItems.forEach(function (item) {
        // Disclosure semantics are added here rather than in the payload so the
        // renderer's attribute allowlist does not have to admit them.
        if (item.li.querySelector('.outline-detail')) {
          item.li.setAttribute('role', 'button');
          item.li.setAttribute('tabindex', '0');
          item.li.setAttribute('aria-expanded', 'false');
        }
        item.li.addEventListener('click', function (e) {
          if (e.target.closest('a.ts')) return; // timestamp click seeks via link handler
          activateTopic(item);
        });
        item.li.addEventListener('keydown', function (e) {
          if (e.target.closest('a.ts')) return; // let the timestamp link keep Enter
          if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
          e.preventDefault();  // Space would otherwise scroll the page
          activateTopic(item);
        });
      });

      // Auto-sync outline with video position
      setInterval(function () {
        if (!ytPlayer || !ytPlayer.getCurrentTime) return;
        var cur = ytPlayer.getCurrentTime();
        var active = null;
        topicItems.forEach(function (item) {
          if (item.t <= cur) active = item.li;
        });
        // Only update if it changed
        var current = document.querySelector('ol.topics li.active');
        if (active !== current) setActiveItem(active);
        var dur = ytPlayer.getDuration ? ytPlayer.getDuration() : 0;
        if (dur > 0) {
          document.getElementById('progress-fill').style.width = (cur / dur * 100) + '%';
        }
      }, 1000);

      // Speed buttons
      var speedBtns = document.querySelectorAll('.speed-btn');
      speedBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var rate = parseFloat(this.getAttribute('data-speed'));
          if (ytPlayer && ytPlayer.setPlaybackRate) ytPlayer.setPlaybackRate(rate);
          speedBtns.forEach(function (b) { b.classList.remove('active'); });
          this.classList.add('active');
        });
      });


      document.getElementById('play-pause-btn').addEventListener('click', function () {
        if (!ytPlayer || !ytPlayer.getPlayerState) return;
        ytPlayer.getPlayerState() === 1 ? ytPlayer.pauseVideo() : ytPlayer.playVideo();
      });

      // Overlay intercepts clicks on the video area so the iframe never steals keyboard focus
      document.getElementById('yt-overlay').addEventListener('click', function () {
        if (!ytPlayer || !ytPlayer.getPlayerState) return;
        ytPlayer.getPlayerState() === 1 ? ytPlayer.pauseVideo() : ytPlayer.playVideo();
        document.body.focus();
      });

      // Seek ±5s
      document.getElementById('seek-back').addEventListener('click', function () {
        if (ytPlayer && ytPlayer.getCurrentTime)
          ytPlayer.seekTo(Math.max(0, ytPlayer.getCurrentTime() - 5), true);
      });
      document.getElementById('seek-fwd').addEventListener('click', function () {
        if (ytPlayer && ytPlayer.getCurrentTime)
          ytPlayer.seekTo(ytPlayer.getCurrentTime() + 5, true);
      });

      // Live time display
      function formatTime(s) {
        s = Math.floor(s || 0);
        var h = Math.floor(s / 3600);
        var m = Math.floor((s % 3600) / 60);
        var sec = s % 60;
        if (h > 0)
          return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
        return m + ':' + String(sec).padStart(2, '0');
      }
      setInterval(function () {
        if (!ytPlayer || !ytPlayer.getCurrentTime) return;
        var cur = ytPlayer.getCurrentTime();
        var dur = ytPlayer.getDuration();
        var el = document.getElementById('time-display');
        if (el) el.textContent = formatTime(cur) + ' / ' + (dur > 0 ? formatTime(dur) : '–:––');
      }, 500);

      (function () {
        var track = document.getElementById('progress-track');
        var fill = document.getElementById('progress-fill');
        var dragging = false;
        var dragRect;

        function seekByEvent(e) {
          if (!ytPlayer || !ytPlayer.getDuration) return;
          var pct = Math.min(1, Math.max(0, (e.clientX - dragRect.left) / dragRect.width));
          ytPlayer.seekTo(ytPlayer.getDuration() * pct, true);
          ytPlayer.playVideo();
        }

        track.addEventListener('mousedown', function (e) {
          dragging = true;
          dragRect = track.getBoundingClientRect();
          fill.style.transition = 'none';
          seekByEvent(e);
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });

        function onMove(e) {
          if (!dragging) return;
          seekByEvent(e);
        }

        function onUp() {
          dragging = false;
          fill.style.transition = '';
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
        }
      })();

      (function () {
        var navLinks = document.querySelectorAll('.section-nav a');
        var clicking = false;
        var clickTimer = null;
        navLinks.forEach(function (a) {
          a.addEventListener('click', function () {
            navLinks.forEach(function (l) { l.classList.remove('active'); });
            this.classList.add('active');
            clicking = true;
            clearTimeout(clickTimer);
            clickTimer = setTimeout(function () { clicking = false; }, 1000);
          });
        });
        var rightEl = document.querySelector('.right');
        var sections = Array.from(document.querySelectorAll('.right section'));
        var hasScrolled = false;
        rightEl.addEventListener('scroll', function () { hasScrolled = true; }, { once: true });
        var io = new IntersectionObserver(function (entries) {
          if (!hasScrolled || clicking) return;
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              var id = entry.target.id;
              navLinks.forEach(function (a) {
                a.classList.toggle('active', a.getAttribute('href') === '#' + id);
              });
            }
          });
        }, { root: rightEl, threshold: 0, rootMargin: '0px 0px -75% 0px' });
        sections.forEach(function (s) { io.observe(s); });
      })();

      var SECTION_TOOLTIPS = {
        'summary': 'A short overview of the video\'s core argument and conclusion.',
        'takeaway': 'The one thing to take away — going further than the summary.',
        'key-points': 'Key concepts and insights — each with analytical depth added.'
      };

      // Open all links in the YouTube description in a new tab
      document.querySelectorAll('.video-description a').forEach(function (a) {
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
      });

      document.querySelectorAll('.right section').forEach(function (sec) {
        var h2 = sec.querySelector('h2');
        if (!h2) return;

        // Info button
        var infoTooltip = SECTION_TOOLTIPS[sec.id];
        if (infoTooltip) {
          var infoBtn = document.createElement('button');
          infoBtn.className = 'section-info';
          infoBtn.textContent = 'ⓘ';
          infoBtn.setAttribute('data-tooltip', infoTooltip);
          infoBtn.setAttribute('aria-label', infoTooltip);
          h2.appendChild(infoBtn);
        }
      });

      // Walk a node to Markdown so the <strong>/<em>/<code> structure the skill
      // is asked to produce survives the export instead of flattening to prose.
      function mdInline(node) {
        if (!node) return '';
        return Array.from(node.childNodes).map(function (n) {
          if (n.nodeType === 3) return n.textContent;
          if (n.nodeType !== 1) return '';
          var inner = mdInline(n);
          switch (n.tagName) {
            case 'STRONG': case 'B': return '**' + inner.trim() + '**';
            case 'EM': case 'I':     return '*' + inner.trim() + '*';
            case 'CODE':             return '`' + inner.trim() + '`';
            case 'BR':               return '\n';
            default:                 return inner;
          }
        }).join('').replace(/[ \t]+/g, ' ').trim();
      }

      document.getElementById('md-export-btn').addEventListener('click', function () {
        // Title
        var title = document.querySelector('h1').innerText;

        // Meta line — strip the "Open on YouTube ↗" link text, keep the rest
        var metaEl = document.querySelector('.meta-line');
        var factsEl = metaEl.querySelector('.meta-facts');
        var metaText = (factsEl ? factsEl.textContent : '').trim();
        var videoUrl = metaEl.querySelector('a') ? metaEl.querySelector('a').href : '';

        // Summary
        var summary = mdInline(document.querySelector('#summary p'));

        // Description (optional — only present when yt-dlp was used)
        var descEl = document.querySelector('.description-details .video-description');
        var description = descEl ? descEl.innerText.trim() : '';

        // Key Points
        var keyPoints = Array.from(document.querySelectorAll('#key-points li'))
          .map(function (li) {
            var detail = li.querySelector('p');
            var headlineSrc = document.createElement('span');
            Array.from(li.childNodes)
              .filter(function (n) { return n.nodeType === 3 || (n.nodeType === 1 && n.tagName !== 'P'); })
              .forEach(function (n) { headlineSrc.appendChild(n.cloneNode(true)); });
            var line = '- ' + mdInline(headlineSrc);
            if (detail) line += '\n  ' + mdInline(detail);
            return line;
          }).join('\n');

        // Takeaway
        var takeaway = mdInline(document.querySelector('#takeaway p'));

        // Outline — each li has data-t (seconds), .outline-title and optional .outline-detail
        var outline = Array.from(document.querySelectorAll('.topics li')).map(function (li) {
          var tsEl = li.querySelector('a.ts');
          var t = (tsEl ? tsEl.getAttribute('data-t') : null) || '0';
          var tsText = tsEl ? tsEl.innerText : '0:00';
          var titleEl = li.querySelector('.outline-title');
          var detailEl = li.querySelector('.outline-detail');
          var topicText = titleEl ? mdInline(titleEl) : li.innerText.replace(tsText, '').trim();
          var detail = mdInline(detailEl);
          var url = 'https://www.youtube.com/watch?v=' + VIDEO_ID + '&t=' + t;
          var line = '- [' + tsText + '](' + url + ') ' + topicText;
          if (detail) line += ' — ' + detail;
          return line;
        }).join('\n');

        // Generation footer — model, timestamp, duration (any/all may be missing)
        var genParts = [];
        if (VL_META.generatedAt) {
          var genStr = formatGeneratedAtLocal(VL_META.generatedAt);
          if (genStr) genParts.push('Generated ' + genStr);
        }
        var modelStr = VL_META.agentModel || VL_META.modelName;
        if (modelStr) genParts.push('with ' + modelStr);
        var durStr = formatDurationSeconds(VL_META.durationSeconds);
        if (durStr) genParts.push('in ' + durStr);
        var genFooter = genParts.length
          ? ['', '---', '', '*' + genParts.join(' · ') + ' · [video-lens](https://github.com/kar2phi/video-lens)*']
          : [];

        var md = [
          '# ' + title,
          '',
          metaText,
          videoUrl ? '[Watch on YouTube](' + videoUrl + ')' : '',
          '',
          '> Generated by the [video-lens](https://github.com/kar2phi/video-lens) Claude skill.',
          '',
          '---',
          '',
          '## Outline',
          '',
          outline,
          '',
          '## Summary',
          '',
          summary,
          '',
          '## Takeaway',
          '',
          takeaway,
          '',
          '## Key Points',
          '',
          keyPoints,
        ].concat(description ? ['', '## YouTube Description', '', description] : [])
         .concat(genFooter)
         .join('\n');

        // Trigger download
        var blob = new Blob([md], { type: 'text/markdown' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = window.location.pathname.split('/').pop().replace(/\.html$/, '.md');
        // Anchor must be in the document, and the URL must outlive the click —
        // revoking synchronously cancels the download outside Chrome.
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        setTimeout(function () {
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }, 0);
      });

      function cycleSpeed(dir) {
        var speeds = [1, 1.25, 1.5, 1.75, 2];
        var active = document.querySelector('.speed-btn.active');
        if (!active) return;
        var idx = speeds.indexOf(parseFloat(active.getAttribute('data-speed')));
        var next = speeds[Math.max(0, Math.min(speeds.length - 1, idx + dir))];
        if (ytPlayer && ytPlayer.setPlaybackRate) ytPlayer.setPlaybackRate(next);
        speedBtns.forEach(function (b) { b.classList.remove('active'); });
        document.querySelector('.speed-btn[data-speed="' + next + '"]').classList.add('active');
      }

      document.addEventListener('keydown', function (e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.key === ' ' || e.key === 'k') {
          e.preventDefault();
          if (ytPlayer && ytPlayer.getPlayerState) {
            ytPlayer.getPlayerState() === 1 ? ytPlayer.pauseVideo() : ytPlayer.playVideo();
          }
        } else if (e.key === 'j' || e.key === 'ArrowLeft') {
          if (ytPlayer && ytPlayer.getCurrentTime)
            ytPlayer.seekTo(Math.max(0, ytPlayer.getCurrentTime() - 5), true);
        } else if (e.key === 'l' || e.key === 'ArrowRight') {
          if (ytPlayer && ytPlayer.getCurrentTime)
            ytPlayer.seekTo(ytPlayer.getCurrentTime() + 5, true);
        } else if (e.key === 'c') {
          toggleCaptions();
        } else if (e.key === 'f') {
          e.preventDefault();
          toggleFullscreen();
        } else if (e.key === '<' || e.key === ',') {
          cycleSpeed(-1);
        } else if (e.key === '>' || e.key === '.') {
          cycleSpeed(1);
        } else if (e.key === '1') {
          applySplit(30);
        } else if (e.key === '2') {
          applySplit(45);
        } else if (e.key === '3') {
          applySplit(maxVideoSplit());
        }
      });

      // Draggable resizer + split presets
      var resizer = document.getElementById('resizer');
      var layout = document.querySelector('.layout');
      var SPLIT_KEY = 'video-lens:split';
      var DEFAULT_SPLIT = 45;

      // Restore saved split on load
      (function () {
        var saved = localStorage.getItem(SPLIT_KEY);
        if (saved) document.documentElement.style.setProperty('--left-w', saved + '%');
      })();

      resizer.addEventListener('mousedown', function (e) {
        e.preventDefault();
        resizer.classList.add('dragging');
        document.addEventListener('mousemove', onDrag);
        document.addEventListener('mouseup', stopDrag);
      });
      resizer.addEventListener('dblclick', function () {
        document.documentElement.style.setProperty('--left-w', DEFAULT_SPLIT + '%');
        localStorage.removeItem(SPLIT_KEY);
      });

      function onDrag(e) {
        var pct = (e.clientX / window.innerWidth) * 100;
        pct = Math.min(Math.max(pct, 20), maxVideoSplit());
        document.documentElement.style.setProperty('--left-w', pct + '%');
      }

      function stopDrag() {
        resizer.classList.remove('dragging');
        document.removeEventListener('mousemove', onDrag);
        document.removeEventListener('mouseup', stopDrag);
        var cur = document.documentElement.style.getPropertyValue('--left-w');
        if (cur) localStorage.setItem(SPLIT_KEY, parseFloat(cur).toFixed(1));
      }

      // Split preset buttons
      // L is dynamic: the exact panel % where the video fills height without letterboxing
      function maxVideoSplit() {
        var maxH = window.innerHeight - 220; // matches the calc(100vh - 220px) cap in CSS
        var maxW = maxH * 16 / 9;
        return Math.min(80, Math.max(20, (maxW / window.innerWidth) * 100));
      }

      function applySplit(pct) {
        layout.classList.add('snapping');
        document.documentElement.style.setProperty('--left-w', pct + '%');
        localStorage.setItem(SPLIT_KEY, pct.toFixed(1));
        setTimeout(function () { layout.classList.remove('snapping'); }, 250);
      }
