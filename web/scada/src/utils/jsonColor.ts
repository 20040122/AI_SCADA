export function colorJson(obj: unknown): string {
  const str = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"([^"]+)":/g, '<span class="text-[#7ec8f0]">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="text-[#a8e6a3]">"$1"</span>')
    .replace(/: (-?[\d.]+)/g, ': <span class="text-[#ffcc80]">$1</span>')
    .replace(/: (true|false)/g, ': <span class="text-[#ff8a80]">$1</span>');
}
