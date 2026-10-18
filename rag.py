import hashlib
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from chromadb.errors import NotFoundError
from pydantic import BaseModel, Field

from settings import settings


BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CHROMA_DIR = BASE_DIR / "data" / "chroma"

COLLECTION_NAME = "clinic_knowledge"

CHUNK_SIZE = 900
CHUNK_OVERLAP = 0
DEFAULT_RESULTS_COUNT = 1


class KnowledgeSearchResult(BaseModel):
    content: str = Field(description="محتوى المقطع المسترجع من قاعدة معرفة العيادة")
    source: str = Field(description="اسم الملف الذي أُخذ منه المقطع")
    chunk_index: int = Field(description="ترتيب المقطع داخل الملف")
    distance: float | None = Field(default=None, description="المسافة الدلالية بين السؤال والمقطع")


def get_embedding_function() -> OpenAIEmbeddingFunction:
    return OpenAIEmbeddingFunction(api_key=settings.openai_api_key, model_name=settings.embedding_model)


def get_chroma_client() -> chromadb.PersistentClient:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def get_collection() -> Collection:
    client = get_chroma_client()

    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"description": "قاعدة معرفة مساعد استقبال العيادة",},
    )


def read_knowledge_files() -> list[tuple[Path, str]]:
    if not KNOWLEDGE_DIR.exists():
        raise FileNotFoundError(f"مجلد المعرفة غير موجود: {KNOWLEDGE_DIR}")

    files = sorted(KNOWLEDGE_DIR.glob("*.txt"))

    if not files:
        raise FileNotFoundError(f"لا توجد ملفات TXT داخل المجلد: {KNOWLEDGE_DIR}")

    documents: list[tuple[Path, str]] = []

    for file_path in files:
        content = file_path.read_text(encoding="utf-8").strip()

        if content:
            documents.append((file_path, content))

    if not documents:
        raise ValueError("ملفات المعرفة موجودة، لكنها لا تحتوي على نصوص قابلة للفهرسة.")

    return documents


def split_text(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP,) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("يجب أن تكون قيمة chunk_size أكبر من صفر.")

    if chunk_overlap < 0:
        raise ValueError("لا يمكن أن تكون قيمة chunk_overlap سالبة.")

    if chunk_overlap >= chunk_size:
        raise ValueError("يجب أن تكون chunk_overlap أصغر من chunk_size.")

    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]

    chunks: list[str] = []
    current_chunk = ""

    for paragraph in paragraphs:
        candidate = (f"{current_chunk}\n\n{paragraph}".strip() if current_chunk else paragraph)

        if len(candidate) <= chunk_size:
            current_chunk = candidate
            continue

        if current_chunk:
            chunks.append(current_chunk)

            overlap_text = (current_chunk[-chunk_overlap:].strip() if chunk_overlap > 0 else "")

            current_chunk = ( f"{overlap_text}\n\n{paragraph}".strip() if overlap_text else paragraph)
        else:
            start = 0
            step = chunk_size - chunk_overlap

            while start < len(paragraph):
                chunk = paragraph[start : start + chunk_size].strip()

                if chunk:
                    chunks.append(chunk)

                start += step

            current_chunk = ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def create_chunk_id(source: str, chunk_index: int, content: str,) -> str:
    raw_value = f"{source}:{chunk_index}:{content}"
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()

    return f"{source}-{chunk_index}-{digest[:16]}"


def prepare_knowledge_chunks() -> tuple[list[str], list[str], list[dict[str, Any]]]:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for file_path, content in read_knowledge_files():
        chunks = split_text(content)

        for chunk_index, chunk in enumerate(chunks):
            source = file_path.name

            ids.append(create_chunk_id(source=source, chunk_index=chunk_index, content=chunk))

            documents.append(chunk)

            metadatas.append({"source": source, "chunk_index": chunk_index})

    return ids, documents, metadatas


def index_knowledge_base(rebuild: bool = False) -> int:
    client = get_chroma_client()

    if rebuild:
        try:
            client.delete_collection(name=COLLECTION_NAME)
        except NotFoundError:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"description": "قاعدة معرفة مساعد استقبال العيادة"}
    )

    ids, documents, metadatas = prepare_knowledge_chunks()

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas,)

    return len(documents)


def ensure_knowledge_base() -> Collection:
    collection = get_collection()

    if collection.count() == 0:
        index_knowledge_base()
        collection = get_collection()

    return collection


def search_knowledge(query: str, results_count: int = DEFAULT_RESULTS_COUNT) -> list[KnowledgeSearchResult]:
    cleaned_query = query.strip()

    if not cleaned_query:
        raise ValueError("لا يمكن البحث باستخدام سؤال فارغ.")

    if results_count <= 0:
        raise ValueError("يجب أن تكون قيمة results_count أكبر من صفر.")

    collection = ensure_knowledge_base()

    available_documents = collection.count()

    if available_documents == 0:
        return []

    safe_results_count = min(results_count, available_documents)

    query_result = collection.query(
        query_texts=[cleaned_query],
        n_results=safe_results_count,
        include=["documents", "metadatas", "distances"]
    )

    documents = query_result.get("documents") or [[]]
    metadatas = query_result.get("metadatas") or [[]]
    distances = query_result.get("distances") or [[]]

    found_documents = documents[0] if documents else []
    found_metadatas = metadatas[0] if metadatas else []
    found_distances = distances[0] if distances else []

    results: list[KnowledgeSearchResult] = []

    for index, document in enumerate(found_documents):
        metadata = (found_metadatas[index] if index < len(found_metadatas) else {})

        distance = (found_distances[index] if index < len(found_distances) else None)

        results.append(
            KnowledgeSearchResult(
                content=document, source=str(metadata.get("source", "unknown")),
                chunk_index=int(metadata.get("chunk_index", 0)),
                distance=(float(distance) if distance is not None else None),
            )
        )

    return results


def format_search_results(results: list[KnowledgeSearchResult]) -> str:
    if not results:
        return ("لم يتم العثور على معلومات مناسبة في قاعدة معرفة العيادة.")

    formatted_sections: list[str] = []

    for result in results:formatted_sections.append("\n".join([f"المصدر: {result.source}", result.content]))

    return "\n\n---\n\n".join(formatted_sections)


if __name__ == "__main__":
    indexed_count = index_knowledge_base(rebuild=True)

    print(f"تمت فهرسة {indexed_count} مقطعًا من قاعدة المعرفة.")

    question = input("اكتب سؤالًا لاختبار البحث: ")

    search_results = search_knowledge(question)

    print("\nنتائج البحث:\n")
    print(format_search_results(search_results))
