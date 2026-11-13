# codebase-explainer (Claude Code skill)

Type `/codebase-explainer` inside any repo and Claude writes `CODEBASE_GUIDE.md`. The guide explains what every file does, why the app needs it, and how the parts connect, with Mermaid diagrams.

## Install (once, works in every repo)

Unzip so the folder lands in your personal skills directory:

- macOS / Linux: `~/.claude/skills/codebase-explainer/`
- Windows: `%USERPROFILE%\.claude\skills\codebase-explainer\`

```bash
mkdir -p ~/.claude/skills
unzip codebase-explainer.zip -d ~/.claude/skills/
```

Restart Claude Code (or start a new session) and type `/` to see it in the menu.

**Or install it in just one project:** copy the folder to `<your-project>/.claude/skills/codebase-explainer/`. Claude Code then loads it whenever it is opened in that project, and anyone who clones the repo gets it too. The scanner skips its own folder, so the skill's files never show up in your guide.

Works in the `claude` CLI (any terminal, including VS Code's) and in the Claude Code VS Code extension.

## Use

```text
/codebase-explainer                      # whole repo, full depth
/codebase-explainer src/api              # deep-dive one folder
/codebase-explainer --quick              # overview + diagrams + key files only
/codebase-explainer --out docs/GUIDE.md  # choose the output path
```

You can also just ask, "explain how this codebase works", and Claude will pick the skill up on its own.

## What's inside

| File | Purpose |
|---|---|
| `SKILL.md` | The workflow Claude follows: scan, read, trace flows, write, verify. |
| `template.md` | Section-by-section structure of the guide. |
| `reference/mermaid-guide.md` | Diagram patterns and the syntax rules that keep them rendering on GitHub. |
| `scripts/scan_repo.py` | Fast inventory: stack, entry points, import graph, hub files, routes, env var names. |
| `scripts/verify_guide.py` | Checks the guide: no invented paths, every file explained, valid Mermaid. |
| `examples/example-guide.md` | A real generated guide, for reference. |

## Requirements

- Claude Code.
- Python 3.8+ for the two scripts (standard library only). Without Python the skill falls back to Claude's own search tools.
- Optional: `npm i -g @mermaid-js/mermaid-cli` lets the verifier render-test every diagram.
