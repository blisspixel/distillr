# Dependency security review, October 24, 2026

Reviewed `main` at `7fd9d89f8ec0e7907536ce8478205544c5f64acb`, then moved the
optional checker and the trust bundle forward. The published release is
[0.20.8](https://github.com/blisspixel/distillr/releases/tag/v0.20.8)
(`31f022b242920f4885e9bf88334b5873eadee908`). This is a version and call-path
review. No exploit was run.

## Transformers

GitHub Dependabot had four high `transformers` alerts and one medium alert.
The package is only the optional `entailment` extra. Production code imports
`AutoConfig` and `AutoModelForSequenceClassification` for the pinned HHEM
checker. It does not call `load_custom_generate`, `save_pretrained`, LightGlue,
or `Trainer`.

| Advisory | GitHub range | What 5.20.2 does |
| --- | --- | --- |
| GHSA-xrqw-3rrv-vx5w, path traversal in `save_pretrained` | `< 5.10.0` | Patched in 5.10.0. Distillr does not save tokenizers or chat templates. |
| GHSA-fgcw-684q-jj6r, LightGlue initialization | `< 5.5.0` | Patched in 5.5.0. The checker loads one pinned sequence-classification class. |
| GHSA-29pf-2h5f-8g72, remote code during model init | `< 5.3.0` | Patched in 5.3.0. HHEM and its foundation files stay on reviewed revisions. |
| GHSA-69w3-r845-3855, `Trainer` checkpoint restore | `< 5.0.0rc3` | Medium. Patched before 5.0. No Trainer path. |
| GHSA-x9r9-c232-4q39, custom generation download before consent | `4.49.0` through `5.8.1`, no patched version field | Distillr does not call `GenerativePreTrainedModel.load_custom_generate`. The upstream fix `cbc1651` is absent from tags `v5.10.0` and `v5.16.1` and present in `v5.17.0` and `v5.20.2`. NVD prose says affected through 5.16.1. The floor is `transformers>=5.17,<6`, locked at 5.20.2. |

`5.10` alone would clear the three advisories that name a patched release. It
would not contain the custom-generation fix. The reachable Distillr path is
still the consent-gated `from_pretrained(..., trust_remote_code=True)` call on
one reviewed revision.

HHEM revision `de9a5e6ba9ba49531a022dba17e35ffeb2a6fad8` is the child of the
previous pin `8e4a2e6e96c708cc76c2344f7e4757df2515292c`. The configuration file
is identical. `modeling_hhem_v2.py` adds `self.post_init()`, which Transformers
5 requires. `huggingface-hub` moves to `>=1.31,<3` because Transformers 5.20
requires that line. The foundation snapshot call stays `repo_id`, `revision`,
`allow_patterns`, and `local_files_only`.

## emSign trust bundle

The locked runtime bundle was `certifi==2026.5.20`. The project now requires
`certifi>=2026.10.19` and locks `2026.10.23`. Built wheel metadata must carry
that floor.

The same lock raises direct and transitive floors that `pip-audit` still
reported after the Transformers move:

| Package | Floor | Locked | Role |
| --- | --- | --- | --- |
| pypdf | `>=6.21.2` | 6.21.2 | Runtime PDF extraction |
| opentelemetry-api | `>=1.45.1` | 1.45.1 | Runtime API pulled by mcp. No exporter is configured |
| filelock | `>=4.2.1,<5` | 4.2.4 | Entailment extra. huggingface-hub, torch, and virtualenv accept 4.x below 5. Distillr does not import it |
| setuptools | `>=84.1.0` | 84.2.1 | Entailment extra. torch accepts `>=77` |
| virtualenv | `>=21.14.9` | 21.14.13 | Development group used by pre-commit |

The resolver also moved `distlib` to 0.4.4 and `packaging` to 26.3. On
2026-10-24, `uv run --frozen pip-audit --skip-editable` and the hashed
entailment export audit both finished with no known vulnerabilities.

uv consumers move to `0.13.5`. `0.13.4` removes the affected root
([GHSA-hq85-5cpj-mr62](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62)).
`0.13.5` also rejects the compromised intermediates and updates managed CPython
builds that bundle pip 26.2.2. The container image
`ghcr.io/astral-sh/uv:0.13.5` was present. Installer scripts pin that version
and the downloaded installer hashes.

Development `pip` is locked at `26.2.2` through the dev group. It is not a
runtime dependency.

PyPI publishing uses `pypa/gh-action-pypi-publish` commit
`7245906fb61fa33a13554f9d5fb856fe61758086` (v1.14.3). That runtime lock has
`certifi==2026.10.19` and `sigstore==4.5.1`. The GHCR tag for that commit
exists. OIDC, attestations, and the main-branch ancestry check stay in place.

## Limits

This does not inspect machines that already overrode the CA bundle, pinned an
older uv, or kept an old virtual environment. Application upgrade steps are in
[install.md](../install.md#updates). No exploit was run.

`find_insights` and `read_insight` now carry snapshot identity. Issue #62 is
addressed by that handoff. Issues #61 and #63 stay open: local reasoning
evidence and the research-recipe comparison still need expert-reviewed quality
evidence and belong to the `0.20.9` baseline. Defaults are unchanged. The
freeze-time medium-or-higher gate remains `0.20.11`.
