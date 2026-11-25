---
description: Check UI files against the design system that governs them
argument-hint: "[path, or nothing for the current directory]"
---

Check design-system compliance of: $ARGUMENTS

1. If no path was given, use the current working directory.
2. Call `which_system` first and say in one line which design system applies. If none does, say
   so and stop — do not guess one.
3. Call `check_design` on the path.
4. Report it usefully rather than dumping the list:
   - Lead with the error and warning counts.
   - Group by rule, worst first.
   - For each `error`, say what to change, with file and line.
   - `thai_font_size` and `dark_mode_hardcoded` are real breakages — call them out explicitly.
   - Treat `palette` as advisory: a chart or infographic legitimately uses colours outside the
     brand palette, so do not demand changes there without asking.
5. Offer to fix the errors. Change nothing until the user agrees.
