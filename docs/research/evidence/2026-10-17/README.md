# Local maintenance evidence, October 17, 2026

These sanitized JSON receipts describe specific candidates and methods.
[SHA256SUMS](SHA256SUMS) binds each JSON file. Raw model output, hardware
inventory and private machine paths remain in ignored scratch storage.

| Receipt | What it establishes |
| --- | --- |
| [CPU operator candidate](operator-cpu-candidate.json) | Installed wheel on Windows 11, Python 3.15, 32 logical CPUs and 64 GiB RAM; isolated cloud-disabled Ollama; public Gemma 4 e2b Q4_K_M model with zero VRAM; setup, missing daemon/model, bench, current arXiv preview, process-tree interruption, recovery, no-op, ask, audit, force and exact shortlist replay; token/cost ledgers and relative artifact hashes |
| [Earlier candidate](operator-earlier-candidate.json) | Retains the failed answer publication that exposed grouped-citation parsing and exit-status bugs; it is not a passing answer journey |
| [Numeric verification](verification-numeric.json) | Controlled synthetic analysis at the external boundary, real capture/publication/audit, one supported numeric claim and one unsupported prose claim; numeric-only warn and strict publish with explicit limited coverage |
| [CPU prose verification](verification-prose.json) | The same controlled candidate with the actual local HHEM checker; warn flags the prose claim and strict refuses publication while retaining the source and refusal receipt |
| [Paper refusal](paper-refusal-installed.json) | Final installed candidate, controlled metadata/analysis, real single and batch CLI verification: exit 1, receipt retained, no insight publication or follow-on synthesis |
| [DNS failure](dns-failure-installed.json) | Reserved `.invalid` name, capture-only and no-metered; exit 1 with pre-capture HTTPS/public-DNS/page-URL validation failure, no traceback or invented 429 hint |
| [CPU tail probe](cpu-tail-probe.json) | Python 3.14.7, torch 2.12.0+cpu and transformers 4.57.6; CUDA absent; a 1,542-token pair with supported tail evidence scores 0.9877 versus 0.0942 for the contradiction |
| [Browser](browser.json) | Synthetic library, official integrity-checked axe-core 4.14.0, four pages in both house palettes and standalone export: no automated WCAG A/AA violations; mobile layout, 200% CSS zoom, keyboard, clipboard announcements, System changes, import, refresh, removal and persistence |
| [First rendered frames](appearance-first-frames.json) | Installed candidate, stored Dark and Light, a 200 ms delayed blocking theme script: all first eight rendered body frames use the requested theme and stable background |
| [Retained native evaluation](native-plugin-retained.json) | Six unchanged skill/eval cases and retained native report hashes, three runs per arm; no new native call or claim of a new evaluation baseline |
| [Core install](install-core.json) and [CPU extra](install-cpu-extra.json) | Exact candidate wheel, installed package versions and logical file sizes; the CPU environment has a CPU-only torch build and no NVIDIA distributions |
| [Final local gate](quality-gate.json) | 7,672 tests passed with 95.40% combined coverage and branch measurement; lint, type, import, audit, contract, distribution and build checks; checkout runtime files byte-matched to the installed candidate wheel |

The successful paper replay projected 8m10s and took 7m17s including command
startup. Its ledger records 22,682 input and 4,419 output tokens, two local
calls, $0, and zero metered or unknown-cost calls. Numeric verification flagged
one of eleven checked claims. Completion is not a semantic quality pass.

The answer correctly gave 7,128 entities and declined security claims absent
from the synthetic note. Its grouped citations retained both exact paths and
source/derived origins. This one-case inspection does not establish general
citation faithfulness. The calibrated research-desk baseline remains 0.20.8.

The wheel is 1,246,788 bytes. The installed core environment accounts for
227,432,854 logical bytes; the extra-enabled CPU environment accounts for
888,115,929. These measurements exclude the shared interpreter, model cache and
external browser cache, and do not claim unique physical disk allocation.

Persistent empty lock files retain the identity needed for waiting processes.
They are coordination state, not abandoned publication files. The successful
journey left no temporary publication files. Recovery used a killed command
process tree; the isolated validation daemon and retained model workers were
then stopped, preserving the pre-existing shared daemon.

Browser checks do not replace screen-reader review. CPU tail evidence does not
calibrate all prose judgments. The optional extra remains unavailable on Python
3.15 until PyTorch supplies wheels. The broad 1.0 cross-platform, semantic and
freeze-time gates remain separate from these maintenance receipts.
