(function () {
  "use strict";

  function tabsIn(tablist) {
    return Array.from(tablist.querySelectorAll('[role="tab"]'));
  }

  function activateTab(tab, moveFocus) {
    var tablist = tab.closest('[role="tablist"]');
    if (!tablist) return;

    tabsIn(tablist).forEach(function (candidate) {
      var selected = candidate === tab;
      var panelId = candidate.getAttribute("aria-controls");
      var panel = panelId ? document.getElementById(panelId) : null;
      candidate.setAttribute("aria-selected", selected ? "true" : "false");
      candidate.setAttribute("tabindex", selected ? "0" : "-1");
      candidate.classList.toggle("active", selected);
      if (panel) {
        panel.hidden = !selected;
        panel.classList.toggle("active", selected);
      }
    });

    if (moveFocus) tab.focus();
  }

  document.addEventListener("click", function (event) {
    if (!(event.target instanceof Element)) return;
    var tab = event.target.closest('[role="tab"]');
    if (tab) activateTab(tab, false);
  });

  document.addEventListener("keydown", function (event) {
    if (!(event.target instanceof Element)) return;
    var tab = event.target.closest('[role="tab"]');
    if (!tab) return;
    var tablist = tab.closest('[role="tablist"]');
    if (!tablist) return;
    var tabs = tabsIn(tablist);
    var index = tabs.indexOf(tab);
    var next = null;

    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = tabs[(index + 1) % tabs.length];
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = tabs[(index - 1 + tabs.length) % tabs.length];
    } else if (event.key === "Home") {
      next = tabs[0];
    } else if (event.key === "End") {
      next = tabs[tabs.length - 1];
    }

    if (next) {
      event.preventDefault();
      activateTab(next, true);
    }
  });
})();
