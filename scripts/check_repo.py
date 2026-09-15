#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""公開前にリポジトリを点検する。

外から clone した人がつまずく箇所を機械的に洗う。目視で「たぶん大丈夫」と
判断するのをやめるための道具。

見るもの:
  1. Markdown の相対リンクが実在するファイルを指しているか
  2. 追跡ファイルの中に、追跡外(.gitignore 済み)のパスへの参照がないか
  3. スクリプトが参照するディレクトリのうち、clone 直後に無いもの
  4. 記事本文など、公開すべきでない大きさのファイルが追跡されていないか

使い方:
    ./scripts/check_repo.py
    ./scripts/check_repo.py --verbose
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Markdown の [text](link) から相対リンクだけ拾う。
# 外部 URL、アンカーのみ、mailto は対象外。
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# 追跡ファイルが参照していたら困るパス。clone 直後には存在しない。
UNTRACKED_DIRS = ["data/raw", "data/interim", "data/processed", "data/roundtrip"]

# これを超える追跡ファイルは、記事本文などの混入を疑う。
SIZE_WARN = 500_000


def tracked_files() -> list[Path]:
    """公開されうるファイルを返す。

    追跡済みだけを見ていたら、まだ add していない README の誤りを
    素通りさせた。commit すれば公開されるものは同じ扱いにする。
    --others --exclude-standard で、.gitignore されていない未追跡も拾う。
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def check_links(files: list[Path]) -> list[str]:
    """Markdown の相対リンクが実在するか。"""
    problems = []
    for f in files:
        if f.suffix != ".md" or not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in LINK_RE.finditer(text):
            link = m.group(1)
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = (f.parent / link.split("#")[0]).resolve()
            if not target.exists():
                rel = f.relative_to(ROOT)
                line = text[: m.start()].count("\n") + 1
                problems.append(f"{rel}:{line}  リンク切れ: {link}")
    return problems


def check_untracked_refs(files: list[Path]) -> list[str]:
    """追跡ファイルが、追跡外ディレクトリを手順として案内していないか。

    スクリプトが data/raw を読むのは正常。問題なのは README や docs が
    「このファイルを見てください」と、clone 先に無いものを指す場合。
    """
    problems = []
    docs = [f for f in files if f.suffix == ".md" and f.exists()]
    for f in docs:
        text = f.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            for d in UNTRACKED_DIRS:
                if d not in line:
                    continue
                # コードブロック内の実行例や、生成手順の説明は正常。
                # 「参照してください」系の案内だけを拾いたいが、機械的に
                # 区別できないので、リンク記法になっているものだけ問題とする。
                if re.search(r"\[[^\]]*\]\([^)]*" + re.escape(d), line):
                    problems.append(f"{f.relative_to(ROOT)}:{i}  追跡外へのリンク: {d}")
    return problems


def check_sizes(files: list[Path]) -> list[str]:
    problems = []
    for f in files:
        if not f.exists():
            continue
        size = f.stat().st_size
        if size > SIZE_WARN:
            problems.append(f"{f.relative_to(ROOT)}  {size / 1024:.0f} KB — 中身を確認")
    return problems


def check_commands(files: list[Path]) -> list[str]:
    """Markdown のコードブロックに書いた ./scripts/*.py の引数が実在するか。

    README に `--from` と書いたが実際は `--months` だった、という取り違えを
    実際にやったので、機械で見るようにした。--help の出力に載っていない
    長い引数を指摘する。
    """
    problems = []
    helps: dict[tuple[str, str], str] = {}
    cmd_re = re.compile(r"\./(scripts/[\w_]+\.py)((?:\s+[^\n|>]*)?)")

    def help_for(script: str, sub: str) -> str:
        """--help の出力。サブコマンドがあればそちらを引く。

        roundtrip_queue.py は build/work/status/report を持ち、--mode は
        build 側にしかない。トップレベルだけ見て「無い」と誤検知した。
        """
        key = (script, sub)
        if key in helps:
            return helps[key]
        argv = [str(ROOT / script)] + ([sub] if sub else []) + ["--help"]
        try:
            r = subprocess.run(argv, cwd=ROOT, capture_output=True,
                               text=True, timeout=120)
            helps[key] = r.stdout if r.returncode == 0 else ""
        except Exception:  # noqa: BLE001 — 点検を止めたくない
            helps[key] = ""
        return helps[key]

    for f in files:
        if f.suffix != ".md" or not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in cmd_re.finditer(text):
            script, rest = m.group(1), m.group(2)
            opts = re.findall(r"(--[a-z][\w-]*)", rest)
            if not opts:
                continue
            path = ROOT / script
            if not path.exists():
                problems.append(f"{f.relative_to(ROOT)}  存在しないスクリプト: {script}")
                continue
            # 最初の非オプション語をサブコマンド候補とする
            words = [w for w in rest.split() if not w.startswith("-")]
            sub = words[0] if words and re.fullmatch(r"[a-z][\w-]*", words[0]) else ""
            h = help_for(script, sub) or help_for(script, "")
            if not h:
                problems.append(f"{script}  --help が動かない")
                continue
            for o in opts:
                if o not in h:
                    line = text[: m.start()].count("\n") + 1
                    rel = f.relative_to(ROOT)
                    problems.append(f"{rel}:{line}  {script} に {o} は無い")
    return problems


def check_numbers(files: list[Path]) -> list[str]:
    """記事と docs に書いた数字が、いまのデータと合っているか。

    check_article.py に任せる。データを測り直すたびに数字がずれるので、
    公開前にはここも通したい。data/processed が無い環境では黙って飛ばす。
    """
    if not (ROOT / "data" / "processed").exists():
        return []
    checker = ROOT / "scripts" / "check_article.py"
    if not checker.exists():
        return []
    targets = [f.relative_to(ROOT) for f in files
               if f.suffix == ".md" and f.exists()
               and f.parent.name in {"docs", "article"}]
    if not targets:
        return []
    # 189か月の読み込みが重いので、まとめて1回だけ起動する。
    # ファイルごとに呼ぶと24ファイルで5分を超えた。
    argv = [str(checker)]
    for t in targets:
        argv += ["--file", str(t)]
    try:
        r = subprocess.run(argv, cwd=ROOT, capture_output=True,
                           text=True, timeout=600)
    except Exception as e:  # noqa: BLE001 — 点検を止めたくない
        return [f"数字の照合が動かない: {e}"]
    if r.returncode == 0:
        return []
    problems = []
    current = ""
    for line in r.stdout.splitlines():
        m = re.match(r"## (\S+) — ", line)
        if m:
            current = m.group(1)
            continue
        s = line.strip()
        if s and s[0].isdigit() and "行目" in s:
            problems.append(f"{current}:{s}")
    return problems


def check_entrypoints() -> list[str]:
    """外から来た人が最初に開くファイルがあるか。"""
    problems = []
    for name in ["README.md", "LICENSE"]:
        if not (ROOT / name).exists():
            problems.append(f"{name} がない")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--verbose", action="store_true", help="問題がない項目も表示")
    args = ap.parse_args()

    files = tracked_files()
    checks = [
        ("記事とdocsの数字", check_numbers(files)),
        ("入口のファイル", check_entrypoints()),
        ("Markdown のリンク", check_links(files)),
        ("追跡外への参照", check_untracked_refs(files)),
        ("ドキュメントのコマンド", check_commands(files)),
        ("大きい追跡ファイル", check_sizes(files)),
    ]

    total = 0
    for name, problems in checks:
        if problems:
            total += len(problems)
            print(f"\n## {name} — {len(problems)}件")
            for p in problems:
                print(f"  {p}")
        elif args.verbose:
            print(f"\n## {name} — 問題なし")

    print(f"\n追跡ファイル {len(files)}件 / 指摘 {total}件")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
