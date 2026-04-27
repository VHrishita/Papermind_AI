"""
PaperMind - Summarizer Module
Implements TF-IDF + TextRank summarization (fully offline)
"""

import re
import math
from collections import defaultdict

import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords

# Download required NLTK data on first run
for pkg in ["punkt", "stopwords", "punkt_tab"]:
    try:
        nltk.download(pkg, quiet=True)
    except Exception:
        pass

STOP_WORDS = set(stopwords.words("english"))


# ── Helper Functions ────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Remove noise characters from extracted PDF text"""
    text = re.sub(r"\n{3,}", "\n\n", text)          # Collapse multiple blank lines
    text = re.sub(r"[ \t]{2,}", " ", text)           # Collapse multiple spaces
    text = re.sub(r"[^\x00-\x7F]+", " ", text)       # Remove non-ASCII chars
    text = re.sub(r"\b\d+\b", "", text)               # Remove lone numbers
    return text.strip()


def tokenize_sentences(text: str) -> list:
    """Split text into clean sentences"""
    text = clean_text(text)
    sentences = sent_tokenize(text)
    # Filter out very short sentences (likely headers/noise)
    return [s.strip() for s in sentences if len(s.split()) > 5]


def compute_tfidf(sentences: list) -> dict:
    """
    Compute TF-IDF score for each word across all sentences.
    Returns dict of {word: tfidf_score}
    """
    # Term Frequency: count how often each word appears in each sentence
    tf = defaultdict(lambda: defaultdict(int))
    for i, sentence in enumerate(sentences):
        words = word_tokenize(sentence.lower())
        for word in words:
            if word.isalpha() and word not in STOP_WORDS:
                tf[i][word] += 1

    # Document Frequency: how many sentences contain each word
    df = defaultdict(int)
    for i in tf:
        for word in tf[i]:
            df[word] += 1

    N = len(sentences)

    # TF-IDF score per word
    tfidf = defaultdict(float)
    for i in tf:
        for word, count in tf[i].items():
            tfidf[word] += count * math.log((N + 1) / (df[word] + 1))

    return dict(tfidf)


def score_sentences_tfidf(sentences: list, tfidf: dict) -> list:
    """
    Score each sentence based on TF-IDF word scores.
    Returns list of (score, index, sentence) tuples.
    """
    scored = []
    for i, sentence in enumerate(sentences):
        words = word_tokenize(sentence.lower())
        score = sum(tfidf.get(w, 0) for w in words if w.isalpha())
        # Normalize by sentence length to avoid bias toward long sentences
        score = score / (len(words) + 1)
        scored.append((score, i, sentence))
    return scored


def textrank_scores(sentences: list) -> list:
    """
    Simple TextRank: build similarity graph between sentences,
    then rank by total similarity weight (like PageRank concept).
    Returns list of (score, index, sentence).
    """
    def sentence_similarity(s1, s2):
        """Jaccard-style similarity between two sentences"""
        w1 = set(word_tokenize(s1.lower())) - STOP_WORDS
        w2 = set(word_tokenize(s2.lower())) - STOP_WORDS
        if not w1 or not w2:
            return 0.0
        intersection = w1 & w2
        union = w1 | w2
        return len(intersection) / len(union)

    n = len(sentences)
    # Build similarity matrix
    scores = [0.0] * n
    for i in range(n):
        for j in range(n):
            if i != j:
                scores[i] += sentence_similarity(sentences[i], sentences[j])

    # Return as (score, index, sentence) list
    return [(scores[i], i, sentences[i]) for i in range(n)]


def combined_score(sentences: list) -> list:
    """
    Combine TF-IDF and TextRank scores for better results.
    """
    tfidf = compute_tfidf(sentences)
    tfidf_scored = score_sentences_tfidf(sentences, tfidf)
    tr_scored = textrank_scores(sentences)

    # Normalize both score lists to [0,1]
    def normalize(scored):
        scores = [s for s, _, _ in scored]
        max_s = max(scores) if max(scores) > 0 else 1
        return [(s / max_s, i, sent) for s, i, sent in scored]

    tfidf_n = {i: s for s, i, _ in normalize(tfidf_scored)}
    tr_n = {i: s for s, i, _ in normalize(tr_scored)}

    # Average the two scores
    combined = []
    for idx, sentence in enumerate(sentences):
        score = (tfidf_n.get(idx, 0) + tr_n.get(idx, 0)) / 2
        combined.append((score, idx, sentence))

    return combined


# ── Public API ──────────────────────────────────────────────────────────────────

def summarize_text(text: str, ratio: float = 0.25) -> str:
    """
    Generate a paragraph summary using combined TF-IDF + TextRank.
    ratio = fraction of sentences to include (0.25 = top 25%)
    """
    text = text[:8000]
    sentences = tokenize_sentences(text)
    if len(sentences) < 3:
        return text[:1000]  # Return raw text if too short

    scored = combined_score(sentences)

    # Select top sentences (ratio-based)
    n_select = max(3, int(len(sentences) * ratio))
    top = sorted(scored, reverse=True)[:n_select]

    # Re-order selected sentences by original position
    top_sorted = sorted(top, key=lambda x: x[1])

    summary = " ".join(sent for _, _, sent in top_sorted)
    return summary


def extract_key_points(text: str, n_points: int = 7) -> list:
    """
    Extract key bullet points from text.
    Returns list of strings.
    """
    text = text[:8000]
    sentences = tokenize_sentences(text)
    if not sentences:
        return ["Could not extract key points."]

    scored = combined_score(sentences)
    top = sorted(scored, reverse=True)[:n_points]
    top_sorted = sorted(top, key=lambda x: x[1])

    points = []
    for _, _, sent in top_sorted:
        # Clean up the sentence
        sent = sent.strip()
        if len(sent) > 20:
            points.append(sent)

    return points


def one_line_summary(text: str) -> str:
    """
    Generate a single-sentence abstract-style summary.
    Picks the single highest-scored sentence.
    """
    text = text[:8000]
    sentences = tokenize_sentences(text)
    if not sentences:
        return "Unable to generate summary."

    scored = combined_score(sentences)
    best = max(scored, key=lambda x: x[0])
    return best[2]
