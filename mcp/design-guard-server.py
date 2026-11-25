#!/usr/bin/env python3
"""
design-guard MCP server.

Turns the design-system rules written in prose in CLAUDE.md into checks a tool
can actually enforce, for any MCP client (Claude Code, Antigravity, ...).

Zero dependencies: Python 3.8+ standard library only.
Rules live in rules/systems.json and are edited there, not in this file.

stdio rules obeyed: stdout carries nothing but one JSON-RPC message per line;
logging goes to stderr.
"""

import json
import os
import re
import sys

SERVER_NAME = "design-guard"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
LATEST_PROTOCOL = SUPPORTED_PROTOCOLS[0]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
def _resolve_rules():
    """Your own rules win over the bundled ones, so a plugin update cannot
    overwrite them. Order: $DESIGN_GUARD_RULES, ~/.design-guard/systems.json,
    then the copy shipped with the plugin."""
    explicit = os.environ.get("DESIGN_GUARD_RULES")
    if explicit:
        return os.path.expanduser(explicit)
    user = os.path.expanduser("~/.design-guard/systems.json")
    if os.path.isfile(user):
        return user
    return os.path.join(ROOT, "rules", "systems.json")


RULES_PATH = _resolve_rules()

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "out", "__pycache__",
             ".next", ".nuxt", "coverage", ".venv", "venv"}
MAX_FINDINGS = 300

EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF" "\U0000FE0F" "\U0001F900-\U0001F9FF" "]"
)
HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
FONT_SIZE_PX = re.compile(r"font-size\s*:\s*([0-9.]+)px")
FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}]+)")
DARK_SELECTOR = re.compile(r"prefers-color-scheme\s*:\s*dark|\[data-theme[^\]]*dark", re.I)
MOTION = re.compile(r"\b(transition|animation)\s*:", re.I)
REDUCED = re.compile(r"prefers-reduced-motion", re.I)
THAI = re.compile(r"[\u0E00-\u0E7F]")
CUSTOM_PROP = re.compile(r"^\s*--[a-z0-9-]+\s*:")
AT_FONT_FACE = re.compile(r"@font-face")
SELECTORY = re.compile(r"^\s*([^{}@]+?)\s*\{\s*$")
BADGEISH = re.compile(r"badge|chip|tag|pill|label|lozenge", re.I)


def log(msg):
    print("[design-guard] %s" % msg, file=sys.stderr, flush=True)


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def norm_hex(value):
    value = value.lower().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return "#" + value


def chroma(hex_value):
    """0 for grey, higher for saturated. Lets neutrals through the palette check."""
    v = norm_hex(hex_value).lstrip("#")
    r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    return (max(r, g, b) - min(r, g, b)) / 255.0


def system_for(path, rules):
    """Which design system governs this path? Longest matching path wins."""
    real = os.path.abspath(os.path.expanduser(path)).replace(os.sep, "/")
    best, best_len = None, -1
    for system in rules["systems"]:
        for fragment in system.get("paths", []):
            frag = fragment.strip("/")
            if ("/" + frag + "/") in (real + "/") and len(frag) > best_len:
                best, best_len = system, len(frag)
    return best


def iter_files(target, rules):
    exts = tuple(rules.get("ui_extensions", []))
    target = os.path.abspath(os.path.expanduser(target))
    if os.path.isfile(target):
        yield target
        return
    for base, dirs, names in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in names:
            if name.endswith(exts):
                yield os.path.join(base, name)


def check_file(path, system):
    """Return a list of findings for one file under one design system."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except Exception as exc:
        return [{"file": path, "line": 0, "rule": "unreadable",
                 "severity": "warn", "message": str(exc), "snippet": ""}]

    for skip in system.get("skip_paths", []):
        if skip in path.replace(os.sep, "/"):
            return []

    enabled = set(system.get("checks", []))
    palette = {norm_hex(c) for c in system.get("palette", [])}
    min_px = system.get("min_font_px")
    head = system.get("font_stack_head")
    forbid = [(re.compile(f["pattern"], re.I), f) for f in system.get("forbid", [])]

    out = []
    dark_depth = 0
    in_dark = False
    face_depth = 0
    in_face = False
    svg_depth = 0
    has_motion = False
    has_reduced = False
    selector = ""
    in_comment = False
    seen_palette = set()

    def add(line_no, rule, severity, message, snippet):
        out.append({"file": path, "line": line_no, "rule": rule, "severity": severity,
                    "message": message, "snippet": snippet.strip()[:120]})

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # An inline brand mark or icon carries its own colours; work out the <svg>
        # state before any colour check runs, and treat a one-line <svg>...</svg>
        # as inside it too.
        # A comment that merely *describes* a rule must not trip it.
        was_comment = in_comment
        if "/*" in line and "*/" not in line.split("/*", 1)[1]:
            in_comment = True
        code = line
        if was_comment or in_comment:
            code = ""
        if "*/" in line:
            in_comment = False
            code = line.split("*/", 1)[1]
        if stripped.startswith(("//", "*", "<!--", "#")) or was_comment:
            code = ""
        if "/*" in code:
            code = code.split("/*", 1)[0]
        if "//" in code and "://" not in code:
            code = code.split("//", 1)[0]
        if not code.strip():
            if MOTION.search(line):
                pass
            continue

        line = code
        opens = len(re.findall(r"<svg\b", line, re.I))
        closes = len(re.findall(r"</svg>", line, re.I))
        line_has_svg = opens > 0 or closes > 0 or svg_depth > 0
        svg_depth = max(0, svg_depth + opens - closes)

        # --- track the current selector so rules can be context-aware
        sel = SELECTORY.match(line)
        if sel:
            selector = sel.group(1)
        elif "{" in line and "}" not in line:
            selector = line.split("{")[0].strip() or selector

        # --- forbidden patterns from the rules file
        for pattern, spec in forbid:
            if pattern.search(line):
                if spec.get("only_selectors_matching") and not BADGEISH.search(selector + " " + line):
                    continue
                add(i, "forbid", spec.get("severity", "warn"), spec["message"], line)

        # --- emoji in UI source
        if "emoji" in enabled:
            found = EMOJI.search(line)
            if found and not stripped.startswith(("//", "*", "#")):
                add(i, "emoji", "error",
                    "no emoji in the UI — use a line icon instead (found %r)" % found.group(0), line)

        # --- dark-mode block tracking
        if DARK_SELECTOR.search(line):
            in_dark = True
            dark_depth = 0
        if in_dark:
            dark_depth += line.count("{") - line.count("}")
            if "dark_mode_hardcoded" in enabled and not CUSTOM_PROP.match(line):
                for m in HEX.finditer(line):
                    if chroma(m.group(0)) > 0.10:
                        add(i, "dark_mode_hardcoded", "error",
                            "hard-coded colour %s inside a dark-mode block — use a token or "
                            "color-mix(in srgb, var(--blue) N%%, transparent)" % m.group(0), line)
            if dark_depth <= 0 and "}" in line:
                in_dark = False

        # --- palette drift
        if "palette" in enabled and not in_dark and not line_has_svg:
            for m in HEX.finditer(line):
                value = norm_hex(m.group(0))
                if chroma(value) > 0.12 and value not in palette and value not in seen_palette:
                    seen_palette.add(value)
                    add(i, "palette", "warn",
                        "%s is not in the %s palette (first use; shown once per file)"
                        % (value, system["id"]), line)

        # --- font size: a hard floor for anything, and the real rule for Thai text
        if "min_font_size" in enabled:
            hard = system.get("hard_min_font_px", 10)
            for m in FONT_SIZE_PX.finditer(line):
                size = float(m.group(1))
                if size < float(hard):
                    add(i, "min_font_size", "error",
                        "font-size %spx is below the %spx hard floor — unreadable at any script"
                        % (m.group(1), hard), line)
                elif min_px and size < float(min_px) and THAI.search(line):
                    add(i, "thai_font_size", "error",
                        "font-size %spx on a line containing Thai text; Thai must not go below %spx"
                        % (m.group(1), min_px), line)

        # --- font stack head (a @font-face block declares a font, it does not use one)
        if "font_stack_head" in enabled and head and not in_face:
            for m in FONT_FAMILY.finditer(line):
                stack = m.group(1).strip()
                if "var(" in stack or "inherit" in stack:
                    continue
                first = stack.split(",")[0].strip().strip("'\"")
                if first.lower() not in (head.lower(), "inherit"):
                    add(i, "font_stack_head", "warn",
                        "font stack starts with %r; %s expects %r first" % (first, system["id"], head), line)

        # --- @font-face and <svg> region tracking
        if AT_FONT_FACE.search(line):
            in_face = True
            face_depth = 0
        if in_face:
            face_depth += line.count("{") - line.count("}")
            if face_depth <= 0 and "}" in line:
                in_face = False
        if MOTION.search(line):
            has_motion = True
        if REDUCED.search(line):
            has_reduced = True

    if "reduced_motion" in enabled and has_motion and not has_reduced:
        add(0, "reduced_motion", "warn",
            "this file animates but never honours prefers-reduced-motion", "")

    return out


# --------------------------------------------------------------------------- tools

TOOLS = [
    {
        "name": "check_design",
        "title": "Check files against the project's design system",
        "description": (
            "Lint CSS/HTML/JS/Vue/Svelte/PHP files against the design system that governs their "
            "path, and report violations with file and line. Catches palette drift, emoji in the "
            "UI, type below the size floor, hard-coded colours inside dark-mode blocks, pill radii "
            "where the system wants square badges, missing prefers-reduced-motion, and wrong font "
            "stacks. Call it after writing or editing any UI file, and before telling the user the "
            "work is done."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files or directories to check. A directory is walked recursively.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["all", "error"],
                    "description": "'error' hides warnings. Default 'all'.",
                },
                "system": {
                    "type": "string",
                    "description": "Force a design system id instead of inferring it from the path.",
                },
            },
            "required": ["paths"],
            "additionalProperties": False,
        },
    },
    {
        "name": "which_system",
        "title": "Which design system governs this path",
        "description": (
            "Report which design system applies to a path, with its palette, type floor, font "
            "stack and the rules that will be enforced. Call this before starting UI work in an "
            "unfamiliar project so the first draft is already in the right language."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Any file or directory path."}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_systems",
        "title": "List every configured design system",
        "description": "Show all design systems, the paths they govern, and where their rules live.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def tool_check_design(args):
    rules = load_rules()
    paths = args.get("paths") or []
    if not isinstance(paths, list) or not paths:
        raise ValueError("paths is required and must be a non-empty array")
    only_errors = args.get("severity") == "error"
    forced = args.get("system")

    findings, checked, unknown = [], 0, []
    for target in paths:
        expanded = os.path.abspath(os.path.expanduser(target))
        if not os.path.exists(expanded):
            raise ValueError("path does not exist: %s" % target)
        for path in iter_files(expanded, rules):
            if forced:
                system = next((s for s in rules["systems"] if s["id"] == forced), None)
                if system is None:
                    raise ValueError("unknown system id: %s" % forced)
            else:
                system = system_for(path, rules)
            if system is None:
                unknown.append(path)
                continue
            checked += 1
            findings.extend(check_file(path, system))

    if only_errors:
        findings = [f for f in findings if f["severity"] == "error"]

    total = len(findings)
    truncated = total > MAX_FINDINGS
    shown = findings[:MAX_FINDINGS]

    errors = sum(1 for f in findings if f["severity"] == "error")
    head = "Checked %d file%s. %d error%s, %d warning%s." % (
        checked, "" if checked == 1 else "s",
        errors, "" if errors == 1 else "s",
        total - errors, "" if total - errors == 1 else "s")

    body = []
    for f in shown:
        where = "%s:%s" % (os.path.relpath(f["file"]), f["line"] or "?")
        body.append("%-5s %-20s %s\n        %s%s" % (
            f["severity"].upper(), f["rule"], where, f["message"],
            ("\n        > " + f["snippet"]) if f["snippet"] else ""))

    if truncated:
        body.append("... %d more findings not shown (cap is %d)." % (total - MAX_FINDINGS, MAX_FINDINGS))
    if unknown:
        body.append("\n%d file(s) sit outside every configured design system and were skipped, "
                    "e.g. %s" % (len(unknown), os.path.relpath(unknown[0])))
    if not shown:
        body.append("No violations found.")

    return {
        "content": [{"type": "text", "text": head + "\n\n" + "\n".join(body)}],
        "structuredContent": {"checked": checked, "errors": errors,
                              "warnings": total - errors, "findings": shown},
        "isError": False,
    }


def tool_which_system(args):
    rules = load_rules()
    path = args.get("path")
    if not path:
        raise ValueError("path is required")
    system = system_for(path, rules)
    if system is None:
        ids = ", ".join(s["id"] for s in rules["systems"])
        return {"content": [{"type": "text", "text":
                "No configured design system governs %s.\nKnown systems: %s\n"
                "Add its path to %s to cover it." % (path, ids, RULES_PATH)}]}
    lines = [
        "%s  (id: %s)" % (system["title"], system["id"]),
        "governs      : %s" % ", ".join(system.get("paths", [])),
        "palette      : %s" % ", ".join(system.get("palette", [])) or "(unconstrained)",
        "type floor   : %spx" % system.get("min_font_px", "-"),
        "font stack   : starts with %r" % system.get("font_stack_head", "-"),
        "checks       : %s" % ", ".join(system.get("checks", [])),
        "reference    : %s" % system.get("reference", "-"),
    ]
    for rule in system.get("forbid", []):
        lines.append("forbidden    : %s  (%s)" % (rule["message"], rule["severity"]))
    if system.get("skip_reason"):
        lines.append("not checked  : %s" % system["skip_reason"])
    return {"content": [{"type": "text", "text": "\n".join(lines)}],
            "structuredContent": {"system": system["id"]}}


def tool_list_systems(_args):
    rules = load_rules()
    lines = ["Rules file: %s" % RULES_PATH, ""]
    for s in rules["systems"]:
        lines.append("%-14s %s" % (s["id"], s["title"]))
        lines.append("%-14s %s" % ("", ", ".join(s.get("paths", []))))
    return {"content": [{"type": "text", "text": "\n".join(lines)},
                        {"type": "resource_link", "uri": "file://" + RULES_PATH,
                         "name": "systems.json", "description": "the editable rule set",
                         "mimeType": "application/json"}],
            "structuredContent": {"systems": [s["id"] for s in rules["systems"]]}}


HANDLERS = {"check_design": tool_check_design,
            "which_system": tool_which_system,
            "list_systems": tool_list_systems}

# --------------------------------------------------------------------------- protocol


def handle(message):
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if msg_id is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def fail(code, text):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({
            "protocolVersion": asked if asked in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": ("Call check_design after editing any UI file, and which_system "
                             "before starting UI work in an unfamiliar project."),
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if handler is None:
            return fail(-32602, "Unknown tool: %s" % params.get("name"))
        try:
            return ok(handler(params.get("arguments") or {}))
        except Exception as exc:
            log("tool failed: %r" % exc)
            return ok({"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return fail(-32601, "Method not found: %s" % method)


def main():
    log("started; rules at %s" % RULES_PATH)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        try:
            response = handle(message)
        except Exception as exc:
            log("handler crashed: %r" % exc)
            response = {"jsonrpc": "2.0", "id": message.get("id"),
                        "error": {"code": -32603, "message": "Internal error: %s" % exc}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
