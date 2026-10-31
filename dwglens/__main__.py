"""命令行入口：python -m dwglens <文件或目录>"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .probe import probe
from .report import render_html, render_json, render_scan, render_text


def _iter_dwg(root: str):
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith((".dwg", ".dxf")):
                yield os.path.join(dirpath, f)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dwg-lens",
        description="DWG 图纸体检：判断你的查看器能不能读对这张图，会丢什么。",
    )
    ap.add_argument("path", nargs="?", help="DWG/DXF 文件，或目录（配合 --scan）")
    ap.add_argument("--json", action="store_true", help="输出 JSON，方便接脚本")
    ap.add_argument("--html", metavar="OUT", help="另存一份 HTML 报告")
    ap.add_argument("--scan", action="store_true", help="批量体检目录，输出 Markdown 表")
    ap.add_argument("--fail-on-high", action="store_true",
                    help="出现高风险图纸时退出码为 2（可接 CI）")
    ap.add_argument("--version", action="version", version=f"dwg-lens {__version__}")
    args = ap.parse_args(argv)

    if not args.path:
        ap.print_help()
        return 0

    target = Path(args.path)
    if not target.exists():
        print(f"找不到：{args.path}", file=sys.stderr)
        return 1

    # 批量模式
    if args.scan or target.is_dir():
        if not target.is_dir():
            print("--scan 需要传目录", file=sys.stderr)
            return 1
        files = list(_iter_dwg(str(target)))
        if not files:
            print("目录下没有 .dwg / .dxf", file=sys.stderr)
            return 1
        infos = []
        for f in files:
            try:
                infos.append(probe(f))
            except Exception as ex:                      # 单张出错不中断整批
                print(f"[跳过] {f}: {ex}", file=sys.stderr)
        out = render_scan(infos)
        print(render_json_many(infos) if args.json else out)
        if args.html:
            Path(args.html).write_text(_scan_html(infos), encoding="utf-8")
            print(f"\nHTML 报告已写入：{args.html}", file=sys.stderr)
        if args.fail_on_high and any(i.risk == "high" for i in infos):
            return 2
        return 0

    # 单文件
    try:
        info = probe(str(target))
    except Exception as ex:
        print(f"解析失败：{ex}", file=sys.stderr)
        return 1

    print(render_json(info) if args.json else render_text(info))

    if args.html:
        Path(args.html).write_text(render_html(info), encoding="utf-8")
        print(f"HTML 报告已写入：{args.html}", file=sys.stderr)

    return 2 if (args.fail_on_high and info.risk == "high") else 0


def render_json_many(infos) -> str:
    import json
    return json.dumps([i.to_dict() for i in infos], ensure_ascii=False, indent=2)


def _scan_html(infos) -> str:
    rows = "".join(
        f"<tr><td>{i.path}</td><td>{i.version_code}</td><td>{i.size:,}</td>"
        f"<td>{i.risk}</td><td>{i.vendors[0].name if i.vendors else '—'}</td></tr>"
        for i in infos
    )
    return (
        '<!doctype html><meta charset="utf-8"><title>批量体检</title>'
        "<style>body{font:15px/1.7 sans-serif;padding:32px}"
        "table{border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:6px 12px;text-align:left}</style>"
        "<h1>DWG 批量体检</h1><table><tr><th>文件</th><th>版本</th><th>大小</th>"
        f"<th>风险</th><th>自定义对象</th></tr>{rows}</table>"
    )


if __name__ == "__main__":
    raise SystemExit(main())
