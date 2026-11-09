#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对比 small / medium 在电话窄带音频上的识别效果与耗时（本机 CPU）。"""
import os
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from faster_whisper import WhisperModel

WAVS = ["tts/selftest.wav", "tts/selftest-phone.wav"]

for name in ("small", "medium"):
    t0 = time.perf_counter()
    model = WhisperModel(name, device="cpu", compute_type="int8")
    load = time.perf_counter() - t0
    print(f"\n=== {name} | 加载 {load:.1f}s ===")
    for wav in WAVS:
        t1 = time.perf_counter()
        segments, info = model.transcribe(wav, language="zh", vad_filter=True)
        text = "".join(s.text for s in segments).strip()
        cost = time.perf_counter() - t1
        print(f"  {wav}  ({info.duration:.1f}s 音频, 识别 {cost:.1f}s, {cost / info.duration:.2f}x 实时)")
        print(f"    {text}")
