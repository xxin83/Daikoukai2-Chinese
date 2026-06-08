#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import re
import unicodedata
import tkinter as tk
from tkinter import filedialog, messagebox
try:
    from opencc import OpenCC
except Exception:
    OpenCC = None
_CC_S2T = OpenCC("s2t") if OpenCC else None
_CC_T2S = OpenCC("t2s") if OpenCC else None

TABLE_RE = re.compile(r"^\s*([0-9A-Fa-f]{2,6})=(.*)\s*$")


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "big5", "cp932"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def load_table_tokens(path: Path):
    text = read_text_auto(path)
    tokens = set()
    for ln in text.splitlines():
        m = TABLE_RE.match(ln)
        if not m:
            continue
        rhs = m.group(2)
        if rhs:
            tokens.add(rhs)
    return tokens


def pseudo_simp_trad_variants(ch: str):
    # 轻量内置（可扩充）：繁简 + 中日常见字形
    pairs = {
        "你": "妳", "妳": "你",
        "并": "並", "並": "并",
        "么": "麼", "麼": "么",
        "厂": "廠", "廠": "厂",
        "万": "萬", "萬": "万",
        "说": "說", "說": "说",
        "后": "後", "後": "后",
        "台": "臺", "臺": "台",
        "国": "國", "國": "国",
        "学": "學", "學": "学",
        "広": "廣", "廣": "広",
        "沢": "澤", "澤": "沢",
        "鉄": "鐵", "鐵": "鉄",
        "気": "氣", "氣": "気",
    }
    v = []
    if ch in pairs:
        v.append(pairs[ch])
    return v


def opencc_variants(ch: str):
    out = set()
    if _CC_S2T is None or _CC_T2S is None:
        return out
    try:
        out.add(_CC_S2T.convert(ch))
        out.add(_CC_T2S.convert(ch))
    except Exception:
        return set()
    return {x for x in out if x and x != ch}


def candidate_aliases(tok: str):
    cands = set()
    cands.add(unicodedata.normalize("NFKC", tok))
    for ch in tok:
        for v in pseudo_simp_trad_variants(ch):
            cands.add(v)
        for v in opencc_variants(ch):
            cands.add(v)
    cands.discard(tok)
    cands.discard("")
    return cands


def build_alias(normal_tbl: Path, kata_tbl: Path | None):
    tokens = set()
    tokens |= load_table_tokens(normal_tbl)
    if kata_tbl:
        tokens |= load_table_tokens(kata_tbl)

    alias = {}
    for t in sorted(tokens):
        # 仅单字符做别名最稳
        if len(t) != 1:
            continue
        cands = candidate_aliases(t)
        # 宽松策略：主字在码表即可，别名不要求也在码表中
        hit = [x for x in cands if x != t]
        if hit:
            alias[t] = sorted(set(hit), key=lambda x: ord(x))

    # 双向补全
    for k, arr in list(alias.items()):
        for v in arr:
            alias.setdefault(v, [])
            if k not in alias[v]:
                alias[v].append(k)

    for k in list(alias.keys()):
        alias[k] = sorted(set(alias[k]), key=lambda x: ord(x))

    return alias, len(tokens)


def write_alias_txt(alias: dict, out_path: Path):
    lines = ["# 自动生成别名字典", "# 格式: 主字=别名1,别名2", ""]
    for k in sorted(alias.keys(), key=lambda x: ord(x)):
        arr = [x for x in alias[k] if x != k]
        if not arr:
            continue
        lines.append(f"{k}={','.join(arr)}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("生成别名字典")
        self.root.geometry("820x250")

        self.normal_var = tk.StringVar()
        self.kata_var = tk.StringVar()
        self.out_var = tk.StringVar(value=r"E:\sfc\Roms\字库\别名字典_auto.txt")
        self.status_var = tk.StringVar(value="就绪")

        self._build()

    def _pick_normal(self):
        p = filedialog.askopenfilename(title="选择普通码表", filetypes=[("Text", "*.txt *.tbl"), ("All", "*.*")])
        if p:
            self.normal_var.set(p)

    def _pick_kata(self):
        p = filedialog.askopenfilename(title="选择片假名码表(可选)", filetypes=[("Text", "*.txt *.tbl"), ("All", "*.*")])
        if p:
            self.kata_var.set(p)

    def _pick_out(self):
        p = filedialog.asksaveasfilename(title="保存别名字典", defaultextension=".txt", initialfile="别名字典_auto.txt", filetypes=[("Text", "*.txt")])
        if p:
            self.out_var.set(p)

    def _run(self):
        n = self.normal_var.get().strip()
        k = self.kata_var.get().strip()
        o = self.out_var.get().strip()
        if not n:
            messagebox.showerror("错误", "请选择普通码表")
            return
        try:
            alias, tok_cnt = build_alias(Path(n), Path(k) if k else None)
            write_alias_txt(alias, Path(o))
            self.status_var.set(f"完成: 码表字符 {tok_cnt}，别名主项 {len(alias)} -> {o}")
            messagebox.showinfo("完成", f"码表字符数: {tok_cnt}\n别名主项数: {len(alias)}\n输出: {o}")
        except Exception as ex:
            self.status_var.set("失败")
            messagebox.showerror("错误", str(ex))

    def _build(self):
        frm = tk.Frame(self.root)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(frm, text="普通码表", width=12, anchor="w").grid(row=0, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.normal_var).grid(row=0, column=1, sticky="we", pady=6)
        tk.Button(frm, text="选择", command=self._pick_normal, width=10).grid(row=0, column=2, padx=6)

        tk.Label(frm, text="片假名码表", width=12, anchor="w").grid(row=1, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.kata_var).grid(row=1, column=1, sticky="we", pady=6)
        tk.Button(frm, text="选择", command=self._pick_kata, width=10).grid(row=1, column=2, padx=6)

        tk.Label(frm, text="输出字典", width=12, anchor="w").grid(row=2, column=0, sticky="w", pady=6)
        tk.Entry(frm, textvariable=self.out_var).grid(row=2, column=1, sticky="we", pady=6)
        tk.Button(frm, text="保存为", command=self._pick_out, width=10).grid(row=2, column=2, padx=6)

        tk.Button(frm, text="开始生成", command=self._run, width=12).grid(row=3, column=1, sticky="w", pady=10)
        tk.Label(frm, textvariable=self.status_var, fg="blue", anchor="w").grid(row=4, column=0, columnspan=3, sticky="we", pady=8)

        frm.grid_columnconfigure(1, weight=1)


def cli_main():
    p = argparse.ArgumentParser(description="生成别名字典")
    p.add_argument("--normal", help="普通码表路径")
    p.add_argument("--kata", help="片假名码表路径", default="")
    p.add_argument("--out", help="输出别名字典路径", default=r"E:\sfc\Roms\字库\别名字典_auto.txt")
    p.add_argument("--ui", action="store_true", help="使用图形界面")
    args = p.parse_args()

    if args.ui or not args.normal:
        root = tk.Tk()
        App(root)
        root.mainloop()
        return

    alias, tok_cnt = build_alias(Path(args.normal), Path(args.kata) if args.kata else None)
    write_alias_txt(alias, Path(args.out))
    print(f"码表字符数: {tok_cnt}")
    print(f"别名主项数: {len(alias)}")
    print(f"输出: {args.out}")


if __name__ == "__main__":
    cli_main()
