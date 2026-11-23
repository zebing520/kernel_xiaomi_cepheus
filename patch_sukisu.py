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


def replace_all(s, pairs):
    for old, new in pairs:
        s = s.replace(old, new)
    return s


def drop_line(line_text):
    def f(s):
        return "\n".join(l for l in s.split("\n") if l.strip() != line_text)
    return f


patch("core/init.c", guard_module_import_ns, "guard MODULE_IMPORT_NS (pre-5.3)")
patch("Kbuild", add_nocfi_flag, "define empty __nocfi (pre-5.13)")

# feature/sucompat.c: <linux/pgtable.h> only exists on 5.x; on 4.14 the
# pgtable definitions come via <asm/pgtable.h> (already pulled in by linux/mm.h).
patch("feature/sucompat.c",
      drop_line("#include <linux/pgtable.h>"),
      "drop linux/pgtable.h include")

# copy_*_nofault (5.8+) -> probe_kernel_read/write (present since 2.6.x)
patch("hook/arm64/patch_memory.c",
      lambda s: replace_all(s, [("copy_to_kernel_nofault(", "probe_kernel_write(")]),
      "copy_to_kernel_nofault -> probe_kernel_write")
patch("runtime/ksud_integration.c",
      lambda s: replace_all(s, [
          ("copy_from_user_nofault(", "probe_kernel_read("),
          ("copy_to_user_nofault(", "probe_kernel_write("),
      ]),
      "copy_*_user_nofault -> probe_kernel_*")

# strncpy_from_user_nofault (5.8+) -> strncpy_from_user (available in 4.14)
for f in ["feature/sucompat.c", "runtime/ksud_integration.c", "sulog/event.c"]:
    patch(f,
          lambda s: replace_all(s, [("strncpy_from_user_nofault(", "strncpy_from_user(")]),
          "strncpy_from_user_nofault -> strncpy_from_user")

# copy_from_kernel_nofault (5.8+) -> probe_kernel_read (4.14)
patch("selinux/inode.c",
      lambda s: replace_all(s, [("copy_from_kernel_nofault(", "probe_kernel_read(")]),
      "copy_from_kernel_nofault -> probe_kernel_read")

# __poll_t & kernel-side EPOLL* are 4.16+; 4.14 uses unsigned int / POLL*
poll_pairs = [("__poll_t", "unsigned int"),
              ("EPOLLHUP", "POLLHUP"), ("EPOLLIN", "POLLIN"),
              ("EPOLLRDNORM", "POLLRDNORM"), ("EPOLLERR", "POLLERR"),
              ("EPOLLOUT", "POLLOUT")]
for f in ["infra/event_queue.c", "infra/event_queue.h",
          "infra/file_wrapper.c", "sulog/fd.c"]:
    patch(f, lambda s, p=poll_pairs: replace_all(s, p),
          "__poll_t/EPOLL* -> unsigned int/POLL*")

# struct_size() arrived in 4.18; use sizeof(*node)+len on 4.14.
patch("infra/event_queue.c",
      lambda s: replace_all(s, [("struct_size(node, payload, len)",
                                 "(sizeof(*node) + len)")]),
      "struct_size -> sizeof+len")

# <linux/minmax.h> was split out in 5.10; on 4.14 min/max are in linux/kernel.h.
patch("sulog/event.c",
      drop_line("#include <linux/minmax.h>"),
      "drop linux/minmax.h include")

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
