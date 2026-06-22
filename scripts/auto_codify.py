import json
import os
import shutil
import sys
import time
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader

REFERENCES_DIR = Path("references")
DOCS_DIR = Path("docs/manuals")
SRC_DIR = Path("src")
PROMPT_FILE = Path("PROMPT.md")
MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
PDF_CHUNK_PAGE_SIZE = int(os.environ.get("PDF_CHUNK_PAGE_SIZE", "8"))
TEXT_CHUNK_CHAR_LIMIT = int(os.environ.get("TEXT_CHUNK_CHAR_LIMIT", "12000"))
# 통합 출력이 잘리지 않도록 출력 토큰 한도를 명시한다(#3 완화).
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "8192"))
# 일시적 API 오류 재시도 설정(#4).
API_MAX_RETRIES = int(os.environ.get("API_MAX_RETRIES", "3"))
API_RETRY_BASE_DELAY = float(os.environ.get("API_RETRY_BASE_DELAY", "2"))

try:  # 일시적(transient) 오류만 재시도하기 위한 예외 집합. SDK 버전차에 견고하게 임포트.
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    RETRYABLE_ERRORS: tuple = (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )
except Exception:  # pragma: no cover - SDK 미설치/구버전 방어
    RETRYABLE_ERRORS = ()


class PipelineError(Exception):
    """Raised when the automation pipeline cannot produce valid outputs."""


def call_with_retries(
    func,
    *,
    retries: int = API_MAX_RETRIES,
    base_delay: float = API_RETRY_BASE_DELAY,
    retryable: tuple = RETRYABLE_ERRORS,
    sleep=time.sleep,
):
    """Call func(), retrying transient errors with exponential backoff.

    재시도 대상이 아닌 예외(인증·잘못된 요청 등)는 즉시 전파한다.
    """
    attempts = max(1, retries + 1)
    last_exc = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - retryable 여부로 분기
            if retryable and not isinstance(exc, retryable):
                raise
            last_exc = exc
            if attempt < attempts - 1:
                delay = base_delay * (2 ** attempt)
                log(f"일시적 API 오류, {delay:.0f}s 후 재시도 ({attempt + 1}/{attempts - 1}): {exc}")
                sleep(delay)
    raise last_exc


def log(message: str) -> None:
    """Print a pipeline progress message."""
    print(f"[auto_codify] {message}")


def preview_text(value: str, limit: int = 300) -> str:
    """Return a compact preview for logs."""
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "...(truncated)"


def parse_json_response(content: str, context: str) -> dict:
    """Parse model JSON, accepting bare JSON or a fenced JSON block."""
    stripped = content.strip()
    candidates = [stripped]

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidates.append("\n".join(lines).strip())

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
        candidates.append(stripped[first_brace : last_brace + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            raise PipelineError(f"{context} JSON 루트는 객체여야 합니다.")
        return payload

    raise PipelineError(f"{context} 응답이 유효한 JSON이 아닙니다. preview={preview_text(content)}")


def sanitize_stem(file_path: Path) -> str:
    """Return a filesystem-friendly stem for generated files."""
    sanitized = file_path.stem.replace("/", "_").replace("\\", "_").strip()
    return sanitized or "generated"


def build_client() -> OpenAI:
    """Create the API client after validating required configuration."""
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        raise PipelineError("환경 변수 AI_API_KEY 가 설정되어 있지 않습니다.")
    log(f"API client configured for model={MODEL_NAME}")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def configured_reference_patterns() -> tuple[str, ...]:
    """Return file glob patterns configured for fallback collection."""
    patterns = tuple(
        pattern.strip()
        for pattern in os.environ.get("REFERENCE_PATTERNS", "*.txt,*.pdf").split(",")
        if pattern.strip()
    )
    return patterns or ("*.txt", "*.pdf")


def configured_reference_files() -> tuple[Path, ...]:
    """Return explicit reference files passed by the workflow, if any."""
    raw_value = os.environ.get("REFERENCE_FILES", "").strip()
    if not raw_value:
        return ()

    files = []
    for raw_path in raw_value.splitlines():
        # git 은 비ASCII 경로를 따옴표로 감싸 출력할 수 있다(core.quotePath).
        # 워크플로에서 quotePath=false 로 끄지만, 방어적으로 양끝 따옴표도 제거한다.
        normalized = raw_path.strip().strip('"').strip().replace("\\", "/")
        if not normalized:
            continue
        path = Path(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise PipelineError(f"허용되지 않는 REFERENCE_FILES 경로입니다: {normalized}")
        files.append(path)
    return tuple(files)


def collect_reference_files() -> list[Path]:
    """Return sorted reference files that should be processed."""
    explicit_files = configured_reference_files()
    if explicit_files:
        log(f"Using explicit reference file list: {len(explicit_files)} entries")
        ref_files = []
        for relative_path in explicit_files:
            full_path = (Path.cwd() / relative_path).resolve()
            try:
                full_path.relative_to(REFERENCES_DIR.resolve())
            except ValueError as exc:
                raise PipelineError(
                    f"REFERENCE_FILES 는 references/ 하위만 허용됩니다: {relative_path}"
                ) from exc
            if full_path.is_file():
                ref_files.append(full_path)

        if not ref_files:
            raise PipelineError("REFERENCE_FILES 로 전달된 파일이 존재하지 않습니다.")
        log("Resolved explicit files: " + ", ".join(path.name for path in sorted(ref_files)))
        return sorted(ref_files)

    files = []
    patterns = configured_reference_patterns()
    log(f"Collecting reference files by patterns={patterns}")
    for pattern in patterns:
        files.extend(REFERENCES_DIR.glob(pattern))
    ref_files = sorted(path.resolve() for path in files if path.is_file())
    if not ref_files:
        raise PipelineError(
            f"references/ 폴더에 처리할 파일이 없습니다. patterns={patterns}"
        )
    return ref_files


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    """Extract non-empty text for each PDF page."""
    log(f"Extracting PDF text: {pdf_path.name}")
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        raise PipelineError(f"PDF 파일을 열 수 없습니다: {pdf_path} ({exc})") from exc

    page_texts = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            extracted = (page.extract_text() or "").strip()
        except Exception as exc:
            raise PipelineError(
                f"PDF 페이지 텍스트 추출 실패: {pdf_path} page={index} ({exc})"
            ) from exc
        page_texts.append(extracted)

    if not any(page_texts):
        raise PipelineError(f"PDF에서 텍스트를 추출하지 못했습니다: {pdf_path}")
    return page_texts


def split_pdf_into_chunks(file_path: Path) -> list[dict]:
    """Split a PDF into page-range chunks."""
    pages = extract_pdf_pages(file_path)
    chunks = []

    for start in range(0, len(pages), PDF_CHUNK_PAGE_SIZE):
        end = min(start + PDF_CHUNK_PAGE_SIZE, len(pages))
        selected_pages = pages[start:end]
        content = "\n\n".join(
            f"[Page {page_number}]\n{text}"
            for page_number, text in zip(range(start + 1, end + 1), selected_pages)
            if text.strip()
        ).strip()

        if not content:
            continue

        chunks.append(
            {
                "label": f"pages_{start + 1}_{end}",
                "page_range": {"start": start + 1, "end": end},
                "content": content,
            }
        )

    if not chunks:
        raise PipelineError(f"PDF 청크가 비어 있습니다: {file_path}")
    log(f"Built {len(chunks)} PDF chunks for {file_path.name}")
    return chunks


def split_text_into_chunks(file_path: Path) -> list[dict]:
    """Split a UTF-8 text file into paragraph-based chunks."""
    log(f"Reading text file: {file_path.name}")
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise PipelineError(f"텍스트 파일을 읽을 수 없습니다: {file_path} ({exc})") from exc

    raw_text = raw_text.strip()
    if not raw_text:
        raise PipelineError(f"텍스트 파일이 비어 있습니다: {file_path}")

    paragraphs = [paragraph.strip() for paragraph in raw_text.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        raise PipelineError(f"텍스트 파일에 분석 가능한 문단이 없습니다: {file_path}")

    chunks = []
    current_parts = []
    current_length = 0
    chunk_index = 1

    for paragraph in paragraphs:
        additional_length = len(paragraph) + (2 if current_parts else 0)
        if current_parts and current_length + additional_length > TEXT_CHUNK_CHAR_LIMIT:
            chunks.append(
                {
                    "label": f"chunk_{chunk_index}",
                    "page_range": None,
                    "content": "\n\n".join(current_parts),
                }
            )
            current_parts = [paragraph]
            current_length = len(paragraph)
            chunk_index += 1
        else:
            current_parts.append(paragraph)
            current_length += additional_length

    if current_parts:
        chunks.append(
            {
                "label": f"chunk_{chunk_index}",
                "page_range": None,
                "content": "\n\n".join(current_parts),
            }
        )

    log(f"Built {len(chunks)} text chunks for {file_path.name}")
    return chunks


def build_document_chunks(file_path: Path) -> list[dict]:
    """Build chunks for a reference document."""
    if file_path.suffix.lower() == ".pdf":
        return split_pdf_into_chunks(file_path)
    return split_text_into_chunks(file_path)


def request_chunk_analysis(
    client: OpenAI, file_name: str, chunk: dict
) -> dict:
    """Analyze one chunk and return structured notes for later integration."""
    log(f"Requesting chunk analysis for {file_name} [{chunk['label']}]")
    chunk_prompt = (
        "다음은 구조설계기준 문서의 일부 청크다.\n"
        "이 청크만 기준으로 분석하고, 반드시 유효한 JSON 객체 하나만 반환해.\n"
        "절대 코드펜스나 설명 문장을 추가하지 마.\n"
        "반환 스키마:\n"
        "{\n"
        '  "chunk_label": "string",\n'
        '  "summary_markdown": "string",\n'
        '  "clauses": ["string"],\n'
        '  "formulas": ["string"],\n'
        '  "assumptions": ["string"],\n'
        '  "open_questions": ["string"]\n'
        "}\n\n"
        f"대상 파일명: {file_name}\n"
        f"청크 라벨: {chunk['label']}\n"
        f"페이지 범위: {chunk.get('page_range')}\n\n"
        f"{chunk['content']}"
    )

    try:
        response = call_with_retries(
            lambda: client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": chunk_prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        )
    except Exception as exc:
        raise PipelineError(f"청크 분석 API 호출 실패: {file_name} {chunk['label']} ({exc})") from exc

    content = response.choices[0].message.content if response.choices else None
    if not content or not content.strip():
        raise PipelineError(f"청크 분석 응답이 비어 있습니다: {file_name} {chunk['label']}")

    payload = parse_json_response(content, f"청크 분석: {file_name} {chunk['label']}")

    required_keys = {
        "chunk_label": str,
        "summary_markdown": str,
        "clauses": list,
        "formulas": list,
        "assumptions": list,
        "open_questions": list,
    }
    for key, expected_type in required_keys.items():
        if key not in payload or not isinstance(payload[key], expected_type):
            raise PipelineError(f"청크 분석 필드 오류: {file_name} {chunk['label']} -> {key}")

    if not payload["summary_markdown"].strip():
        raise PipelineError(f"청크 요약이 비어 있습니다: {file_name} {chunk['label']}")

    log(f"Chunk analysis OK for {file_name} [{chunk['label']}]")
    return payload


def request_integrated_output(
    client: OpenAI, system_prompt: str, file_name: str, chunk_analyses: list[dict]
) -> dict:
    """Combine chunk analyses into the final output contract."""
    log(f"Requesting integrated output for {file_name} with {len(chunk_analyses)} chunk analyses")
    integration_input = {
        "file_name": file_name,
        "chunk_analyses": chunk_analyses,
    }
    user_prompt = (
        "다음은 구조설계기준 문서를 청크 단위로 분석한 결과다.\n"
        "이 청크 분석들을 통합해서 최종 산출물을 작성해줘.\n"
        "반드시 유효한 JSON 객체만 반환하고, 설명 문장이나 코드펜스는 절대 추가하지 마.\n\n"
        f"{json.dumps(integration_input, ensure_ascii=False, indent=2)}"
    )

    try:
        response = call_with_retries(
            lambda: client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        )
    except Exception as exc:
        raise PipelineError(f"통합 분석 API 호출 실패: {file_name} ({exc})") from exc

    content = response.choices[0].message.content if response.choices else None
    if not content or not content.strip():
        raise PipelineError(f"통합 분석 응답이 비어 있습니다: {file_name}")

    try:
        payload = parse_json_response(content, f"통합 분석: {file_name}")
        validate_final_payload(payload, file_name)
    except PipelineError:
        # 실패 원인 파악을 위해 모델 원문 미리보기를 stdout 으로 남긴다.
        log(f"통합 분석 실패 — 모델 원문 미리보기: {preview_text(content, 600)}")
        raise
    log(f"Integrated output OK for {file_name}")
    return payload


def normalize_source_rel_path(raw_path: str) -> Path:
    """Reduce a model-provided source path to a safe relative path under src/.

    모델은 PROMPT.md 안내(`/src/ 기준 상대경로`) 때문에 '/src/foo.py' 또는
    'src/foo.py' 처럼 슬래시·접두어가 붙은 경로를 자주 반환한다. 이를 모두
    SRC_DIR 기준 상대경로로 정규화하고, 경로 이탈(..)이나 비-.py 는 거부한다.
    """
    cleaned = raw_path.strip().replace("\\", "/").lstrip("/")
    if cleaned.startswith("src/"):
        cleaned = cleaned[len("src/"):]
    cleaned = cleaned.strip("/")

    candidate = Path(cleaned)
    if not cleaned or candidate.is_absolute() or ".." in candidate.parts:
        raise PipelineError(f"허용되지 않는 source path: {raw_path}")
    if candidate.suffix != ".py":
        raise PipelineError(f"source path 는 .py 여야 합니다: {raw_path}")
    return candidate


def validate_final_payload(payload: dict, file_name: str) -> None:
    """Validate the final output contract."""
    required_keys = {
        "manual_markdown": str,
        "source_files": list,
        "assumptions": list,
        "open_questions": list,
    }
    for key, expected_type in required_keys.items():
        if key not in payload:
            raise PipelineError(f"응답 필드 누락: {file_name} -> {key}")
        if not isinstance(payload[key], expected_type):
            raise PipelineError(f"응답 필드 타입 오류: {file_name} -> {key}")

    if not payload["manual_markdown"].strip():
        raise PipelineError(f"manual_markdown 이 비어 있습니다: {file_name}")
    if not payload["source_files"]:
        raise PipelineError(f"source_files 가 비어 있습니다: {file_name}")

    for index, source_file in enumerate(payload["source_files"], start=1):
        if not isinstance(source_file, dict):
            raise PipelineError(f"source_files[{index}] 형식 오류: {file_name}")
        path_value = source_file.get("path")
        content_value = source_file.get("content")
        if not isinstance(path_value, str) or not path_value.strip():
            raise PipelineError(f"source_files[{index}].path 형식 오류: {file_name}")
        if not isinstance(content_value, str) or not content_value.strip():
            raise PipelineError(f"source_files[{index}].content 형식 오류: {file_name}")

        # 슬래시/접두어 변형을 정규화하면서 경로 이탈·비-.py 를 검증한다.
        try:
            normalize_source_rel_path(path_value)
        except PipelineError as exc:
            raise PipelineError(f"{exc} (대상: {file_name})") from exc


def safe_source_path(relative_path: str, root: Path = SRC_DIR) -> Path:
    """Resolve a source file path under `root` without allowing traversal."""
    normalized = normalize_source_rel_path(relative_path)
    candidate = (root / normalized).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise PipelineError(
            f"{root.as_posix()} 밖으로 벗어나는 경로는 허용되지 않습니다: {relative_path}"
        ) from exc
    return candidate


def write_outputs(reference_file: Path, chunk_analyses: list[dict], payload: dict) -> None:
    """Persist manual markdown, chunk metadata, source files, and summary metadata."""
    base_name = sanitize_stem(reference_file)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    SRC_DIR.mkdir(parents=True, exist_ok=True)

    manual_path = DOCS_DIR / f"{base_name}_분석.md"
    manual_path.write_text(payload["manual_markdown"].strip() + "\n", encoding="utf-8")

    # 생성 소스는 reference 별 하위 폴더(src/<규범명>/)에 모은다.
    # 재처리 시 모델이 파일명을 다르게 지어도 고아가 쌓이지 않도록, 먼저 폴더를 비운다(멱등).
    # (src/ 루트의 손으로 작성한 모듈은 건드리지 않는다.)
    src_subdir = SRC_DIR / base_name
    if src_subdir.exists():
        shutil.rmtree(src_subdir)
    src_subdir.mkdir(parents=True, exist_ok=True)

    saved_sources = []
    for source_file in payload["source_files"]:
        source_path = safe_source_path(source_file["path"].strip(), src_subdir)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(source_file["content"].rstrip() + "\n", encoding="utf-8")
        saved_sources.append(str(source_path.relative_to(Path.cwd())).replace("\\", "/"))

    metadata = {
        "reference_file": str(reference_file.as_posix()),
        "manual_file": str(manual_path.as_posix()),
        "source_files": saved_sources,
        "assumptions": payload["assumptions"],
        "open_questions": payload["open_questions"],
    }
    metadata_path = DOCS_DIR / f"{base_name}_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    chunk_path = DOCS_DIR / f"{base_name}_chunks.json"
    chunk_path.write_text(
        json.dumps(chunk_analyses, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log(
        f"Saved outputs for {reference_file.name}: manual={manual_path.name}, "
        f"sources={len(saved_sources)}, chunks={len(chunk_analyses)}"
    )


def process_reference_file(client: OpenAI, system_prompt: str, file_path: Path) -> None:
    """Process one reference file through chunk analysis and integration."""
    chunks = build_document_chunks(file_path)
    chunk_analyses = []

    for chunk in chunks:
        print(f"  청크 분석: {chunk['label']}")
        chunk_analyses.append(request_chunk_analysis(client, file_path.name, chunk))

    payload = request_integrated_output(client, system_prompt, file_path.name, chunk_analyses)
    write_outputs(file_path, chunk_analyses, payload)


def main() -> None:
    try:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        raise PipelineError(f"PROMPT.md 를 읽을 수 없습니다. ({exc})") from exc

    client = build_client()
    ref_files = collect_reference_files()
    log(f"Processing {len(ref_files)} reference file(s)")
    failures = []

    for file_path in ref_files:
        log(f"분석 시작: {file_path.name}")
        try:
            process_reference_file(client, system_prompt, file_path)
        except PipelineError as exc:
            failures.append(str(exc))
            log(f"실패: {exc}")
            print(f"실패: {exc}", file=sys.stderr)
            continue
        log(f"저장 완료: docs/manuals/{sanitize_stem(file_path)}_분석.md, src/*.py")

    if failures:
        print("\n파이프라인 실패 요약:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except PipelineError as exc:
        print(f"치명적 오류: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
