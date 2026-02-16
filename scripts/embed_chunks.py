#!/usr/bin/env python3
"""
Embed chunks_content.jsonl with vector embeddings.

Reads chunks, embeds each text field, writes output with 'embedding' field added.

Usage:
   python scripts/embed_chunks.py \\
      --input textbook_index/eecs281_textbook/chunks_content.jsonl \\
      --client dummy --dim 64

   python scripts/embed_chunks.py \\
      --input textbook_index/eecs281_textbook/chunks_content.jsonl \\
      --client external --dim 1536
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.embedding_client import DummyHashEmbeddingClient, ExternalEmbeddingClient


def embed_chunks(
   input_path: Path,
   output_path: Path,
   client,
   max_chars: int = 0,
   verbose: bool = True,
) -> dict:
   """
   Read chunks JSONL, add 'embedding' field, write to output.

   Args:
      input_path:  Path to chunks_content.jsonl
      output_path: Path to write embedded chunks
      client:      EmbeddingClient instance
      max_chars:   If > 0, truncate text before embedding
      verbose:     Print progress

   Returns:
      Stats dict with count, dim, output_path
   """
   count = 0

   with open(input_path, 'r', encoding='utf-8') as fin, \
        open(output_path, 'w', encoding='utf-8') as fout:

      for line in fin:
         line = line.strip()
         if not line:
            continue

         record = json.loads(line)
         text = record.get('text', '')

         if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars]

         record['embedding'] = client.embed(text)
         fout.write(json.dumps(record, ensure_ascii=False) + '\n')
         count += 1

         if verbose and count % 100 == 0:
            print(f"  Embedded {count} chunks...")

   # Write sidecar meta
   meta_path = output_path.parent / "embedding_meta.json"
   meta = {
      "embedding_dim": client.dim,
      "total_chunks": count,
      "source": str(input_path),
      "output": str(output_path),
   }
   with open(meta_path, 'w', encoding='utf-8') as f:
      json.dump(meta, f, indent=2)

   if verbose:
      print(f"\n  Embedded {count} chunks (dim={client.dim})")
      print(f"  Output: {output_path}")
      print(f"  Meta: {meta_path}")

   return {"count": count, "dim": client.dim, "output": str(output_path)}


def main():
   parser = argparse.ArgumentParser(description="Embed chunks with vector embeddings.")
   parser.add_argument('--input', '-i', required=True,
                       help="Path to chunks_content.jsonl")
   parser.add_argument('--out', '-o', default=None,
                       help="Output path (default: chunks_content_embedded.jsonl)")
   parser.add_argument('--inplace', action='store_true',
                       help="Overwrite input file in-place")
   parser.add_argument('--client', choices=['dummy', 'external'], default='dummy',
                       help="Embedding client (default: dummy)")
   parser.add_argument('--dim', type=int, default=64,
                       help="Embedding dimension (default: 64)")
   parser.add_argument('--max-chars', type=int, default=0,
                       help="Truncate text to N chars before embedding (0=no truncation)")

   args = parser.parse_args()

   input_path = Path(args.input)
   if not input_path.exists():
      print(f"Error: Input file not found: {input_path}")
      sys.exit(1)

   if args.inplace:
      import tempfile
      output_path = Path(tempfile.mktemp(suffix='.jsonl', dir=input_path.parent))
   elif args.out:
      output_path = Path(args.out)
   else:
      output_path = input_path.parent / "chunks_content_embedded.jsonl"

   if args.client == 'dummy':
      client = DummyHashEmbeddingClient(dim=args.dim)
   else:
      client = ExternalEmbeddingClient(dim=args.dim)

   print(f"Embedding chunks...")
   print(f"  Input: {input_path}")
   print(f"  Client: {args.client} (dim={client.dim})")

   embed_chunks(input_path, output_path, client, max_chars=args.max_chars)

   if args.inplace:
      output_path.rename(input_path)
      print(f"\n  Overwrote {input_path}")

   print("\nDone.")


if __name__ == '__main__':
   main()
