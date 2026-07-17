# Schema Validation Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the Schema validation page with the existing dark SCADA blue-gray theme.

**Architecture:** Keep the existing three-column React layout and validation data flow. Replace invalid CSS variable references and light Tailwind state backgrounds with the existing global theme variables and semantic status colors.

**Tech Stack:** React, TypeScript, Tailwind CSS v4 utility classes, Vite, Python 3.9, ruff.

## Global Constraints

- Do not change validation APIs, store behavior, component structure, or user-facing interactions.
- Reuse existing CSS variables from `web/scada/src/index.css`.
- Do not add code comments.
- Run the frontend build and `ruff check` before completion.

---

### Task 1: Normalize Schema page theme classes

**Files:**
- Modify: `web/scada/src/components/schema/RuleLibraryPage.tsx`
- Modify: `web/scada/src/components/schema/ValidatorPanel.tsx`

**Interfaces:**
- Consumes the existing `ruleCategories`, `layoutConfig`, `useRuleStore`, and `ValidatorPanel` interfaces unchanged.
- Produces the same rendered content and validation interactions with only color and contrast changes.

- [ ] **Step 1: Replace invalid base theme variables**

In both files, replace every occurrence of `var(--bg1)` with `var(--bg)`, `var(--border1)` with `var(--border)`, and `var(--text1)` with `var(--text)`. Preserve all dimensions, layout utilities, labels, and event handlers.

- [ ] **Step 2: Replace light status backgrounds**

Use these exact replacements in `RuleLibraryPage.tsx`:

```tsx
p.required ? "bg-[rgba(224,85,85,0.14)] text-[var(--error)]" : "bg-[var(--bg3)] text-[var(--text3)]"
```

Replace the legal sample label and block classes with:

```tsx
<div className="text-[11px] font-medium text-[var(--success)] mb-1">✓ 合法示例</div>
<pre className="text-[10px] p-2 rounded border border-[rgba(62,207,122,0.45)] bg-[rgba(62,207,122,0.08)] text-[var(--text)] overflow-x-auto max-h-[160px]">
```

Replace the illegal sample label and block classes with:

```tsx
<div className="text-[11px] font-medium text-[var(--error)] mb-1">✗ 非法示例</div>
<pre className="text-[10px] p-2 rounded border border-[rgba(224,85,85,0.45)] bg-[rgba(224,85,85,0.08)] text-[var(--text)] overflow-x-auto max-h-[160px]">
```

Use equivalent semantic classes in `ValidatorPanel.tsx`:

```tsx
error: "bg-[rgba(224,85,85,0.1)] text-[var(--error)] border-[rgba(224,85,85,0.45)]"
warning: "bg-[rgba(232,168,64,0.1)] text-[var(--warn)] border-[rgba(232,168,64,0.45)]"
```

The result header should use `bg-[var(--success)]` for valid results and `bg-[var(--error)]` for invalid results. Error and warning list panels should use the low-opacity backgrounds above, with matching text colors.

- [ ] **Step 3: Search for leftover invalid or light classes**

Run:

```bash
rg -n -- "--bg1|--border1|--text1|bg-(red|green|yellow|gray)-|dark:bg-" web/scada/src/components/schema
```

Expected: no matches.

- [ ] **Step 4: Build the frontend**

Run:

```bash
npm run build
```

from `web/scada`, and verify it exits successfully without TypeScript or CSS compilation errors.

### Task 2: Verify repository quality checks

**Files:**
- No source files.

- [ ] **Step 1: Run ruff**

Run:

```bash
ruff check
```

from the repository root. Verify the command completes successfully, or report any pre-existing unrelated findings separately.

- [ ] **Step 2: Inspect the final diff**

Run:

```bash
git diff -- web/scada/src/components/schema/RuleLibraryPage.tsx web/scada/src/components/schema/ValidatorPanel.tsx
```

Verify only theme classes changed and no validation logic or unrelated user changes were modified.
