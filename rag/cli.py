"""
Interactive RAG CLI for querying textbook indexes.

Usage:
   python -m rag.cli --book eecs281_textbook --root textbook_index
"""

import sys
import argparse
from pathlib import Path

from rag.retrieve import Retriever
from rag.embedding_client import DummyHashEmbeddingClient, ExternalEmbeddingClient


def run_cli(retriever: Retriever, top_k: int = 5) -> None:
   """Run interactive query loop."""

   print("\n" + "=" * 70)
   print("RAG TEXTBOOK SEARCH")
   print("=" * 70)
   print(f"  Index: {retriever.index_dir}")
   print(f"  Chunks: {len(retriever.chunk_ids)}")
   print()
   print("Commands:")
   print("  <query>          Search for relevant chunks")
   print("  :show <chunk_id> Show full text of a chunk")
   print("  :quit            Exit")
   print("=" * 70)

   while True:
      try:
         query = input("\n? ").strip()
      except (KeyboardInterrupt, EOFError):
         print("\nGoodbye!")
         break

      if not query:
         continue

      if query.lower() in (':quit', ':exit', ':q'):
         print("Goodbye!")
         break

      if query.startswith(':show '):
         chunk_id = query[6:].strip()
         meta = retriever.meta.get(chunk_id)
         if meta:
            print(f"\n{'=' * 70}")
            print(f"Chunk: {chunk_id}")
            print(f"Chapter {meta.get('chapter_number')}: {meta.get('chapter_title', '')}")
            print(f"Section {meta.get('section_number')}: {meta.get('section_title', '')}")
            print(f"Pages: {meta.get('page_start')}-{meta.get('page_end')}")
            print(f"{'=' * 70}")
            print(meta.get('text', '(no text)'))
            print(f"{'=' * 70}")
         else:
            print(f"  Chunk not found: {chunk_id}")
         continue

      # Retrieve
      results = retriever.retrieve(query, final_k=top_k)

      if not results:
         print("  No results found.")
         continue

      print(f"\n  Top {len(results)} results:")
      print("-" * 70)

      for i, r in enumerate(results, 1):
         score = r['score']
         chunk_id = r['chunk_id']
         ch = r.get('chapter_number', '?')
         sec = r.get('section_number', '?')
         title = r.get('section_title', '')
         pages = f"p{r.get('page_start', '?')}-{r.get('page_end', '?')}"
         text = r.get('text', '')
         snippet = text[:300].replace('\n', ' ')
         if len(text) > 300:
            snippet += '...'

         print(f"\n  [{i}] score={score:.3f}  {chunk_id}")
         print(f"      Ch.{ch} / {sec}: {title}  ({pages})")
         print(f"      {snippet}")

      print("-" * 70)


def main():
   parser = argparse.ArgumentParser(description="Interactive RAG search CLI.")
   parser.add_argument('--book', '-b', required=True,
                       help="Book name (directory name under root)")
   parser.add_argument('--root', '-r', default='textbook_index',
                       help="Root index directory (default: textbook_index)")
   parser.add_argument('--client', choices=['dummy', 'external'], default='dummy',
                       help="Embedding client for queries (default: dummy)")
   parser.add_argument('--dim', type=int, default=64,
                       help="Embedding dimension (default: 64)")
   parser.add_argument('--top-k', type=int, default=5,
                       help="Number of results (default: 5)")

   args = parser.parse_args()

   index_dir = Path(args.root) / args.book / "index"
   if not index_dir.exists():
      print(f"Error: Index not found at {index_dir}")
      print(f"Run scripts/build_index.py first.")
      sys.exit(1)

   if args.client == 'dummy':
      client = DummyHashEmbeddingClient(dim=args.dim)
   else:
      client = ExternalEmbeddingClient(dim=args.dim)

   retriever = Retriever(index_dir, embedding_client=client)
   run_cli(retriever, top_k=args.top_k)


if __name__ == '__main__':
   main()
