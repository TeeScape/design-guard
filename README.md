# Design Guard

An MCP server that enforces the design system a file belongs to, instead of hoping the agent
remembers the house style.

Design rules usually live in prose — a `CLAUDE.md`, a wiki page, a Figma comment. Agents read
them once and drift anyway. This maps **path → design system → rules**, and reports violations
with file and line, for Claude Code and any other MCP client.

## Tools

| tool | does |
|---|---|
| `which_system(path)` | which system governs this path: palette, type floor, font stack, what is banned |
| `check_design(paths)` | lint files or directories; returns findings with file, line and fix |
| `list_systems()` | every configured system and the paths it covers |

## Checks

`emoji` · `palette` · `min_font_size` · `thai_font_size` · `dark_mode_hardcoded` · `forbid`
(system-specific bans) · `reduced_motion` · `font_stack_head`

It deliberately does **not** flag: comments that merely describe a rule, token definitions inside
a dark-mode block, or colours inside an inline `<svg>` brand mark.

## Rules live in JSON, not in code

`rules/systems.json` holds every system, its paths, palette, floors and bans. Add a project by
adding a path. Point `DESIGN_GUARD_RULES` at another file to use a different rule set.

```json
{
  "id": "example-marketing",
  "paths": ["code/example-site"],
  "palette": ["#1b9b6f", "#15805c", "#1e3240"],
  "min_font_px": 13,
  "checks": ["emoji", "palette", "min_font_size", "font_stack_head"],
  "forbid": [
    {"pattern": "#3b6cf6", "message": "the app's blue must never appear on the marketing site", "severity": "error"}
  ]
}
```

## Install

Zero dependencies — Python 3.8+ standard library, nothing to install.

**Claude Code**
```
/plugin marketplace add <path-or-repo>
```
```
/plugin install design-guard@design-guard
```

**Antigravity, or any other MCP client**
```bash
python3 /path/to/design-guard/mcp/design-guard-server.py
```
Register that command as an MCP server. For Antigravity:
```bash
"/Applications/Antigravity IDE.app/Contents/Resources/app/bin/antigravity-ide" \
  --add-mcp '{"name":"design-guard","command":"python3","args":["/path/to/design-guard/mcp/design-guard-server.py"]}'
```

## Measured on real codebases

Run across three private projects while building it:

| codebase | files | errors | note |
|---|---|---|---|
| a design system kept in line by its own tests | 39 | **0** | the tool stays quiet |
| a larger app that had drifted | 8 | 44 | 26 of them Thai text set below the 13px floor |
| a marketing site | 10 | 4 | including another product's blue that had leaked in |

Staying quiet on a clean codebase is the point. A linter that always shouts gets ignored.

The first pass on that middle project produced **335 errors, almost all false** — a comment
describing a rule tripped that rule, a token definition inside a dark block looked like a
hard-coded colour, `@font-face` looked like a font choice, a single-line inline `<svg>` leaked
its brand colours into the palette check, and a 13px floor meant for Thai text was being applied
to every 11px Latin caption. Those are the cases the checks now handle; it is worth tuning any
rule set the same way before trusting it.

## License

MIT
