"""
PaperMind - Utility Functions
PDF extraction, section detection, keyword extraction, simplification, export.
"""

import re
import os
from collections import Counter

import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords

for pkg in ["punkt", "stopwords", "punkt_tab"]:
    try:
        nltk.download(pkg, quiet=True)
    except Exception:
        pass

STOP_WORDS = set(stopwords.words("english"))


# ── PDF Text Extraction ─────────────────────────────────────────────────────────

def extract_text_from_pdf(filepath: str) -> str:
    """
    Extract raw text from a PDF file using PyMuPDF (fitz).
    Falls back to pdfminer if fitz is not installed.
    """
    # Try PyMuPDF (fastest and most accurate)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(filepath)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text("text"))
        doc.close()
        full_text = "\n".join(text_parts)
        return clean_extracted_text(full_text)
    except ImportError:
        pass

    # Fallback: pdfminer
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(filepath)
        return clean_extracted_text(text)
    except ImportError:
        pass

    # Last resort: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages)
        return clean_extracted_text(text)
    except Exception as e:
        raise RuntimeError(f"Could not extract text from PDF. Install PyMuPDF: pip install pymupdf. Error: {e}")


def clean_extracted_text(text: str) -> str:
    """Clean raw PDF extracted text"""
    if not text:
        return ""

    import re

    # Normalize whitespace
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Remove standalone page numbers
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)

    # Remove common journal header/footer junk
    text = re.sub(r"IJNRD.*?www\.ijnrd\.org", "", text, flags=re.IGNORECASE)
    text = re.sub(r"ISSN:.*?\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Volume\s+\d+.*?Issue\s+\d+", "", text, flags=re.IGNORECASE)

    # Remove short page labels like j270, j271
    text = re.sub(r"\bj\d+\b", "", text, flags=re.IGNORECASE)

    # Remove repeated figure labels and noisy section labels
    text = re.sub(r"BLOCK DIAGRAM", "", text, flags=re.IGNORECASE)
    text = re.sub(r"WORKING PRINCIPLE", "", text, flags=re.IGNORECASE)
    text = re.sub(r"FIG\.?\s*\d*", "", text, flags=re.IGNORECASE)

    # Remove non-printable characters
    text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", " ", text)

    # Remove very tiny broken words caused by bad extraction
    text = re.sub(r"\b[a-zA-Z]{1,2}\b", "", text)

    # Remove extra spaces again after cleaning
    text = re.sub(r"\s+", " ", text)

    return text.strip()

# ── Section Detection ───────────────────────────────────────────────────────────

# Regex patterns for common research paper sections
SECTION_HEADERS = {
    "Abstract": r"\babstract\b",
    "Introduction": r"\bintroduction\b",
    "Literature Review": r"\b(literature review|related work|background)\b",
    "Methodology": r"\b(methodology|methods?|proposed (method|system|approach))\b",
    "Results": r"\b(results?|experiments?|evaluation|findings)\b",
    "Discussion": r"\bdiscussion\b",
    "Conclusion": r"\b(conclusion|concluding remarks)\b",
    "Future Scope": r"\b(future (work|scope)|limitations?)\b",
    "References": r"\breferences\b",
}


def detect_sections(text: str) -> dict:
    """
    Auto-detect standard paper sections and extract their content.
    Returns dict of { section_name: text_content }
    """
    sections = {}
    text_lower = text.lower()

    for section_name, pattern in SECTION_HEADERS.items():
        match = re.search(pattern, text_lower)
        if match:
            start = match.start()

            # Find the next section header to determine end
            end = len(text)
            for other_name, other_pattern in SECTION_HEADERS.items():
                if other_name == section_name:
                    continue
                other_match = re.search(other_pattern, text_lower[start + 10:])
                if other_match:
                    candidate_end = start + 10 + other_match.start()
                    if candidate_end < end and candidate_end > start:
                        end = candidate_end

            snippet = text[start:end].strip()
            snippet = re.sub(r"\s+", " ", snippet)
            snippet = snippet[:1500]  # Cap at 1500 chars per section

            if len(snippet) > 50:  # Only include non-trivial sections
                sections[section_name] = snippet

    if not sections:
        # Fallback: split by paragraphs
        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 100]
        sections["Content"] = paragraphs[0][:1000] if paragraphs else text[:1000]

    return sections


# ── Keyword Extraction ──────────────────────────────────────────────────────────

def extract_keywords_tfidf(text: str, top_n: int = 15) -> list:
    """TF-IDF based keyword extraction"""
    from sklearn.feature_extraction.text import TfidfVectorizer

    # Split into paragraphs for TF-IDF
    paragraphs = [p for p in text.split("\n\n") if len(p.strip()) > 30]
    if len(paragraphs) < 2:
        paragraphs = sent_tokenize(text)

    if not paragraphs:
        return []

    try:
        vectorizer = TfidfVectorizer(
            max_features=100,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1
        )
        tfidf_matrix = vectorizer.fit_transform(paragraphs)
        feature_names = vectorizer.get_feature_names_out()
        scores = tfidf_matrix.sum(axis=0).A1
        top_indices = scores.argsort()[::-1][:top_n]
        return [feature_names[i] for i in top_indices]
    except Exception:
        return []


def extract_keywords_rake(text: str, top_n: int = 10) -> list:
    """
    Simplified RAKE (Rapid Automatic Keyword Extraction).
    Extracts multi-word phrases.
    """
    # Split text into candidate phrases by stopwords and punctuation
    splitters = re.compile(r"[,.\n;:|!?\(\)\[\]\"']")
    stopword_pattern = re.compile(
        r"\b(" + "|".join(STOP_WORDS) + r")\b", re.IGNORECASE
    )

    # Get candidate phrases
    phrases = []
    for chunk in splitters.split(text.lower()):
        phrase = stopword_pattern.sub("|", chunk)
        for p in phrase.split("|"):
            p = p.strip()
            if len(p.split()) >= 1 and len(p) > 3:
                # Filter out purely numeric or very short
                if re.search(r"[a-z]{3}", p):
                    phrases.append(p)

    # Score phrases by word frequency
    word_freq = Counter()
    for phrase in phrases:
        for word in phrase.split():
            if word.isalpha():
                word_freq[word] += 1

    phrase_scores = {}
    for phrase in phrases:
        words = [w for w in phrase.split() if w.isalpha()]
        if not words:
            continue
        score = sum(word_freq[w] for w in words) / len(words)
        phrase_scores[phrase] = score

    top_phrases = sorted(phrase_scores, key=phrase_scores.get, reverse=True)
    # Return unique phrases
    seen = set()
    result = []
    for p in top_phrases:
        if p not in seen and len(p.split()) <= 4:
            seen.add(p)
            result.append(p)
        if len(result) >= top_n:
            break

    return result


def extract_keywords(text: str, top_n: int = 15) -> list:
    """
    Combined keyword extraction using TF-IDF + RAKE.
    Returns list of keyword strings.
    """
    tfidf_kws = extract_keywords_tfidf(text, top_n=top_n)
    rake_kws = extract_keywords_rake(text, top_n=top_n // 2)

    # Combine and deduplicate
        # Combine and clean keywords
    bad_words = {
        "use", "make", "using", "used", "data", "res", "eng",
        "sci", "inf", "comput", "paper", "study", "result",
        "method", "system", "work", "model", "models",
        "perwej", "www", "ij", "issue", "volume"
    }

    combined = []
    seen = set()

    for kw in tfidf_kws + rake_kws:
        kw_clean = kw.strip().lower()

        # Remove short/broken words
        if len(kw_clean) < 4:
            continue

        # Remove generic useless words
        if kw_clean in bad_words:
            continue

        # Remove numbers
        if kw_clean.isdigit():
            continue

        # Remove duplicates
        if kw_clean not in seen:
            seen.add(kw_clean)
            combined.append(kw_clean)

    return combined[:top_n]


# ── Text Simplification ─────────────────────────────────────────────────────────

# Dictionary of complex research terms → simpler equivalents
JARGON_DICT = {
    "utilize": "use",
    "implement": "build",
    "demonstrate": "show",
    "facilitate": "help",
    "furthermore": "also",
    "subsequently": "then",
    "commence": "start",
    "terminate": "end",
    "ascertain": "find out",
    "endeavour": "try",
    "heterogeneous": "different types of",
    "homogeneous": "same type of",
    "parameters": "settings",
    "algorithm": "step-by-step method",
    "neural network": "brain-like computing model",
    "deep learning": "multi-layer AI learning",
    "convolutional": "pattern-detecting",
    "epoch": "training round",
    "gradient descent": "learning by small steps",
    "overfitting": "memorizing instead of learning",
    "underfitting": "not learning enough",
    "hyperparameter": "tuning setting",
    "benchmark": "standard test",
    "corpus": "collection of text",
    "embedding": "numerical word representation",
    "latency": "delay",
    "throughput": "processing speed",
    "paradigm": "approach or model",
    "aforementioned": "previously mentioned",
    "henceforth": "from now on",
    "pertaining to": "about",
    "notwithstanding": "despite",
    "wherein": "where",
    "heretofore": "until now",
}

LEVEL_CONFIGS = {
    "beginner": {
        "max_sent_words": 20,
        "use_jargon_replace": True,
        "intro": "Here's a simple explanation:\n\n",
    },
    "student": {
        "max_sent_words": 30,
        "use_jargon_replace": True,
        "intro": "Here's the paper explained at student level:\n\n",
    },
    "viva": {
        "max_sent_words": 40,
        "use_jargon_replace": False,
        "intro": "Viva preparation summary (key points):\n\n",
    },
}


def replace_jargon(text: str) -> str:
    """Replace complex terms with simpler alternatives"""
    for complex_term, simple_term in JARGON_DICT.items():
        # Word-boundary aware replacement
        pattern = re.compile(r"\b" + re.escape(complex_term) + r"\b", re.IGNORECASE)
        text = pattern.sub(simple_term, text)
    return text


def shorten_sentences(text: str, max_words: int = 25) -> str:
    """
    Break very long sentences into shorter ones.
    """
    sentences = sent_tokenize(text)
    result = []
    for sent in sentences:
        words = sent.split()
        if len(words) <= max_words:
            result.append(sent)
        else:
            # Split at conjunctions
            parts = re.split(r"\b(which|that|because|although|however|therefore|moreover)\b", sent)
            result.extend([p.strip() for p in parts if len(p.strip()) > 10])

    return " ".join(result)


def simplify_text(text: str, level: str = "beginner", max_chars: int = 3000) -> str:
    """
    Simplify research paper text to a given reading level.

    Levels:
    - beginner: very simple, max 20 words/sentence, all jargon replaced
    - student: moderate, 30 words/sentence, most jargon replaced
    - viva: complete but cleaner, 40 words/sentence, minimal replacement
    """
    config = LEVEL_CONFIGS.get(level, LEVEL_CONFIGS["beginner"])

    # Extract most important content (first 4000 chars)
    if level == "beginner":
        working_text = text[:3000]

    elif level == "student":
        working_text = text[2000:7000]

    elif level == "viva":
        working_text = text[4000:9000]

    else:
        working_text = text[:4000]

    # Apply jargon replacement if configured
    if config["use_jargon_replace"]:
        working_text = replace_jargon(working_text)

    # Shorten long sentences
    working_text = shorten_sentences(working_text, max_words=config["max_sent_words"])

    # Trim to max_chars
    if len(working_text) > max_chars:
        # Cut at sentence boundary
        truncated = working_text[:max_chars]
        last_period = truncated.rfind(".")
        if last_period > max_chars * 0.7:
            truncated = truncated[:last_period + 1]
        working_text = truncated

    return config["intro"] + working_text


# ── PDF Export ──────────────────────────────────────────────────────────────────

def export_report_pdf(report_data: dict, output_path: str):
    """
    Export analysis report as a PDF using ReportLab.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_LEFT, TA_CENTER

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=1 * inch,
            bottomMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Title"],
            fontSize=20,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=12,
            alignment=TA_CENTER,
        )
        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#6366f1"),
            spaceBefore=16,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "CustomBody",
            parent=styles["Normal"],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#374151"),
            spaceAfter=8,
        )

        elements = []

        # Title
        elements.append(Paragraph("PaperMind Analysis Report", title_style))
        elements.append(Paragraph(f"Paper: {report_data.get('filename', 'Unknown')}", body_style))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
        elements.append(Spacer(1, 12))

        # Summary
        elements.append(Paragraph("Summary", heading_style))
        elements.append(Paragraph(report_data.get("summary", ""), body_style))
        elements.append(Spacer(1, 8))

        # Key Points
        elements.append(Paragraph("Key Points", heading_style))
        for point in report_data.get("key_points", []):
            elements.append(Paragraph(f"- {point}", body_style))
        elements.append(Spacer(1, 8))

        # Keywords
        elements.append(Paragraph("Top Keywords", heading_style))
        kws = report_data.get("keywords", [])
        kw_text = ", ".join(kws[:15]) if kws else "None found"
        elements.append(Paragraph(kw_text, body_style))
        elements.append(Spacer(1, 8))

        # Sections
        sections = report_data.get("sections", {})
        if sections:
            elements.append(Paragraph("Detected Sections", heading_style))
            for section_name, section_text in sections.items():
                elements.append(Paragraph(f"{section_name}:", ParagraphStyle(
                    "SectionHead", parent=body_style,
                    fontName="Helvetica-Bold", fontSize=10,
                    textColor=colors.HexColor("#1e293b"),
                )))
                # Clean text for PDF (remove special chars)
                safe_text = re.sub(r"[^\x20-\x7E]", " ", section_text[:600])
                elements.append(Paragraph(safe_text, body_style))
                elements.append(Spacer(1, 4))

        # Footer
        elements.append(Spacer(1, 24))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
        elements.append(Paragraph("Generated by PaperMind - AI Research Paper Simplifier", ParagraphStyle(
            "Footer", parent=body_style,
            fontSize=8, textColor=colors.HexColor("#9ca3af"),
            alignment=TA_CENTER,
        )))

        doc.build(elements)

    except ImportError:
        # Fallback: write plain text file
        txt_path = output_path.replace(".pdf", ".txt")
        with open(txt_path, "w") as f:
            f.write(f"PaperMind Analysis Report\n{'='*50}\n\n")
            f.write(f"Paper: {report_data.get('filename', 'Unknown')}\n\n")
            f.write(f"SUMMARY\n{'-'*30}\n{report_data.get('summary', '')}\n\n")
            f.write(f"KEY POINTS\n{'-'*30}\n")
            for p in report_data.get("key_points", []):
                f.write(f"- {p}\n")
            f.write(f"\nKEYWORDS\n{'-'*30}\n{', '.join(report_data.get('keywords', []))}\n")
        # Copy txt to expected pdf path so send_file works
        import shutil
        shutil.copy(txt_path, output_path)
