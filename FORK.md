# 이 저장소 관리 안내 (Reasonofmoon 포크)

`google-flow-mcp`를 내 필요에 맞게 고쳐 쓰는 비공개 저장소입니다. 지금 버전은 0.2.0입니다.

## 한눈에 보기

| 항목 | 내용 |
|---|---|
| 원본 | PyPI `google-flow-mcp` 0.1.0 (제작자 joshua-daniel-8090, Apache-2.0) |
| 원본 GitHub | `joshuadaniel-8090/google-flow-mcp`, 2026-11-13 기준 404라서 PyPI sdist를 원본으로 사용 |
| `upstream` 브랜치 | 원본 그대로만 담는다. 직접 고치지 않는다 |
| `main` 브랜치 | 내 수정본. 여기서 작업한다 |
| 태그 | `upstream-v<버전>` = 가져온 원본 버전 |

```
upstream:  v0.1.0 ──────────── v0.2.0 (원본이 새로 나오면 스크립트로 추가)
              \                    \
main:          fork 설정 ── 내 수정 ── merge ── 내 수정 ...
```

## 1. Claude Desktop에서 바로 쓰기

`%APPDATA%\Claude\claude_desktop_config.json`의 `mcpServers`에 아래 항목이 들어 있습니다(2026-11-13 추가).

```json
"google-flow-dev": {
  "command": "C:\\Users\\crescent\\.local\\bin\\uv.exe",
  "args": ["--directory", "C:\\Users\\crescent\\projects\\google-flow-mcp", "run", "google-flow-mcp"],
  "env": {
    "GOOGLE_API_KEY": "YOUR_GOOGLE_AI_STUDIO_KEY",
    "FLOW_OUTPUT_DIR": "C:/Users/crescent/Pictures/google-flow"
  }
}
```

1. `YOUR_GOOGLE_AI_STUDIO_KEY`를 **결제가 연결된** Gemini API 키로 바꿉니다. 무료 등급에서는 이미지·영상 모델을 쓸 수 없습니다.
2. 저장하고 Claude Desktop을 완전히 종료(트레이 아이콘 → Quit)한 뒤 다시 엽니다.
3. Claude에게 "flow_list_presets 보여줘"라고 하면 연결 확인 끝.

이 항목은 **작업 폴더에 지금 체크아웃된 코드**를 실행합니다. 평소에는 `main`에 두세요.
설정 변경 전 원본은 `claude_desktop_config.backup-20261113-before-google-flow.json`으로 같은 폴더에 있습니다.

### 자주 바꾸는 설정 (env에 추가)

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `FLOW_DEFAULT_IMAGE_MODEL` | `fast` | `fast`(Nano Banana 2.1), `pro`, `lite` |
| `FLOW_DAILY_IMAGE_LIMIT` | `50` | 하루 이미지 수, `0`은 무제한 |
| `FLOW_DAILY_VIDEO_LIMIT` | `5` | 하루 영상 수 |
| `FLOW_DAILY_BUDGET_USD` | `0`(끔) | 하루 예상 지출 한도 |
| `FLOW_VIDEO_CONFIRM_USD` | `0.5` | 이보다 비싼 영상은 견적부터 보여 줌 |
| `FLOW_MODEL_VIDEO` 등 | README 참고 | 새 모델이 나오면 코드 수정 없이 교체 |
| `FLOW_PRESETS_FILE` | 없음 | 내 프리셋 JSON(예: TPT 표지, 리드마스터 카드) |

전체 목록은 README의 Settings 표를 보세요.

## 2. 기능 고치기

```powershell
cd C:\Users\crescent\projects\google-flow-mcp
git switch -c feat/기능이름      # 작업 브랜치
# src/google_flow_mcp/*.py 수정
git commit -am "feat: ..."
git push -u origin feat/기능이름
gh pr create --fill               # GitHub에서 CI(pytest)가 돌고, 통과하면 main에 합친다
git switch main; git pull         # Claude Desktop이 새 코드를 쓰게 main으로 돌아오기
```

| 파일 | 역할 |
|---|---|
| `server.py` | 도구 9개(`@mcp.tool()` 함수 하나 = 도구 하나) |
| `config.py` | 환경변수, 기본 모델 이름 |
| `presets.py` | 형식·스타일 프리셋 |
| `pricing.py` | 가격표(2026-11-13 공식 가격 기준) |
| `ledger.py` | 파일 이름, `generation_log.jsonl`, 하루 한도 |

바꾼 내용은 `CHANGELOG.md`에 남깁니다(Apache-2.0은 수정 사실 표시를 요구합니다).

## 3. 원본에 새 버전이 나왔을 때

```powershell
pwsh -File scripts/sync-upstream.ps1            # PyPI 최신 버전을 upstream 브랜치에 커밋 + 태그
git push origin upstream --tags
git switch main
git merge upstream                              # 0.2.0은 거의 새로 썼으므로 충돌이 나면 내 쪽을 기준으로 고른다
```

## 4. 테스트

GitHub Actions가 push와 PR마다 Python 3.11/3.12/3.13 × `mcp` 1.x/2.x에서 `pytest`를 돌리고,
서버가 뜨면서 도구 9개가 등록되는지 확인합니다. Google API는 mock이라 **실제 생성은 검증하지 않습니다.**

## 5. 아직 남은 일

- 실제 API 키로 이미지 1장, 360p 3초 영상 1개 생성해 보고 응답 형식 확인(약 $0.10)
- 가격표는 2026-11-13 값. 바뀌면 `pricing.py` 또는 `FLOW_PRICES_FILE` 갱신
- 필요하면 Batch(반값) 이미지 생성 도구 추가 검토
