# Release candidate 0.1.0: errlens-cli

Status: local, unpublished candidate. Project/repository: ErrLens / ErrLens/errlens-cli.
Distribution: **errlens-cli**. Python import: **errlens**. Command: **errlens**.
Version remains **0.1.0**, not 0.1.0rc1. No account settings, commit, push, tag,
release or upload has been performed during preparation.

## Identity decision and availability

The maintainer chose errlens-cli because the separate PyPI distribution errlens
already has version 0.1.0. Historical CI #6 built files under that old distribution
name; those files must not be uploaded as this new candidate.

On 2026-11-10, the official JSON API returned 404 for errlens-cli, errlens_cli
and errlens.cli. All normalize to errlens-cli under PEP 503 (lowercase, replace
runs of hyphen/underscore/period with one hyphen). No published project was found.
The public API does not certify internal reservations or reserve the name. Check
again at account setup/publication; stop if PyPI refuses or another project appears.
A pending Trusted Publisher does not reserve a name either.

After publication: `python -m pip install errlens-cli==0.1.0` installs the `errlens`
console script and `errlens` import. Before publication use a supplied verified
wheel or `python -m pip install .`, not the existing PyPI package named errlens.

## Candidate contents and evidence

Include the acceptance record, temporary-script generator and identity-safe PID
test, plus the reviewed metadata/docs/manifest, CHANGELOG, release notes,
`.github/workflows/publish.yml`, the distribution lookup in `src/errlens/__init__.py`
and its corresponding unit assertion. All other production behavior is unchanged.
Do not include ignored .venv directories, build/dist output, caches or logs.

MIT LICENSE and existing contributor attribution are retained. Python requires
>=3.11; CI qualification is 3.11–3.13. Runtime constraints remain typer>=0.16,<1
and rich>=14,<15. The existing Pre-Alpha classifier describes early-stage maturity.
No author, package capability or unverified support guarantee was invented.

CI #6 passed all 11 jobs at 84dbb9c927b1b0eaf3ac6efc50863b9f0ef72836.
It built errlens-0.1.0-py3-none-any.whl and errlens-0.1.0.tar.gz on Windows/Ubuntu,
installed the wheel and ran tests, but retained no artifacts. This is historical
behavioral evidence, not certification of the new distribution name or workflow.
The final candidate commit needs its normal Tests CI run.

## Temporary macOS CI limitation

All three macOS jobs in [CI #8](https://github.com/ErrLens/errlens-cli/actions/runs/43235376928)
were cancelled before runner assignment. The required Tests workflow temporarily
contains eight jobs: six Linux/Windows tests on Python 3.11–3.13 and two packaging
jobs. The previous macOS passes apply to the earlier tested SHA. The release
candidate has yet to run macOS tests.

The same macOS checks and Python versions are available on the selected ref via
the **Tests (macOS manual)** workflow. When hosted runner capacity recovers, run
that workflow on the current candidate. Restore macOS to the required Tests matrix
once all three jobs receive runners and pass on that ref. Verify the restored
matrix on its new commit. Until restoration, release records should identify any
candidate SHA that has not completed macOS tests.

```powershell
gh workflow run tests-macos.yml --repo ErrLens/errlens-cli --ref main
```

New worktree builds belong in ignored `dist/rc-errlens-cli-0.1.0/` with SHA256SUMS.
The wheel/sdist filenames normalize the name with underscores:

- `errlens_cli-0.1.0-py3-none-any.whl`
- `errlens_cli-0.1.0.tar.gz`

Do not mix them with old errlens archives or merge independent OS builds.
The sdist includes docs, tests and documented experiments; the wheel contains
only errlens modules/resources and errlens_cli distribution metadata/license.

## Local non-publishing verification

```powershell
.venv/rc-tools/Scripts/python.exe -m build --outdir dist/rc-errlens-cli-0.1.0
.venv/rc-tools/Scripts/python.exe -m twine check --strict dist/rc-errlens-cli-0.1.0/errlens_cli-0.1.0-py3-none-any.whl dist/rc-errlens-cli-0.1.0/errlens_cli-0.1.0.tar.gz
Get-FileHash dist/rc-errlens-cli-0.1.0/errlens_cli-0.1.0-py3-none-any.whl, dist/rc-errlens-cli-0.1.0/errlens_cli-0.1.0.tar.gz -Algorithm SHA256
```

Use a clean venv and install the wheel by path, then run version/help, RU/EN
NameError, no-explain and pip check from a temporary directory. Check
`importlib.metadata.version('errlens-cli')`, and inspect the console entry point
`errlens = errlens.cli:main_entry`. No old errlens distribution may be required.
The fresh metadata lookup is the only necessary production code adjustment.
Local validation and hashes are separate from a future committed release.

## Trusted Publishing configuration required from the maintainer

The prepared workflow is `.github/workflows/publish.yml`. It is not committed,
installed on GitHub or executed yet. It uses only workflow_dispatch; push/tag/
release events cannot trigger publication. Input `publish` defaults to false,
which builds/checks/retains artifacts and skips uploading to PyPI. With true,
the workflow requires the v0.1.0 tag and the latest successful Tests run for the
same SHA, then uses a separate environment-gated Linux publishing job. Only that
job receives id-token:write; no PyPI API token or secret is configured.

After separate authorization, create a GitHub environment named `pypi`, with
required maintainer approval and a v0.1.0 tag deployment restriction where
available for the repository/account. Configure an existing or pending PyPI
Trusted Publisher in the correct account:

| Field | Exact value |
| --- | --- |
| Project | errlens-cli |
| Owner | ErrLens |
| Repository | errlens-cli |
| Workflow filename | publish.yml |
| GitHub environment | pypi |

Use the PyPI account Publishing page for a new project. If registration says the
name is reserved/unavailable, stop and report it. Do not fall back to an API token
or silently rename anything. TestPyPI is separate and is not used by this plan.
Official references: [PyPI new project](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[existing project](https://docs.pypi.org/trusted-publishers/adding-a-publisher/),
[PyPA workflow guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

## Future commands — NOT executed, require authorization

Review all intended files, including the three acceptance files, metadata,
README/CONTRIBUTING/MANIFEST, CHANGELOG, release notes, this runbook, __init__,
its unit test and publish.yml. Do not use `git add .` blindly.

```powershell
git diff --check
git add pyproject.toml MANIFEST.in README.md CONTRIBUTING.md CHANGELOG.md docs/manual-acceptance.md docs/releasing.md docs/release-notes-0.1.0.md experiments/manual_acceptance.py tests/integration/test_interrupt_pid.py src/errlens/__init__.py tests/unit/test_cli.py .github/workflows/publish.yml
git commit -m "chore: prepare errlens-cli 0.1.0 release candidate"
git push origin main
$candidateSha = (git rev-parse HEAD).Trim()
gh run list --repo ErrLens/errlens-cli --workflow tests.yml --commit $candidateSha --json databaseId,headSha,status,conclusion
```

Set `$testsRunId` to the returned run ID. Require all eight jobs in the current
Tests workflow to pass. Then
rehearse only artifact building, keeping publication disabled:

```powershell
gh run watch $testsRunId --repo ErrLens/errlens-cli --exit-status
gh workflow run publish.yml --repo ErrLens/errlens-cli --ref main -f publish=false
gh run list --repo ErrLens/errlens-cli --workflow publish.yml --json databaseId,headSha,status,conclusion
```

Check the run SHA matches the candidate, download its release-dist artifact into
a new directory, and inspect candidate/dist plus SHA256SUMS. The workflow stages
an explicit artifact root, preserving dist/ independently of wildcard ancestors.
With `$candidateRunId` set to the rehearsal's ID:

```powershell
gh run download $candidateRunId --repo ErrLens/errlens-cli --name release-dist --dir .venv/downloaded-rc
```

After review, separate tag/publication approval and account configuration:

```powershell
git status --short
git tag -a v0.1.0 $candidateSha -m "ErrLens 0.1.0"
git push origin v0.1.0
```

Wait for tag-triggered Tests if present; it must succeed for that SHA before
publication. Recheck PyPI availability. Only then:

```powershell
gh workflow run publish.yml --repo ErrLens/errlens-cli --ref v0.1.0 -f publish=true
gh run list --repo ErrLens/errlens-cli --workflow publish.yml --json databaseId,headSha,status,conclusion
```

Set `$publishRunId` to that run. Download its own artifact (not an older build),
check hashes/metadata/files and approve the pypi environment job. Publication
uses the exact retained bytes, not another rebuild. Require workflow success
and verify PyPI hashes. No skip-existing option hides duplicate uploads.

```powershell
gh run download $publishRunId --repo ErrLens/errlens-cli --name release-dist --dir .venv/published-candidate
gh run watch $publishRunId --repo ErrLens/errlens-cli --exit-status
```

Before creating a GitHub Release remove the preparation-only preamble from the
draft notes, using reviewed release text. After separate release authorization:

```powershell
gh release create v0.1.0 .venv/published-candidate/dist/errlens_cli-0.1.0-py3-none-any.whl .venv/published-candidate/dist/errlens_cli-0.1.0.tar.gz .venv/published-candidate/SHA256SUMS --repo ErrLens/errlens-cli --verify-tag --title "ErrLens 0.1.0" --notes-file docs/release-notes-0.1.0.md
```

Final SHA, run IDs, hashes and publication date must come from actual approved
actions. Nothing in these instructions authorizes their execution now.
