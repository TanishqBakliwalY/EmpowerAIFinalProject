"""Build the self-contained report.html and slides.html (the two files submitted on Canvas).

    python docs/build.py --repo https://github.com/<user>/<repo>            # public repo
    python docs/build.py --repo https://github.com/<user>/<repo> --private  # private repo (zlisto added)
    python docs/build.py                                                    # rebuild with the saved settings

Reads docs/report.src.html and docs/slides.src.html, fills in the GitHub repo link (both files must carry it, because the
graders clone the repo from the link in the submitted files), and replaces every local image reference
(src="shots/x.png", src="diagrams/y.svg") with an embedded data: URI, so each file opens on any computer by
double-clicking, with every screenshot showing. The repo settings are saved in docs/submission.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent
OUT = DOCS.parent  # report.html and slides.html land in the repo root
SETTINGS = DOCS / "submission.json"

_SRC = re.compile(r'(src|href)="((?:shots|diagrams)/[^"]+)"')
_REPO = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/?$")


def inline(html: str) -> tuple[str, int]:
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        path = DOCS / m.group(2)
        if not path.exists():
            raise FileNotFoundError(f"missing asset: {path}")
        mime = "image/svg+xml" if path.suffix == ".svg" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        n += 1
        return f'{m.group(1)}="data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"'

    return _SRC.sub(repl, html), n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="GitHub repo URL, e.g. https://github.com/user/empower-ops-agents")
    vis = ap.add_mutually_exclusive_group()
    vis.add_argument("--private", action="store_true", help="the repo is private (zlisto added as a collaborator)")
    vis.add_argument("--public", action="store_true", help="the repo is public")
    args = ap.parse_args()

    cfg = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    if args.repo:
        if not _REPO.match(args.repo.strip()):
            raise SystemExit(f"--repo should look like https://github.com/<user>/<repo>, got: {args.repo}")
        cfg["repo_url"] = args.repo.strip().rstrip("/")
    if args.private or args.public:
        cfg["private"] = bool(args.private)
    if cfg:
        SETTINGS.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    repo = cfg.get("repo_url")
    if repo:
        note = (" · <b>private repository</b>: the course staff's GitHub account (zlisto) is added as a collaborator"
                if cfg.get("private") else " · public repository")
    else:
        repo, note = "ADD-REPO-URL", ' <b style="color:#c0392b">[GitHub repo link missing: run docs/build.py --repo …]</b>'

    problems = []
    for name in ("report", "slides"):
        src = DOCS / f"{name}.src.html"
        html = src.read_text(encoding="utf-8")
        if "{{REPO_URL}}" not in html:
            problems.append(f"{name}: has no {{{{REPO_URL}}}} placeholder, so the repo link would be missing")
        html = html.replace("{{REPO_URL}}", repo).replace("{{REPO_NOTE}}", note)
        html, n = inline(html)
        problems += [f"{name}: unfilled placeholder '{m}'" for m in sorted(set(re.findall(r"\[\[[^\]]{0,60}", html)))]
        out = OUT / f"{name}.html"
        out.write_text(html, encoding="utf-8")
        print(f"{out.name}: {n} embedded images, {out.stat().st_size / 1e6:.1f} MB, repo link {'set' if 'repo_url' in cfg else 'MISSING'}")

    if "repo_url" not in cfg:
        problems.insert(0, "no GitHub repo link yet: run  python docs/build.py --repo https://github.com/<user>/<repo> [--private]")
    elif "private" not in cfg:
        problems.insert(0, "say whether the repo is private: add --private or --public")
    if problems:
        print("\nNOT READY TO SUBMIT:")
        for p in problems:
            print("  -", p)
    else:
        print(f"\nReady to submit: report.html and slides.html both link to {cfg['repo_url']}"
              f" ({'private' if cfg.get('private') else 'public'}).")


if __name__ == "__main__":
    main()
