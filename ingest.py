"""Re-read the files in knowledge/<course>/ and rebuild the search index.
   Run after adding or changing course material:  python ingest.py"""
import config, rag
for c in config.COURSES:
    n = len(rag.build_chunks(c)); print(f"{c}: {n} chunks")
    if config.OPENAI_API_KEY:
        rag.build_embeddings(c); print("  embeddings built")
    else:
        print("  (no OPENAI_API_KEY: keyword search only. Set the key and run again for full AI search)")
