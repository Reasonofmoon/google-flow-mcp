<#
.SYNOPSIS
  PyPI에 올라온 google-flow-mcp 원본을 `upstream` 브랜치에 커밋한다.

.DESCRIPTION
  원본 GitHub 저장소(joshuadaniel-8090/google-flow-mcp)는 2026-11-13 기준 404라서
  PyPI sdist(.tar.gz)를 원본으로 삼는다.

  1. PyPI JSON에서 해당 버전의 sdist 주소와 SHA256을 읽는다.
  2. 내려받은 파일의 SHA256이 PyPI 값과 같은지 확인한다.
  3. 임시 폴더에 풀고, 현재 작업 폴더나 main 브랜치는 건드리지 않고
     `upstream` 브랜치에만 새 커밋을 만든다(임시 index 사용, 파일 삭제 없음).
  4. `upstream-v<버전>` 태그를 단다.

  그다음 main에 합치는 일은 사람이 직접 한다:
    git merge upstream     # 충돌이 나면 내 수정과 원본 변경을 비교해서 고른다

.EXAMPLE
  pwsh -File scripts/sync-upstream.ps1                 # PyPI 최신 버전
  pwsh -File scripts/sync-upstream.ps1 -Version 0.2.0  # 특정 버전
#>
param(
  [string]$Version = '',
  [string]$Package = 'google-flow-mcp',
  [string]$Branch = 'upstream'
)
$ErrorActionPreference = 'Stop'

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw 'git 저장소 안에서 실행하세요.' }

# 1) PyPI 메타데이터
$metaUrl = if ($Version) { "https://pypi.org/pypi/$Package/$Version/json" } else { "https://pypi.org/pypi/$Package/json" }
$meta = Invoke-RestMethod $metaUrl
$Version = $meta.info.version
$sdist = $meta.urls | Where-Object { $_.packagetype -eq 'sdist' } | Select-Object -First 1
if (-not $sdist) { throw "버전 $Version 에 sdist가 없습니다." }

$tag = "upstream-v$Version"
if (git tag --list $tag) { Write-Host "이미 가져온 버전입니다: $tag"; exit 0 }

# 2) 내려받기 + SHA256 확인
$work = Join-Path ([IO.Path]::GetTempPath()) ("gfm-sync-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $work | Out-Null
$tgz = Join-Path $work $sdist.filename
Invoke-WebRequest $sdist.url -OutFile $tgz
$hash = (Get-FileHash $tgz -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $sdist.digests.sha256.ToLower()) { throw "SHA256 불일치: $hash" }
Write-Host "SHA256 확인: $hash"

# 3) 풀기 (sdist 최상위 폴더 하나 아래가 소스)
tar -xzf $tgz -C $work
$src = Get-ChildItem $work -Directory | Select-Object -First 1
if (-not $src) { throw '압축 해제 결과가 없습니다.' }
$srcPath = $src.FullName

# 4) 임시 index로 upstream 브랜치에 커밋
$indexFile = Join-Path $work 'index'
$env:GIT_INDEX_FILE = $indexFile
try {
  $parent = git rev-parse --verify --quiet "refs/heads/$Branch"
  if ($parent) { git read-tree $parent } else { git read-tree --empty }
  $gitDir = (git rev-parse --absolute-git-dir).Trim()
  git --git-dir="$gitDir" --work-tree="$srcPath" -C "$srcPath" add -A .
  git rm -q --cached --ignore-unmatch PKG-INFO | Out-Null   # 빌드 때 생기는 파일이라 제외
  $tree = (git write-tree).Trim()
  $msg = "upstream: import $Package $Version from PyPI sdist`n`nsource: $($sdist.url)`nsha256: $hash"
  if ($parent) {
    if ((git rev-parse "$parent^{tree}").Trim() -eq $tree) { Write-Host '원본 내용이 바뀌지 않았습니다.'; exit 0 }
    $commit = ($msg | git commit-tree $tree -p $parent).Trim()
  } else {
    $commit = ($msg | git commit-tree $tree).Trim()
  }
  git update-ref "refs/heads/$Branch" $commit
  git tag -a $tag $commit -m "$Package $Version (PyPI sdist, sha256 $hash)"
} finally {
  Remove-Item Env:\GIT_INDEX_FILE
}

Write-Host ""
Write-Host "완료: $Branch <- $commit ($tag)"
Write-Host "다음 단계:"
Write-Host "  git push origin $Branch --tags"
Write-Host "  git merge $Branch        # main에서 실행, 충돌은 직접 해결"
Write-Host "임시 폴더(지워도 됨): $work"
