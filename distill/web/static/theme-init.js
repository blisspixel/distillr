(function () {
  "use strict";
  var meta = document.querySelector('meta[name="distill-themes"]');
  var collection = meta ? JSON.parse(meta.content) : {themes: [], notices: []};
  var key = "distill.appearance.v1";
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch (_) {}
  var preference = {
    mode: ["dark", "light", "system"].includes(saved.mode) ? saved.mode : "dark",
    dark: saved.dark || "house-dark",
    light: saved.light || "house-light"
  };
  var system = window.matchMedia("(prefers-color-scheme: dark)");
  function selected(variant) {
    var theme = collection.themes.find(function (item) { return item.slug === preference[variant] && item.variant === variant; });
    if (theme) return theme.slug;
    if (preference[variant] !== "house-" + variant) {
      var message = "Theme unavailable. Using house-" + variant + ".";
      collection.notices = collection.notices || [];
      if (!collection.notices.includes(message)) collection.notices.push(message);
    }
    preference[variant] = "house-" + variant;
    return preference[variant];
  }
  function apply(persist) {
    selected("dark"); selected("light");
    var variant = preference.mode === "system" ? (system.matches ? "dark" : "light") : preference.mode;
    document.documentElement.dataset.theme = selected(variant);
    document.documentElement.dataset.appearance = preference.mode;
    if (persist) { try { localStorage.setItem(key, JSON.stringify(preference)); } catch (_) {} }
  }
  function choose(change) {
    Object.assign(preference, change);
    var update = function () { apply(true); sync(); };
    if (document.startViewTransition && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.startViewTransition(update);
    } else { update(); }
  }
  function sync() {
    document.querySelectorAll("[data-appearance]").forEach(function (element) { element.value = preference.mode; });
    document.querySelectorAll("[data-theme-slot]").forEach(function (element) { element.value = preference[element.dataset.themeSlot]; });
    document.querySelectorAll("[data-theme-choice]").forEach(function (element) {
      element.setAttribute("aria-pressed", String(element.dataset.themeChoice === document.documentElement.dataset.theme));
    });
    var notice = document.querySelector("[data-theme-notice]");
    if (notice) notice.textContent = (collection.notices || []).join(" ");
  }
  async function refresh() {
    var response = await fetch("/themes", {cache: "no-store"});
    if (!response.ok) throw new Error("Theme refresh failed");
    var data = await response.json();
    collection = data;
    var style = document.getElementById("theme-live-css");
    if (!style) { style = document.createElement("style"); style.id = "theme-live-css"; document.head.append(style); }
    style.textContent = data.css;
    document.querySelectorAll("[data-theme-slot]").forEach(function (select) {
      select.replaceChildren();
      collection.themes.filter(function (theme) { return theme.variant === select.dataset.themeSlot; }).forEach(function (theme) {
        var option = document.createElement("option"); option.value = theme.slug; option.textContent = theme.name; select.append(option);
      });
    });
    var cards = document.querySelector(".theme-cards");
    if (cards) {
      cards.replaceChildren();
      collection.themes.forEach(function (theme) {
        var button = document.createElement("button");
        button.type = "button"; button.className = "theme-card";
        button.dataset.theme = theme.slug; button.dataset.themeChoice = theme.slug;
        var name = document.createElement("span"); name.textContent = theme.name; button.append(name);
        var sample = document.createElement("small"); sample.textContent = "Research text"; button.append(sample);
        var chips = document.createElement("span"); chips.className = "theme-chips";
        [["success", "OK"], ["warning", "Attention"], ["error", "Error"], ["info", "Info"]].forEach(function (item) {
          var chip = document.createElement("i"); chip.className = "chip-" + item[0]; chip.textContent = item[1]; chips.append(chip);
        });
        button.append(chips); cards.append(button);
      });
    }
    apply(false); sync();
  }
  function announce(message) {
    var region = document.querySelector("[data-theme-notice]");
    if (region) region.textContent = message;
  }
  document.addEventListener("change", async function (event) {
    var target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.matches("[data-appearance]")) choose({mode: target.value});
    if (target.matches("[data-theme-slot]")) { var change = {}; change[target.dataset.themeSlot] = target.value; choose(change); }
    if (target.matches("[data-theme-file]") && target.files.length) {
      try {
        if (target.files[0].size > 16384) throw new Error("Theme exceeds 16 KB");
        var content = await target.files[0].text();
        var response = await fetch("/themes/import", {method: "POST", headers: {"Content-Type": "application/json", "X-Distill-Theme-Token": target.dataset.themeToken}, body: JSON.stringify({content: content})});
        if (!response.ok) { var error = await response.json(); throw new Error(error.detail || "Theme refused"); }
        await refresh(); announce("Theme imported. Select it in its appearance slot.");
      } catch (error) { announce(error.message); }
      target.value = "";
    }
  });
  document.addEventListener("click", function (event) {
    if (!(event.target instanceof Element)) return;
    var card = event.target.closest("[data-theme-choice]");
    if (card) {
      var theme = collection.themes.find(function (item) { return item.slug === card.dataset.themeChoice; });
      if (theme) { var change = {mode: theme.variant}; change[theme.variant] = theme.slug; choose(change); }
    }
    if (event.target.closest("[data-theme-refresh]")) refresh().catch(function (error) { announce(error.message); });
  });
  system.addEventListener("change", function () { if (preference.mode === "system") { apply(false); sync(); } });
  apply(false);
  document.addEventListener("DOMContentLoaded", function () {
    sync();
    var live = document.createElement("span"); live.className = "sr-only"; live.setAttribute("aria-live", "polite"); document.body.append(live);
    document.querySelectorAll("code").forEach(function (code) {
      if (!code.textContent.trim().startsWith("distill ")) return;
      var button = document.createElement("button"); button.type = "button"; button.className = "copy-command"; button.textContent = "Copy";
      button.setAttribute("aria-label", "Copy command: " + code.textContent.trim());
      button.addEventListener("click", async function () {
        try { await navigator.clipboard.writeText(code.textContent.trim()); live.textContent = "Copied"; button.textContent = "Copied"; }
        catch (_) { live.textContent = "Copy unavailable. Select the command text to copy it."; }
      });
      code.after(button);
    });
  });
})();
