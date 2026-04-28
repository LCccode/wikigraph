"""LLM Wiki CLI entry point."""

import shutil
import sys
from pathlib import Path

from lcwiki import __version__

_PLATFORM_CONFIG = {
    "claude": {
        "skill_file": "skill.md",
        "skill_dst": Path(".claude") / "skills" / "lcwiki" / "SKILL.md",
        "agents_md": False,
        "default_kb": None,  # Claude Code infers from conversation context
    },
    "claw": {
        "skill_file": "skill-claw.md",
        # OpenClaw reads skills from `<home>/.openclaw/workspace/skills/<name>/SKILL.md`
        # (not `.openclaw/skills/`). Every other skill on the platform lives under
        # workspace/skills/, and openclaw.json pins the workspace root there.
        # Historical bug: versions <=0.3.0 wrote to `.openclaw/skills/lcwiki/`
        # which OpenClaw never read — agents had no SKILL.md and improvised.
        "skill_dst": Path(".openclaw") / "workspace" / "skills" / "lcwiki" / "SKILL.md",
        "agents_md": True,
        "default_kb": Path(".openclaw") / "lcwiki",  # relative to $HOME
    },
}


_KB_SUBDIRS = (
    "raw/inbox",
    "raw/archive",
    "raw/failed",
    "staging/pending",
    "staging/processing",
    "staging/review",
    "staging/failed",
    "vault/wiki/articles",
    "vault/wiki/concepts",
    "vault/wiki/decisions",
    "vault/wiki/templates",
    "vault/meta",
    "vault/graph",
    "vault/queries/memory",
    "vault/queries/cache",
    "logs/reports",
)

_KB_README = """# lcwiki default KB

This is the default knowledge base for lcwiki on this machine (created by
`lcwiki install --platform claw`). When you run a `/lcwiki ...` command
without an explicit `kb_path` argument, it operates on this directory.

## How to use

1. Drop documents (Word / PDF / Excel / PPT / images / audio / video) into
   `raw/inbox/`.
2. In your AI assistant (OpenClaw), type `/lcwiki ingest` — no path needed.
3. Follow with `/lcwiki compile` then `/lcwiki graph`.
4. Query: `/lcwiki query "your question"`.

## Directory layout

    raw/inbox/         drop new documents here
    raw/archive/       processed documents (by sha256)
    staging/           compile task queue
    vault/wiki/        structured articles and concept pages
    vault/meta/        concepts_index, source_map, graph_index
    vault/graph/       graph.json, graph.html, reports
    logs/              run reports and JSONL logs

If you want a separate KB (per-project or otherwise), pass an explicit
path: `/lcwiki ingest /path/to/other-kb`.
"""


def _ensure_kb_structure(kb_root: Path) -> bool:
    """Create the empty kb skeleton. Returns True if created anew, False if it already had structure."""
    already_structured = (kb_root / "vault").exists() and (kb_root / "raw").exists()
    for sub in _KB_SUBDIRS:
        (kb_root / sub).mkdir(parents=True, exist_ok=True)
    readme = kb_root / "README.md"
    if not readme.exists():
        readme.write_text(_KB_README, encoding="utf-8")
    return not already_structured

_AGENTS_MD_MARKER = "<!-- lcwiki:start -->"
_AGENTS_MD_SECTION = f"""{_AGENTS_MD_MARKER}
## lcwiki

This project has the lcwiki knowledge base skill installed. The **default KB** lives at `~/.openclaw/lcwiki/` and is used whenever a `/lcwiki ...` command is issued without an explicit path.

- **Add documents**: drop Word/PDF/Excel/PPT/image/audio/video files into `~/.openclaw/lcwiki/raw/inbox/`
- **Build/update**: run `/lcwiki ingest` (then `compile`, then `graph`) — no path argument needed
- **Query**: `/lcwiki query "your question"`
- **Graph report**: `~/.openclaw/lcwiki/vault/graph/GRAPH_REPORT_SUMMARY.md`
- **Health check**: `/lcwiki audit` (orphan nodes, duplicate concepts — LLM + user confirmation before any change)

For a project-local KB instead of the default, pass an explicit path: `/lcwiki ingest /path/to/kb`.
<!-- lcwiki:end -->
"""


def install(platform: str = "claude") -> None:
    """Install skill file to the appropriate platform directory."""
    if platform not in _PLATFORM_CONFIG:
        supported = ", ".join(_PLATFORM_CONFIG)
        print(f"error: unknown platform '{platform}'. Choose from: {supported}", file=sys.stderr)
        sys.exit(1)

    cfg = _PLATFORM_CONFIG[platform]
    skill_src = Path(__file__).parent / cfg["skill_file"]
    if not skill_src.exists():
        print(
            f"error: {cfg['skill_file']} not found in package - reinstall lcwiki",
            file=sys.stderr,
        )
        sys.exit(1)

    skill_dst = Path.home() / cfg["skill_dst"]
    skill_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(skill_src, skill_dst)
    (skill_dst.parent / ".lcwiki_version").write_text(__version__, encoding="utf-8")
    print(f"  skill installed  ->  {skill_dst}")

    if cfg["agents_md"]:
        _install_agents_md(Path("."))

    # Provision the default kb for platforms that have one (e.g. OpenClaw).
    default_kb_rel = cfg.get("default_kb")
    if default_kb_rel is not None:
        default_kb = Path.home() / default_kb_rel
        created = _ensure_kb_structure(default_kb)
        if created:
            print(f"  default kb created -> {default_kb}")
        else:
            print(f"  default kb ready   -> {default_kb}")
        print(f"  drop documents into: {default_kb / 'raw' / 'inbox'}")

    # Optional system dependency check: LibreOffice for .doc/.ppt handling.
    # Don't auto-install (needs sudo, varies across OS) — just guide the user.
    _check_libreoffice_hint()

    print()
    print(f"Done. Use /lcwiki in {'Claude Code' if platform == 'claude' else 'OpenClaw'} to run the knowledge base.")


def _check_libreoffice_hint() -> None:
    """Print an install hint if LibreOffice is absent. Non-blocking.

    LibreOffice enables lcwiki to handle legacy .doc / .ppt (Word 97-2003,
    PowerPoint 97-2003) formats by auto-converting them to .docx / .pptx
    before downstream processing. Without it, .doc / .ppt files will be
    classified as 'failed' during /lcwiki ingest — other files still work.
    """
    import shutil as _sh
    if _sh.which("soffice") or _sh.which("libreoffice"):
        print("  libreoffice detected — .doc / .ppt will be auto-converted")
        return
    print()
    print("  ℹ️  LibreOffice not found (optional, free, no API key)")
    print("     Install it to handle legacy .doc / .ppt files:")
    print("       Ubuntu/Debian:  apt install -y libreoffice-core")
    print("       macOS:          brew install libreoffice")
    print("       (~200 MB one-time; nothing leaves your machine)")
    print("     Without it, .doc / .ppt files will be skipped during ingest.")


def _install_agents_md(project_dir: Path) -> None:
    """Write lcwiki section to AGENTS.md (for OpenClaw and similar platforms)."""
    target = project_dir / "AGENTS.md"
    if target.exists():
        content = target.read_text(encoding="utf-8")
        if _AGENTS_MD_MARKER in content:
            print("  lcwiki already configured in AGENTS.md")
            return
        target.write_text(content.rstrip() + "\n\n" + _AGENTS_MD_SECTION, encoding="utf-8")
    else:
        target.write_text(_AGENTS_MD_SECTION, encoding="utf-8")
    print(f"  AGENTS.md updated  ->  {target.resolve()}")


def uninstall(platform: str = "claude") -> None:
    """Remove installed skill file."""
    if platform not in _PLATFORM_CONFIG:
        print(f"error: unknown platform '{platform}'.", file=sys.stderr)
        sys.exit(1)

    cfg = _PLATFORM_CONFIG[platform]
    skill_dir = (Path.home() / cfg["skill_dst"]).parent
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
        print(f"  skill removed  ->  {skill_dir}")
    else:
        print("  nothing to remove")

    if cfg["agents_md"]:
        _uninstall_agents_md(Path("."))


def _uninstall_agents_md(project_dir: Path) -> None:
    """Remove lcwiki section from AGENTS.md."""
    import re
    target = project_dir / "AGENTS.md"
    if not target.exists():
        return
    content = target.read_text(encoding="utf-8")
    cleaned = re.sub(
        r"<!-- lcwiki:start -->.*?<!-- lcwiki:end -->\n*",
        "",
        content,
        flags=re.DOTALL,
    ).strip()
    if cleaned:
        target.write_text(cleaned + "\n", encoding="utf-8")
    else:
        target.unlink()
    print(f"  AGENTS.md cleaned  ->  {target.resolve()}")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(f"lcwiki {__version__}")
        print()
        print("Usage:")
        print("  lcwiki install [--platform P]                        Install skill (claude|claw)")
        print("  lcwiki uninstall [--platform P]                      Remove installed skill")
        print("  lcwiki version                                       Show version")
        print()
        print("  lcwiki ingest-run --kb KB                            Smart-ingest raw/inbox/")
        print("  lcwiki ingest-verify --kb KB                         Verify ingest artifacts")
        print()
        print("  lcwiki compile-prepare --kb KB                       Stage pending compile tasks")
        print("  lcwiki compile-write --kb KB --task-id T ...         Finalize one compiled article")
        print("  lcwiki compile-reduce --kb KB                        Merge concepts partials → concepts_index.json")
        print("  lcwiki compile-verify --kb KB                        Verify articles + concepts schema")
        print()
        print("  lcwiki graph-run --kb KB --extraction FILE.json      Build graph from extraction JSON")
        print("             [--obsidian] [--obsidian-dir DIR]")
        print("  lcwiki graph-verify --kb KB                          Verify graph outputs are complete")
        print()
        print("Platforms:")
        print("  claude   Claude Code (default)")
        print("  claw     OpenClaw")
        print()
        print("After installing, use /lcwiki in your AI assistant.")
        return

    cmd = args[0]

    if cmd == "version":
        print(f"lcwiki {__version__}")

    elif cmd == "install":
        platform = "claude"
        if "--platform" in args:
            idx = args.index("--platform")
            if idx + 1 < len(args):
                platform = args[idx + 1]
        install(platform)

    elif cmd == "uninstall":
        platform = "claude"
        if "--platform" in args:
            idx = args.index("--platform")
            if idx + 1 < len(args):
                platform = args[idx + 1]
        uninstall(platform)

    elif cmd == "graph-run":
        from lcwiki import graph_cmd
        sys.exit(graph_cmd.main(args[1:]))

    elif cmd == "graph-verify":
        from lcwiki import graph_verify
        sys.exit(graph_verify.main(args[1:]))

    elif cmd == "ingest-run":
        from lcwiki import ingest_cmd
        sys.exit(ingest_cmd.main(args[1:]))

    elif cmd == "ingest-verify":
        from lcwiki import ingest_verify
        sys.exit(ingest_verify.main(args[1:]))

    elif cmd == "compile-prepare":
        from lcwiki import compile_cmd
        sys.exit(compile_cmd.main_prepare(args[1:]))

    elif cmd == "compile-write":
        from lcwiki import compile_cmd
        sys.exit(compile_cmd.main_write(args[1:]))

    elif cmd == "compile-reduce":
        from lcwiki import compile_cmd
        sys.exit(compile_cmd.main_reduce(args[1:]))

    elif cmd == "compile-verify":
        from lcwiki import compile_verify
        sys.exit(compile_verify.main(args[1:]))

    else:
        print(f"error: unknown command '{cmd}'. Run 'lcwiki --help' for usage.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
