#!/usr/bin/env python3
"""Apply legacy-kernel (arm64 / Linux 4.14) compatibility patches to
SukiSU-Nova v3.0.0 kernel tree. Run from the extracted source dir; the
source tree path is passed as argv[1].
"""
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KSU_SRC", "kernel")


def patch(path, transform, label):
    full = os.path.join(SRC, path)
    if not os.path.isfile(full):
        print(f"[SKIP] {label}: file not found {full}")
        return
    s = open(full, encoding="utf-8", errors="surrogateescape").read()
    s2 = transform(s)
    if s2 == s:
        print(f"[SKIP] {label}: no change (already patched or pattern absent)")
        return
    open(full, "w", encoding="utf-8", errors="surrogateescape").write(s2)
    print(f"[OK]   {label}: {path}")


def guard_module_import_ns(s):
    old = ('#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 13, 0)\n'
           'MODULE_IMPORT_NS("VFS_internal_I_am_really_a_filesystem_and_am_NOT_a_driver");\n'
           '#else\n'
           'MODULE_IMPORT_NS(VFS_internal_I_am_really_a_filesystem_and_am_NOT_a_driver);\n'
           '#endif')
    new = ('#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 3, 0)\n'
           '#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 13, 0)\n'
           'MODULE_IMPORT_NS("VFS_internal_I_am_really_a_filesystem_and_am_NOT_a_driver");\n'
           '#else\n'
           'MODULE_IMPORT_NS(VFS_internal_I_am_really_a_filesystem_and_am_NOT_a_driver);\n'
           '#endif\n'
           '#endif  /* KSU: MODULE_IMPORT_NS >= 5.3 */')
    return s.replace(old, new, 1)


def add_nocfi_flag(s):
    if "-D__nocfi=" in s:
        return s
    anchor = "ccflags-y += -Wno-strict-prototypes"
    if anchor not in s:
        return s
    return s.replace(anchor, "ccflags-y += -D__nocfi=\n" + anchor, 1)


patch("core/init.c", guard_module_import_ns, "guard MODULE_IMPORT_NS (pre-5.3)")
patch("Kbuild", add_nocfi_flag, "define empty __nocfi (pre-5.13)")

print("=== verification ===")
init = os.path.join(SRC, "core/init.c")
if os.path.isfile(init):
    for i, line in enumerate(open(init, encoding="utf-8", errors="replace"), 1):
        if "MODULE_IMPORT_NS" in line or "5, 3, 0" in line:
            print(f"init.c:{i}: {line.rstrip()}")
kb = os.path.join(SRC, "Kbuild")
if os.path.isfile(kb):
    for i, line in enumerate(open(kb, encoding="utf-8", errors="replace"), 1):
        if "__nocfi" in line:
            print(f"Kbuild:{i}: {line.rstrip()}")
