/*
 * PsychonautWiki static archive - client-side search + random article.
 * Plain ES5, no dependencies. The original MediaWiki search endpoint and
 * Special:Random are both gone, so this fetches a static index once and
 * does substring matching in the browser instead.
 */
(function () {
  'use strict';

  var INDEX_URL = '/assets/search-index.json';
  var STYLE_ID = 'archive-search-style';
  var MAX_RESULTS = 10;
  var SLIDESHOW_DELAY = 6000;

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.type = 'text/css';
    var css =
      '.archive-suggest{position:absolute;z-index:5000;background:#fff;' +
      'border:1px solid #a2a9b1;font-family:sans-serif;font-size:13px;' +
      'max-height:280px;overflow-y:auto;box-shadow:0 2px 4px rgba(0,0,0,.15);}' +
      '.archive-suggest ul{list-style:none;margin:0;padding:0;}' +
      '.archive-suggest li{padding:4px 8px;cursor:pointer;white-space:nowrap;}' +
      '.archive-suggest li.archive-suggest-active,.archive-suggest li:hover{background:#eaf3ff;}';
    if (style.styleSheet) {
      style.styleSheet.cssText = css;
    } else {
      style.appendChild(document.createTextNode(css));
    }
    document.getElementsByTagName('head')[0].appendChild(style);
  }

  function on(el, name, fn) {
    if (el.addEventListener) {
      el.addEventListener(name, fn, false);
    } else if (el.attachEvent) {
      el.attachEvent('on' + name, fn);
    }
  }

  function preventDefault(e) {
    if (e.preventDefault) {
      e.preventDefault();
    } else {
      e.returnValue = false;
    }
  }

  function hasClass(el, name) {
    return new RegExp('(^|\\s)' + name + '(\\s|$)').test(el.className);
  }

  function addClass(el, name) {
    if (!hasClass(el, name)) {
      el.className = (el.className + ' ' + name).replace(/^\s+|\s+$/g, '');
    }
  }

  function removeClass(el, name) {
    el.className = el.className
      .replace(new RegExp('(^|\\s)' + name + '(?=\\s|$)', 'g'), ' ')
      .replace(/\s+/g, ' ')
      .replace(/^\s+|\s+$/g, '');
  }

  function initMobileNavigation() {
    var body = document.body;
    var panel = document.getElementById('mw-panel');
    var search = document.getElementById('p-search');
    if (!body || !panel || !search || !hasClass(body, 'skin-vector')) {
      return;
    }

    var searchParent = search.parentNode;
    var searchNextSibling = search.nextSibling;
    var support = document.getElementById('p-support');
    var content = document.getElementById('content');
    var footer = document.getElementById('footer');
    var media = window.matchMedia ? window.matchMedia('screen and (max-width: 767px)') : null;
    var open = false;

    var header = document.createElement('div');
    header.className = 'archive-mobile-header noprint';

    var menuButton = document.createElement('button');
    menuButton.className = 'archive-mobile-menu-button';
    menuButton.type = 'button';
    menuButton.setAttribute('aria-controls', 'mw-panel');
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', 'Open navigation menu');

    var menuIcon = document.createElement('span');
    menuIcon.className = 'archive-mobile-menu-icon';
    menuIcon.setAttribute('aria-hidden', 'true');
    for (var i = 0; i < 3; i++) {
      menuIcon.appendChild(document.createElement('span'));
    }
    menuButton.appendChild(menuIcon);
    menuButton.appendChild(document.createTextNode('Menu'));

    header.appendChild(menuButton);

    var brandLink = document.createElement('a');
    brandLink.className = 'archive-mobile-brand mw-wiki-logo';
    brandLink.href = '/';
    brandLink.setAttribute('aria-label', 'PsychonautWiki home');
    header.appendChild(brandLink);

    var closeButton = document.createElement('button');
    closeButton.className = 'archive-mobile-close';
    closeButton.type = 'button';
    closeButton.setAttribute('aria-label', 'Close navigation menu');
    closeButton.appendChild(document.createTextNode('\u00d7'));
    panel.insertBefore(closeButton, panel.firstChild);

    var backdrop = document.createElement('button');
    backdrop.className = 'archive-mobile-backdrop noprint';
    backdrop.type = 'button';
    backdrop.tabIndex = -1;
    backdrop.setAttribute('aria-label', 'Close navigation menu');

    var banner = document.getElementsByClassName('josiekins-archive-banner')[0];
    if (banner && banner.nextSibling) {
      body.insertBefore(header, banner.nextSibling);
    } else {
      body.insertBefore(header, body.firstChild);
    }
    body.appendChild(backdrop);
    addClass(body, 'archive-mobile-ready');

    function isMobile() {
      if (media) {
        return media.matches;
      }
      return document.documentElement.clientWidth < 768;
    }

    function moveSearchToPanel() {
      if (search.parentNode !== panel) {
        panel.insertBefore(search, support && support.parentNode === panel ? support : panel.firstChild);
      }
    }

    function restoreSearch() {
      if (searchParent && search.parentNode !== searchParent) {
        searchParent.insertBefore(search, searchNextSibling);
      }
    }

    function setOpen(nextOpen, returnFocus) {
      open = !!nextOpen && isMobile();
      menuButton.setAttribute('aria-expanded', open ? 'true' : 'false');
      menuButton.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu');
      panel.setAttribute('aria-hidden', open ? 'false' : 'true');
      if (open) {
        addClass(body, 'archive-mobile-menu-open');
        if (content) { content.setAttribute('inert', ''); }
        if (footer) { footer.setAttribute('inert', ''); }
        closeButton.focus();
      } else {
        removeClass(body, 'archive-mobile-menu-open');
        if (content) { content.removeAttribute('inert'); }
        if (footer) { footer.removeAttribute('inert'); }
        if (returnFocus) {
          menuButton.focus();
        }
      }
    }

    function syncLayout() {
      if (isMobile()) {
        moveSearchToPanel();
        panel.setAttribute('aria-hidden', open ? 'false' : 'true');
      } else {
        setOpen(false, false);
        panel.removeAttribute('aria-hidden');
        restoreSearch();
      }
    }

    on(menuButton, 'click', function () {
      setOpen(!open, false);
    });
    on(closeButton, 'click', function () {
      setOpen(false, true);
    });
    on(backdrop, 'click', function () {
      setOpen(false, true);
    });
    on(document, 'keydown', function (e) {
      e = e || window.event;
      if (open && (e.key === 'Escape' || e.keyCode === 27)) {
        setOpen(false, true);
      } else if (open && (e.key === 'Tab' || e.keyCode === 9)) {
        var focusable = panel.querySelectorAll('a[href], button:not([disabled]), input:not([disabled])');
        if (!focusable.length) {
          return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          preventDefault(e);
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          preventDefault(e);
          first.focus();
        }
      }
    });
    on(panel, 'click', function (e) {
      var target = (e || window.event).target;
      while (target && target !== panel) {
        if (target.tagName && target.tagName.toLowerCase() === 'a') {
          setOpen(false, false);
          return;
        }
        target = target.parentNode;
      }
    });

    if (media) {
      if (media.addEventListener) {
        media.addEventListener('change', syncLayout);
      } else if (media.addListener) {
        media.addListener(syncLayout);
      }
    } else {
      on(window, 'resize', syncLayout);
    }

    syncLayout();
  }

  function initSlideshows() {
    var galleries = document.getElementsByTagName('ul');
    var viewportMedia = window.matchMedia ?
      window.matchMedia('screen and (max-width: 767px)') : null;
    var reducedMotionMedia = window.matchMedia ?
      window.matchMedia('(prefers-reduced-motion: reduce)') : null;

    function setup(gallery, mode) {
      var wrapper = gallery.parentNode;
      var nodes = gallery.childNodes;
      var items = [];
      var controls;
      var previousButton;
      var pauseButton = null;
      var nextButton;
      var status;
      var reducedMotion = mode === 'auto' ? reducedMotionMedia : null;
      var pageSize = mode === 'auto' ? 1 :
        ((viewportMedia ? viewportMedia.matches :
          document.documentElement.clientWidth <= 767) ? 1 : 3);
      var index = 0;
      var timer = null;
      var hovered = false;
      var focused = false;
      var autoEnabled = !(reducedMotion && reducedMotion.matches);
      var motionPaused = !autoEnabled;

      if (!wrapper) {
        return;
      }

      for (var i = 0; i < nodes.length; i++) {
        if (nodes[i].nodeType === 1 && nodes[i].tagName.toLowerCase() === 'li') {
          items.push(nodes[i]);
        }
      }

      function makeButton(label, className) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'archive-slideshow-button ' + className;
        button.appendChild(document.createTextNode(label));
        return button;
      }

      function setText(element, text) {
        if (element.firstChild &&
            element.firstChild.nodeType === 3 &&
            !element.firstChild.nextSibling) {
          element.firstChild.nodeValue = text;
          return;
        }
        while (element.firstChild) {
          element.removeChild(element.firstChild);
        }
        element.appendChild(document.createTextNode(text));
      }

      function clearTimer() {
        if (timer !== null) {
          window.clearTimeout(timer);
          timer = null;
        }
      }

      function canAdvanceAutomatically() {
        return mode === 'auto' && autoEnabled && !hovered && !focused && items.length > 1;
      }

      function scheduleTimer() {
        clearTimer();
        if (canAdvanceAutomatically()) {
          primeUpcomingSlide();
          timer = window.setTimeout(function () {
            timer = null;
            if (canAdvanceAutomatically()) {
              index = (index + 1) % items.length;
              render();
              scheduleTimer();
            }
          }, SLIDESHOW_DELAY);
        }
      }

      function updatePauseButton() {
        if (!pauseButton) {
          return;
        }
        setText(pauseButton, autoEnabled ? 'Pause' : 'Resume');
        pauseButton.setAttribute(
          'aria-label',
          autoEnabled ? 'Pause slideshow' : 'Resume slideshow'
        );
        pauseButton.disabled = items.length < 2;
      }

      function primeSlide(item) {
        var imgs = item.getElementsByTagName('img');
        for (var i = 0; i < imgs.length; i++) {
          if (imgs[i].getAttribute('loading') === 'lazy') {
            imgs[i].setAttribute('loading', 'eager');
          }
        }
      }

      function primeUpcomingSlide() {
        // A slide that is not current is display:none, so a native lazy image
        // inside it never starts loading. Only the auto mode advances without
        // user input, so only its next slide needs warming; every other slide
        // becomes visible before it is needed and loads from the viewport.
        var count = items.length;
        if (count > 1) {
          primeSlide(items[(index + 1) % count]);
        }
      }

      function render() {
        var count = items.length;
        var lastStart;
        var visible;

        if (mode === 'pager') {
          lastStart = count ? Math.floor((count - 1) / pageSize) * pageSize : 0;
          index = Math.max(0, Math.min(index, lastStart));
        } else if (count) {
          index = (index + count) % count;
        } else {
          index = 0;
        }

        for (var i = 0; i < count; i++) {
          visible = mode === 'pager' ?
            i >= index && i < index + pageSize :
            i === index;
          if (visible) {
            addClass(items[i], 'archive-slideshow-visible');
            items[i].removeAttribute('aria-hidden');
          } else {
            removeClass(items[i], 'archive-slideshow-visible');
            items[i].setAttribute('aria-hidden', 'true');
          }
        }

        if (!count) {
          setText(status, 'No slides');
        } else if (mode === 'pager') {
          setText(
            status,
            'Page ' + (Math.floor(index / pageSize) + 1) +
              ' of ' + Math.ceil(count / pageSize)
          );
        } else {
          setText(status, 'Slide ' + (index + 1) + ' of ' + count);
        }

        if (mode === 'pager') {
          previousButton.disabled = index === 0;
          nextButton.disabled = index + pageSize >= count;
        } else {
          previousButton.disabled = count < 2;
          nextButton.disabled = count < 2;
        }
        updatePauseButton();
      }

      addClass(wrapper, 'archive-slideshow');

      for (var i = wrapper.childNodes.length - 1; i >= 0; i--) {
        if (wrapper.childNodes[i].nodeType === 1 &&
            hasClass(wrapper.childNodes[i], 'srf-spinner')) {
          wrapper.removeChild(wrapper.childNodes[i]);
          break;
        }
      }

      controls = document.createElement('div');
      controls.className = 'archive-slideshow-controls noprint';
      controls.setAttribute('role', 'group');
      controls.setAttribute('aria-label', 'Slideshow controls');

      previousButton = makeButton(
        'Previous',
        'archive-slideshow-previous'
      );
      previousButton.setAttribute(
        'aria-label',
        mode === 'pager' ? 'Previous page' : 'Previous slide'
      );
      controls.appendChild(previousButton);

      if (mode === 'auto') {
        pauseButton = makeButton('Pause', 'archive-slideshow-pause');
        controls.appendChild(pauseButton);
      }

      nextButton = makeButton('Next', 'archive-slideshow-next');
      nextButton.setAttribute(
        'aria-label',
        mode === 'pager' ? 'Next page' : 'Next slide'
      );
      controls.appendChild(nextButton);

      status = document.createElement('span');
      status.className = 'archive-slideshow-status';
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      status.setAttribute('aria-atomic', 'true');
      controls.appendChild(status);

      wrapper.insertBefore(controls, gallery.nextSibling);
      gallery.style.display = 'block';
      addClass(gallery, 'archive-slideshow-ready');

      on(previousButton, 'click', function () {
        if (mode === 'pager') {
          index = Math.max(0, index - pageSize);
        } else if (items.length) {
          index = (index - 1 + items.length) % items.length;
        }
        render();
        scheduleTimer();
      });

      on(nextButton, 'click', function () {
        if (mode === 'pager') {
          index = Math.min(index + pageSize, Math.max(0, items.length - 1));
        } else if (items.length) {
          index = (index + 1) % items.length;
        }
        render();
        scheduleTimer();
      });

      if (pauseButton) {
        on(pauseButton, 'click', function () {
          autoEnabled = !autoEnabled;
          motionPaused = false;
          updatePauseButton();
          scheduleTimer();
        });

        on(wrapper, 'mouseenter', function () {
          hovered = true;
          clearTimer();
        });
        on(wrapper, 'mouseleave', function () {
          hovered = false;
          scheduleTimer();
        });
        on(wrapper, 'focusin', function () {
          focused = true;
          clearTimer();
        });
        on(wrapper, 'focusout', function () {
          window.setTimeout(function () {
            focused = wrapper.contains ?
              wrapper.contains(document.activeElement) :
              false;
            scheduleTimer();
          }, 0);
        });
      }

      if (mode === 'pager') {
        var syncPageSize = function () {
          var firstItem = index;
          var nextPageSize = viewportMedia ?
            (viewportMedia.matches ? 1 : 3) :
            (document.documentElement.clientWidth <= 767 ? 1 : 3);
          if (nextPageSize !== pageSize) {
            pageSize = nextPageSize;
            index = Math.floor(firstItem / pageSize) * pageSize;
            render();
          }
        };
        if (viewportMedia) {
          if (viewportMedia.addEventListener) {
            viewportMedia.addEventListener('change', syncPageSize);
          } else if (viewportMedia.addListener) {
            viewportMedia.addListener(syncPageSize);
          }
        } else {
          on(window, 'resize', syncPageSize);
        }
      }

      if (reducedMotion) {
        var syncMotion = function (event) {
          if (event.matches) {
            if (autoEnabled) {
              autoEnabled = false;
              motionPaused = true;
            }
          } else if (motionPaused) {
            autoEnabled = true;
            motionPaused = false;
          }
          updatePauseButton();
          scheduleTimer();
        };
        if (reducedMotion.addEventListener) {
          reducedMotion.addEventListener('change', syncMotion);
        } else if (reducedMotion.addListener) {
          reducedMotion.addListener(syncMotion);
        }
      }

      render();
      scheduleTimer();
    }

    for (var i = 0; i < galleries.length; i++) {
      var mode = galleries[i].getAttribute('data-nav-control');
      if (hasClass(galleries[i], 'gallery') &&
          (mode === 'pager' || mode === 'auto') &&
          !hasClass(galleries[i], 'archive-slideshow-ready')) {
        setup(galleries[i], mode);
      }
    }
  }

  /*
   * Every control this archive cannot honour is rendered without an href, so a
   * click on one already goes nowhere. Silence reads as a broken page, so a
   * single delegated listener answers the click with a short shake instead.
   */
  function initInertControls() {
    var SHAKE_CLASS = 'archive-inert-shake';
    var SHAKE_MS = 420;

    function isInert(el) {
      if (el.nodeType !== 1) {
        return false;
      }
      if (el.id === 'archive-random-link') {
        return false;
      }
      if (el.getAttribute('aria-disabled') === 'true') {
        return true;
      }
      var inert = el.getAttribute('data-archive-inert');
      if (inert) {
        return true;
      }
      var behavior = el.getAttribute('data-archive-link-behavior');
      return behavior === 'disable' || behavior === 'unresolved';
    }

    function nearestInert(node) {
      while (node && node !== document.body && node !== document) {
        if (node.getAttribute && isInert(node)) {
          return node;
        }
        node = node.parentNode;
      }
      return null;
    }

    on(document, 'click', function (e) {
      e = e || window.event;
      var target = nearestInert(e.target || e.srcElement);
      if (!target) {
        return;
      }
      preventDefault(e);
      if (hasClass(target, SHAKE_CLASS)) {
        return;
      }
      addClass(target, SHAKE_CLASS);
      window.setTimeout(function () {
        removeClass(target, SHAKE_CLASS);
      }, SHAKE_MS);
    });
  }

  function init() {
    initMobileNavigation();
    initSlideshows();
    initInertControls();

    var input = document.getElementById('searchInput');
    if (!input) {
      return;
    }

    injectStyle();

    var index = null;
    var loading = false;
    var pending = [];
    var box = null;
    var items = [];
    var activeIndex = -1;

    function loadIndex(callback) {
      if (index) {
        if (callback) { callback(index); }
        return;
      }
      if (callback) { pending.push(callback); }
      if (loading) {
        return;
      }
      loading = true;
      var xhr = new XMLHttpRequest();
      xhr.open('GET', INDEX_URL, true);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) {
          return;
        }
        loading = false;
        try {
          index = (xhr.status === 200 || xhr.status === 0) ? JSON.parse(xhr.responseText) : [];
        } catch (err) {
          index = [];
        }
        var callbacks = pending;
        pending = [];
        for (var i = 0; i < callbacks.length; i++) {
          callbacks[i](index);
        }
      };
      xhr.send(null);
    }

    function closeBox() {
      if (box && box.parentNode) {
        box.parentNode.removeChild(box);
      }
      box = null;
      items = [];
      activeIndex = -1;
    }

    function findMatches(query) {
      var q = query.toLowerCase();
      var prefix = [];
      var substring = [];
      for (var i = 0; i < index.length && (prefix.length + substring.length) < 200; i++) {
        var entry = index[i];
        var pos = entry[0].toLowerCase().indexOf(q);
        if (pos === 0) {
          prefix.push(entry);
        } else if (pos > 0) {
          substring.push(entry);
        }
      }
      return prefix.concat(substring).slice(0, MAX_RESULTS);
    }

    function navigate(path) {
      window.location.href = path;
    }

    function setActive(idx) {
      if (!box) {
        return;
      }
      var lis = box.getElementsByTagName('li');
      for (var i = 0; i < lis.length; i++) {
        lis[i].className = (i === idx) ? 'archive-suggest-active' : '';
      }
      activeIndex = idx;
    }

    function renderResults(results) {
      closeBox();
      if (!results.length) {
        return;
      }
      items = results;

      var parent = input.parentNode;
      if (!parent) {
        return;
      }
      parent.style.position = parent.style.position || 'relative';

      box = document.createElement('div');
      box.className = 'archive-suggest';
      box.style.top = (input.offsetTop + input.offsetHeight) + 'px';
      box.style.left = input.offsetLeft + 'px';
      box.style.minWidth = input.offsetWidth + 'px';

      var ul = document.createElement('ul');
      for (var i = 0; i < results.length; i++) {
        var li = document.createElement('li');
        li.appendChild(document.createTextNode(results[i][0]));
        li.onmousedown = (function (path) {
          return function (e) {
            preventDefault(e || window.event);
            navigate(path);
          };
        })(results[i][1]);
        ul.appendChild(li);
      }
      box.appendChild(ul);
      parent.appendChild(box);
    }

    function onInput() {
      var query = input.value;
      if (!query) {
        closeBox();
        return;
      }
      if (!index) {
        loadIndex(function () { onInput(); });
        return;
      }
      renderResults(findMatches(query));
    }

    function onKeyDown(e) {
      e = e || window.event;
      var key = e.keyCode;
      if (key === 27) {
        closeBox();
        return;
      }
      if (!box || !items.length) {
        return;
      }
      if (key === 40) {
        preventDefault(e);
        setActive((activeIndex + 1) % items.length);
      } else if (key === 38) {
        preventDefault(e);
        setActive((activeIndex - 1 + items.length) % items.length);
      } else if (key === 13 && activeIndex >= 0 && items[activeIndex]) {
        preventDefault(e);
        navigate(items[activeIndex][1]);
      }
    }

    on(input, 'focus', function () { loadIndex(); });
    on(input, 'input', onInput);
    on(input, 'keydown', onKeyDown);
    on(input, 'blur', function () { setTimeout(closeBox, 150); });

    var form = input.form;
    if (form) {
      on(form, 'submit', function (e) {
        e = e || window.event;
        preventDefault(e);
        var best = null;
        if (activeIndex >= 0 && items[activeIndex]) {
          best = items[activeIndex];
        } else if (index && input.value) {
          var results = findMatches(input.value);
          if (results.length) {
            best = results[0];
          }
        }
        if (best) {
          navigate(best[1]);
        }
        return false;
      });
    }

    var randomLink = document.getElementById('archive-random-link');
    if (randomLink) {
      on(randomLink, 'click', function (e) {
        e = e || window.event;
        preventDefault(e);
        loadIndex(function (idx) {
          if (idx && idx.length) {
            navigate(idx[Math.floor(Math.random() * idx.length)][1]);
          }
        });
        return false;
      });
    }
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    init();
  } else if (document.addEventListener) {
    document.addEventListener('DOMContentLoaded', init, false);
  } else if (document.attachEvent) {
    document.attachEvent('onreadystatechange', function () {
      if (document.readyState === 'complete') {
        init();
      }
    });
  }
})();
