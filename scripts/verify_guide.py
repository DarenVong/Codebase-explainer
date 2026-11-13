#!/usr/bin/env python3
"""
verify_guide.py - check a generated codebase guide against the real repository.

Usage:
    python3 verify_guide.py GUIDE.md [--root ROOT] [--focus SUBDIR]
                            [--min-coverage 1.0] [--render]

Checks:
  1. Paths   - every repo path written in `backticks` really exists (catches invented files).
  2. Coverage- every source / config / schema / migration / CI / style / test file is
               explained, either by its full path or by a narrow glob such as `src/ui/*.tsx`
               or `tests/**`. Folder mentions like `src/` do NOT count as coverage.
  3. Mermaid - each ```mermaid block starts with a known diagram type and avoids the
               syntax mistakes that most often break GitHub rendering. With --render (and
               the Mermaid CLI `mmdc` installed) every diagram is actually rendered.
  4. Shape   - the guide has the core sections and at least three diagrams.

Exit code 0 = pass, 1 = problems to fix, 2 = usage error.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_repo import LANG_BY_EXT, classify, git_info, list_files  # noqa: E402

KNOWN_EXTRA_EXT = {".lock", ".env", ".conf", ".properties", ".plist", ".gradle", ".mod", ".sum"}
REQUIRED_KINDS = {"source", "script", "config", "schema", "database", "migration", "ci", "style", "test"}

DIAGRAM_TYPES = {
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram", "stateDiagram-v2",
    "erDiagram", "journey", "gantt", "pie", "mindmap", "timeline", "gitGraph", "quadrantChart",
    "requirementDiagram", "C4Context", "C4Container", "C4Component", "C4Dynamic", "sankey-beta",
    "xychart-beta", "block-beta", "architecture-beta", "packet-beta", "kanban",
}

SHAPES = [  # (opener, closers) - longest openers first
    ("[[", ("]]",)), ("[(", (")]",)), ("((", ("))",)), ("([", ("])",)), ("{{", ("}}",)),
    ("[/", ("/]", "\\]")), ("[\\", ("\\]", "/]")), ("[", ("]",)), ("(", (")",)), ("{", ("}",)),
    (">", ("]",)),
]
LABEL_SPECIAL = set('()[]{}<>;"')
NODE_RE = re.compile(r"([A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*)\s*(?=[\[\(\{>])")
BLOCK_OPENERS = re.compile(r"^\s*(alt|opt|loop|par|critical|break|rect|box)\b")


# --------------------------------------------------------------------------
# Markdown parsing
# --------------------------------------------------------------------------


def split_markdown(text: str):
    """Return (prose_lines, mermaid_blocks). prose_lines = [(lineno, line)] outside fences."""
    prose, blocks = [], []
    fence, fence_lang, buf, start = None, None, [], 0
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(`{3,}|~{3,})\s*([\w-]*)", line)
        if fence is None and m:
            fence, fence_lang, buf, start = m.group(1), m.group(2).lower(), [], i
            continue
        if fence is not None:
            if line.strip().startswith(fence):
                if fence_lang == "mermaid":
                    blocks.append((start, buf))
                fence = None
            else:
                buf.append(line)
            continue
        prose.append((i, line))
    return prose, blocks


def code_spans(prose):
    for lineno, line in prose:
        for m in re.finditer(r"(?<!`)`([^`\n]+)`(?!`)", line):
            yield lineno, m.group(1)


def normalize_token(tok: str):
    t = tok.strip().strip("'\"")
    t = re.sub(r"#L\d+.*$", "", t)
    t = re.sub(r":\d+(-\d+)?$", "", t)
    t = t.rstrip(".,;:")
    if t.startswith("./"):
        t = t[2:]
    return t


def looks_like_path(t: str) -> bool:
    if not t or any(c.isspace() for c in t):
        return False
    if t.startswith(("http:", "https:", "/", "@", "$", "-", "~", "<", "#", "npm:", "git@")):
        return False
    if any(c in t for c in "(){}=<>,;'\"|`!?"):
        return False
    if "/" in t:
        return True
    return bool(re.fullmatch(r"[\w.\-+]+\.[A-Za-z0-9]{1,10}", t)) or t.startswith(".")


# --------------------------------------------------------------------------
# Mermaid lint
# --------------------------------------------------------------------------


def strip_quoted(s: str) -> str:
    return re.sub(r'"[^"]*"', '""', s)


def lint_flowchart(lines, start, errors, warnings):
    ids = set()
    sub_open = 0
    for off, raw in enumerate(lines, 1):
        ln = start + off
        line = raw.split("%%", 1)[0]
        s = line.strip()
        if not s:
            continue
        if s.startswith(("classDef", "class ", "style ", "linkStyle", "click ", "direction")):
            continue
        if re.match(r"^subgraph\b", s):
            sub_open += 1
            title = strip_quoted(s[len("subgraph"):])
            if set(title) & set('(){}<>;') :
                errors.append(f"line {ln}: subgraph title has special characters - write `subgraph id [\"Title (x)\"]`")
            continue
        if s == "end":
            sub_open -= 1
            continue
        if line.count('"') % 2:
            errors.append(f"line {ln}: unbalanced double quote")
            continue
        if re.search(r"(-->|---|-\.->|==>|--o|--x)\s*end\b|\bend\s*(-->|---|-\.->|==>|\[|\(|\{)", s):
            errors.append(f"line {ln}: lower-case `end` used as a node id breaks the diagram - rename it (e.g. `done`)")
        # node labels
        i = 0
        while i < len(line):
            m = NODE_RE.match(line, i) if (i == 0 or not (line[i - 1].isalnum() or line[i - 1] in "_-")) else None
            if not m:
                # skip quoted strings and edge labels wholesale
                if line[i] == '"':
                    j = line.find('"', i + 1)
                    i = len(line) if j == -1 else j + 1
                    continue
                if line[i] == "|":
                    j = line.find("|", i + 1)
                    if j == -1:
                        break
                    label = line[i + 1:j]
                    if not (label.startswith('"') and label.endswith('"')) and set(label) & LABEL_SPECIAL:
                        errors.append(f"line {ln}: edge label |{label}| has special characters - quote it: |\"{label}\"|")
                    i = j + 1
                    continue
                i += 1
                continue
            node_id = m.group(1)
            pos = m.end()
            opener, closers = next(((o, c) for o, c in SHAPES if line.startswith(o, pos)), (None, None))
            if opener is None:
                i = pos + 1
                continue
            ids.add(node_id)
            body_start = pos + len(opener)
            if line.startswith('"', body_start):
                q = line.find('"', body_start + 1)
                if q == -1:
                    errors.append(f"line {ln}: unterminated quoted label for `{node_id}`")
                    break
                after = line[q + 1:]
                close = next((c for c in closers if after.lstrip().startswith(c)), None)
                if close is None:
                    errors.append(f"line {ln}: label of `{node_id}` is not closed with {' or '.join(closers)}")
                    break
                i = q + 1 + (len(after) - len(after.lstrip())) + len(close)
                continue
            idx = [line.find(c, body_start) for c in closers]
            idx = [x for x in idx if x != -1]
            if not idx:
                if opener in ("[/", "[\\"):
                    errors.append(f"line {ln}: label of `{node_id}` starts with a slash, which Mermaid reads as a slanted "
                                  f"shape - quote it: {node_id}[\"{line[pos + 1:].split(']')[0]}\"]")
                else:
                    errors.append(f"line {ln}: label of `{node_id}` is never closed")
                break
            end = min(idx)
            label = line[body_start:end]
            bad = set(label) & LABEL_SPECIAL
            if bad:
                errors.append(f"line {ln}: label of `{node_id}` contains {''.join(sorted(bad))} without quotes - "
                              f"write {node_id}{opener}\"{label}\"{closers[0]}")
            close_len = next(len(c) for c in closers if line.startswith(c, end))
            i = end + close_len
        for e in re.findall(r"([A-Za-z0-9_][\w-]*)\s*(?:-->|---|-\.->|==>)", strip_quoted(line)):
            ids.add(e)
    if sub_open != 0:
        errors.append(f"diagram at line {start}: `subgraph` / `end` count mismatch ({sub_open:+d})")
    if len(ids) > 30:
        warnings.append(f"diagram at line {start}: {len(ids)} nodes - split it or group nodes into subgraphs (aim for <= 20)")


def lint_sequence(lines, start, errors, warnings):
    depth = 0
    for off, raw in enumerate(lines, 1):
        ln = start + off
        s = raw.split("%%", 1)[0].strip()
        if not s:
            continue
        if BLOCK_OPENERS.match(s):
            depth += 1
        elif s == "end":
            depth -= 1
        elif ":" in s and re.search(r"(->>|-->>|->|-->|-x|--x|-\)|--\))", s):
            msg = s.split(":", 1)[1]
            if ";" in msg:
                errors.append(f"line {ln}: ';' inside a message breaks the diagram - use ',' instead")
        if s.count('"') % 2:
            errors.append(f"line {ln}: unbalanced double quote")
    if depth != 0:
        errors.append(f"diagram at line {start}: alt/opt/loop/par/rect blocks and `end` are unbalanced ({depth:+d})")


def lint_er(lines, start, errors, warnings):
    in_entity = False
    for off, raw in enumerate(lines, 1):
        ln = start + off
        s = raw.split("%%", 1)[0].strip()
        if not s:
            continue
        if s.endswith("{"):
            in_entity = True
            if not re.fullmatch(r'[A-Za-z_][\w-]*(\s*\["[^"]*"\])?\s*\{', s):
                errors.append(f"line {ln}: entity name must be letters/digits/_/- (got `{s[:-1].strip()}`)")
            continue
        if s == "}":
            in_entity = False
            continue
        if in_entity:
            if not re.fullmatch(r'[\w\[\]()<>,.-]+\s+[\w-]+(\s+(PK|FK|UK)(\s*,\s*(PK|FK|UK))*)?(\s+"[^"]*")?', s):
                warnings.append(f"line {ln}: attribute should look like `type name PK \"comment\"`")
            continue
        if ("--" in s or ".." in s) and not re.fullmatch(
                r'[A-Za-z_][\w-]*\s+[|o}{]{2}(--|\.\.)[|o}{]{2}\s+[A-Za-z_][\w-]*\s*:\s*("[^"]*"|[\w-]+)', s):
            errors.append(f"line {ln}: relationship should look like `USER ||--o{{ ORDER : places`")


def lint_mermaid(blocks):
    errors, warnings = [], []
    for start, lines in blocks:
        body = [ln for ln in lines]
        first = next((l.strip() for l in body if l.strip() and not l.strip().startswith("%%")), "")
        if first == "---":  # front-matter config block
            try:
                close = [l.strip() for l in body].index("---", [l.strip() for l in body].index("---") + 1)
                first = next((l.strip() for l in body[close + 1:] if l.strip() and not l.strip().startswith("%%")), "")
            except ValueError:
                pass
        kind = first.split()[0] if first else ""
        if kind not in DIAGRAM_TYPES:
            errors.append(f"diagram at line {start}: unknown or missing diagram type `{kind or '(empty)'}`")
            continue
        if kind in {"flowchart", "graph"}:
            lint_flowchart(body[1:] if body and body[0].strip() == first else body, start + 1, errors, warnings)
        elif kind == "sequenceDiagram":
            lint_sequence(body, start, errors, warnings)
        elif kind == "erDiagram":
            lint_er(body[1:], start + 1, errors, warnings)
        else:
            for off, raw in enumerate(body, 1):
                if raw.count('"') % 2:
                    errors.append(f"line {start + off}: unbalanced double quote")
    return errors, warnings


def render_mermaid(blocks):
    mmdc = shutil.which("mmdc")
    if not mmdc:
        return None, ["`mmdc` not found - install with `npm i -g @mermaid-js/mermaid-cli` to render-check diagrams"]
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        cfg = os.path.join(tmp, "puppeteer.json")
        with open(cfg, "w") as fh:
            json.dump({"args": ["--no-sandbox", "--disable-setuid-sandbox"]}, fh)
        for n, (start, lines) in enumerate(blocks, 1):
            src = os.path.join(tmp, f"d{n}.mmd")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            try:
                r = subprocess.run([mmdc, "-q", "-p", cfg, "-i", src, "-o", os.path.join(tmp, f"d{n}.svg")],
                                   capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                errors.append(f"diagram at line {start}: render timed out")
                continue
            if r.returncode != 0:
                msg = [m.strip() for m in (r.stderr or r.stdout).strip().splitlines() if m.strip()]
                at = next((k for k, m in enumerate(msg) if "rror" in m), 0)
                detail = " | ".join(m for m in msg[at:at + 4] if not m.startswith("at "))
                errors.append(f"diagram at line {start}: does not render - {detail[:400]}")
    return errors, []


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify a codebase guide against the repository.")
    ap.add_argument("guide")
    ap.add_argument("--root", default=".", help="repository root (default: current directory)")
    ap.add_argument("--focus", help="only require coverage for this sub-folder")
    ap.add_argument("--min-coverage", type=float, default=1.0, help="required share of files explained (default 1.0)")
    ap.add_argument("--render", action="store_true", help="also render every diagram with mmdc if installed")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isfile(args.guide):
        print(f"error: guide not found: {args.guide}", file=sys.stderr)
        return 2
    with open(args.guide, encoding="utf-8") as fh:
        text = fh.read()

    files = list_files(root, git_info(root) is not None)
    fileset = set(files)
    guide_rel = os.path.relpath(os.path.abspath(args.guide), root).replace(os.sep, "/")
    files = [f for f in files if f != guide_rel]
    dirs = {"/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)}
    top_level = {f.split("/")[0] for f in files}
    basenames = {f.rsplit("/", 1)[-1] for f in files}
    focus = args.focus.strip("/") + "/" if args.focus else None
    required = [f for f in files if classify(f) in REQUIRED_KINDS and (focus is None or f.startswith(focus))]
    required_set = set(required)

    prose, blocks = split_markdown(text)
    mentioned, missing, warn_names, globs_used, broad = set(), [], [], [], []
    for lineno, raw in code_spans(prose):
        tok = normalize_token(raw)
        if tok in fileset:
            mentioned.add(tok)
            continue
        if not looks_like_path(tok):
            continue
        if "*" in tok or "?" in tok:
            hits = [f for f in files if fnmatch.fnmatch(f, tok)]
            if not hits:
                missing.append((lineno, tok, "glob matches no files"))
                continue
            req_hits = [h for h in hits if h in required_set]
            if tok in {"**", "*", "**/*"} or (len(required) >= 20 and len(req_hits) > 0.4 * len(required)):
                broad.append((lineno, tok, len(req_hits)))
                continue
            globs_used.append(tok)
            mentioned.update(hits)
            continue
        if tok.endswith("/"):
            if tok.rstrip("/") not in dirs and tok.split("/")[0] in top_level:
                missing.append((lineno, tok, "folder not found"))
            continue
        if tok in fileset:
            mentioned.add(tok)
            continue
        if tok in dirs:
            continue
        if "/" in tok:
            if tok.split("/")[0] in top_level:
                missing.append((lineno, tok, "path not found"))
            continue
        ext = os.path.splitext(tok)[1].lower()
        if tok not in basenames and not tok.startswith(".") and (ext in LANG_BY_EXT or ext in KNOWN_EXTRA_EXT):
            warn_names.append((lineno, tok))

    covered = [f for f in required if f in mentioned]
    uncovered = [f for f in required if f not in mentioned]
    coverage = len(covered) / len(required) if required else 1.0

    m_errors, m_warnings = lint_mermaid(blocks)
    r_errors, r_notes = ([], [])
    if args.render and blocks:
        r_errors, r_notes = render_mermaid(blocks)
        r_errors = r_errors or []

    headings = [l.lower() for _, l in prose if l.lstrip().startswith("#")]
    shape_warn = []
    for need, words in [("architecture diagram section", ("architecture", "big picture")),
                        ("file-by-file section", ("file-by-file", "file by file", "what each file does")),
                        ("learning path section", ("learning path", "read in this order", "where to start"))]:
        if not any(any(w in h for w in words) for h in headings):
            shape_warn.append(f"missing {need}")
    if len(blocks) < 3:
        shape_warn.append(f"only {len(blocks)} Mermaid diagram(s) - aim for at least 3")

    ok_paths = not missing
    ok_cov = coverage + 1e-9 >= args.min_coverage
    ok_mer = not m_errors and not r_errors
    print(f"CODEBASE GUIDE CHECK: {args.guide}  (root: {root})")
    print(f"{'PASS' if ok_paths else 'FAIL'}  Paths: {len(mentioned)} repo files referenced, {len(missing)} wrong")
    for lineno, tok, why in missing[:60]:
        print(f"      - line {lineno}: `{tok}` - {why}")
    print(f"{'PASS' if ok_cov else 'FAIL'}  Coverage: {len(covered)}/{len(required)} files explained "
          f"({coverage:.0%}, need {args.min_coverage:.0%})" + (f" - globs used: {len(globs_used)}" if globs_used else ""))
    for f in uncovered[:80]:
        print(f"      - not explained: {f}")
    if len(uncovered) > 80:
        print(f"      … and {len(uncovered) - 80} more")
    for lineno, tok, n in broad:
        print(f"      ! line {lineno}: glob `{tok}` covers {n} files - too broad to count, split it per folder")
    print(f"{'PASS' if ok_mer else 'FAIL'}  Mermaid: {len(blocks)} diagram(s), {len(m_errors) + len(r_errors)} error(s), "
          f"{len(m_warnings)} warning(s){' (rendered with mmdc)' if args.render and r_notes == [] and blocks else ''}")
    for e in m_errors + r_errors:
        print(f"      - {e}")
    for w in m_warnings + r_notes:
        print(f"      ! {w}")
    if warn_names or shape_warn:
        print("NOTE  Other:")
        for lineno, tok in warn_names[:20]:
            print(f"      ! line {lineno}: `{tok}` is not a file name in this repo (fine if it is a library/tool name)")
        for w in shape_warn:
            print(f"      ! {w}")
    passed = ok_paths and ok_cov and ok_mer
    print("RESULT: " + ("PASS" if passed else "FAIL - fix the items above and run again"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
