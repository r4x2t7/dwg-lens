"""三种输出：终端文本、JSON、单文件 HTML。"""

from __future__ import annotations

import html
import json

from .probe import DwgInfo

RISK_LABEL = {"high": "高", "medium": "中", "low": "低"}


def _bar(n: int, width: int = 24) -> str:
    return "#" * max(0, min(width, n))


def render_text(info: DwgInfo) -> str:
    L: list[str] = []
    L.append("")
    L.append("─" * 62)
    L.append(f" {info.path}")
    L.append("─" * 62)
    L.append(f" 文件大小   {info.size:,} 字节")
    L.append(f" 格式版本   {info.version_code} → {info.version_name}")
    if info.maintenance:
        L.append(f" 维护版本   {info.maintenance}")
    L.append(f" 压缩存储   {'是（需解压才能读全）' if info.compressed else '否'}")
    L.append(f" 缩略图     {'有' if info.has_thumbnail else '未检出'}")
    if info.save_hints:
        L.append(f" 保存线索   {', '.join(info.save_hints)}（从绘图仪/字体路径推测，可能含模板残留）")
    L.append(f" 外部参照   {'疑似 ' + str(info.xref_count) + ' 处' if info.xref_count else '无'}")
    if info.truncated:
        L.append(" 注意       文件超过 256MB，只扫描了前 256MB")

    L.append("")
    L.append(f" 【风险】{RISK_LABEL[info.risk]} — {info.risk_reason}")

    if info.vendors:
        L.append("")
        L.append(" 【自定义对象】")
        for v in info.vendors:
            L.append(f"   · {v.name}  命中 {v.hits} 次  [{', '.join(v.signatures[:4])}]")
            L.append(f"     {v.note}")

    if info.fonts:
        L.append("")
        L.append(f" 【字体依赖】{len(info.fonts)} 个")
        shx = [f for f in info.fonts if f.lower().endswith(".shx")]
        ttf = [f for f in info.fonts if not f.lower().endswith(".shx")]
        if shx:
            L.append(f"   SHX（缺失会导致乱码）: {', '.join(shx)}")
        if ttf:
            L.append(f"   TTF/TTC: {', '.join(ttf)}")

    if info.title_fields:
        L.append("")
        L.append(f" 【图签字段】{', '.join(info.title_fields)}")

    if info.text_samples:
        L.append("")
        L.append(f" 【图面文字】抽样 {len(info.text_samples)} 条（已滤掉压缩噪音）")
        for s in info.text_samples[:18]:
            L.append(f"   · {s}")

    if info.keywords:
        L.append("")
        L.append(" 【用词分布】")
        for k, n in info.keywords[:12]:
            L.append(f"   {k:<6} {_bar(n, 12)} {n}")

    L.append("")
    return "\n".join(L)


def render_json(info: DwgInfo) -> str:
    return json.dumps(info.to_dict(), ensure_ascii=False, indent=2)


def render_scan(infos: list[DwgInfo]) -> str:
    """批量汇总：拿这张表去和 SDK 供应商谈，比空谈需求有用。"""
    L: list[str] = []
    L.append("| 文件 | 版本 | 大小 | 风险 | 自定义对象 | 字体 |")
    L.append("|---|---|---|---|---|---|")
    for i in infos:
        name = i.path.replace("\\", "/").split("/")[-1]
        v = i.vendors[0].name.split(" ")[0] if i.vendors else "—"
        fonts = f"{len(i.fonts)} 个" if i.fonts else "—"
        L.append(
            f"| {name} | {i.version_code} | {i.size/1024:.0f} KB | "
            f"{RISK_LABEL[i.risk]} | {v} | {fonts} |"
        )
    hi = sum(1 for i in infos if i.risk == "high")
    L.append("")
    L.append(f"共 {len(infos)} 张，高风险（带自定义对象）{hi} 张。")
    return "\n".join(L)


def render_html(info: DwgInfo) -> str:
    e = html.escape
    rows = [
        ("格式版本", f"{info.version_code} → {info.version_name}"),
        ("文件大小", f"{info.size:,} 字节"),
        ("压缩存储", "是" if info.compressed else "否"),
        ("缩略图", "有" if info.has_thumbnail else "未检出"),
        ("外部参照", f"{info.xref_count} 处" if info.xref_count else "无"),
    ]
    vendor_html = ""
    for v in info.vendors:
        vendor_html += (
            f"<tr><td>{e(v.name)}</td><td>{v.hits}</td>"
            f"<td><code>{e(', '.join(v.signatures))}</code></td>"
            f"<td>{e(v.note)}</td></tr>"
        )
    if not vendor_html:
        vendor_html = '<tr><td colspan="4">未检出</td></tr>'

    fonts_html = "".join(f"<li>{e(f)}</li>" for f in info.fonts) or "<li>无</li>"
    text_html = "".join(f"<li>{e(t)}</li>" for t in info.text_samples) or "<li>无</li>"

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>DWG 体检 · {e(info.path.split(chr(92))[-1].split('/')[-1])}</title>
<style>
 body{{font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
      margin:0;padding:40px;background:#f6f7f9;color:#1b1b1f}}
 .card{{background:#fff;border-radius:12px;padding:28px 32px;max-width:880px;
        margin:0 auto 20px;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#6b6b76;font-size:13px;margin-bottom:22px}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #ececf0;vertical-align:top}}
 th{{color:#6b6b76;font-weight:500;width:30%}}
 code{{background:#f2f3f5;padding:1px 5px;border-radius:4px;font-size:12px}}
 .risk{{display:inline-block;padding:3px 12px;border-radius:99px;font-size:13px;font-weight:600}}
 .high{{background:#fde8e4;color:#b3341a}} .medium{{background:#fdf3e0;color:#8a5a10}}
 .low{{background:#e6f4ea;color:#1e6b32}}
 ul{{margin:6px 0;padding-left:20px;columns:2;font-size:13px}}
</style></head><body>
<div class="card">
  <h1>DWG 体检报告</h1>
  <div class="sub">{e(info.path)}</div>
  <p>风险等级：<span class="risk {info.risk}">{RISK_LABEL[info.risk]}</span>
     <span class="sub">{e(info.risk_reason)}</span></p>
  <table>
    {''.join(f'<tr><th>{e(k)}</th><td>{e(v)}</td></tr>' for k, v in rows)}
  </table>
</div>
<div class="card">
  <h1>厂商自定义对象</h1>
  <table><tr><th style="width:26%">来源</th><th style="width:10%">命中</th>
  <th>签名</th><th>影响</th></tr>{vendor_html}</table>
</div>
<div class="card">
  <h1>字体依赖（{len(info.fonts)}）</h1><ul>{fonts_html}</ul>
</div>
<div class="card">
  <h1>图面文字抽样</h1><ul>{text_html}</ul>
</div>
</body></html>"""
