#!/usr/bin/env python3
"""
Replicates the X-Ray OpenGL renderer shader preprocessing
(src/Layers/xrRenderPC_GL/rgl_shaders.cpp :: CRender::shader_compile +
 shader_sources_manager::load_includes) and emits a single flat GLSL
translation unit so that it can be fed to glslang / other validators.

Engine behaviour that is reproduced here:
  * `#include "a\b.h"` is resolved against the *shader root* (gl/), never
    against the directory of the including file, and backslashes are
    normalised to the host separator.
  * the include is a dumb textual splice, done recursively, with no
    once-semantics (the headers rely on their own #ifndef guards).
  * the option block (#version, #extension, #define ...) is prepended as
    separate glShaderSource() strings, i.e. plain text lines.
"""
import argparse
import os
import re
import sys

INCLUDE_RE = re.compile(r'#include\s*"([^"]+)"')


class Flattener:
    def __init__(self, root):
        self.root = root
        self.lines = []        # flat output lines
        self.map = []          # flat line -> (origin file, origin line)

    def emit(self, text, origin, origin_line):
        self.lines.append(text)
        self.map.append((origin, origin_line))

    def resolve(self, inc):
        rel = inc.replace("\\", os.sep).replace("/", os.sep)
        return os.path.join(self.root, rel)

    def add_file(self, path, stack=()):
        rel = os.path.relpath(path, self.root)
        if rel in stack:                       # cycle guard (engine would recurse forever)
            self.emit("// !! recursive include cut: %s" % rel, rel, 0)
            return
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        for n, line in enumerate(src.splitlines(), 1):
            m = INCLUDE_RE.search(line)
            if m:
                before = line[:m.start()]
                after = line[m.end():]
                if before.strip():
                    self.emit(before, rel, n)
                inc_path = self.resolve(m.group(1))
                if not os.path.isfile(inc_path):
                    self.emit("#error missing include %s" % m.group(1), rel, n)
                else:
                    self.add_file(inc_path, stack + (rel,))
                if after.strip():
                    self.emit(after, rel, n)
            else:
                self.emit(line, rel, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--shader", required=True, help="path relative to root")
    ap.add_argument("--define", "-D", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--map", help="write flatline->origin map here")
    args = ap.parse_args()

    f = Flattener(os.path.abspath(args.root))

    # --- option block, exactly as rgl_shaders.cpp builds it -----------------
    f.emit("#version 410", "<options>", 0)
    f.emit("#extension GL_ARB_separate_shader_objects : enable", "<options>", 0)
    f.emit("#pragma optimize (on)", "<options>", 0)
    f.emit("// %s" % args.shader, "<options>", 0)
    for d in args.define:
        if "=" in d:
            k, v = d.split("=", 1)
            f.emit("#define %s %s" % (k, v), "<options>", 0)
        else:
            f.emit("#define %s 1" % d, "<options>", 0)

    f.add_file(os.path.join(f.root, args.shader.replace("\\", os.sep)))

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(f.lines) + "\n")
    if args.map:
        with open(args.map, "w", encoding="utf-8") as fh:
            for i, (origin, ln) in enumerate(f.map, 1):
                fh.write("%d\t%s\t%d\n" % (i, origin, ln))
    return 0


if __name__ == "__main__":
    sys.exit(main())
