# Optional dependency review, October 17, 2026

Static triage of the eight imported GitHub Dependabot alerts accompanied the maintenance release. This is a review of Distill's reachable paths, not a repository-wide security scan or a clean optional dependency audit. No exploit was executed.

| Advisory | Assessment and action |
| --- | --- |
| GHSA-27vj-qcqg-25rc, fsspec | Distill does not expose ReferenceFileSystem templates. Raise the optional floor and lock to patched 2026.6.0. |
| GHSA-h35f-9h28-mq5c, setuptools | Distill builds with uv_build rather than the affected MANIFEST.in mechanism. Raise the optional floor and lock to patched 83.0.0. |
| GHSA-rrmf-rvhw-rf47, torch | No attacker-selected TorchScript compilation path. Raise the optional floor and lock to patched 2.14.1; prove the CPU build separately. |
| GHSA-x9r9-c232-4q39, Transformers | No custom generation loader or generate path; the approved checker uses sequence classification and predict. |
| GHSA-xrqw-3rrv-vx5w, Transformers | No tokenizer or processor save_pretrained path. |
| GHSA-fgcw-684q-jj6r, Transformers | Fixed T5 classification model; no attacker-selected LightGlue dispatch. |
| GHSA-29pf-2h5f-8g72, Transformers | The previously unversioned foundation metadata required follow-up. Both outer HHEM code and inner configuration/tokenizer are now bound to reviewed immutable revisions. Captured source text cannot select configuration or kernels; the canonical lock has no kernels package. |
| GHSA-69w3-r845-3855, Transformers | No Trainer checkpoint/RNG restoration path, and the torch version exceeds the affected older restoration prerequisite. |

Transformers 4.57.6 remains within the five advisory version ranges. These version alerts stay visible. Reassess the call paths before adding training, custom generation, arbitrary model configurations, tokenizer saving, or changing the approved model stack. Do not treat the reachable-path assessment as a vendor fix or dismiss the alerts in bulk.

Primary records: [GHSA-27vj-qcqg-25rc](https://github.com/advisories/GHSA-27vj-qcqg-25rc), [GHSA-h35f-9h28-mq5c](https://github.com/advisories/GHSA-h35f-9h28-mq5c), [GHSA-rrmf-rvhw-rf47](https://github.com/advisories/GHSA-rrmf-rvhw-rf47), [GHSA-x9r9-c232-4q39](https://github.com/advisories/GHSA-x9r9-c232-4q39), [GHSA-xrqw-3rrv-vx5w](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w), [GHSA-fgcw-684q-jj6r](https://github.com/advisories/GHSA-fgcw-684q-jj6r), [GHSA-29pf-2h5f-8g72](https://github.com/advisories/GHSA-29pf-2h5f-8g72), [GHSA-69w3-r845-3855](https://github.com/advisories/GHSA-69w3-r845-3855).

The canonical structured initial and follow-up assessments are held in the local Codex Security artifact store. This document is the public, sanitized review copy.
