# Opt-in sampled video evidence API

This Python API qualifies retained sampled PNGs and captured text. It does not
change CLI, MCP or default video processing. Import functions directly from
`distill.pipeline.analysis.video_evidence`; the general analysis facade remains
unchanged. Execution still requires applicable model, time and spending authority.

The caller supplies `LocalVideoFrames`, its confined `frame_root`, captured text,
`DistillConfig` and explicit routing. Retain acquisition receipts before calling.

```python
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.video_evidence import analyze_local_video_evidence

local = RouterConfig(
    provider="ollama", model=installed_vision_model,
    analysis_provider="ollama", cost_mode="no-metered",
    fallback_provider="", fallback_model="",
)
result = analyze_local_video_evidence(
    title, captured_text, frames, frame_root, config,
    router_config=local, tracker=tracker,
    transcript_origin="asr",
    transcript_source_sha256=captured_text_source_sha256,
    max_tokens=4096,
)
```

`analyze_local_video_evidence` preserves the local-only contract for all four
stages. Both image calls require a proved local Ollama model advertising vision.
Missing files, wrong hashes, invalid origins, incomplete responses or unknown
review criteria produce an incomplete result. The transcript origin is one of
`provided_text`, `captions`, `asr` or `model_brief`; the default remains unbound
provided text. A supplied transcript source hash must match the retained video.
ASR and model briefs are model-derived text, not verified verbatim primary text.

For separately authorized text processing, use explicit routes:

```python
from distill.pipeline.analysis.video_evidence import analyze_sampled_video_evidence

result = analyze_sampled_video_evidence(
    title, captured_text, frames, frame_root, config,
    vision_router_config=local,
    text_router_config=approved_text_router,
    tracker=approved_budget_tracker,
    transcript_origin="asr",
    transcript_source_sha256=captured_text_source_sha256,
    max_tokens=4096,
)
```

The two text passes use the explicitly supplied text router. Metered text
requires permitting configuration, known pricing and an explicit tracker budget.
Both routes reject configured fallback. Images remain local; this API does not
enable cloud image transport or automatically choose another provider.
Canonical routing, retry policy and accounting remain in `distill.llm` and
`CostTracker`. `route_policy` and every actual response receipt disclose routing.

At most four logical calls run: local image observation, existing video text
extraction and synthesis, then local image review. Output budgets are explicit
integers from 1 to 8192 tokens, defaulting to 4096. Provider attempts can differ
from logical calls, so retain actual attempt receipts and external trial limits.

Captured file duration is known from the acquisition manifest. Requested frame
anchors do not establish measured presentation times or continuous visibility
between samples. Original upstream completeness remains unestablished. Exact
duplicate frame bytes share one image payload while retaining every requested
anchor. A model description is derived evidence, not independent corroboration.

`model_review_passed` means the five model-review criteria passed for that exact
candidate. Independent review can still reject it. Retain the original result
and require a fresh verdict for any regenerated candidate; a previous passing
self-review does not transfer. This path establishes neither universal video
comprehension, whole-chain privacy nor release qualification.
