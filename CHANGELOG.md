# Changelog

원본(upstream)과 다른 점만 적습니다. 원본 버전은 `upstream-v*` 태그를 보세요.

## [Unreleased] - Reasonofmoon fork

### Added
- `FORK.md`: 브랜치 구조, 수정·테스트·원본 동기화 방법
- `NOTICE`, `CHANGELOG.md`: Apache-2.0 수정 사실 표시
- `scripts/sync-upstream.ps1`: PyPI 원본을 SHA256 확인 후 `upstream` 브랜치에 커밋

### Fixed
- `mcp` 의존성을 `<2`로 고정. mcp 2.x에서 `mcp.server.fastmcp`가 없어져 원본 0.1.0은 새로 설치하면 실행되지 않음 (나중에 `MCPServer`로 이전 검토)

### Changed
- `pyproject.toml`: 프로젝트 URL을 이 포크로 변경 (원본 URL은 `Upstream`으로 유지)
- `README.md`: 맨 위에 포크 안내 추가
- CI: `feat/**` 브랜치 push에서도 테스트 실행

## 0.1.0 - upstream
- PyPI 원본 그대로 (`upstream-v0.1.0`)
