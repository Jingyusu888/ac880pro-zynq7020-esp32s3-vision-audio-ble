#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""parse_hmi.py -- USART HMI / Nextion .HMI 容器解析与完整性校验（纯标准库，零依赖）

用途
    1) 判定一个 .HMI 是否完整（没传坏）：段表最大 end 是否等于文件长度。
    2) 列出容器内所有段（Program.s / N.pa / N.zi / N.i / N.is ...）。
    3) 导出任意段，做逐字节比对（图片、字库、页面数据）。

容器格式（实测 D:\\petlink2 的 petlink_monitor.HMI 反解，非官方文档）
    u32  count                       段数
    每段 28 字节，自 offset 4 起连续排列：
        char name[16]   ASCII，右侧补 0
        u32  offset     数据在文件中的绝对偏移
        u32  size       数据长度
        u32  crc/flag
    前 4 段（main.HMI 等）+ 段表尾部的页属性/事件块属于工具自身的目录结构；
    0.pa 是"页面数据 + 该页 5 个事件代码槽"，att-NN / codes*-N 名字出现在 0.pa 内部，
    不在顶层段表里 —— 这一点常被误判为"编译产物"。

用法
    python parse_hmi.py <file.HMI> --list
    python parse_hmi.py <file.HMI> --verify
    python parse_hmi.py <file.HMI> --extract 0.pa --out 0.pa
    python parse_hmi.py <file.HMI> --extract-all out_dir
"""
import argparse
import hashlib
import os
import struct
import sys

ENTRY = 28
NAME_LEN = 16


def read_entries(data):
    if len(data) < 4:
        raise ValueError("file too short")
    count = struct.unpack("<I", data[:4])[0]
    if count <= 0 or 4 + count * ENTRY > len(data):
        raise ValueError("bad segment count %r" % count)
    out = []
    for i in range(count):
        base = 4 + i * ENTRY
        raw_name = data[base:base + NAME_LEN]
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", "replace")
        if not name:
            # 容器里成对出现的目录项（main.HMI / Program.s 的第二份）首字节被
            # 标志位覆盖成 0x00，名字因此以 \x00 开头；退而取首个 0x00 之后的内容。
            name = raw_name.lstrip(b"\x00").split(b"\x00", 1)[0].decode("ascii", "replace")
        if not name:
            name = "(dir-%d)" % i
        off, size, crc = struct.unpack("<III", data[base + NAME_LEN:base + ENTRY])
        out.append({"idx": i, "name": name, "offset": off, "size": size, "crc": crc})
    return count, out


def cmd_list(data):
    count, entries = read_entries(data)
    print("file size : %d bytes" % len(data))
    print("md5       : %s" % hashlib.md5(data).hexdigest())
    print("segments  : %d" % count)
    print("%-4s %-16s %10s %10s %10s  %s" % ("#", "name", "offset", "size", "end", "ok"))
    for e in entries:
        end = e["offset"] + e["size"]
        ok = "yes" if (e["size"] == 0 or (e["offset"] >= 0 and end <= len(data))) else "NO"
        print("%-4d %-16s %10d %10d %10d  %s"
              % (e["idx"], e["name"], e["offset"], e["size"], end, ok))


def cmd_verify(data):
    count, entries = read_entries(data)
    real = [e for e in entries if e["size"] > 0]
    if not real:
        print("FAIL: no payload segments")
        return 1
    max_end = max(e["offset"] + e["size"] for e in real)
    bad = [e for e in real
           if e["offset"] < 0 or e["offset"] + e["size"] > len(data)]
    # 段区间是否重叠
    ordered = sorted(real, key=lambda e: e["offset"])
    overlap = []
    for prev, cur in zip(ordered, ordered[1:]):
        if cur["offset"] < prev["offset"] + prev["size"]:
            overlap.append((prev["name"], cur["name"]))
    print("segments        : %d (%d with payload)" % (count, len(real)))
    print("file size       : %d" % len(data))
    print("max segment end : %d" % max_end)
    print("out of bounds   : %s" % (bad or "none"))
    print("overlapping     : %s" % (overlap or "none"))
    if bad or overlap:
        print("RESULT: FAIL (structure broken)")
        return 1
    if max_end == len(data):
        print("RESULT: OK (last segment ends exactly at EOF -> not truncated)")
        return 0
    print("RESULT: WARN (max end %d != file size %d -> trailing bytes or truncation)"
          % (max_end, len(data)))
    return 2


def cmd_extract(data, name, out):
    _, entries = read_entries(data)
    hit = [e for e in entries if e["name"] == name and e["size"] > 0]
    if not hit:
        print("segment %r not found; available: %s"
              % (name, sorted({e["name"] for e in entries if e["size"] > 0})))
        return 1
    e = hit[0]
    blob = data[e["offset"]:e["offset"] + e["size"]]
    with open(out, "wb") as f:
        f.write(blob)
    print("wrote %s  %d bytes  md5=%s" % (out, len(blob), hashlib.md5(blob).hexdigest()))
    return 0


def cmd_extract_all(data, outdir):
    _, entries = read_entries(data)
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for e in entries:
        if e["size"] == 0:
            continue
        name = e["name"] or ("seg%d.bin" % e["idx"])
        path = os.path.join(outdir, "%02d_%s" % (e["idx"], name.replace("/", "_")))
        with open(path, "wb") as f:
            f.write(data[e["offset"]:e["offset"] + e["size"]])
        n += 1
    print("extracted %d segments to %s" % (n, outdir))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="USART HMI .HMI container parser")
    ap.add_argument("file")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--extract")
    ap.add_argument("--out")
    ap.add_argument("--extract-all")
    a = ap.parse_args(argv)

    with open(a.file, "rb") as f:
        data = f.read()

    if a.verify:
        return cmd_verify(data)
    if a.extract:
        return cmd_extract(data, a.extract, a.out or a.extract)
    if a.extract_all:
        return cmd_extract_all(data, a.extract_all)
    return cmd_list(data)


if __name__ == "__main__":
    sys.exit(main())
