# Changelog

원본(upstream)과 다른 점만 적습니다. 원본 버전은 `upstream-v*` 태그를 보세요.

## 0.2.0 - 2026-11-13 (Reasonofmoon fork)

### 바뀐 이유
- 원본 영상 모델 `veo-3.1-generate-preview`는 2026-10-22에 서비스 종료됨(공식 문서 확인). 영상 도구 3개가 동작할 수 없었다.
- 원본 이미지 도구는 Imagen용 `generate_images`에 Nano Banana(Gemini) 모델을 넣어 호출했다. 현재 공식 문서의 Nano Banana 호출 방식은 Interactions API다.
- `mcp` 2.x에서 `mcp.server.fastmcp`가 없어져 새로 설치하면 시작조차 안 됐다.

### Changed
- 이미지·영상 모두 Gemini Interactions API(`client.aio.interactions.create`)로 이전
- 영상 모델: Veo 3.1 Preview → Gemini Omni Flash (`gemini-omni-1.2-flash`), 길이 3~15초, 360p~4K
- 기본 이미지 모델: Nano Banana Pro → Nano Banana 2.1 (`fast`, 약 4분의 1 가격). `model="pro"`로 계속 사용 가능
- `flow_edit_image`: 마스크 없이 자연어로 편집. `edit_mode="free"` 추가, `mask_mode`는 무시(호환용으로 남김)
- `flow_extend_video`: `previous_interaction_id`로 이어 만들기 지원, 로컬 MP4는 Files API로 업로드
- `flow_generate_video`: 마지막 프레임(`last_frame_path`)과 참고 이미지 최대 6장 지원. `enhance_prompt`는 무시
- `mcp` 1.x(`FastMCP`)와 2.x(`MCPServer`) 모두 지원, 의존성 `mcp[cli]>=1.0.0,<3`
- `google-genai>=3.3.0`, Python 3.11 이상(google-genai 3.3.0 요구 사항). `Pillow` 의존성 제거
- CI: Python 3.11/3.12/3.13 × mcp 1.x/2.x, 서버 시작과 도구 9개 등록 확인

### Added
- 모델 이름 환경변수: `FLOW_DEFAULT_IMAGE_MODEL`, `FLOW_MODEL_IMAGE_FAST/PRO/LITE`, `FLOW_MODEL_VIDEO`
- 파일 이름에 프롬프트 요약(한글 유지): `20261113_091500_image_neon-tokyo-alley_0.png`
- 생성 기록 `generation_log.jsonl`(성공·실패, 모델, 프롬프트, 설정, 결과 경로, 예상 비용, 소요 시간, interaction_id)
- 형식 프리셋 7개(`youtube-thumbnail`, `shorts`, `pinterest-pin`, `instagram-post`, `worksheet`, `banner`, `square`)와 스타일 프리셋 7개, `FLOW_PRESETS_FILE`로 추가
- 예상 비용 안내: 결과마다 예상 비용 표시, 영상이 `FLOW_VIDEO_CONFIRM_USD`(기본 $0.50)를 넘으면 견적만 돌려주고 `confirm_cost=true`로 다시 불러야 생성
- 하루 한도: `FLOW_DAILY_IMAGE_LIMIT`(50), `FLOW_DAILY_VIDEO_LIMIT`(5), `FLOW_DAILY_BUDGET_USD`(끔)
- 새 도구: `flow_list_presets`, `flow_estimate_cost`, `flow_usage_today`
- 자리표시자 API 키(`YOUR_...`)를 넣은 채 실행하면 바로 알아보기 쉬운 오류

### Fixed (0.1.x)
- `mcp` 의존성을 `<2`로 고정 (PR #1). 0.2.0에서 2.x 지원으로 대체

### Added (fork setup)
- `FORK.md`, `NOTICE`, `scripts/sync-upstream.ps1`

## 0.1.0 - upstream
- PyPI 원본 그대로 (`upstream-v0.1.0`)
