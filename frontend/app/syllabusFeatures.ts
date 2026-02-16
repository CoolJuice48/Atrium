/**
 * Extract features from syllabus text (topics, weeks, textbooks).
 * Runs entirely client-side; no plaintext sent to server.
 */

const STOP_WORDS = new Set(
  "a an the and or but in on at to for of with by from as is was are were been be have has had do does did will would could should may might must can".split(
    " "
  )
);

function extractTopics(text: string): string[] {
  const words = text
    .toLowerCase()
    .replace(/[^\w\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length >= 4 && !STOP_WORDS.has(w));
  const counts = new Map<string, number>();
  for (const w of words) {
    counts.set(w, (counts.get(w) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20)
    .map(([w]) => w);
}

function extractWeeks(text: string): number[] {
  const weeks: number[] = [];
  const re = /week\s*(\d+)/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const n = parseInt(m[1], 10);
    if (n >= 1 && n <= 52 && !weeks.includes(n)) weeks.push(n);
  }
  return weeks.sort((a, b) => a - b);
}

function extractTextbooks(text: string): string[] {
  const textbooks: string[] = [];
  const re = /(?:textbook|book|required reading)[:\s]+([^\n]+)/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const t = m[1].trim().slice(0, 200);
    if (t && !textbooks.includes(t)) textbooks.push(t);
  }
  return textbooks.slice(0, 10);
}

export interface SyllabusFeatures {
  topics: string[];
  weeks: number[];
  textbooks: string[];
}

export function extractFeaturesFromText(text: string): SyllabusFeatures {
  return {
    topics: extractTopics(text),
    weeks: extractWeeks(text),
    textbooks: extractTextbooks(text),
  };
}

/** Extract text from File (text or PDF). */
export async function extractTextFromFile(file: File): Promise<string> {
  if (file.type === "text/plain" || file.name.endsWith(".txt")) {
    return file.text();
  }
  if (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) {
    const { getDocument } = await import("pdfjs-dist");
    const pdf = await getDocument(await file.arrayBuffer()).promise;
    const pages: string[] = [];
    for (let i = 1; i <= Math.min(pdf.numPages, 50); i++) {
      const page = await pdf.getPage(i);
      const content = await page.getTextContent();
      pages.push(content.items.map((it) => ("str" in it ? it.str : "")).join(" "));
    }
    return pages.join("\n");
  }
  return "";
}
