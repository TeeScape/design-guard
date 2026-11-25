---
name: design-guard
description: Check UI work against the design system that governs the project, and find out which system applies before starting. Use whenever writing or editing CSS, HTML, JSX, Vue, Svelte or PHP that renders UI — colours, type, spacing, radii, dark mode, icons, animation. Triggers on "design system", "check the styling", "does this match our design", "which design system", "ตรวจดีไซน์", "ตรงกับ design system ไหม", "สีถูกไหม", "ฟอนต์เล็กไป".
---

# Design Guard

Design-system rules written in prose get forgotten. This turns them into checks.

## Use the MCP tools

If this session has `which_system`, `check_design` and `list_systems`, use them:

- **Before** starting UI work in a project: `which_system(path)` reports the palette, the type
  floor, the font stack and what is forbidden there, so the first draft is already right.
- **After** writing or editing any UI file: `check_design(paths)`, before telling the user the
  work is done. Fix every `error`; a `warn` is a judgement call worth raising with them.

If a path matches no configured system, `which_system` says so — then say so too, rather than
guessing a design system.

## Reading the output

| rule | means |
|---|---|
| `emoji` | an emoji or dingbat in UI text; these systems use line icons |
| `palette` | a saturated colour outside the system's palette (once per file, advisory) |
| `min_font_size` | below the hard legibility floor |
| `thai_font_size` | Thai text below the system's floor — a real rule, not a preference |
| `dark_mode_hardcoded` | a literal colour inside a dark-mode block; use a token or `color-mix` |
| `forbid` | a system-specific ban: frosted glass, pill badges, a dark mode that should not exist, a rival brand's blue |
| `reduced_motion` | the file animates but never honours `prefers-reduced-motion` |
| `font_stack_head` | the font stack does not start with the system's family |

Comments are ignored, so a comment describing a rule does not trip it. Token definitions inside a
dark-mode block are correct and are not flagged. Inline `<svg>` marks keep their own colours.

## When it disagrees with you

`rules/systems.json` is the source of truth, not your memory of the house style. If a finding
looks wrong, read that file and tell the user which rule you think is miswritten. Never silently
ignore a finding, and never edit the rules just to make a check pass.
