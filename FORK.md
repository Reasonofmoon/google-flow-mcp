# 이 저장소 관리 안내 (Reasonofmoon 포크)

`google-flow-mcp`를 내 필요에 맞게 고쳐 쓰려고 만든 비공개 저장소입니다.

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

## 1. 기능 고치기

```powershell
cd C:\Users\crescent\projects\google-flow-mcp
git switch -c feat/기능이름      # 작업 브랜치
# src/google_flow_mcp/server.py 수정
git commit -am "feat: ..."
git push -u origin feat/기능이름
gh pr create --fill               # GitHub에서 CI(pytest)가 돌고, 통과하면 main에 합친다
```

- 도구 하나 = `server.py`의 `@mcp.tool()` 함수 하나입니다. 새 도구는 같은 형식으로 함수를 추가하면 됩니다.
- 바꾼 내용은 `CHANGELOG.md`에 한 줄씩 남깁니다(Apache-2.0은 수정 사실 표시를 요구합니다).

## 2. 고친 버전을 Claude Desktop에서 쓰기

PyPI 버전 대신 이 폴더의 코드를 실행하도록 `claude_desktop_config.json`에 추가합니다.

```json
{
  "mcpServers": {
    "google-flow-dev": {
      "command": "uv",
      "args": ["--directory", "C:\\Users\\crescent\\projects\\google-flow-mcp", "run", "google-flow-mcp"],
      "env": {
        "GOOGLE_API_KEY": "YOUR_GOOGLE_AI_STUDIO_KEY",
        "FLOW_OUTPUT_DIR": "C:/Users/crescent/Pictures/ai-outputs"
      }
    }
  }
}
```

설정 파일 위치(Windows): `%APPDATA%\Claude\claude_desktop_config.json`
(Microsoft Store판은 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`)
저장 후 Claude Desktop을 다시 시작합니다. API 키는 이 저장소에 커밋하지 않습니다.

## 3. 원본에 새 버전이 나왔을 때

```powershell
pwsh -File scripts/sync-upstream.ps1            # PyPI 최신 버전을 upstream 브랜치에 커밋 + 태그
git push origin upstream --tags
git switch main
git merge upstream                              # 충돌이 나면 직접 비교해서 해결
```

스크립트는 PyPI가 알려 준 SHA256과 내려받은 파일이 같은지 확인한 다음에만 커밋합니다.
작업 폴더와 `main`은 건드리지 않습니다.

## 4. 테스트

GitHub Actions(`.github/workflows/ci.yml`)가 push와 PR마다 Python 3.10/3.11/3.12에서 `pytest`를 돌립니다.
테스트는 Google API를 실제로 부르지 않고 mock으로 확인합니다.

## 업그레이드 아이디어 (메모)

- 모델 이름을 환경변수로 바꿀 수 있게 하기 (새 Gemini/Veo 모델이 나와도 코드 수정 없이 대응)
- 결과 파일 이름에 프롬프트 요약 넣기, 생성 기록(JSONL) 남기기
- 이미지 비율·스타일 프리셋 (예: 썸네일 16:9, 핀터레스트 2:3, 쇼츠 9:16)
- Veo 사용 전 예상 비용 안내, 하루 생성 한도
