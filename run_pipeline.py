#!/usr/bin/env python3
"""
Textbook Pipeline & Search

Single entry point for the complete workflow:
  1. PDF → PageRecords + Chapters + Sections + SectionsWithText
  2. Q&A Extraction
  3. QuestionBank Creation
  4. Embed into Search Index

Modes:
  [P] Process - Extract, embed, and index PDFs
  [S] Search  - Interactive textbook search
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"
CONVERTED_DIR = ROOT / "converted"

PDF_DIR.mkdir(exist_ok=True)
CONVERTED_DIR.mkdir(exist_ok=True)


def list_pdfs():
    """List all PDFs in the pdfs/ directory."""
    pdfs = sorted(PDF_DIR.glob("*.pdf"))

    if not pdfs:
        print("\n⚠ No PDFs found in pdfs/ directory")
        print(f"  Place PDF files in: {PDF_DIR.absolute()}")
        return []

    print("\n" + "="*70)
    print("AVAILABLE PDFs")
    print("="*70)

    for i, pdf in enumerate(pdfs, 1):
        size_mb = pdf.stat().st_size / (1024 * 1024)

        # Check if already converted
        converted_dir = CONVERTED_DIR / pdf.stem
        status = "✓ Converted" if converted_dir.exists() else "○ Not converted"

        print(f"{i}. {pdf.name:<40s} ({size_mb:6.2f} MB)  {status}")

    return pdfs


def show_process_menu(pdfs):
    """Display processing menu and get user choice."""
    print("\n" + "="*70)
    print("PROCESS OPTIONS")
    print("="*70)
    print("  [A] Convert ALL PDFs")
    print("  [1-9] Convert specific PDF by number")
    print("  [C] Classify pages for all converted textbooks")
    print("  [R] Build content corpus for all converted textbooks")
    print("  [E] Embed all converted textbooks into search index")
    print("  [L] List PDFs again")
    print("  [B] Back to main menu")
    print("  [Q] Quit")
    print("="*70)

    choice = input("\nYour choice: ").strip().upper()
    return choice


def embed_textbook(pdf_name, output_dir, search):
    """
    Embed a single textbook's sections into the search index.

    Args:
        pdf_name: Name of the PDF (stem)
        output_dir: Path to the converted output directory
        search: TextbookSearchOffline instance

    Returns:
        True if successful, False otherwise
    """
    # Prefer chunked sections, fall back to non-chunked
    chunked_file = output_dir / f"{pdf_name}_SectionsWithText_Chunked.jsonl"
    plain_file = output_dir / f"{pdf_name}_SectionsWithText.jsonl"

    sections_file = chunked_file if chunked_file.exists() else plain_file

    if not sections_file.exists():
        print(f"  ⚠ No sections file found for {pdf_name}, skipping embedding")
        return False

    search.load_textbook(sections_file, book_name=pdf_name)
    return True


def embed_all_converted():
    """Find and embed all converted textbooks into the search index."""
    from legacy.textbook_search_offline import TextbookSearchOffline

    print("\n" + "="*70)
    print("EMBEDDING ALL CONVERTED TEXTBOOKS")
    print("="*70 + "\n")

    search = TextbookSearchOffline()

    # Find all converted directories
    converted_dirs = sorted(d for d in CONVERTED_DIR.iterdir() if d.is_dir())

    if not converted_dirs:
        print("✗ No converted textbooks found")
        print(f"  Process PDFs first to create converted output")
        return

    loaded = 0
    for d in converted_dirs:
        book_name = d.name
        if embed_textbook(book_name, d, search):
            loaded += 1

    print("\n" + "="*70)
    print(f"EMBEDDING COMPLETE — {loaded} textbook(s) indexed")
    print("="*70)
    search.stats()
    search.list_books()


def process_pdf(
    pdf_path,
    auto_chunk=None,
    classify_pages=False,
    build_corpus=False,
    backend="pymupdf",
    pymupdf_mode="text",
    emit_pdf_toc=False,
    emit_page_labels=False,
):
    """
    Process a single PDF through the complete pipeline.

    Args:
        pdf_path: Path to PDF file
        auto_chunk: True/False for auto-chunking, None to ask user
        classify_pages: If True, run page classification after PageRecords generation
        build_corpus: If True, build content corpus after embedding step
        backend: Extraction backend ("pymupdf" or "legacy")
        pymupdf_mode: PyMuPDF mode ("text" or "blocks")
        emit_pdf_toc: Write TOC sidecar file (pymupdf backend only)
        emit_page_labels: Write page labels sidecar file (pymupdf backend only)

    Returns:
        True if successful, False otherwise
    """
    pdf_name = pdf_path.stem

    print("\n" + "="*70)
    print(f"PROCESSING: {pdf_path.name}")
    print("="*70)

    try:
        # ── STEP 1: Convert PDF → JSONL + Sections ──────────────────────
        print("\n" + "="*70)
        print("STEP 1: CONVERTING PDF TO JSONL")
        print("="*70 + "\n")

        from pdf_to_jsonl import convert_pdf

        output_dir_name = pdf_name

        doc_id, output_dir = convert_pdf(
            pdf_path,
            output_dir_name=output_dir_name,
            auto_chunk=auto_chunk,
            backend=backend,
            pymupdf_mode=pymupdf_mode,
            emit_pdf_toc=emit_pdf_toc,
            emit_page_labels=emit_page_labels,
        )

        print(f"\n✓ Conversion complete")
        print(f"  Document ID: {doc_id}")
        print(f"  Output dir: {output_dir}\n")

        # ── STEP 1.5 (optional): Classify pages ─────────────────────────
        if classify_pages:
            print("="*70)
            print("STEP 1.5: CLASSIFYING PAGES")
            print("="*70 + "\n")

            pages_file = output_dir / f"{pdf_name}_PageRecords"
            if pages_file.exists():
                from legacy.page_classifier import classify_pagerecords
                cls_out = output_dir / f"{pdf_name}_PageClassifications.jsonl"
                classify_pagerecords(pages_file, cls_out)
                print(f"\n✓ Page classification complete: {cls_out.name}\n")
            else:
                print(f"⚠ PageRecords not found, skipping classification\n")

        # ── STEP 2: Extract Q&A ──────────────────────────────────────────
        print("="*70)
        print("STEP 2: EXTRACTING Q&A")
        print("="*70 + "\n")

        pages_file = output_dir / f"{pdf_name}_PageRecords"
        doc_file = output_dir / f"{pdf_name}_DocumentRecord"

        if not pages_file.exists():
            print(f"⚠ Pages file missing: {pages_file}")
            print("  Skipping Q&A extraction")
        else:
            with open(doc_file, "r", encoding="utf-8") as f:
                book_id = json.load(f).get("id")

            from legacy.qa_handler import extract_qas
            questions_path, answers_path = extract_qas(pages_file, book_id)

            print(f"\n✓ Q&A extraction complete")
            print(f"  Questions: {questions_path}")
            print(f"  Answers: {answers_path}\n")

        # ── STEP 3: Build QuestionBank ────────────────────────────────────
        print("="*70)
        print("STEP 3: CREATING QUESTIONBANK")
        print("="*70 + "\n")

        from legacy.qa_schema import QuestionBank, Question, Answer

        bank = QuestionBank(
            name=f"{pdf_name} Question Bank",
            description=f"Questions and answers extracted from {pdf_name}"
        )

        # Load questions
        q_count = 0
        questions_path = output_dir / f"{pdf_name}_Questions.jsonl"
        if questions_path.exists():
            with open(questions_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    q_data = json.loads(line)
                    question = Question(
                        question_id=q_data.get("id", ""),
                        question_text=q_data.get("question_text", ""),
                        question_type="multiple_choice",
                        source_type="textbook",
                        source_book=pdf_name,
                        source_chapter=q_data.get("chapter"),
                        source_page=q_data.get("pdf_page"),
                        source_section=", ".join(q_data.get("section_titles", []))
                    )
                    bank.add_question(question)
                    q_count += 1

        # Load answers
        a_count = 0
        answers_path = output_dir / f"{pdf_name}_Answers.jsonl"
        if answers_path.exists():
            with open(answers_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    a_data = json.loads(line)
                    answer = Answer(
                        question_id=a_data.get("id", ""),
                        answer_text=a_data.get("answer_text", ""),
                        source=pdf_name
                    )
                    bank.add_answer(answer)
                    a_count += 1

        bank_file = output_dir / f"{pdf_name}_QuestionBank.json"
        bank.save(str(bank_file))

        print(f"✓ QuestionBank created: {bank_file.name}")
        print(f"  Questions: {q_count}")
        print(f"  Answers: {a_count}\n")

        # ── STEP 4: Embed into Search Index ───────────────────────────────
        print("="*70)
        print("STEP 4: EMBEDDING INTO SEARCH INDEX")
        print("="*70 + "\n")

        from legacy.textbook_search_offline import TextbookSearchOffline

        search = TextbookSearchOffline()

        if embed_textbook(pdf_name, output_dir, search):
            print(f"\n✓ {pdf_name} embedded into search index")
            search.stats()
        else:
            print(f"⚠ Could not embed {pdf_name} (no sections file)")

        print()

        # ── STEP 5 (optional): Build content corpus ──────────────────────
        if build_corpus:
            print("="*70)
            print("STEP 5: BUILDING CONTENT CORPUS")
            print("="*70 + "\n")

            # Find sections file (prefer chunked)
            chunked_file = output_dir / f"{pdf_name}_SectionsWithText_Chunked.jsonl"
            plain_file = output_dir / f"{pdf_name}_SectionsWithText.jsonl"
            sections_file = chunked_file if chunked_file.exists() else plain_file

            cls_file = output_dir / f"{pdf_name}_PageClassifications.jsonl"
            cls_path = cls_file if cls_file.exists() else None

            if sections_file.exists():
                from rag.build_content_corpus import build_corpus as run_corpus_build
                corpus_out = ROOT / "textbook_index"
                run_corpus_build(
                    sections_path=sections_file,
                    page_cls_path=cls_path,
                    out_root=corpus_out,
                    book_name_override=pdf_name,
                )
                print(f"\n✓ Content corpus built\n")
            else:
                print(f"⚠ No SectionsWithText file found, skipping corpus build\n")

        # ── Summary ───────────────────────────────────────────────────────
        print("="*70)
        print(f"✓ {pdf_name} COMPLETE — Output files:")
        print("="*70)

        key_files = [
            f"{pdf_name}_PageRecords",
            f"{pdf_name}_PageClassifications.jsonl",
            f"{pdf_name}_Chapters.jsonl",
            f"{pdf_name}_Sections.jsonl",
            f"{pdf_name}_SectionsWithText_Chunked.jsonl",
            f"{pdf_name}_SectionsWithText.jsonl",
            f"{pdf_name}_DocumentRecord",
            f"{pdf_name}_Questions.jsonl",
            f"{pdf_name}_Answers.jsonl",
            f"{pdf_name}_QuestionBank.json"
        ]

        for filename in key_files:
            filepath = output_dir / filename
            if filepath.exists():
                size = filepath.stat().st_size
                if size > 1024 * 1024:
                    size_str = f"{size / (1024*1024):.2f} MB"
                else:
                    size_str = f"{size / 1024:.1f} KB"

                if "SectionsWithText" in filename:
                    print(f"  ✨ {filename:<50s}  {size_str:>10s}  ← INDEXED")
                else:
                    print(f"     {filename:<50s}  {size_str:>10s}")

        print("\n")
        return True

    except Exception as e:
        print(f"\n✗ Error processing {pdf_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def classify_all_converted():
    """Run page classification on all converted textbooks that have PageRecords."""
    from legacy.page_classifier import classify_pagerecords

    print("\n" + "="*70)
    print("CLASSIFYING ALL CONVERTED TEXTBOOKS")
    print("="*70 + "\n")

    converted_dirs = sorted(d for d in CONVERTED_DIR.iterdir() if d.is_dir())

    if not converted_dirs:
        print("✗ No converted textbooks found")
        return

    classified = 0
    for d in converted_dirs:
        book_name = d.name
        pages_file = d / f"{book_name}_PageRecords"
        cls_out = d / f"{book_name}_PageClassifications.jsonl"

        if not pages_file.exists():
            print(f"  ⚠ No PageRecords for {book_name}, skipping")
            continue

        print(f"\n  Classifying {book_name}...")
        classify_pagerecords(pages_file, cls_out)
        classified += 1

    print("\n" + "="*70)
    print(f"CLASSIFICATION COMPLETE — {classified} textbook(s) classified")
    print("="*70)


def build_corpus_all_converted():
    """Build content corpus for all converted textbooks that have SectionsWithText."""
    from rag.build_content_corpus import build_corpus as run_corpus_build

    print("\n" + "="*70)
    print("BUILDING CONTENT CORPUS FOR ALL CONVERTED TEXTBOOKS")
    print("="*70 + "\n")

    converted_dirs = sorted(d for d in CONVERTED_DIR.iterdir() if d.is_dir())

    if not converted_dirs:
        print("✗ No converted textbooks found")
        return

    built = 0
    corpus_out = ROOT / "textbook_index"

    for d in converted_dirs:
        book_name = d.name

        # Prefer chunked sections
        chunked = d / f"{book_name}_SectionsWithText_Chunked.jsonl"
        plain = d / f"{book_name}_SectionsWithText.jsonl"
        sections_file = chunked if chunked.exists() else plain

        if not sections_file.exists():
            print(f"  ⚠ No SectionsWithText for {book_name}, skipping")
            continue

        cls_file = d / f"{book_name}_PageClassifications.jsonl"
        cls_path = cls_file if cls_file.exists() else None

        print(f"\n  Building corpus for {book_name}...")
        run_corpus_build(
            sections_path=sections_file,
            page_cls_path=cls_path,
            out_root=corpus_out,
            book_name_override=book_name,
        )
        built += 1

    print("\n" + "="*70)
    print(f"CORPUS BUILD COMPLETE — {built} textbook(s) processed")
    print("="*70)


def process_all_pdfs(
    pdfs,
    auto_chunk=True,
    classify_pages=False,
    build_corpus=False,
    backend="pymupdf",
    pymupdf_mode="text",
    emit_pdf_toc=False,
    emit_page_labels=False,
):
    """Process all PDFs in batch mode."""
    print("\n" + "="*70)
    print(f"BATCH PROCESSING: {len(pdfs)} PDFs")
    print("="*70)
    print(f"Auto-chunking: {'ENABLED' if auto_chunk else 'DISABLED'}")
    print(f"Page classification: {'ENABLED' if classify_pages else 'DISABLED'}")
    print(f"Content corpus: {'ENABLED' if build_corpus else 'DISABLED'}")
    print(f"Backend: {backend} (mode: {pymupdf_mode})")

    successful = 0
    failed = 0

    for i, pdf in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}] Processing {pdf.name}...")

        if process_pdf(
            pdf,
            auto_chunk=auto_chunk,
            classify_pages=classify_pages,
            build_corpus=build_corpus,
            backend=backend,
            pymupdf_mode=pymupdf_mode,
            emit_pdf_toc=emit_pdf_toc,
            emit_page_labels=emit_page_labels,
        ):
            successful += 1
        else:
            failed += 1

    # Final summary
    print("\n" + "="*70)
    print("BATCH PROCESSING COMPLETE")
    print("="*70)
    print(f"  Successful: {successful}/{len(pdfs)}")
    print(f"  Failed: {failed}/{len(pdfs)}")

    if successful > 0:
        print(f"\n✓ {successful} textbook(s) processed and indexed!")


def search_mode():
    """Interactive textbook search."""
    from legacy.textbook_search_offline import TextbookSearchOffline

    print("\n" + "="*70)
    print("TEXTBOOK SEARCH")
    print("="*70)

    search = TextbookSearchOffline()

    if len(search.documents) == 0:
        print("\n⚠ Search index is empty!")
        print("  Process PDFs first with [P] to extract and embed textbooks.")
        return

    search.stats()
    search.list_books()

    print("\n" + "="*70)
    print("Ready! Type your questions (or 'quit' to go back)")
    print("Modes:")
    print("  [default]  Answer mode — composed answer + key points")
    print("  'search'   Toggle to raw chunk search mode")
    print("Commands: 'stats', 'books', 'full', 'snippets', 'quit'")
    print("="*70)

    show_full = False
    show_snippets = False
    answer_mode = True  # Default to answer mode

    while True:
        try:
            prompt = "\nA? " if answer_mode else "\n? "
            query = input(prompt).strip()

            if not query:
                continue

            if query.lower() in ['quit', 'exit', 'q']:
                break

            if query.lower() == 'stats':
                search.stats()
                continue

            if query.lower() == 'books':
                search.list_books()
                continue

            if query.lower() == 'full':
                show_full = not show_full
                print(f"  Full text: {'ON' if show_full else 'OFF'}")
                continue

            if query.lower() == 'snippets':
                show_snippets = not show_snippets
                print(f"  Raw snippets: {'ON' if show_snippets else 'OFF'}")
                continue

            if query.lower() == 'search':
                answer_mode = not answer_mode
                mode_name = "Answer" if answer_mode else "Search"
                print(f"  Mode: {mode_name}")
                continue

            if answer_mode:
                search.answer(
                    query,
                    n_sentences=5,
                    n_chunks=5,
                    qa_dir=CONVERTED_DIR,
                    show_snippets=show_snippets,
                )
            else:
                search.ask(query, n_results=3, show_full_text=show_full)

        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"Error: {e}")


def _ask_backend_options():
    """Prompt user for extraction backend options. Returns (backend, pymupdf_mode, emit_toc, emit_labels)."""
    be_choice = input("Backend? [P]yMuPDF / [L]egacy (default=P): ").strip().upper()
    if be_choice == 'L':
        backend = "legacy"
        pymupdf_mode = "text"
        emit_toc = False
        emit_labels = False
    else:
        backend = "pymupdf"
        mode_choice = input("  PyMuPDF mode? [T]ext / [B]locks (default=T): ").strip().upper()
        pymupdf_mode = "blocks" if mode_choice == 'B' else "text"
        toc_choice = input("  Emit PDF TOC? (y/N, default=N): ").strip().upper()
        emit_toc = toc_choice == 'Y'
        labels_choice = input("  Emit page labels? (y/N, default=N): ").strip().upper()
        emit_labels = labels_choice == 'Y'
    return backend, pymupdf_mode, emit_toc, emit_labels


def process_mode():
    """Interactive PDF processing loop."""
    pdfs = list_pdfs()

    if not pdfs:
        return

    while True:
        choice = show_process_menu(pdfs)

        if choice in ('Q',):
            print("\nGoodbye!")
            sys.exit(0)

        elif choice == 'B':
            return

        elif choice == 'L':
            pdfs = list_pdfs()

        elif choice == 'C':
            classify_all_converted()

        elif choice == 'R':
            build_corpus_all_converted()

        elif choice == 'E':
            embed_all_converted()

        elif choice == 'A':
            print("\nBatch processing options:")
            chunk_choice = input("Enable auto-chunking for all? (Y/n, default=Y): ").strip().upper()
            auto_chunk = chunk_choice != 'N'
            cls_choice = input("Classify pages? (y/N, default=N): ").strip().upper()
            classify = cls_choice == 'Y'
            corpus_choice = input("Build content corpus? (y/N, default=N): ").strip().upper()
            do_corpus = corpus_choice == 'Y'

            be, pm, toc, labels = _ask_backend_options()

            process_all_pdfs(
                pdfs, auto_chunk=auto_chunk,
                classify_pages=classify, build_corpus=do_corpus,
                backend=be, pymupdf_mode=pm,
                emit_pdf_toc=toc, emit_page_labels=labels,
            )
            pdfs = list_pdfs()

        elif choice.isdigit():
            idx = int(choice) - 1

            if 0 <= idx < len(pdfs):
                pdf = pdfs[idx]

                print(f"\nProcessing: {pdf.name}")
                chunk_choice = input("Enable chunking? (Y/n, default=Y): ").strip().upper()
                auto_chunk = chunk_choice != 'N'
                cls_choice = input("Classify pages? (y/N, default=N): ").strip().upper()
                classify = cls_choice == 'Y'
                corpus_choice = input("Build content corpus? (y/N, default=N): ").strip().upper()
                do_corpus = corpus_choice == 'Y'

                be, pm, toc, labels = _ask_backend_options()

                process_pdf(
                    pdf, auto_chunk=auto_chunk,
                    classify_pages=classify, build_corpus=do_corpus,
                    backend=be, pymupdf_mode=pm,
                    emit_pdf_toc=toc, emit_page_labels=labels,
                )
                pdfs = list_pdfs()
            else:
                print(f"\n✗ Invalid number. Choose 1-{len(pdfs)}")

        else:
            print("\n✗ Invalid choice. Try again.")


def main():
    """Main entry point — choose Process or Search."""
    print("="*70)
    print("TEXTBOOK PIPELINE & SEARCH")
    print("="*70)
    print("\n  [P] Process PDFs  — Extract, embed, and index textbooks")
    print("  [S] Search        — Search your indexed textbooks")
    print("  [Q] Quit")
    print("="*70)

    while True:
        choice = input("\nYour choice: ").strip().upper()

        if choice == 'Q':
            print("\nGoodbye!")
            sys.exit(0)

        elif choice == 'P':
            process_mode()
            # After returning from process mode, show main menu again
            print("\n" + "="*70)
            print("TEXTBOOK PIPELINE & SEARCH")
            print("="*70)
            print("\n  [P] Process PDFs  — Extract, embed, and index textbooks")
            print("  [S] Search        — Search your indexed textbooks")
            print("  [Q] Quit")
            print("="*70)

        elif choice == 'S':
            search_mode()
            # After returning from search, show main menu again
            print("\n" + "="*70)
            print("TEXTBOOK PIPELINE & SEARCH")
            print("="*70)
            print("\n  [P] Process PDFs  — Extract, embed, and index textbooks")
            print("  [S] Search        — Search your indexed textbooks")
            print("  [Q] Quit")
            print("="*70)

        else:
            print("✗ Invalid choice. Enter P, S, or Q.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Goodbye!")
        sys.exit(0)
