// Appearance: follow the device's light or dark setting, unless the person chose Light or Dark in Account.
// Loaded in <head> before the stylesheet, so a dark page never flashes white first.
(function () {
  var choice = null;
  try { choice = localStorage.getItem("tallytime-theme"); } catch (e) { /* storage blocked: follow the device */ }
  if (choice === "light" || choice === "dark") document.documentElement.setAttribute("data-theme", choice);
})();
