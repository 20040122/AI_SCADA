export function colorJson(obj: unknown): string {
  const str = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"([^"]+)":/g, '<span class="text-[var(--json-key)]">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="text-[var(--json-string)]">"$1"</span>')
    .replace(/: (-?[\d.]+)/g, ': <span class="text-[var(--json-number)]">$1</span>')
    .replace(/: (true|false)/g, ': <span class="text-[var(--json-boolean)]">$1</span>');
}
