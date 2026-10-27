// HTMX response policy.
// - 4xx with an HTML fragment (validation, conflict, rate limit, wrong password on /login) is swapped in.
// - 401 elsewhere and 403 carry HX-Redirect, and anything that is not HTML (JSON from the origin check) is never swapped.
// - Everything else that fails (5xx, dropped connection) gets a visible alert above the form.
var ALERT_CLASS = "alert alert-error js-alert";

function showAlert(source, text) {
  var host = (source && source.closest("form")) || document.querySelector("main .sheet") || document.body;
  var box = document.querySelector(".js-alert");
  if (!box) {
    box = document.createElement("div");
    box.className = ALERT_CLASS;
    box.setAttribute("role", "alert");
    box.tabIndex = -1;
  }
  box.textContent = text;
  host.prepend(box);
  box.focus();
}

document.addEventListener("htmx:beforeSwap", function (e) {
  var xhr = e.detail.xhr;
  var status = xhr.status;
  var isHtml = (xhr.getResponseHeader("Content-Type") || "").indexOf("text/html") === 0;
  var isLogin = e.detail.pathInfo.requestPath === "/login";
  var swappable = status >= 400 && status < 500 && status !== 403 && (status !== 401 || isLogin);
  if (swappable && isHtml) {
    e.detail.shouldSwap = true;
    e.detail.isError = false;
  } else if (status >= 400) {
    e.detail.shouldSwap = false;
  }
});

document.addEventListener("htmx:responseError", function (e) {
  var status = e.detail.xhr.status;
  if (e.detail.xhr.getResponseHeader("HX-Redirect")) return;
  showAlert(e.detail.elt, status >= 500 ? "Ошибка сервера. Повторите попытку позже." : "Запрос отклонён. Обновите страницу и повторите.");
});

document.addEventListener("htmx:sendError", function (e) {
  showAlert(e.detail.elt, "Нет связи с сервером. Проверьте соединение и повторите.");
});

// After a swap move focus to the first invalid field, or to the error alert.
document.addEventListener("htmx:afterSettle", function () {
  var target = document.querySelector("main [aria-invalid='true']") || document.querySelector("main .alert-error");
  if (target) target.focus();
});

// Date fields: keep digits only and put the dots in (дд.мм.гггг) while typing.
document.addEventListener("input", function (e) {
  var el = e.target;
  if (!el.matches || !el.matches("[data-date-mask]")) return;
  var d = el.value.replace(/\D/g, "").slice(0, 8);
  el.value = d.length > 4 ? d.slice(0, 2) + "." + d.slice(2, 4) + "." + d.slice(4) : d.length > 2 ? d.slice(0, 2) + "." + d.slice(2) : d;
});
