"""Write ESSOAR_SUBMISSION.ko.md (submission guide for the author) from the preprint front matter."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
front = (ROOT / "docs/preprint/sections/0_front.md").read_text()
title = re.search(r'title: "(.+?)"', front).group(1)
kp = re.search(r"# Key Points\n\n(.+?)\n\n# Abstract", front, re.S).group(1).strip()
abstract = re.search(r"# Abstract\n\n(.+?)\n\n# Plain Language Summary", front, re.S).group(1).strip()
pls = re.search(r"# Plain Language Summary\n\n(.+)", front, re.S).group(1).strip()
doi = (ROOT / "docs/preprint/DOI").read_text().strip()
text = f"""# ESSOAr 제출 안내 (교수님 직접 제출)

ESS Open Archive(https://essopenarchive.org) 제출은 교수님 계정 로그인(ORCID)이 필요해 Claude가 하지 않았습니다. 아래 값을 그대로 입력하시면 됩니다. GWFM-KR 노트 때와 같은 절차입니다.

## 올릴 파일
- 원고 PDF: `docs/preprint/GeoAI-THM-Studio_preprint.pdf` (GitHub와 Zenodo에도 같은 파일이 있습니다)

## 입력 항목
- **Title:** {title}
- **Authors (순서대로):**
  1. Eungyu Park, GeoAI Alignment, Inc., Daegu, Republic of Korea (corresponding, egpark@knu.ac.kr, ORCID 0000-0002-2293-4686)
  2. Taeyu Kim, GeoAI Alignment, Inc., Daegu, Republic of Korea
  3. Jangwon Park, GeoAI Alignment, Inc., Daegu, Republic of Korea
- **Subject areas:** Hydrology; Informatics; (선택) Solid Earth / Geomechanics
- **Keywords:** OpenGeoSys; language-model agent; thermo-hydro-mechanical; groundwater; verification; radioactive waste
- **License:** CC BY-NC 4.0
- **Related identifier (software/data):** https://doi.org/{doi} (Zenodo), https://github.com/geoaialignment/geoai-thm-studio
- **Competing interests:** The authors declare there are no conflicts of interest for this manuscript.
- **Funding:** GeoAI Alignment, Inc.

## Key Points
{kp}

## Abstract
{abstract}

## Plain Language Summary
{pls}

## 제출 뒤
- ESSOAr DOI가 나오면 알려 주세요. Zenodo 레코드의 관련 식별자(메타데이터만 수정 가능)와 GitHub README·CITATION.cff에 넣겠습니다.
"""
(ROOT / "ESSOAR_SUBMISSION.ko.md").write_text(text)
print("written")
