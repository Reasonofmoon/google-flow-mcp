# Changelog

원본(upstream)과 다른 점만 적습니다. 원본 버전은 `upstream-v*` 태그를 보세요.

## 0.3.2 - 2026-11-13

공개 저장소를 깨끗한 환경에서 처음 사용자처럼 설치해 써 보고 찾은 문제를 고쳤다.

### Fixed
- **오류 이유가 사용자에게 전달되지 않던 문제.** `mcp` 2.x는 `ToolError`가 아닌 예외의 메시지를 숨기고 "Error executing tool X"만 돌려준다. 그래서 "GOOGLE_API_KEY가 없다", "하루 예산 초과", "샷을 찾을 수 없다" 같은 안내가 모두 사라졌다. 모든 도구를 `tool()` 래퍼로 등록해 이유를 그대로 전달한다
- 세로 프로젝트의 샷을 편집하거나 세로 영상을 연장할 때 화면 비율을 요청에 넣지 않던 문제(가로 영상이 돌아올 수 있었다). 프로젝트 비율 또는 원본 파일의 비율을 넣는다
- `LICENSE`가 원본에서 물려받은 축약본이라 GitHub가 라이선스를 인식하지 못했다. Apache-2.0 전문으로 교체
- 서버가 클라이언트에 버전을 알리지 않던 문제(`mcp` 2.x)

### Added
- `examples/mcp_smoke_test.py`: 실제 stdio 서버에 MCP로 접속해 데모 모드로 영상 한 편을 끝까지 만들고 오류 안내까지 확인하는 설치 점검 스크립트(26개 확인)
- CI에 Windows와 macOS 추가, 점검 스크립트를 모든 조합에서 실행
- `flow_extend_video`의 `aspect_ratio`가 다시 동작한다(로컬 파일은 자동 감지)

### Docs
- `FORK.md`에서 개인 PC 경로를 일반 예시로 바꾸고 공개 이후 상태로 고쳤다

## 0.3.1 - 2026-11-13

### Changed
- 데모 모드 자리표시 이미지를 장면 카드(하늘·해·언덕 + 샷 제목 자막)로 다시 그렸다
- 접촉 인화(contact sheet) 라벨을 오른쪽 위로 옮겨 제목과 자막을 가리지 않게 했다

### Docs
- README를 시각 자료 중심으로 다시 구성: 움직이는 SVG 배너, 데모 GIF, Archify로 만든 구조도·작업 흐름도(밝은·어두운 테마 겸용 SVG), 보드·키프레임·프레임 검토 스크린샷
- 다이어그램 원본(JSON)과 다시 만드는 방법을 `docs/diagrams/`에 보관
- 스크린샷과 GIF는 데모 모드 결과라서 자리표시 그림이다

## 0.3.0 - 2026-11-13 (Reasonofmoon fork) — Studio

Google Flow 앱의 작업 방식(재료, 프레임에서 영상, 장면 이어 붙이기, 편집)을 Gemini API 위에 다시 만들었다.
도구 9개 → 21개, 프롬프트 3개.

### Added
- **프로젝트** (`flow_project`): 재료·스토리보드·테이크·음성·완성 영상을 한 폴더(`projects/<이름>/`)에 보관. 다음 할 일 안내
- **재료** (`flow_ingredient_save`): 인물·사물·장소·스타일을 저장하고 프롬프트에 `@이름`으로 부르면 참고 이미지와 설명이 자동으로 붙는다. 참고 시트 자동 생성 가능
- **스토리보드** (`flow_storyboard_plan`, `flow_shot_update`, `flow_storyboard_keyframes`, `flow_storyboard_render`): 샷 목록 → 샷마다 싼 키프레임 → 키프레임을 첫 장면으로 영상 렌더. `draft`(360p) / `standard`(720p) / `high`(1080p)
- **백그라운드 렌더**: 샷을 동시에 렌더하고, 정한 시간이 지나면 도구는 반환하되 렌더는 계속된다. `flow_project`로 진행 확인
- **영상 편집** (`flow_edit_video`): 한 문장으로 추가·제거·스타일 변경. 스토리보드 샷을 편집하면 새 테이크로 쌓인다
- **음악** (`flow_generate_music`, Lyria)과 **내레이션** (`flow_generate_narration`, Gemini TTS, 한국어 포함)
- **합치기** (`flow_assemble`): 선택한 테이크를 이어 붙이고, 샷별 트림을 적용하고, 음악(반복·페이드아웃)과 내레이션을 섞는다. 로컬 ffmpeg, API 비용 없음
- **눈으로 확인**: 이미지 도구가 미리보기를 함께 돌려주고, `flow_review`가 영상의 프레임 여러 장을 돌려준다. 어시스턴트가 결과를 직접 보고 판단할 수 있다
- **보드** (`flow_board`): 프로젝트 전체를 보여 주는 HTML 한 장(재생기 포함)
- **카메라 프리셋 18개** (`camera="push-in"`, `"orbit"`, `"drone"` 등), `flow_generate_video`에도 적용
- **데모 모드** (`FLOW_DEMO=1`): API 키 없이 전체 흐름을 자리표시 미디어로 체험. 전송·과금 없음. `examples/offline_demo.py`
- **MCP 프롬프트**: `short_film`, `product_ad`, `social_image_set`
- `python -m google_flow_mcp` 실행 지원

### Changed
- 하루 한도 기본값: 이미지 100, 영상 20, **예산 $5**(전에는 이미지 50, 영상 5, 예산 없음). 여러 샷을 렌더할 수 있게 개수를 늘리고 금액으로 막는다
- 의존성: `Pillow`(미리보기), `imageio-ffmpeg`(ffmpeg 내장) 추가, `mcp[cli]>=1.12,<3`
- 도구가 문자열 또는 [문자열, 이미지]를 돌려준다(`FLOW_INLINE_PREVIEW=0`으로 끌 수 있음)

### 검증
- 테스트 49개, Python 3.11~3.13 × `mcp` 1.x/2.x. Google API는 mock, ffmpeg 이어 붙이기·믹싱·프레임 추출은 실제 실행, 실제 stdio 서버 프로세스와 JSON-RPC 통신, 데모 모드 전체 흐름
- 실제 API 키로 한 생성은 아직 검증하지 않았다

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
