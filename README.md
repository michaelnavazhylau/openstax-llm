# openstax-llm 🧠📚

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Powered by openstax-md](https://img.shields.io/badge/compiler-openstax--md-purple)](https://github.com/michaelnavazhylau/openstax-md)

**Pedagogical semantic chunking, RAG dataset preparation, and LLM fine-tuning pipelines from OpenStax textbooks.**

Built on top of [`openstax-md`](https://github.com/michaelnavazhylau/openstax-md), `openstax-llm` transforms rich OpenStax college textbooks into structured, citation-aware, formula-safe datasets for vector search (RAG) and model fine-tuning.

---

## ⚡ Why openstax-llm?

Generic chunkers (like simple character or recursive token splitters) break down on technical academic textbooks:
- They cut mathematical formulas in half (`$x^2 + \dots$` split from `\dots + y^2$`).
- They disassociate worked examples from their solutions.
- They lose the chapter and section hierarchy needed for citations.

`openstax-llm` provides:
1. **Pedagogical Boundary Awareness**: Respects textbook structure—keeping Worked Examples (`Example 1.1`), Problem Sets, Definitions, and Section Summaries intact.
2. **Formula Integrity**: Guarantees that inline and display LaTeX math equations are never split across chunk boundaries.
3. **Docker-Style On-Demand Textbook Fetching**: Uses `openstax-md` to pull textbooks directly from the OpenStax catalog without manual cloning.
4. **Out-of-the-Box RAG & Fine-Tuning Readiness**: Exports directly to JSONL format compatible with Chroma, Pinecone, Qdrant, LanceDB, LlamaIndex, LangChain, and Hugging Face `datasets`.

---

## 🚀 Installation

```bash
# Add to your project with uv
uv add git+https://github.com/michaelnavazhylau/openstax-llm.git

# Or install with pip
pip install git+https://github.com/michaelnavazhylau/openstax-llm.git
```

Or install as a standalone CLI tool:

```bash
uv tool install git+https://github.com/michaelnavazhylau/openstax-llm.git
```

---

## 💻 CLI Usage

```bash
# 1. Search the catalog for available textbooks
openstax-llm search physics

# 2. Inspect a textbook's chunk statistics
openstax-llm info astronomy-2e

# 3. Prepare and chunk a textbook directly into a JSONL dataset
openstax-llm prepare calculus-volume-1 -o datasets/calculus_v1.jsonl --target-words 400
```

---

## 🐍 Python SDK

```python
from openstax_llm import TextBookDataset, prepare_textbook

# 1. Load, compile, and chunk directly from a catalog slug
dataset = TextBookDataset.from_textbook("astronomy-2e")
print(f"Loaded {len(dataset.chunks)} chunks across {dataset.total_words:,} words.")

# 2. Export to JSONL for vector databases
dataset.to_jsonl("datasets/astronomy.jsonl")

# 3. Access records programmatically
for chunk in dataset.chunks[:3]:
    print(f"[{chunk.chunk_id}] {chunk.section} ({chunk.chunk_type}): {chunk.text[:80]}...")

# 4. Convert directly to Hugging Face dataset format
records = dataset.to_records()
# dataset = datasets.Dataset.from_list(records)
```

### Chunk Schema

Each JSONL record contains:

```json
{
  "chunk_id": "1.1-c002",
  "text": "### Example 1.1: Finding the Domain of a Function\nConsider $f(x) = \\sqrt{x - 2}$...",
  "book_slug": "calculus-volume-1",
  "book_title": "Calculus Volume 1",
  "chapter": "1",
  "section": "1.1",
  "section_title": "Functions and Their Graphs",
  "chunk_type": "example",
  "word_count": 184,
  "token_est": 239,
  "metadata": {}
}
```

---

## 📄 License

MIT License. OpenStax textbooks are licensed by Rice University under CC BY-NC-SA 4.0.
