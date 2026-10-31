"""字节层探测。不做解压，只做能可靠做的事。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .vendors import (
    COMPRESSED_FROM,
    DOMAIN_KEYWORDS,
    TITLE_FIELDS,
    VENDORS,
    VERSIONS,
)

MAX_BYTES = 256 * 1024 * 1024  # 超过就只读前 256MB，避免把内存吃光

CJK_RUN = re.compile(rb"(?:[\xb0-\xf7][\xa1-\xfe]){2,}")
FONT_RE = re.compile(rb"[A-Za-z0-9_\-\.]{2,64}\.(?:shx|SHX|ttf|TTF|ttc|TTC|otf|OTF)")
ASCII_RUN = re.compile(rb"[\x20-\x7e]{5,}")


@dataclass
class VendorHit:
    name: str
    hits: int
    signatures: list[str]
    note: str


@dataclass
class DwgInfo:
    path: str
    size: int
    version_code: str = "?"
    version_name: str = "未知"
    maintenance: int = 0
    compressed: bool = False
    has_thumbnail: bool = False
    fonts: list[str] = field(default_factory=list)
    vendors: list[VendorHit] = field(default_factory=list)
    xref_count: int = 0
    title_fields: list[str] = field(default_factory=list)
    keywords: list[tuple[str, int]] = field(default_factory=list)
    text_samples: list[str] = field(default_factory=list)
    save_hints: list[str] = field(default_factory=list)
    truncated: bool = False
    risk: str = "low"
    risk_reason: str = ""

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["vendors"] = [v.__dict__ for v in self.vendors]
        return d


def _read(path: str) -> tuple[bytes, bool]:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read(min(size, MAX_BYTES))
    return data, size > MAX_BYTES


def _cjk_runs(data: bytes) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in CJK_RUN.finditer(data):
        try:
            t = m.group().decode("gbk")
        except UnicodeDecodeError:
            continue
        if len(t) < 2 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _fonts(data: bytes) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in FONT_RE.finditer(data):
        name = m.group().decode("latin1")
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(name)
    # shx 排前面：它们是乱码的直接原因
    found.sort(key=lambda s: (not s.lower().endswith(".shx"), s.lower()))
    return found


def _vendors(data: bytes) -> list[VendorHit]:
    low = data.lower()
    hits: list[VendorHit] = []
    for name, sigs, note in VENDORS:
        matched: list[str] = []
        total = 0
        for sig in sigs:
            n = low.count(sig.lower())
            if n:
                total += n
                matched.append(sig.decode("latin1"))
        if total:
            hits.append(VendorHit(name=name, hits=total, signatures=matched, note=note))
    hits.sort(key=lambda v: -v.hits)
    return hits


def _save_hints(data: bytes) -> list[str]:
    """从绘图仪/字体路径里推测保存环境。纯文本线索，不保证准确。"""
    hints: list[str] = []
    for m in ASCII_RUN.finditer(data):
        s = m.group().decode("latin1")
        if re.search(r"autocad\s*\d{4}", s, re.I):
            v = re.search(r"autocad\s*(\d{4})", s, re.I).group(1)
            tag = f"AutoCAD {v}"
            if tag not in hints:
                hints.append(tag)
    return hints


def _assess(info: DwgInfo) -> None:
    if info.vendors:
        names = "、".join(v.name for v in info.vendors)
        info.risk = "high"
        info.risk_reason = (
            f"检出 {len(info.vendors)} 个厂商自定义对象（{names}）。"
            "这类实体在第三方解析器里通常是代理框或直接丢失，"
            "自研/开源方案不要承诺能完整显示。"
        )
    elif info.compressed:
        info.risk = "medium"
        info.risk_reason = (
            "图面数据段为压缩存储，纯字节扫描只能看到部分文字；"
            "需完整解析（LibreDWG / ODA）才能判断丢不丢实体。"
        )
    else:
        info.risk = "low"
        info.risk_reason = "未检出厂商自定义对象，且为早期未压缩版本，基础实体通常可直接读取。"


def probe(path: str) -> DwgInfo:
    data, truncated = _read(path)
    info = DwgInfo(path=path, size=os.path.getsize(path), truncated=truncated)

    if len(data) >= 6:
        code = data[0:6].decode("latin1", "replace")
        info.version_code = code
        info.version_name = VERSIONS.get(code, "未知（可能是很老的版本）")
        info.compressed = code in COMPRESSED_FROM
    if len(data) > 0x0B:
        info.maintenance = data[0x0B]

    info.has_thumbnail = b"\x89PNG\r\n\x1a\n" in data[:65536]
    info.fonts = _fonts(data)
    info.vendors = _vendors(data)
    info.save_hints = _save_hints(data)

    low = data.lower()
    info.xref_count = low.count(b".dwg") + low.count(b"xref")

    runs = _cjk_runs(data)
    joined = "\n".join(runs)
    info.title_fields = [f for f in TITLE_FIELDS if f in joined]

    counts: dict[str, int] = {}
    samples: list[str] = []
    for r in runs:
        hit = [k for k in DOMAIN_KEYWORDS if k in r]
        if not hit:
            continue          # 没有工程用词 = 压缩流噪音，丢掉
        for k in hit:
            counts[k] = counts.get(k, 0) + 1
        if 3 <= len(r) <= 40 and r not in samples:
            samples.append(r)

    info.keywords = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    info.text_samples = samples[:60]

    _assess(info)
    return info
