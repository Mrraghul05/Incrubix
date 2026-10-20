# Sources, dependencies and licensing inventory

## Product code and assessment inputs

- IncuBrix Assessment 4 brief: supplied confidential assessment PDF. Keep it out of public repositories; `.gitignore` excludes it.
- No third-party datasets, destination research, media files, or generated media are included. Example requests and test content are synthetic; placeholder/test URLs use reserved `.invalid` domains. `config/destinations.yaml` includes `https://dev.to` as a destination reference but sets its connection to simulation mode.
- No external model/provider API is called by the application at runtime. The signed webhook can make HTTP requests only when explicitly configured in native mode; use it only against a local mock or a partner-agreed sandbox.

## Runtime dependencies

The exact versions below are the resolved Windows `.venv` inventory inspected on 2026-10-20. The project currently uses version ranges in `pyproject.toml`, not a lockfile, so a future install can resolve different versions. Licenses were checked from installed package metadata and official PyPI project pages where metadata was absent.

| Package | Resolved version | License |
|---|---:|---|
| FastAPI | 0.115.14 | MIT |
| Pydantic | 2.14.1 | MIT |
| Pydantic Core | 2.50.1 | MIT |
| HTTPX | 0.28.1 | BSD-3-Clause |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| Starlette | 0.46.2 | BSD-3-Clause |
| AnyIO | 4.15.1 | MIT |
| annotated-types | 0.8.0 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| certifi | 2026.10.18 | MPL-2.0 |
| idna | 3.20 | BSD-3-Clause |
| click | 8.5.0 | BSD-3-Clause |
| httptools | 0.9.0 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| watchfiles | 1.3.0 | MIT |
| websockets | 17.2 | BSD-3-Clause |
| uvloop | Linux-only `uvicorn[standard]` extra | MIT OR Apache-2.0 |

## Build, test and environment dependencies

| Package | Resolved version | License |
|---|---:|---|
| pytest | 8.4.2 | MIT |
| iniconfig | 2.3.1 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pluggy | 1.7.0 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| colorama | 0.4.6 | BSD-3-Clause |
| setuptools build backend | version resolved by build environment | MIT |
| Python 3.12 | environment | PSF-2.0 |

## Submission workbook preparation tools (not part of product runtime)

| Package | Version | License | Use |
|---|---:|---|---|
| XlsxWriter | 3.2.9 | BSD-2-Clause | Created the local Excel submission-form draft. |
| openpyxl | 3.1.5 | MIT | Updated the draft with the latest evidence and rule review. |

The Dockerfile uses the mutable `python:3.12-slim` base tag. This Windows dependency inventory does not establish the exact Linux image digest, Linux-only dependency resolution, or Debian OS-package notices. Build an SBOM and review notices for the exact image and resolved lock before commercial release. No package above is identified as AGPL; this inventory is not a complete container SBOM.

## Primary license sources

- [FastAPI on PyPI](https://pypi.org/project/fastapi/) - MIT.
- [Pydantic on PyPI](https://pypi.org/project/pydantic/) - MIT.
- [HTTPX on PyPI](https://pypi.org/project/httpx/) - BSD-3-Clause.
- [Uvicorn on PyPI](https://pypi.org/project/uvicorn/) - BSD-3-Clause.
- [PyYAML on PyPI](https://pypi.org/project/PyYAML/) - MIT.
- [pytest on PyPI](https://pypi.org/project/pytest/) - MIT.
- [certifi on PyPI](https://pypi.org/project/certifi/) - MPL-2.0.
- [Colorama on PyPI](https://pypi.org/project/colorama/) - BSD-3-Clause.
- [uvloop on PyPI](https://pypi.org/project/uvloop/) - MIT OR Apache-2.0.
- [XlsxWriter on PyPI](https://pypi.org/project/XlsxWriter/) - BSD-2-Clause; submission workbook preparation only.
- [openpyxl on PyPI](https://pypi.org/project/openpyxl/) - MIT; submission workbook preparation only.
- [Official Python image metadata](https://github.com/docker-library/official-images/blob/master/library/python) - current `3.12-slim` tag mapping; the tag is mutable.

The default software dependency set appears commercially usable under the listed licenses. Final commercial clearance remains incomplete until versions are locked and the exact Linux container and operating-system packages are inventoried.
