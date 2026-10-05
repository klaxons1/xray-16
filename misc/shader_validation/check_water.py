#!/usr/bin/env python3
"""Validate the OpenGL water shaders over the matrix of #defines the engine
can actually generate, using glslang (desktop GLSL 4.10 front end)."""
import itertools
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.join(REPO, "res", "gamedata", "shaders", "gl")
# glslangValidator (or the newer `glslang`) must be on PATH, or point GLSLANG at it.
GLSLANG = os.environ.get("GLSLANG", "glslangValidator")
# Generated translation units are build artifacts: keep them out of the tree.
WORK = os.environ.get("SHADERCHECK_WORK") or tempfile.mkdtemp(prefix="xr-shadercheck-")
os.makedirs(WORK, exist_ok=True)

SHADERS = [
    ("water.vs", "vert", []),
    ("water.ps", "frag", []),
    ("water_soft.vs", "vert", []),
    ("water_soft.ps", "frag", []),
    ("waterd.vs", "vert", []),
    ("waterd.ps", "frag", []),
    ("waterd_soft.vs", "vert", []),
    ("waterd_soft.ps", "frag", []),
]

# The knobs rgl_shaders.cpp toggles that can reach the water shaders.
# NOTE: USE_MSAA / MSAA_OPTIMIZATION are global engine options, so they are
# applied to the water shaders too and must be part of the matrix.
MATRIX = []
for ssr in [None, "1", "2", "3", "4"]:
    for soft in [False, True]:
        for gbuf in [False, True]:
            for msaa in [False, True]:
                for half in [False, True]:
                    for jitter in [False, True]:
                        if half and not ssr:
                            continue          # engine only emits these with SSR on
                        if jitter and not ssr:
                            continue
                        d = []
                        if ssr:
                            d.append("SSR_QUALITY=%s" % ssr)
                        if half:
                            d.append("SSR_HALF_DEPTH")
                        if jitter:
                            d.append("SSR_JITTER")
                        if soft:
                            d.append("USE_SOFT_WATER")
                        if gbuf:
                            d.append("GBUFFER_OPTIMIZATION")
                        if msaa:
                            d.append("USE_MSAA")
                            d.append("MSAA_SAMPLES=4")
                            d.append("ISAMPLE=uint(0)")
                        MATRIX.append(d)


def load_map(path):
    m = {}
    for line in open(path, encoding="utf-8"):
        a, b, c = line.rstrip("\n").split("\t")
        m[int(a)] = (b, int(c))
    return m


# glslang prints "ERROR: <file>:<line>: msg" when given a file,
# and "ERROR: <stringnum>:<line>: msg" for stdin.
ERR_RE = re.compile(r"^(ERROR|WARNING):\s*\S*?:?(\d+):\s*(.*)$")


def run(shader, stage, defines):
    tag = shader.replace(".", "_") + "__" + ("_".join(defines) or "base")
    tag = re.sub(r"[^A-Za-z0-9_]", "_", tag)
    flat = os.path.join(WORK, tag + "." + stage)
    mapf = os.path.join(WORK, tag + ".map")
    cmd = [sys.executable, os.path.join(HERE, "flatten.py"),
           "--root", ROOT, "--shader", shader, "--out", flat, "--map", mapf]
    for d in defines:
        cmd += ["-D", d]
    subprocess.run(cmd, check=True)

    # Plain desktop-GLSL validation: no --client/-V/-G, because the engine
    # feeds this straight to the driver's GLSL compiler, not to SPIR-V.
    p = subprocess.run([GLSLANG, "-S", stage, flat],
                       capture_output=True, text=True)
    lm = load_map(mapf)
    msgs = []
    for line in (p.stdout + p.stderr).splitlines():
        m = ERR_RE.match(line.strip())
        if not m:
            continue
        sev, ln, text = m.group(1), int(m.group(2)), m.group(3)
        origin = lm.get(ln, ("?", 0))
        msgs.append((sev, origin[0], origin[1], text, ln))
    return p.returncode, msgs


def main():
    only = sys.argv[1:] or None
    seen = {}
    total_fail = 0
    for shader, stage, extra in SHADERS:
        if only and shader not in only:
            continue
        for defines in MATRIX:
            rc, msgs = run(shader, stage, defines + extra)
            errs = [m for m in msgs if m[0] == "ERROR"]
            if errs:
                total_fail += 1
                cfg = " ".join(defines) or "(defaults)"
                print("=" * 78)
                print("FAIL %-16s [%s]" % (shader, cfg))
                for sev, f, l, t, fl in errs:
                    print("   %s  %s:%d   %s" % (sev, f, l, t))
                    key = (f, l, t)
                    seen.setdefault(key, []).append((shader, cfg))
    print()
    print("#" * 78)
    print("# UNIQUE DIAGNOSTICS")
    print("#" * 78)
    for (f, l, t), where in sorted(seen.items()):
        print("* %s:%d" % (f, l))
        print("    %s" % t)
        print("    hit by %d configuration(s), e.g. %s [%s]" % (len(where), where[0][0], where[0][1]))
    print("\nfailing configurations: %d" % total_fail)


if __name__ == "__main__":
    main()
