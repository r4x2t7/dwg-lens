"""用合成样本做单元测试 —— 仓库里不放任何真实图纸。"""

from __future__ import annotations

import io
import json
import os
import struct
import tempfile
import unittest
from contextlib import redirect_stdout

from dwglens.__main__ import main
from dwglens.probe import probe


def make_dwg(version: str = "AC1018", body: bytes = b"") -> bytes:
    """拼一个最小的假 DWG：版本头 + 一段填充 + 尾部的业务字节。"""
    head = version.encode("latin1") + b"\x00" * 5 + b"\x68" + b"\x00"
    head += struct.pack("<I", 0)          # preview addr
    head += b"\x00" * (0x80 - len(head))
    return head + b"\x00" * 0x200 + body


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write(self, name: str, data: bytes) -> str:
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p


class TestHeader(Tmp):
    def test_r2004(self):
        p = self.write("a.dwg", make_dwg("AC1018"))
        info = probe(p)
        self.assertEqual(info.version_code, "AC1018")
        self.assertIn("2004", info.version_name)
        self.assertTrue(info.compressed)

    def test_r2000_not_compressed(self):
        p = self.write("b.dwg", make_dwg("AC1015"))
        info = probe(p)
        self.assertIn("2000", info.version_name)
        self.assertFalse(info.compressed)
        self.assertEqual(info.risk, "low")

    def test_unknown_version(self):
        p = self.write("c.dwg", b"AC9999" + b"\x00" * 100)
        info = probe(p)
        self.assertEqual(info.version_name, "未知（可能是很老的版本）")


class TestVendors(Tmp):
    def test_hongye_high_risk(self):
        p = self.write("hy.dwg", make_dwg(body=b"FHyAppModul\x00PipeValveStyle\x00www.hongye.com.cn"))
        info = probe(p)
        self.assertEqual(info.risk, "high")
        self.assertTrue(any("鸿业" in v.name for v in info.vendors))
        self.assertIn("FHyAppModul", info.vendors[0].signatures)

    def test_tianzheng(self):
        p = self.write("tz.dwg", make_dwg(body=b"TCH_WALL\x00TCH_OPENING"))
        info = probe(p)
        self.assertEqual(info.risk, "high")
        self.assertTrue(any("天正" in v.name for v in info.vendors))

    def test_clean_file(self):
        p = self.write("clean.dwg", make_dwg(body=b"AcDbLine\x00AcDbCircle"))
        info = probe(p)
        self.assertEqual(info.vendors, [])
        self.assertEqual(info.risk, "medium")   # R2004 压缩，但不是高危


class TestFonts(Tmp):
    def test_fonts(self):
        p = self.write("f.dwg", make_dwg(body=b"hztxt.shx\x00SIMPLEX.shx\x00simsun.ttf"))
        info = probe(p)
        self.assertEqual(len(info.fonts), 3)
        # shx 必须排在前面
        self.assertTrue(info.fonts[0].endswith(".shx"))
        self.assertIn("hztxt.shx", info.fonts)
        self.assertIn("SIMPLEX.shx", info.fonts)

    def test_dedup_case_insensitive(self):
        p = self.write("d.dwg", make_dwg(body=b"hztxt.shx\x00HZTXT.SHX"))
        self.assertEqual(len(probe(p).fonts), 1)


class TestText(Tmp):
    def test_keyword_kept_garbage_dropped(self):
        good = "四层平面图".encode("gbk")
        garbage = "沥奶感啼".encode("gbk")      # 压缩流里的噪音，不含工程用词
        p = self.write("t.dwg", make_dwg(body=good + b"\x00" * 8 + garbage))
        info = probe(p)
        self.assertIn("四层平面图", info.text_samples)
        self.assertNotIn("沥奶感啼", info.text_samples)
        self.assertTrue(any(k == "平面图" for k, _ in info.keywords))

    def test_title_fields(self):
        body = "阶段".encode("gbk") + b"\x00" + "图册号".encode("gbk")
        p = self.write("ti.dwg", make_dwg(body=body))
        info = probe(p)
        self.assertIn("阶段", info.title_fields)
        self.assertIn("图册号", info.title_fields)


class TestCli(Tmp):
    def test_json_output(self):
        p = self.write("j.dwg", make_dwg(body=b"FHyAppModul"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([p, "--json"])
        self.assertEqual(rc, 0)
        d = json.loads(buf.getvalue())
        self.assertEqual(d["version_code"], "AC1018")
        self.assertEqual(d["risk"], "high")
        self.assertIsInstance(d["vendors"], list)

    def test_fail_on_high(self):
        p = self.write("h.dwg", make_dwg(body=b"TCH_WALL"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([p, "--fail-on-high"]), 2)

    def test_missing_file(self):
        self.assertEqual(main(["definitely_not_here.dwg"]), 1)

    def test_scan_dir(self):
        self.write("x.dwg", make_dwg(body=b"TCH_WALL"))
        self.write("y.dwg", make_dwg(body=b"AcDbLine"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([self.dir, "--scan"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("| 文件 |", out)
        self.assertIn("高风险", out)


if __name__ == "__main__":
    unittest.main()
