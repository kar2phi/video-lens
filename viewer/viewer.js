// video-lens viewer: one script for the local report and the share page (035 §4, 036).
// The same bytes on every page. Everything it needs is in the markup:
//   #yt-facade[data-video-id]   the player box; with data-autoload the player loads at once
//   ol.topics[data-duration]    the outline: li > a.ts[data-t], .outline-title, .outline-detail
//   ol.kp-list > li             key points: strong, p (why), p (detail); optional a.ts[data-t]
// It never reads the mode. It creates no style attribute, style element or script text, so the
// share page's CSP (style-src 'self') holds. Without it the page is fully readable and every
// time link opens YouTube.
(function () {
  "use strict";

  var root = document.documentElement;
  var KEYS = {
    theme: "theme", // shared with the gallery
    split: "video-lens:split",
    speed: "video-lens:speed",
    skim: "video-lens:skim",
    outline: "video-lens:outline",
  };
  var DEFAULT_SPLIT = 44;
  var MIN_SPLIT = 22;
  var RATES = [1, 1.25, 1.5, 1.75, 2];

  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function write(key, value) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch (e) { /* private mode: the choice lasts for this page only */ }
  }

  // ── Before the first paint: saved choices, so nothing jumps after load ──
  root.classList.add("js");
  root.setAttribute("data-tab", "read");
  var savedTheme = read(KEYS.theme);
  if (savedTheme === "dark" || savedTheme === "light") root.setAttribute("data-theme", savedTheme);
  var savedSplit = parseFloat(read(KEYS.split));
  if (savedSplit >= MIN_SPLIT && savedSplit <= 80) root.style.setProperty("--split", savedSplit + "%");
  if (read(KEYS.skim) === "1") root.setAttribute("data-skim", "");
  if (read(KEYS.outline) === "full") root.setAttribute("data-outline", "full");

  function $(id) { return document.getElementById(id); }
  function all(selector, scope) { return Array.prototype.slice.call((scope || document).querySelectorAll(selector)); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }
  function clock(t) {
    t = Math.max(0, Math.floor(t || 0));
    var h = Math.floor(t / 3600);
    var m = Math.floor((t % 3600) / 60);
    var s = String(t % 60).padStart(2, "0");
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + s : m + ":" + s;
  }

  // ── The player adapter (035 §4.3): the only code that touches YouTube ──
  // One implementation for both modes. The page decides with data-autoload whether the player
  // loads at once (local) or on the first click on the panel or on a time (share).
  function makePlayer(facade) {
    var videoId = facade && facade.getAttribute("data-video-id");
    if (videoId && !/^[A-Za-z0-9_-]{11}$/.test(videoId)) videoId = null;
    var frame = null;
    var api = null;
    var ready = false;
    var pending = null;
    var captions = false;
    var listeners = [];

    function tell(state) { listeners.forEach(function (cb) { cb(state); }); }
    function fail() {
      // Embedding is off for this video, or the player cannot run here: the same box the share
      // page renders for a "noembed" video. From here on every time link opens YouTube.
      var id = videoId;
      api = null; frame = null; ready = false; videoId = null;
      facade.textContent = "";
      facade.classList.remove("loaded");
      facade.classList.add("noembed");
      var link = el("a", "watch-link", "Watch on YouTube ↗");
      link.href = "https://www.youtube.com/watch?v=" + id;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      facade.appendChild(link);
      tell("failed");
    }

    var player = {
      available: function () { return !!videoId; },
      loaded: function () { return !!frame; },
      ready: function () { return ready; },
      frame: function () { return frame; },
      onState: function (cb) { listeners.push(cb); },
      load: function (start, autoplay) {
        if (frame || !videoId) return;
        var src = "https://www.youtube-nocookie.com/embed/" + videoId + "?enablejsapi=1&rel=0&playsinline=1";
        if (/^https?:/.test(location.origin)) src += "&origin=" + encodeURIComponent(location.origin);
        if (autoplay) src += "&autoplay=1";
        if (start) src += "&start=" + start;
        frame = document.createElement("iframe");
        frame.id = "yt-player";
        frame.title = "YouTube video player";
        frame.src = src;
        frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
        frame.setAttribute("allowfullscreen", "");
        facade.textContent = "";
        facade.classList.add("loaded");
        facade.appendChild(frame);
        function attach() {
          api = new window.YT.Player(frame, {
            events: {
              onReady: function () {
                ready = true;
                tell("ready");
                if (pending !== null) player.seek(pending);
                pending = null;
              },
              onStateChange: function (e) { tell(e.data === 1 ? "playing" : "idle"); },
              onError: fail,
            },
          });
        }
        if (window.YT && window.YT.Player) attach();
        else {
          window.onYouTubeIframeAPIReady = attach;
          var script = document.createElement("script");
          script.src = "https://www.youtube.com/iframe_api";
          document.head.appendChild(script);
        }
      },
      seek: function (t) {
        if (ready) { api.seekTo(t, true); api.playVideo(); }
        else if (frame) pending = t;
        else player.load(t, true);
      },
      shift: function (dt) { if (ready) api.seekTo(Math.max(0, api.getCurrentTime() + dt), true); },
      toggle: function () {
        if (!ready) return false;
        if (api.getPlayerState() === 1) api.pauseVideo(); else api.playVideo();
        return true;
      },
      time: function () { return ready && api.getCurrentTime ? api.getCurrentTime() : 0; },
      duration: function () { return ready && api.getDuration ? api.getDuration() : 0; },
      rate: function (r) { if (ready) api.setPlaybackRate(r); },
      mute: function () { if (ready) { if (api.isMuted()) api.unMute(); else api.mute(); } },
      captions: function () {
        if (!ready) return;
        captions = !captions;
        try {
          if (captions) api.loadModule("captions"); else api.unloadModule("captions");
        } catch (e) { /* the player's own CC button still works */ }
      },
      fullscreen: function () {
        if (!frame) return;
        // iPhone Safari has no element fullscreen API on a div; the player's own button still works.
        var exit = document.exitFullscreen || document.webkitExitFullscreen;
        var enter = facade.requestFullscreen || facade.webkitRequestFullscreen;
        if (document.fullscreenElement || document.webkitFullscreenElement) {
          if (exit) exit.call(document);
        } else if (enter) {
          var p = enter.call(facade);
          if (p && p.catch) p.catch(function () { /* refused: nothing to undo */ });
        }
      },
    };
    return player;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var layout = document.querySelector(".layout");
    var facade = $("yt-facade");
    var player = makePlayer(facade);
    var outlineEl = $("outline");
    var list = document.querySelector(".topics");
    var knownDuration = list ? parseInt(list.getAttribute("data-duration"), 10) || 0 : 0;

    var sections = all(".topics > li").map(function (li) {
      var link = li.querySelector("a.ts[data-t]");
      var title = li.querySelector(".outline-title");
      return { li: li, t: link ? parseInt(link.getAttribute("data-t"), 10) || 0 : 0, title: title ? title.textContent : "" };
    });
    var points = all(".kp-list > li").map(function (li, i) {
      var link = li.querySelector(":scope > a.ts[data-t]");
      var paras = all(":scope > p", li);
      li.id = "kp-" + (i + 1);
      // New fragments: strong, p (why), p (detail). Reports written before 036: strong, bare text, p (detail).
      return { li: li, n: i + 1, t: link ? parseInt(link.getAttribute("data-t"), 10) : null,
        why: paras.length > 1 ? paras[0] : null, detail: paras.length > 1 ? paras[1] : null, only: paras.length === 1 ? paras[0] : null };
    });

    var active = -1;
    var started = false; // no section is "playing" until the video has run or a time was chosen
    var hold = null;     // a time just asked for; shown until the player reports it (or 5 s pass)
    var holdUntil = 0;
    var rate = parseFloat(read(KEYS.speed));
    if (RATES.indexOf(rate) < 0) rate = 1;

    function total() { return player.duration() || knownDuration; }
    function inView() {
      var r = facade.getBoundingClientRect();
      var visible = Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0);
      return visible >= r.height / 2;
    }
    function go(t) {
      // The player must be in view before it starts (YouTube: autoplay only when visible).
      if (!inView()) facade.scrollIntoView({ block: "start" });
      player.seek(t);
      started = true;
      hold = t;
      holdUntil = Date.now() + 5000;
      setActive(indexAt(t));
      paint(t);
    }
    function hint() {
      // Playback keys before the click that loads the player: point at the button, load nothing.
      var button = facade && facade.querySelector(".load");
      if (!button) return;
      button.classList.remove("nudge");
      void button.offsetWidth;
      button.classList.add("nudge");
    }

    // ── Outline, timeline and the now-playing bar ──
    function indexAt(t) {
      var found = -1;
      for (var i = 0; i < sections.length; i++) if (sections[i].t <= t) found = i;
      return found;
    }
    function endOf(i) {
      if (i + 1 < sections.length) return sections[i + 1].t;
      var d = total();
      if (d > sections[i].t) return d;
      return sections[i].t + (i ? sections[i].t / i : 60); // unknown length: an average section
    }

    var segs = [];
    var timeline = null;
    if (sections.length > 1 && player.available()) {
      timeline = el("div", "timeline");
      timeline.setAttribute("aria-hidden", "true"); // the outline is the accessible list
      sections.forEach(function (sec, i) {
        var seg = el("div", "seg");
        seg.title = clock(sec.t) + "  " + sec.title;
        seg.style.flexGrow = String(Math.max(1, endOf(i) - sec.t));
        var fill = document.createElement("i");
        seg.appendChild(fill);
        timeline.appendChild(seg);
        segs.push({ seg: seg, fill: fill });
        seg.addEventListener("mouseenter", function () { showNow(i); });
        seg.addEventListener("click", function (e) {
          var r = seg.getBoundingClientRect();
          var part = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
          go(Math.floor(sec.t + part * (endOf(i) - sec.t)));
        });
      });
      timeline.addEventListener("mouseleave", function () { showNow(active); });
      facade.after(timeline);
    }

    var nowbar = document.querySelector(".nowbar");
    var speedBtn = $("speed");
    function showNow(i) {
      var sec = sections[i < 0 ? 0 : i];
      if (!sec) return;
      $("now-idx").textContent = (i < 0 ? 1 : i + 1) + "/" + sections.length;
      $("now-title").textContent = sec.title;
    }
    function setActive(i) {
      if (i === active) return;
      if (sections[active]) sections[active].li.classList.remove("active");
      active = i;
      var sec = sections[i];
      if (sec) {
        sec.li.classList.add("active");
        keepVisible(sec.li);
      }
      points.forEach(function (p) { p.li.classList.toggle("now", !!sec && p.t === sec.t); });
      showNow(i);
    }
    function keepVisible(li) {
      // Only inside the outline's own scroll box (wide layout), and not while the reader is in it.
      if (outlineEl.scrollHeight <= outlineEl.clientHeight || outlineEl.matches(":hover")) return;
      var head = outlineEl.querySelector(".sec-head");
      var top = li.offsetTop - (head ? head.offsetHeight : 0);
      var bottom = li.offsetTop + li.offsetHeight;
      if (top < outlineEl.scrollTop) outlineEl.scrollTop = top;
      else if (bottom > outlineEl.scrollTop + outlineEl.clientHeight) outlineEl.scrollTop = bottom - outlineEl.clientHeight + 8;
    }
    function paint(t) {
      var d = total();
      $("clock").textContent = player.ready() ? clock(t) + " / " + clock(d) : (d ? clock(d) : "");
      segs.forEach(function (s, i) {
        var done = i < active;
        s.seg.classList.toggle("done", done);
        var part = i === active ? (t - sections[i].t) / Math.max(1, endOf(i) - sections[i].t) : 0;
        s.fill.style.width = done ? "" : Math.min(100, Math.max(0, part * 100)) + "%";
      });
    }
    function tick() {
      if (!player.ready()) return;
      var t = player.time();
      if (hold !== null) {
        if (Math.abs(t - hold) < 3 || Date.now() > holdUntil) hold = null;
        else t = hold;
      }
      if (started) setActive(indexAt(t));
      paint(t);
    }
    setInterval(tick, 400);
    player.onState(function (state) {
      if (state === "ready" && rate !== 1) player.rate(rate);
      if (state === "playing") started = true;
      if (state === "failed") {
        if (timeline) timeline.remove();
        if (nowbar) nowbar.hidden = true;
        setActive(-1);
        return;
      }
      root.classList.toggle("playing", state === "playing");
      tick();
    });

    function step(dir) {
      if (!sections.length || !player.available()) return;
      var i = active;
      if (dir < 0) i = (i > 0 && player.time() - sections[i].t < 3) ? i - 1 : Math.max(0, i);
      else i = Math.min(sections.length - 1, i + 1);
      go(sections[i].t);
    }
    function setRate(next) {
      rate = next;
      write(KEYS.speed, rate === 1 ? null : String(rate));
      speedBtn.textContent = rate + "×";
      player.rate(rate);
    }
    function stepRate(dir) {
      var i = RATES.indexOf(rate) + dir;
      if (i >= 0 && i < RATES.length) setRate(RATES[i]);
    }

    if (nowbar && sections.length && player.available()) {
      nowbar.hidden = false;
      speedBtn.textContent = rate + "×";
      showNow(-1);
      paint(0);
      $("sec-prev").addEventListener("click", function () { step(-1); });
      $("sec-next").addEventListener("click", function () { step(1); });
      speedBtn.addEventListener("click", function () { setRate(RATES[(RATES.indexOf(rate) + 1) % RATES.length]); });
    }

    // A key point names its outline section; the section points back with the point's number.
    points.forEach(function (p) {
      if (p.t === null) return;
      var sec = sections.filter(function (s) { return s.t === p.t; })[0];
      if (!sec) return;
      var box = sec.li.querySelector(".kp-refs");
      if (!box) {
        box = el("span", "kp-refs");
        sec.li.appendChild(box);
      }
      var a = el("a", "kp-ref", String(p.n));
      a.href = "#" + p.li.id;
      a.title = "Key point " + p.n;
      box.appendChild(a);
    });

    // One click handler for every time on the page.
    document.addEventListener("click", function (e) {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var target = e.target instanceof Element ? e.target : null;
      if (!target) return;
      var ref = target.closest(".kp-ref");
      if (ref) {
        e.preventDefault();
        var kp = document.querySelector(ref.getAttribute("href"));
        if (!kp) return;
        setTab("read");
        kp.scrollIntoView({ block: "start", behavior: "smooth" });
        kp.classList.remove("flash");
        void kp.offsetWidth;
        kp.classList.add("flash");
        return;
      }
      if (!player.available()) return; // no player: the links open YouTube
      var timed = target.closest("a.ts[data-t]");
      if (!timed) {
        var row = target.closest(".topics > li");
        timed = row && row.querySelector("a.ts[data-t]");
      }
      if (!timed) return;
      var t = parseInt(timed.getAttribute("data-t"), 10);
      if (!(t >= 0)) return;
      e.preventDefault();
      // A clicked link must not keep the focus: Space is play and pause, not "open the link".
      if (e.detail > 0 && document.activeElement instanceof HTMLElement) document.activeElement.blur();
      go(t);
    });

    if (facade && player.available()) {
      var loadButton = facade.querySelector(".load");
      if (loadButton) loadButton.addEventListener("click", function () { player.load(0, true); });
      if (facade.hasAttribute("data-autoload")) {
        var note = $("file-note");
        if (location.protocol === "file:" && note) {
          // YouTube refuses to play from file://. The shell holds the text; fill in the command
          // and the link the way serve_report.sh serves this file: a report in a folder named
          // "reports" is served from the parent folder at /reports/<file>, any other from its own folder.
          var parts = location.pathname.split("/");
          var name = parts.pop();
          var folder = parts[parts.length - 1];
          var dir = parts.join("/");
          var urlPath = name;
          if (folder === "reports") { parts.pop(); dir = parts.join("/"); urlPath = "reports/" + name; }
          try { dir = decodeURIComponent(dir); } catch (e) { /* keep the encoded path */ }
          dir = dir.replace(/^\/([A-Za-z]:)/, "$1"); // file:///C:/Users/… on Windows
          var cmd = $("file-cmd");
          var here = $("file-link");
          if (cmd && dir) cmd.textContent = 'cd "' + dir + '" && python3 -m http.server 8765';
          if (here) { here.href += urlPath; here.textContent += "/" + urlPath; } // the shell holds the host
          note.hidden = false;
        } else {
          player.load(0, false);
        }
      }
    }

    // A click inside the player moves keyboard focus into YouTube's frame. Take it back when
    // the pointer returns to the page, so the page's shortcuts work again.
    document.addEventListener("mouseover", function () {
      var frame = player.frame();
      if (frame && document.activeElement === frame) frame.blur();
    });

    // ── Tabs (narrow screens) ──
    var tabs = document.querySelector(".tabs");
    var stage = document.querySelector(".stage");
    function setTab(name) {
      if (!tabs || root.getAttribute("data-tab") === name) return;
      root.setAttribute("data-tab", name);
      all("[data-tab]", tabs).forEach(function (b) {
        b.setAttribute("aria-selected", b.getAttribute("data-tab") === name ? "true" : "false");
      });
      // If the reader has scrolled into a tab, start the other one at its top, under the player.
      if (getComputedStyle(tabs).display === "none") return;
      var first = name === "read" ? $("read") : outlineEl;
      var top = first.getBoundingClientRect().top + window.scrollY - stage.offsetHeight;
      if (window.scrollY > top) window.scrollTo(0, top);
    }
    if (tabs && outlineEl && sections.length) {
      tabs.hidden = false;
      tabs.addEventListener("click", function (e) {
        var b = e.target instanceof Element ? e.target.closest("[data-tab]") : null;
        if (b) setTab(b.getAttribute("data-tab"));
      });
      if (window.ResizeObserver) {
        new ResizeObserver(function () {
          var sticky = getComputedStyle(stage).position === "sticky";
          root.style.setProperty("--stage-h", (sticky ? stage.offsetHeight : 0) + "px");
        }).observe(stage);
      }
    }

    // ── Density: outline descriptions, key-point details ──
    function flag(attr, key, on, onValue, button) {
      if (on) root.setAttribute(attr, onValue); else root.removeAttribute(attr);
      write(key, on ? (onValue || "1") : null);
      if (button) button.setAttribute("aria-pressed", on ? "true" : "false");
    }
    var outlineBtn = $("outline-btn");
    var skimBtn = $("skim-btn");
    function toggleOutline() {
      flag("data-outline", KEYS.outline, root.getAttribute("data-outline") !== "full", "full", outlineBtn);
    }
    function toggleSkim() {
      flag("data-skim", KEYS.skim, !root.hasAttribute("data-skim"), "", skimBtn);
    }
    if (outlineBtn && sections.some(function (s) { return s.li.querySelector(".outline-detail"); })) {
      outlineBtn.hidden = false;
      outlineBtn.setAttribute("aria-pressed", root.getAttribute("data-outline") === "full" ? "true" : "false");
      outlineBtn.addEventListener("click", toggleOutline);
    }
    if (skimBtn && points.some(function (p) { return p.detail; })) {
      skimBtn.hidden = false;
      skimBtn.setAttribute("aria-pressed", root.hasAttribute("data-skim") ? "true" : "false");
      skimBtn.addEventListener("click", toggleSkim);
      points.forEach(function (p) {
        if (!p.detail) return;
        var more = el("button", "tool quiet kp-toggle", "Detail");
        more.type = "button";
        more.setAttribute("aria-expanded", "false");
        more.addEventListener("click", function () {
          var open = p.li.classList.toggle("open");
          more.setAttribute("aria-expanded", open ? "true" : "false");
          more.textContent = open ? "Less" : "Detail";
        });
        p.li.appendChild(more);
      });
    }

    // ── Theme ──
    function toggleTheme() {
      var dark = root.getAttribute("data-theme")
        ? root.getAttribute("data-theme") === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      var next = dark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      write(KEYS.theme, next);
    }

    // ── Generation facts (local report): date, model and time taken, from the meta block ──
    var facts = $("gen-facts");
    var metaBlock = $("video-lens-meta");
    if (facts && metaBlock) {
      try {
        var meta = JSON.parse(metaBlock.textContent) || {};
        var when = meta.generatedAt ? new Date(meta.generatedAt) : null;
        var text = "";
        if (when && !isNaN(when.getTime())) {
          text += " on " + when.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
        }
        var extra = [meta.agentModel || meta.modelName, typeof meta.durationSeconds === "number" ? Math.round(meta.durationSeconds) + " s" : ""]
          .filter(Boolean).join(", ");
        if (extra) text += " (" + extra + ")";
        facts.textContent = text;
      } catch (e) { /* the sentence reads fine without the facts */ }
    }

    // ── Markdown: built from the page, no network ──
    function mdInline(node) {
      if (!node) return "";
      return Array.prototype.map.call(node.childNodes, function (n) {
        if (n.nodeType === 3) return n.textContent;
        if (n.nodeType !== 1 || n.classList.contains("ts") || n.tagName === "BUTTON") return "";
        var inner = mdInline(n);
        switch (n.tagName) {
          case "STRONG": case "B": return "**" + inner.trim() + "**";
          case "EM": case "I": return "*" + inner.trim() + "*";
          case "CODE": return "`" + inner.trim() + "`";
          case "BR": return "\n";
          default: return inner;
        }
      }).join("").replace(/[ \t]+/g, " ").trim();
    }
    function paras(selector) {
      return all(selector).map(mdInline).join("\n\n");
    }
    function bareText(li) {
      // Reports written before 036: the "why" is text directly in the li, after a dash.
      return Array.prototype.filter.call(li.childNodes, function (n) { return n.nodeType === 3; })
        .map(function (n) { return n.textContent; }).join(" ").replace(/\s+/g, " ").replace(/^\s*—\s*/, "").trim();
    }
    function markdown() {
      // The masthead link, not the facade: a "noembed" share page renders the facade without
      // data-video-id, and the link is always there, built from the validated ID.
      var ytLink = document.querySelector("a.yt-link[href]");
      var watch = ytLink ? ytLink.getAttribute("href")
        : "https://www.youtube.com/watch?v=" + ((facade && facade.getAttribute("data-video-id")) || "");
      var title = document.querySelector("h1").textContent.trim();
      var metaLine = document.querySelector(".meta-facts");
      var lines = ["# " + title, ""];
      if (metaLine && metaLine.textContent.trim()) lines.push(metaLine.textContent.trim());
      lines.push("[Watch on YouTube](" + watch + ")", "", "## Summary", "", paras("#summary > p"),
        "", "## Takeaway", "", paras("#takeaway > p"), "", "## Key Points", "");
      points.forEach(function (p) {
        var head = p.li.querySelector(":scope > strong");
        var line = "- **" + (head ? head.textContent.trim() : "") + "**";
        var why = p.why ? mdInline(p.why) : (bareText(p.li) || mdInline(p.only));
        var detail = p.detail ? mdInline(p.detail) : (bareText(p.li) ? mdInline(p.only) : "");
        if (why) line += " — " + why;
        if (p.t !== null) line += " ([" + clock(p.t) + "](" + watch + "&t=" + p.t + "s))";
        if (detail) line += "\n  " + detail;
        lines.push(line);
      });
      lines.push("", "## Outline", "");
      sections.forEach(function (sec) {
        var detail = mdInline(sec.li.querySelector(".outline-detail"));
        lines.push("- [" + clock(sec.t) + "](" + watch + "&t=" + sec.t + "s) " + sec.title + (detail ? " — " + detail : ""));
      });
      var description = document.querySelector(".video-description");
      if (description) lines.push("", "## YouTube Description", "", description.innerText.trim());
      var gen = document.querySelector(".colophon .gen");
      lines.push("", "---", "", "*" + (gen ? gen.textContent.trim() : "Made with video-lens") + "*");
      return lines.join("\n") + "\n";
    }
    function said(button, text) {
      var old = button.textContent;
      button.textContent = text;
      setTimeout(function () { button.textContent = old; }, 1600);
    }
    function copyMarkdown() {
      var button = $("md-copy");
      var md = markdown();
      function fallback() {
        var area = document.createElement("textarea");
        area.value = md;
        document.body.appendChild(area);
        area.select();
        var ok = false;
        try { ok = document.execCommand("copy"); } catch (e) { /* nothing more to try */ }
        area.remove();
        said(button, ok ? "Copied ✓" : "Copy failed");
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(md).then(function () { said(button, "Copied ✓"); }, fallback);
      } else {
        fallback();
      }
    }
    function saveMarkdown() {
      var file = location.pathname.split("/").pop().replace(/\.html$/, "");
      if (!file || /^[A-Za-z0-9_-]{22}$/.test(file)) file = "video-lens-report"; // never the share ID
      var url = URL.createObjectURL(new Blob([markdown()], { type: "text/markdown" }));
      var a = document.createElement("a");
      a.href = url;
      a.download = file + ".md";
      a.hidden = true;
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { a.remove(); URL.revokeObjectURL(url); }, 0);
    }

    // ── Help ──
    var help = $("help");
    function toggleHelp() {
      if (!help || !help.showModal) return;
      if (help.open) help.close(); else { help.showModal(); help.focus(); }
    }
    if (help) {
      help.addEventListener("click", function (e) { if (e.target === help) help.close(); });
      $("help-close").addEventListener("click", function () { help.close(); });
    }

    [["md-copy", copyMarkdown], ["md-save", saveMarkdown], ["help-btn", toggleHelp], ["theme-btn", toggleTheme]]
      .forEach(function (pair) {
        var b = $(pair[0]);
        if (!b) return;
        b.hidden = false;
        b.addEventListener("click", pair[1]);
      });
    // A button clicked with the mouse must not keep Space for itself: Space is play and pause.
    document.addEventListener("click", function (e) {
      var b = e.target instanceof Element ? e.target.closest("button") : null;
      if (b && e.detail > 0 && !b.closest("dialog")) b.blur();
    });

    // ── Divider and the three sizes ──
    var divider = $("divider");
    function maxSplit() {
      // The widest pane where the video still fits the height without black bars.
      // The text keeps at least 22rem.
      var w = (window.innerHeight - 240) * 16 / 9;
      var room = 100 - (22 * 16 + 9) / window.innerWidth * 100;
      return Math.max(MIN_SPLIT, Math.min(75, room, (w / window.innerWidth) * 100));
    }
    function setSplit(pct, save) {
      pct = Math.min(Math.max(pct, MIN_SPLIT), maxSplit());
      root.style.setProperty("--split", pct + "%");
      if (divider) divider.setAttribute("aria-valuenow", String(Math.round(pct)));
      if (save) write(KEYS.split, pct.toFixed(1));
    }
    function snap(pct) {
      layout.classList.add("snapping");
      if (pct === DEFAULT_SPLIT) {
        root.style.removeProperty("--split");
        write(KEYS.split, null);
        divider.setAttribute("aria-valuenow", String(DEFAULT_SPLIT));
      } else {
        setSplit(pct, true);
      }
      setTimeout(function () { layout.classList.remove("snapping"); }, 250);
    }
    function currentSplit() {
      return parseFloat(root.style.getPropertyValue("--split")) || DEFAULT_SPLIT;
    }
    if (divider && layout) {
      divider.setAttribute("aria-valuemin", String(MIN_SPLIT));
      divider.setAttribute("aria-valuemax", "75");
      divider.setAttribute("aria-valuenow", String(Math.round(currentSplit())));
      var drop = function (e) {
        if (!root.classList.contains("dragging")) return;
        root.classList.remove("dragging");
        if (divider.hasPointerCapture(e.pointerId)) divider.releasePointerCapture(e.pointerId);
        write(KEYS.split, currentSplit().toFixed(1));
      };
      divider.addEventListener("pointerdown", function (e) {
        if (e.button !== 0) return;
        e.preventDefault();
        divider.setPointerCapture(e.pointerId); // keeps the drag alive over the player's frame
        root.classList.add("dragging");
      });
      divider.addEventListener("pointermove", function (e) {
        if (!divider.hasPointerCapture(e.pointerId)) return;
        setSplit((e.clientX / window.innerWidth) * 100, false);
      });
      divider.addEventListener("pointerup", drop);
      divider.addEventListener("pointercancel", drop);
      divider.addEventListener("dblclick", function () { snap(DEFAULT_SPLIT); });
      divider.addEventListener("keydown", function (e) {
        var k = e.key;
        if (k === "ArrowLeft") setSplit(currentSplit() - 2, true);
        else if (k === "ArrowRight") setSplit(currentSplit() + 2, true);
        else if (k === "Home") setSplit(MIN_SPLIT, true);
        else if (k === "End") setSplit(maxSplit(), true);
        else if (k === "Enter") snap(DEFAULT_SPLIT);
        else return;
        e.preventDefault();
        e.stopPropagation();
      });
    }

    // ── Keyboard: the same keys as inside the YouTube player, plus the page's own ──
    document.addEventListener("keydown", function (e) {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      var target = e.target instanceof Element ? e.target : null;
      if (target && target.closest("input, textarea, select, [contenteditable]")) return;
      var k = e.key;
      if (help && help.open) {
        if (k === "?") { e.preventDefault(); help.close(); }
        return;
      }
      // A focused link or button keeps Enter and Space.
      if ((k === " " || k === "Enter") && target && target.closest("a, button, summary")) return;
      var ready = player.ready();
      switch (k) {
        case " ": case "k":
          if (player.toggle()) e.preventDefault(); // before the player is loaded, Space still scrolls
          else if (k === "k") hint();
          break;
        case "j": if (ready) player.shift(-10); else hint(); break;
        case "l": if (ready) player.shift(10); else hint(); break;
        case "ArrowLeft": if (ready) { e.preventDefault(); player.shift(-5); } break;
        case "ArrowRight": if (ready) { e.preventDefault(); player.shift(5); } break;
        case "p": if (player.loaded()) step(-1); else hint(); break;
        case "n": if (player.loaded()) step(1); else hint(); break;
        case ",": case "<": if (speedBtn) stepRate(-1); break;
        case ".": case ">": if (speedBtn) stepRate(1); break;
        case "m": player.mute(); break;
        case "c": player.captions(); break;
        case "f": player.fullscreen(); break;
        case "1": if (divider) snap(30); break;
        case "2": if (divider) snap(DEFAULT_SPLIT); break;
        case "3": if (divider) snap(maxSplit()); break;
        case "o": if (outlineBtn && !outlineBtn.hidden) toggleOutline(); break;
        case "s": if (skimBtn && !skimBtn.hidden) toggleSkim(); break;
        case "e": copyMarkdown(); break;
        case "t": toggleTheme(); break;
        case "?": toggleHelp(); break;
        default: return;
      }
    });
  });
})();
