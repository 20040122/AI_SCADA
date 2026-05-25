let _timer: ReturnType<typeof setTimeout>;

export function notify(msg: string, type: "" | "s" | "w" | "e" = "") {
  const el = document.getElementById("scada-notify");
  if (!el) return;
  el.textContent = msg;
  el.className = "notify show" + (type ? ` ${type}` : "");
  clearTimeout(_timer);
  _timer = setTimeout(() => {
    el.className = "notify";
  }, 2200);
}