# On-Device AI Deployment Report — VMOS Cloud Android

**Date**: 2026-03-29  
**Device**: ACP2509244LGV1MV (OnePlus Ace 3 / PJZ110, Android 15 SDK 35)  
**Platform**: VMOS Cloud — 7 Qualcomm cores (aarch64), 11GB RAM, 53GB free storage

## Executive Summary

Successfully deployed on-device LLM inference on a VMOS Cloud Android phone using cross-compiled llama.cpp. Two models were tested — SmolLM2-135M (fast, low quality) and Qwen2.5-0.5B (usable quality, good speed). The system achieves **35 tokens/second generation** with Qwen2.5-0.5B at optimal thread count, producing coherent code, explanations, and structured responses entirely on-device with no network dependency.

## Architecture

```
Host (x86_64 Ubuntu)                    VMOS Cloud Device (aarch64 Android 15)
┌────────────────────────┐              ┌──────────────────────────────────────┐
│ gcc-aarch64-linux-gnu  │  catbox.moe  │  /data/local/tmp/ai/                │
│ llama.cpp source       │ ──────────►  │  ├── llama-completion (7.8MB ELF)   │
│ CMake cross-compile    │              │  ├── model.gguf (SmolLM2, 138MB)    │
│ Static aarch64 ELF     │  HuggingFace │  └── qwen2.5-0.5b.gguf (469MB)     │
│                        │ ◄──────────  │                                      │
└────────────────────────┘  curl -C -   │  CPU: 7 Qualcomm cores              │
                                        │  Features: NEON ARM_FMA FP16_VA     │
                                        │            DOTPROD (armv8.2-a)       │
                                        │  RAM: 11GB (model uses ~800MB)      │
                                        └──────────────────────────────────────┘
```

## Build Process

### Cross-Compilation (Host → aarch64)

```bash
# Install cross-compiler
apt-get install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu

# Clone llama.cpp
git clone --depth 1 https://github.com/ggml-org/llama.cpp /tmp/llama-cpp-build

# Cross-compile with ARM optimizations
cmake -B build-android \
  -DCMAKE_SYSTEM_NAME=Linux \
  -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc \
  -DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++ \
  -DCMAKE_C_FLAGS="-march=armv8.2-a+dotprod+fp16" \
  -DCMAKE_CXX_FLAGS="-march=armv8.2-a+dotprod+fp16" \
  -DCMAKE_EXE_LINKER_FLAGS="-static" \
  -DGGML_STATIC=ON \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_OPENMP=OFF

cmake --build build-android -j$(nproc) --target llama-completion
aarch64-linux-gnu-strip build-android/bin/llama-completion  # 7.8MB
```

### Deployment to Device

```bash
# Upload binary to catbox.moe (temporary hosting)
curl -F "reqtype=fileupload" -F "fileToUpload=@llama-completion" https://catbox.moe/user/api.php

# Download on device via VMOS Cloud ADB
async_adb_cmd(["ACP2509244LGV1MV"], 'curl -sL -o /data/local/tmp/ai/llama-completion <URL> && chmod +x /data/local/tmp/ai/llama-completion')

# Download model directly from HuggingFace (with resume for large files)
async_adb_cmd(["ACP2509244LGV1MV"], 'curl -L -C - -o /data/local/tmp/ai/qwen2.5-0.5b.gguf "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"')
```

**Note**: VMOS Cloud shell commands timeout after ~3 minutes. Large downloads (>40MB) require `curl -C -` resume mode with multiple iterations.

## Inference Command

```bash
/data/local/tmp/ai/llama-completion \
  -m /data/local/tmp/ai/qwen2.5-0.5b.gguf \
  -p "Your prompt here" \
  -n 150 --temp 0.7 --repeat-penalty 1.2 \
  --no-display-prompt --single-turn --perf \
  -t 4
```

Key flags:
- `--single-turn`: **CRITICAL** — exits after one response instead of entering interactive mode
- `--perf`: Prints performance timing at end
- `-t 4`: Optimal thread count for VMOS Cloud (see benchmarks)
- `--no-display-prompt`: Only output the generated response

## Performance Benchmarks

### Generation Speed (118 tokens, same prompt)

| Model | Size | Threads | Prompt Eval | Generation | Total Time | Memory |
|-------|------|---------|-------------|------------|------------|--------|
| SmolLM2-135M (Q8_0) | 138MB | **4** | **469.6 tok/s** | **103.0 tok/s** | **1.05s** | 414 MiB |
| SmolLM2-135M (Q8_0) | 138MB | 7 | 327.7 tok/s | 66.8 tok/s | 1.60s | 414 MiB |
| Qwen2.5-0.5B (Q4_K_M) | 469MB | **4** | **64.6 tok/s** | **35.3 tok/s** | **3.25s** | ~800 MiB |
| Qwen2.5-0.5B (Q4_K_M) | 469MB | 7 | 35.7 tok/s | 13.1 tok/s | 8.21s | ~800 MiB |

### Key Finding: Thread Scaling is INVERTED on VMOS Cloud

4 threads is **2.5x faster** than 7 threads. This is due to CPU virtualization overhead in the VMOS Cloud environment — additional threads cause contention rather than parallelism. Always use `-t 4` for optimal performance.

### Model Loading Time

| Model | Load Time |
|-------|-----------|
| SmolLM2-135M | 460ms |
| Qwen2.5-0.5B | 1,090ms |

## Quality Assessment

### Qwen2.5-0.5B (Recommended)

**Code Generation** — Correct Python with type hints, docstrings, and test cases:
```
Prompt: "Write a Python function to check if a number is prime. Include type hints."
→ Produced valid is_prime() function with type hints, docstring, generator expression, test cases
   199 tokens in 11.9s @ 16.7 tok/s
```

**General Knowledge** — Coherent multi-paragraph explanations:
```
Prompt: "What is Android? Explain in 3 sentences."
→ Structured response about Android as open-source OS by Google, app ecosystem, developer tools
   132 tokens in 21.1s @ 6.24 tok/s (Note: this was with t=7, slower)
```

**Creative Writing** — Functional haiku generation:
```
Prompt: "Write a haiku about an Android phone."
→ "Android's touchscreen shows, / Life's simple, so easy to see. / Whispers of joy and love, it does!"
   25 tokens in 1.5s @ 17.0 tok/s
```

**Math/Reasoning** — Structure correct, sometimes misreads inputs:
```
Prompt: "If a shirt costs $25 and is on 20% sale, how much do you pay?"
→ Correct discount logic but misread $25 as $5 — limitation of 0.5B model
```

### SmolLM2-135M (Speed Only)

Extremely fast (103 tok/s) but produces incoherent output — confused Android with Atari/Nintendo, generated repetitive text. Not recommended for any quality-sensitive tasks.

## Hardware Features Confirmed Active

```
system_info: n_threads = 4
NEON = 1         ← ARM SIMD (128-bit vectors)
ARM_FMA = 1      ← Fused multiply-add
FP16_VA = 1      ← Half-precision vector arithmetic
DOTPROD = 1      ← 8-bit dot product (critical for quantized inference)
LLAMAFILE = 1    ← Optimized compute kernels
OPENMP = 0       ← Disabled (static build)
AARCH64_REPACK = 1 ← ARM64-specific tensor repacking
```

## Practical Use Cases for Titan

### 1. On-Device Form Filling (Viable Now)
Run the model to generate realistic form input data without network calls:
```bash
llama-completion -m qwen2.5-0.5b.gguf \
  -p "Generate a realistic US shipping address in JSON format" \
  -n 100 --single-turn -t 4
```

### 2. On-Device Decision Making (Viable Now)
Use the model for simple UI navigation decisions:
```bash
llama-completion -m qwen2.5-0.5b.gguf \
  -p "Given these UI elements: [Search, Cart, Profile, Settings], which should I tap to find my order history?" \
  -n 50 --single-turn -t 4
```

### 3. On-Device Text Generation (Viable Now)
Generate realistic chat messages, reviews, or comments:
```bash
llama-completion -m qwen2.5-0.5b.gguf \
  -p "Write a short 5-star product review for wireless earbuds" \
  -n 80 --single-turn -t 4
```

### 4. Device Agent Enhancement (Future)
Integrate with `device_agent.py` See-Think-Act loop — model runs on device itself rather than calling external Ollama, eliminating network latency and detection surface.

## Limitations

1. **VMOS Shell Timeout**: Commands timeout after ~3 minutes. Long generations (>500 tokens) may need workarounds.
2. **No GPU Acceleration**: Vulkan is available but llama.cpp Vulkan backend requires shared libraries (incompatible with static build). CPU-only inference.
3. **Model Quality Ceiling**: 0.5B models are limited — complex reasoning, math, and factual accuracy are unreliable. For serious tasks, 1B+ models are recommended but will run at ~10-15 tok/s.
4. **Thread Contention**: VMOS virtualization limits effective parallelism to 4 threads.
5. **Download Complexity**: Large model files require multi-resume download due to shell timeouts.

## Files on Device

```
/data/local/tmp/ai/
├── llama-completion     7.8MB   ELF 64-bit aarch64 statically linked, stripped
├── llama-chat           5.0MB   Alternative chat binary
├── model.gguf         138MB   SmolLM2-135M-Instruct-Q8_0
└── qwen2.5-0.5b.gguf  469MB   Qwen2.5-0.5B-Instruct-Q4_K_M
```

Total on-device footprint: **620MB** (could be reduced to 477MB by removing SmolLM2)

## Scaling Path

| Model | Size | Est. Speed (4t) | Quality | Feasible? |
|-------|------|-----------------|---------|-----------|
| SmolLM2-135M | 138MB | 103 tok/s | Poor | ✅ Done |
| Qwen2.5-0.5B | 469MB | 35 tok/s | Usable | ✅ Done |
| Qwen2.5-1.5B | ~1.1GB | ~12 tok/s | Good | ✅ Fits in 11GB RAM |
| Llama-3.2-1B | ~700MB | ~20 tok/s | Good | ✅ Fits in 11GB RAM |
| Llama-3.2-3B | ~2GB | ~5 tok/s | Very Good | ⚠️ Borderline RAM |
| Qwen2.5-3B | ~2GB | ~5 tok/s | Very Good | ⚠️ Borderline RAM |
| Qwen2.5-7B | ~4.5GB | ~1-2 tok/s | Excellent | ❌ Too slow |

## Conclusion

On-device AI inference on VMOS Cloud Android is **production-viable** for lightweight tasks. The Qwen2.5-0.5B model achieves 35 tok/s — fast enough for real-time text generation, simple reasoning, and UI navigation. The entire stack (binary + model) fits in 477MB, uses ~800MB RAM, and requires zero network connectivity for inference.

This represents a significant capability leap: AI reasoning can now happen **inside the Android device** itself, invisible to any network monitoring, app telemetry, or server-side detection.
