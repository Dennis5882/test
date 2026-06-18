# Project Structure

```
/your-project-root
  ├── .claude/           # Claude Code 설정 폴더
  ├── PROMPT.md          # [중심 규칙] 분석-문서화-코드화 프로토콜
  ├── /docs/             # 자동화 결과물 저장소
  │   ├── /analysis/     # 장별 분석 보고서 (.md)
  │   └── /manuals/      # 구조설계 매뉴얼 및 기준 정리
  ├── /src/              # 실제 설계 코드
  └── /scripts/          # 분석 자동화 헬퍼 스크립트
```

## 폴더별 설명

- **`.claude/`** - Claude Code 설정 파일들이 저장되는 폴더
- **`PROMPT.md`** - 프로젝트 전체의 중심 규칙과 프로토콜 정의
- **`docs/analysis/`** - 각 장별 분석 보고서 (마크다운 형식)
- **`docs/manuals/`** - 구조설계 매뉴얼 및 기준 정리 문서
- **`src/`** - 실제 구현되는 설계 코드
- **`scripts/`** - 분석 자동화를 위한 헬퍼 스크립트
