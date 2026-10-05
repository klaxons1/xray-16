# OpenGL water shader validation

Tooling used to validate the GL water shaders
(`res/gamedata/shaders/gl/water*.{vs,ps}` and their `iostructs/`) against the
OpenGL 4.1 core / GLSL 4.10 specification.

## Why a custom harness

The GL shaders cannot be fed to `glslangValidator` directly:

* They are HLSL-flavoured sources that only become GLSL after
  `shared/common.h` aliases (`float4` → `vec4`, `mul()`, `tex2D`, …).
* `#include "a\b.h"` uses **backslashes** and is always resolved against the
  `gl/` shader root, not against the including file.
* The engine does not use a real include mechanism at all. It textually
  splices files together in `shader_sources_manager::load_includes()` and then
  prepends the `#version` / `#extension` / `#define` block as separate
  `glShaderSource()` strings — see
  `src/Layers/xrRenderPC_GL/rgl_shaders.cpp :: CRender::shader_compile`.

`flatten.py` reproduces exactly that, emitting one flat translation unit plus a
line map so diagnostics can be traced back to the original file and line.

## Usage

```sh
# glslangValidator must be on PATH, or point GLSLANG at it
GLSLANG=/path/to/glslangValidator python3 misc/shader_validation/check_water.py
```

`check_water.py` walks the matrix of preprocessor options that
`rgl_shaders.cpp` can actually emit for the water shaders — `SSR_QUALITY`
(unset/1..4), `SSR_HALF_DEPTH`, `SSR_JITTER`, `USE_SOFT_WATER`,
`GBUFFER_OPTIMIZATION`, `USE_MSAA`/`MSAA_SAMPLES`/`ISAMPLE` — over all eight
water shaders (1088 translation units) and validates each one as desktop
GLSL 4.10.

Note that `--client opengl100` / `-G` must **not** be used: those select
`ARB_gl_spirv` semantics, which impose rules (e.g. "non-opaque uniforms need an
explicit `layout(location=)`") that do not apply here, because the engine hands
GLSL source straight to the driver's compiler.

## Result

All 1088 configurations compile cleanly. glslang alone therefore does **not**
find the defect described below: it is a violation of the *OpenGL API*
specification on the shader/vertex-array interface, which a stand-alone GLSL
front end cannot see.

## Defect found: integer vertex attribute fed through the float path

`res/gamedata/shaders/gl/iostructs/v_waterd.h` declared the water distortion
pass' TEXCOORD0 input with a **signed-integer** type:

```glsl
struct v_vert { ... int2 uv; /* TEXCOORD0 */ };
layout(location = TEXCOORD0) in int2 v_vert_uv;
```

The OpenGL 4.6 core specification, §10.2 *Current Vertex Attribute Values*,
states:

> When values for a vertex shader attribute variable are sourced from an
> enabled generic vertex attribute array, the array must be specified by a
> command compatible with the data type of the variable. The values loaded into
> a shader attribute variable bound to generic attribute index are **undefined**
> if the array for index was not specified by:
> * `VertexAttribFormat`, for floating-point base type attributes;
> * `VertexAttribIFormat` with type `BYTE`, `SHORT` or `INT` for **signed
>   integer base type attributes**; or
> * `VertexAttribIFormat` with type `UNSIGNED_BYTE`, `UNSIGNED_SHORT` or
>   `UNSIGNED_INT` for unsigned integer base type attributes.

The GL backend never calls the integer variants. In
`src/Layers/xrRenderGL/glBufferUtils.cpp` every attribute goes through the
floating-point path:

```cpp
CHK_GL(glVertexAttribPointer(location, size, type, normalized, stride, (void*)offset));
...
CHK_GL(glVertexAttribFormat(location, size, type, normalized, offset));
```

and `D3DDECLTYPE_SHORT2` (the water mesh's packed `-16..+16` texcoord) maps to
`GL_SHORT` with `normalized = GL_FALSE`, i.e. the shorts are *converted to
float*. Reading that attribute as `ivec2` is therefore undefined behaviour; in
practice drivers hand the shader the raw IEEE-754 bit pattern of the converted
float, so `unpack_tc_base()` produced garbage texture coordinates.

This was a leftover from the Direct3D source the GL port was derived from:
DX11 maps `D3DDECLTYPE_SHORT2` to `DXGI_FORMAT_R16G16_SINT`
(`src/Layers/xrRenderDX11/dx11BufferUtils.cpp`), where the shader legitimately
receives SINT values and `int2` is correct.

Corroborating evidence that `float2` is the correct declaration:

* `iostructs/v_water.h` declares the **same** attribute, at the **same**
  location, consumed by the **same** `unpack_tc_base()` helper, as `float2`.
  `water.vs` and `waterd.vs` render the same water geometry with the same
  vertex format.
* `v_waterd.h:29` was the only integer-typed vertex input in the entire
  `res/gamedata/shaders/gl` tree.

Fixed by declaring the attribute as `float2`.
