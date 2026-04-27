"""
PaperMind - Q&A Engine
Semantic question answering over PDF text using TF-IDF cosine similarity.
Falls back gracefully if sentence-transformers is unavailable.
No external API needed.
"""

import re
import math
import numpy as np
from collections import defaultdict

import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords

for pkg in ["punkt", "stopwords", "punkt_tab"]:
    try:
        nltk.download(pkg, quiet=True)
    except Exception:
        pass

STOP_WORDS = set(stopwords.words("english"))

# Try to load sentence-transformers for better semantic matching
USE_SBERT = False
sbert_model = None
try:
    from sentence_transformers import SentenceTransformer
    sbert_model = SentenceTransformer("all-MiniLM-L6-v2")
    USE_SBERT = True
    print("[QA Engine] Using Sentence-BERT for semantic matching.")
except Exception:
    print("[QA Engine] sentence-transformers not available. Using TF-IDF fallback.")


# ── TF-IDF Vector Helpers ───────────────────────────────────────────────────────

def build_tfidf_vectors(documents: list):
    """
    Build TF-IDF vectors for a list of text documents (sentences).
    Returns (vocabulary, tfidf_matrix) where matrix is list of dicts.
    """
    # Step 1: Tokenize all documents
    tokenized = []
    for doc in documents:
        tokens = [
            w.lower() for w in word_tokenize(doc)
            if w.isalpha() and w.lower() not in STOP_WORDS
        ]
        tokenized.append(tokens)

    # Step 2: Build vocabulary
    vocab = set()
    for tokens in tokenized:
        vocab.update(tokens)
    vocab = list(vocab)
    vocab_index = {w: i for i, w in enumerate(vocab)}

    N = len(documents)

    # Step 3: Compute TF for each document
    tf_list = []
    for tokens in tokenized:
        tf = defaultdict(float)
        total = len(tokens) if tokens else 1
        for token in tokens:
            tf[token] += 1 / total
        tf_list.append(tf)

    # Step 4: Compute IDF
    df = defaultdict(int)
    for tokens in tokenized:
        for token in set(tokens):
            df[token] += 1

    idf = {w: math.log((N + 1) / (df[w] + 1)) for w in vocab}

    # Step 5: Compute TF-IDF vector for each document as numpy array
    vectors = []
    for tf in tf_list:
        vec = np.zeros(len(vocab))
        for word, tf_val in tf.items():
            if word in vocab_index:
                vec[vocab_index[word]] = tf_val * idf[word]
        vectors.append(vec)

    return vocab, vectors


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Compute cosine similarity between two vectors"""
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


# ── Index Builder ───────────────────────────────────────────────────────────────

def build_index(text: str):
    """
    Pre-build the sentence index from paper text.
    Returns index dict used by answer_question().
    """
    sentences = [s.strip() for s in sent_tokenize(text) if len(s.split()) > 4]

    if USE_SBERT and sbert_model:
        embeddings = sbert_model.encode(sentences, show_progress_bar=False)
        return {
            "sentences": sentences,
            "embeddings": embeddings,
            "mode": "sbert"
        }
    else:
        _, vectors = build_tfidf_vectors(sentences)
        return {
            "sentences": sentences,
            "vectors": vectors,
            "mode": "tfidf"
        }


# ── Intent Detection ────────────────────────────────────────────────────────────

INTENT_KEYWORDS = {
    "objective": ["objective", "goal", "aim", "purpose", "research goal", "this paper"],
    "dataset": ["dataset", "data", "corpus", "benchmark", "training data", "test data", "evaluation"],
    "methodology": ["method", "methodology", "approach", "algorithm", "technique", "model", "proposed"],
    "results": ["result", "performance", "accuracy", "score", "experiment", "evaluation", "achieved"],
    "conclusion": ["conclusion", "conclude", "summary", "finding", "contribution"],
    "limitation": ["limitation", "weakness", "drawback", "constraint", "future", "cannot"],
    "future": ["future", "future work", "scope", "plan", "extend", "improve"],
}


def detect_intent(question: str) -> str:
    """Detect the intent of the question"""
    q_lower = question.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            return intent
    return "general"


def get_intent_context(intent: str, sentences: list, ranked: list) -> str:
    """
    Boost sentences that match the detected intent.
    """
    boost_words = INTENT_KEYWORDS.get(intent, [])
    boosted = []
    for score, sent in ranked:
        bonus = sum(1 for w in boost_words if w in sent.lower()) * 0.3
        boosted.append((score + bonus, sent))
    boosted.sort(reverse=True)
    return boosted


# ── Main Q&A Function ──────────────────────────────────────────────────────────

def answer_question(text: str, question: str, top_k: int = 5) -> str:
    """
    Answer a question about the provided text using semantic search.

    Steps:
    1. Split text into sentences
    2. Find semantically similar sentences to the question
    3. Return the top matching context as the answer
    """
    sentences = [s.strip() for s in sent_tokenize(text) if len(s.split()) > 4]

    if not sentences:
        return "I couldn't find enough content in this paper to answer your question."

    intent = detect_intent(question)
    ranked_pairs = []
    question_lower = question.lower()

    if "objective" in question_lower or "aim" in question_lower:
        question += " purpose goal motivation"

    elif "novelty" in question_lower or "new" in question_lower:
        question += " contribution proposed method improvement advantage"

    elif "method" in question_lower or "approach" in question_lower:
        question += " methodology technique model framework"

    elif "result" in question_lower or "performance" in question_lower:
        question += " outcomes findings accuracy evaluation"

    elif "future" in question_lower:
        question += " future work limitations improvements"

    elif "problem" in question_lower:
        question += " issue challenge research problem motivation"

    # ── Strategy 1: SBERT (best quality) ──────────────────────────────────────
    if USE_SBERT and sbert_model:
        question_emb = sbert_model.encode([question], show_progress_bar=False)[0]
        sentence_embs = sbert_model.encode(sentences, show_progress_bar=False)
        similarities = [cosine_similarity(question_emb, se) for se in sentence_embs]
        ranked_pairs = [(similarities[i], sentences[i]) for i in range(len(sentences))]

    # ── Strategy 2: TF-IDF (fallback) ─────────────────────────────────────────
    else:
        all_docs = sentences + [question]
        _, vectors = build_tfidf_vectors(all_docs)
        q_vec = vectors[-1]
        sent_vecs = vectors[:-1]
        similarities = [cosine_similarity(q_vec, sv) for sv in sent_vecs]
        ranked_pairs = [(similarities[i], sentences[i]) for i in range(len(sentences))]

    # Apply intent boosting
    ranked_pairs = get_intent_context(intent, sentences, ranked_pairs)

    # Sort by score descending
    ranked_pairs.sort(reverse=True)

    # Select top_k sentences
    top_sentences = [sent for score, sent in ranked_pairs[:top_k] if score > 0.05]

    if not top_sentences:
        return (
            "I could not find a direct answer to your question in this paper. "
            "Try rephrasing or asking about the abstract, methodology, or results."
        )

    # Build a coherent response
    response = build_response(question, intent, top_sentences)
    return response


def build_response(question: str, intent: str, sentences: list) -> str:
    """
    Build a readable answer from retrieved sentences.
    """
    intro_map = {
        "objective": "Based on the paper, the main objective is:\n\n",
        "dataset": "Regarding the dataset used in this paper:\n\n",
        "methodology": "The methodology described in this paper:\n\n",
        "results": "Here are the key results from the paper:\n\n",
        "conclusion": "The paper concludes that:\n\n",
        "limitation": "The limitations mentioned in this paper:\n\n",
        "future": "Future work discussed in the paper:\n\n",
        "general": "Based on the paper content:\n\n",
    }

    intro = intro_map.get(intent, "Based on the paper:\n\n")

    # Join top sentences into a readable paragraph
    answer_body = " ".join(sentences[:3])  # Use top 3 for readability

    # Add additional context if available
    extra = ""
    if len(sentences) > 3:
        extra = "\n\nAdditional context: " + " ".join(sentences[3:5])

    return intro + answer_body + extra
