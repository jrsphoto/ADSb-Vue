---
description: Conventions for the DSP layer
globs: ["src/dsp/**/*.rs", "src/ffi/**/*.rs"]
---

# DSP layer

- The FFI boundary is the only place `unsafe` is allowed. Every `unsafe` block
  needs a `// SAFETY:` comment stating the invariant being upheld.
- Sample buffers are always f32 interleaved. Do not introduce a second format.
- No allocation in the hot path. If you need scratch space, take it from the
  preallocated pool.
- Benchmarks live in `benches/`. A change to filter code needs a before/after
  number, not an assertion that it is faster.
