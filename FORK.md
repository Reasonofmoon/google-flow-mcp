# 관리 안내 (포크 유지·보수)

쓰는 방법은 [README.ko.md](README.ko.md)에 있습니다. 이 문서는 코드를 고치고, 원본과 맞추고, 배포 상태를 관리하는 사람을 위한 것입니다.

## 1. 한눈에 보기

| 항목 | 내용 |
|---|---|
| 원본 | PyPI `google-flow-mcp` 0.1.0 (joshua-daniel-8090, Apache-2.0). 원본 GitHub는 2026-11-13 기준 404 |
| `upstream` 브랜치 | 원본 그대로. 직접 고치지 않는다 |
| `main` 브랜치 | 내 수정본. 여기서 작업한다 |
| 태그 | `upstream-v<버전>`은 가져온 원본, `v<버전>`은 이 포크의 버전 |

```
upstream:  v0.1.0 ──────────── (원본이 새로 나오면 스크립트로 추가)
              \
main:          포크 설정 ── v0.2 ── v0.3 ── ...
```

## 2. 코드 고치기

```powershell
cd C:\path\to\google-flow-mcp
git switch -c feat/기능이름
# src/google_flow_mcp/*.py 수정
git commit -am "feat: ..."
git push -u origin feat/기능이름
gh pr create --fill               # GitHub에서 테스트가 돌고, 통과하면 main에 합친다
git switch main; git pull         # 내 PC의 클라이언트가 새 코드를 쓰게 main으로 돌아오기
```

코드를 바꾼 뒤에는 Claude Desktop이나 Claude Code를 완전히 종료하고 다시 열어야 새 코드가 실행됩니다.

| 파일 | 역할 |
|---|---|
| `server.py` | 기본 생성 도구 9개, 공통 함수, 도구 등록(`tool()`) |
| `studio.py` | 프로젝트·스토리보드·렌더·음성·이어 붙이기·검토 도구 12개, 프롬프트 3개 |
| `project.py` | 프로젝트 폴더와 `project.json`, `@태그` 처리 |
| `media.py` | ffmpeg(프레임 추출, 이어 붙이기, 믹싱), 미리보기 이미지 |
| `board.py` | HTML 보드 |
| `demo.py` | 데모 모드(`FLOW_DEMO=1`) |
| `config.py` / `presets.py` / `pricing.py` / `ledger.py` | 설정 / 프리셋·카메라 / 가격표 / 기록·한도 |

바꾼 내용은 `CHANGELOG.md`에 남깁니다. Apache-2.0은 수정 사실 표시를 요구합니다.

## 3. 테스트

| 무엇 | 어떻게 | 확인하는 것 |
|---|---|---|
| 단위 테스트 51개 | `pytest -v` | Google API는 흉내 내고, ffmpeg와 Pillow는 실제로 실행 |
| 설치 점검 | `python examples/mcp_smoke_test.py` | 실제 서버에 MCP로 접속해 데모 모드로 영상 한 편을 끝까지 만들기 |
| 데모 영상 | `python examples/offline_demo.py demo_output` | README 스크린샷의 원본 |
| CI | push와 PR마다 자동 | Linux(Python 3.11~3.13 × mcp 1.x·2.x), Windows, macOS |

실제 API 호출은 자동 테스트에 없습니다. 요청 형식이나 모델 이름을 바꿨다면 결제가 연결된 키로 직접 한 번 만들어 봐야 합니다.

### 실제 호출에서 배운 것

- **API 버전.** `google-genai` 3.x의 기본은 `v1`입니다. 영상(`gemini-omni-1.2-flash`), 음악(Lyria), 내레이션(Gemini 3.8 TTS)은 `v1beta`에만 있어서, 클라이언트를 `v1beta`로 만들어야 합니다(`config.api_version()`).
- **오류 문구.** `mcp` 2.x는 `ToolError`가 아닌 예외의 내용을 숨깁니다. 도구는 반드시 `tool()` 래퍼로 등록합니다.
- **모델 확인은 무료.** `GET /v1beta/models/<이름>`으로 키에서 모델이 보이는지 먼저 확인할 수 있습니다.

## 4. 원본에 새 버전이 나왔을 때

```powershell
pwsh -File scripts/sync-upstream.ps1     # PyPI 최신 버전을 SHA256 확인 후 upstream에 커밋
git push origin upstream --tags
git switch main; git merge upstream      # 거의 새로 썼으므로 충돌이 나면 내 쪽 기준
```

## 5. README 그림 다시 만들기

- 구조도와 작업 흐름도: 원본과 방법은 [docs/diagrams](docs/diagrams)에 있습니다.
- 데모 GIF와 스크린샷: `examples/offline_demo.py` 결과에서 만듭니다. CI가 `offline-demo`라는 이름으로 결과를 올려 둡니다.
- 영어 README를 고치면 `README.ko.md`도 같이 고칩니다.

## 6. 아직 남은 것 (2026-11-13 기준)

- **실제 생성 성공 확인.** 첫 실제 호출(영상)은 API 버전 문제로 실패했고 0.3.3에서 고쳤습니다. 0.3.3으로 이미지, 영상, 음악, 내레이션이 실제로 만들어지는지는 아직 확인하지 못했습니다.
- **이름.** PyPI의 `google-flow-mcp`는 원작자 소유라서 같은 이름으로 올릴 수 없습니다. "Google Flow"는 Google 제품 이름이기도 합니다. PyPI에 올리려면 다른 이름이 필요합니다.
- **가격표.** 2026-11-13 값입니다. 바뀌면 `pricing.py`를 고치거나 `FLOW_PRICES_FILE`을 씁니다. TTS 가격은 2027-01-01에 두 배가 됩니다.
