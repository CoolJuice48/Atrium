#!/usr/bin/env python3
"""
Build FAISS + BM25 search index from embedded chunks.

Usage:
   python scripts/build_index.py \\
      --input textbook_index/eecs281_textbook/chunks_content_embedded.jsonl \\
      --index-dir textbook_index/eecs281_textbook/index
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.build_index import build_index


def main():
   parser = argparse.ArgumentParser(
      description="Build FAISS + BM25 search index from embedded chunks."
   )
   parser.add_argument('--input', '-i', required=True,
                       help="Path to chunks_content_embedded.jsonl")
   parser.add_argument('--index-dir', '-o', default=None,
                       help="Output directory (default: <input_dir>/index/)")

   args = parser.parse_args()

   input_path = Path(args.input)
   if not input_path.exists():
      print(f"Error: Input file not found: {input_path}")
      sys.exit(1)

   index_dir = Path(args.index_dir) if args.index_dir else input_path.parent / "index"

   print(f"Building search index...")
   print(f"  Input: {input_path}")
   print(f"  Output: {index_dir}")

   build_index(input_path, index_dir)

   print("\nDone.")


if __name__ == '__main__':
   main()
