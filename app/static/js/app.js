// Marks the page as scripted: the side menu folds into a panel only when the button that opens it will work.
document.documentElement.classList.add("js");

// HTMX response policy.
// - 4xx with an HTML fragment (validation, conflict, rate limit, wrong password on /login) is swapped in,
//   and so is a 503 with Retry-After (a busy row lock; the fragment says to repeat).
// - 401 elsewhere and 403 carry HX-Redirect, and anything that is not HTML (JSON from the origin check) is never swapped.
// - Everything else that fails (5xx, dropped connection) gets a visible alert above the form.
var ALERT_CLASS = "alert alert-error js-alert";

function showAlert(source, text) {
  var host = (source && source.closest("form, .sheet")) || document.querySelector("main .sheet") || document.body;
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
  var busyRow = status === 503 && xhr.getResponseHeader("Retry-After") !== null; // a row lock is busy: the page says so
  var swappable = (status >= 400 && status < 500 && status !== 403 && (status !== 401 || isLogin)) || busyRow;
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

// After a swap move focus to the first invalid field or the error alert inside what was swapped in,
// otherwise to the row that was just replaced (it carries data-focus).
document.addEventListener("htmx:afterSettle", function (e) {
  var scope = e.target;
  if (!scope.querySelector) return;
  var inside = function (selector) {
    return scope.matches(selector) ? scope : scope.querySelector(selector);
  };
  var target = inside("[aria-invalid='true']") || inside(".alert-error") || inside("[data-focus]");
  if (target) target.focus();
});

// Date fields: keep digits only and put the dots in (дд.мм.гггг) while typing.
document.addEventListener("input", function (e) {
  var el = e.target;
  if (!el.matches || !el.matches("[data-date-mask]")) return;
  var d = el.value.replace(/\D/g, "").slice(0, 8);
  el.value = d.length > 4 ? d.slice(0, 2) + "." + d.slice(2, 4) + "." + d.slice(4) : d.length > 2 ? d.slice(0, 2) + "." + d.slice(2) : d;
});

// Time fields: keep digits only and put the colon in (чч:мм) while typing.
document.addEventListener("input", function (e) {
  var el = e.target;
  if (!el.matches || !el.matches("[data-time-mask]")) return;
  var d = el.value.replace(/\D/g, "").slice(0, 4);
  el.value = d.length > 2 ? d.slice(0, 2) + ":" + d.slice(2) : d;
});

// Athlete picker (registrar, admin): the search results are plain HTML from the server; a click on one fills the hidden
// field that the page sends. `data-apply` names a form to submit once the choice is made.
document.addEventListener("alpine:init", function () {
  Alpine.data("athletePicker", function () {
    return {
      id: "",
      name: "",
      init: function () {
        this.id = this.$refs.id.value;
        this.name = this.$el.dataset.selectedName || "";
      },
      pick: function (e) {
        var item = e.target.closest("[data-athlete-id]");
        if (!item) return;
        this.id = item.dataset.athleteId;
        this.name = item.dataset.athleteName;
        this.$refs.results.replaceChildren();
        this.$refs.search.value = "";
        this.$refs.search.focus();
        this.apply();
      },
      clear: function () {
        this.id = "";
        this.name = "";
        this.$refs.search.focus();
        this.apply();
      },
      apply: function () {
        var form = this.$el.dataset.apply && document.querySelector(this.$el.dataset.apply);
        if (form) this.$nextTick(function () { htmx.trigger(form, "submit"); });
      }
    };
  });
});
