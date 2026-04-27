import { auth, db } from "./firebase-config.js";
import {
  ref,
  push,
  set,
  get
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-database.js";

import {
  onAuthStateChanged
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
/**
 * PaperMind — Frontend Script
 * Handles all UI interactions, API calls, and dynamic rendering.
 */

// ── Config ────────────────────────────────────────────────────────────────────
const API_BASE = "https://papermind-ai-backend-d6pz.onrender.com";
// ── State ─────────────────────────────────────────────────────────────────────
let uploadedPapers = [];          // Array of { paper_id, filename, word_count }
let activePaperId = null;         // Currently selected paper
let topicChart = null;            // Chart.js instance for topic chart
let pdfDoc = null;                // PDF.js document object
let pdfCurrentPage = 1;

// ── DOM Helpers ───────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function show(el) { el?.classList.remove("hidden"); }
function hide(el) { el?.classList.add("hidden"); }

function showLoading(text = "Processing...") {
  $("#loading-text").textContent = text;
  show($("#loading-overlay"));
}
function hideLoading() { hide($("#loading-overlay")); }

function showToast(msg, duration = 3000) {
  const toast = $("#toast");
  toast.textContent = msg;
  show(toast);
  setTimeout(() => hide(toast), duration);
}


// ── Navigation ────────────────────────────────────────────────────────────────
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    const panelName = btn.dataset.panel;

    // Update nav active state
    $$(".nav-item").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    // Show correct panel
    $$(".panel").forEach(p => p.classList.remove("active"));
    $(`#panel-${panelName}`)?.classList.add("active");

    // Update topbar title
    $("#topbar-title").textContent = btn.textContent.trim();
  });
});

// Hamburger for mobile sidebar
$("#hamburger").addEventListener("click", () => {
  $("#sidebar").classList.toggle("open");
});


// ── PDF.js Setup ──────────────────────────────────────────────────────────────
if (typeof pdfjsLib !== "undefined") {
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
}

async function renderPDFPage(pageNum) {
  if (!pdfDoc) return;
  const page = await pdfDoc.getPage(pageNum);
  const canvas = $("#pdf-canvas");
  const ctx = canvas.getContext("2d");

  const viewport = page.getViewport({ scale: 1.2 });
  canvas.height = viewport.height;
  canvas.width = viewport.width;

  await page.render({ canvasContext: ctx, viewport }).promise;
  $("#pdf-page-info").textContent = `Page ${pdfCurrentPage} of ${pdfDoc.numPages}`;
}

$("#pdf-prev").addEventListener("click", () => {
  if (pdfCurrentPage > 1) {
    pdfCurrentPage--;
    renderPDFPage(pdfCurrentPage);
  }
});
$("#pdf-next").addEventListener("click", () => {
  if (pdfDoc && pdfCurrentPage < pdfDoc.numPages) {
    pdfCurrentPage++;
    renderPDFPage(pdfCurrentPage);
  }
});


// ── Upload Logic ──────────────────────────────────────────────────────────────
const dropZone = $("#drop-zone");
const fileInput = $("#file-input");

// Drag & Drop events
dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragging");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragging");
  handleFiles(e.dataTransfer.files);
});

fileInput.addEventListener("change", () => handleFiles(fileInput.files));

async function handleFiles(files) {
  if (!files || files.length === 0) return;

  const formData = new FormData();
  let hasValidFiles = false;
  let firstFile = null;

  for (const file of files) {
    if (file.type === "application/pdf" || file.name.endsWith(".pdf")) {
      formData.append("files", file);
      hasValidFiles = true;
      if (!firstFile) firstFile = file;
    } else {
      showToast(`Skipped: ${file.name} (not a PDF)`);
    }
  }

  if (!hasValidFiles) {
    showToast("Please select PDF files only.");
    return;
  }

  // Show PDF preview using PDF.js
  if (firstFile && typeof pdfjsLib !== "undefined") {
    const fileURL = URL.createObjectURL(firstFile);
    pdfDoc = await pdfjsLib.getDocument(fileURL).promise;
    pdfCurrentPage = 1;
    show($("#pdf-preview-area"));
    renderPDFPage(1);
  }

  showLoading("Uploading & processing PDFs...");

  try {
    const response = await fetch(`${API_BASE}/api/upload`, {      method: "POST",
      body: formData,
    });
    const data = await response.json();
    hideLoading();

    if (!data.papers) {
      showToast("Upload failed. Is the Flask server running?");
      return;
    }

    // Show upload results
    const statusContainer = $("#upload-status");
    show(statusContainer);

    data.papers.forEach(paper => {
      if (paper.error) {
        statusContainer.insertAdjacentHTML("beforeend", `
          <div class="upload-item error">
            <span class="upload-item-icon">✕</span>
            <div class="upload-item-info">
              <div class="upload-item-name">Error</div>
              <div class="upload-item-meta">${paper.error}</div>
            </div>
          </div>
        `);
      } else {
  // 1) save in frontend memory FIRST
  uploadedPapers.push(paper);
  activePaperId = paper.paper_id;

  // 2) instantly update UI
  addPaperToSidebar(paper);
  addPaperToSelects(paper);

  // 3) upload success card
  statusContainer.insertAdjacentHTML("beforeend", `
    <div class="upload-item success">
      <span class="upload-item-icon">✓</span>
      <div class="upload-item-info">
        <div class="upload-item-name">${paper.filename}</div>
        <div class="upload-item-meta">
          ${paper.word_count.toLocaleString()} words · Sections: ${paper.sections_found.join(", ")}
        </div>
      </div>
    </div>
  `);

  // 4) save in Firebase (optional, won’t break UI)
  const user = auth.currentUser;

  if (user) {
    const paperRef = push(ref(db, `users/${user.uid}/papers`));

    set(paperRef, {
      filename: paper.filename,
      paper_id: paper.paper_id,
      word_count: paper.word_count,
      uploadedAt: new Date().toISOString()
    }).catch(err => console.error("Firebase save error:", err));
  }
}
    });

    showToast(`${uploadedPapers.length} paper(s) ready!`);

  } catch (err) {
    hideLoading();
    showToast("Cannot connect to backend. Start Flask with: python app.py");
    console.error(err);
  }
}

function addPaperToSidebar(paper) {
  const list = $("#paper-list");
  const emptyHint = list.querySelector(".empty-hint");
  if (emptyHint) emptyHint.remove();

  const chip = document.createElement("div");
  chip.className = "paper-chip";
  chip.dataset.id = paper.paper_id;
  chip.innerHTML = `
    <div class="paper-chip-dot"></div>
    <div class="paper-chip-name" title="${paper.filename}">${paper.filename}</div>
  `;
  chip.addEventListener("click", () => {
    $$(".paper-chip").forEach(c => c.classList.remove("selected"));
    chip.classList.add("selected");
    activePaperId = paper.paper_id;
    syncSelects(paper.paper_id);
  });
  list.appendChild(chip);
}

function addPaperToSelects(paper) {
  // Add to all <select> dropdowns
  const option = `<option value="${paper.paper_id}">${paper.filename}</option>`;
  [
    "#chat-paper-select", "#summary-paper-select", "#simplify-paper-select",
    "#keywords-paper-select", "#sections-paper-select", "#w2v-paper-select"
  ].forEach(sel => {
    const el = $(sel);
    if (el) el.insertAdjacentHTML("beforeend", option);
  });

  // Add to compare checkboxes
  const checkboxGroup = $("#compare-paper-checkboxes");
  const empty = checkboxGroup.querySelector(".empty-hint");
  if (empty) empty.remove();

  checkboxGroup.insertAdjacentHTML("beforeend", `
    <label class="paper-checkbox-label">
      <input type="checkbox" value="${paper.paper_id}" />
      ${paper.filename}
    </label>
  `);
}

function syncSelects(paperId) {
  [
    "#chat-paper-select", "#summary-paper-select", "#simplify-paper-select",
    "#keywords-paper-select", "#sections-paper-select", "#w2v-paper-select"
  ].forEach(sel => {
    const el = $(sel);
    if (el) el.value = paperId;
  });
}


// ── Summarize ─────────────────────────────────────────────────────────────────
let summaryMode = "short";

$$(".mode-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".mode-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    summaryMode = btn.dataset.mode;
  });
});

$("#btn-summarize").addEventListener("click", async () => {
  const paperId = $("#summary-paper-select").value;
  if (!paperId) return showToast("Please select a paper first.");

  showLoading("Generating summary...");
  try {
    const res = await fetch(`${API_BASE}/api/summarize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, mode: summaryMode }),
    });
    const data = await res.json();
    hideLoading();

    if (data.error) return showToast(data.error);

    const outputEl = $("#summary-output");
    const contentEl = $("#summary-content");
    show(outputEl);

    if (summaryMode === "bullets" && Array.isArray(data.summary)) {
      contentEl.innerHTML = "<ul>" + data.summary.map(p => `<li>${p}</li>`).join("") + "</ul>";
    } else {
      contentEl.textContent = data.summary;
    }

  } catch (err) {
    hideLoading();
    showToast("Request failed. Is the backend running?");
  }
});


// ── Simplify ──────────────────────────────────────────────────────────────────
$("#btn-simplify").addEventListener("click", async () => {
  const paperId = $("#simplify-paper-select").value;
  const level = document.querySelector("input[name='simplify-level']:checked")?.value || "beginner";
  if (!paperId) return showToast("Please select a paper first.");

  showLoading("Simplifying text...");
  try {
    const res = await fetch(`${API_BASE}/api/simplify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, level }),
    });
    const data = await res.json();
    hideLoading();

    if (data.error) return showToast(data.error);

    show($("#simplify-output"));
    $("#simplify-content").textContent = data.simplified;

  } catch (err) {
    hideLoading();
    showToast("Request failed.");
  }
});


// ── Keywords ──────────────────────────────────────────────────────────────────
const KEYWORD_COLORS = [
  ["#6366f1","rgba(99,102,241,0.15)"],
  ["#14b8a6","rgba(20,184,166,0.15)"],
  ["#ec4899","rgba(236,72,153,0.15)"],
  ["#f59e0b","rgba(245,158,11,0.15)"],
  ["#8b5cf6","rgba(139,92,246,0.15)"],
  ["#06b6d4","rgba(6,182,212,0.15)"],
];

$("#btn-keywords").addEventListener("click", async () => {
  const paperId = $("#keywords-paper-select").value;
  if (!paperId) return showToast("Please select a paper.");

  showLoading("Extracting keywords...");
  try {
    const res = await fetch(`${API_BASE}/api/keywords`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId }),
    });
    const data = await res.json();
    hideLoading();

    if (data.error) return showToast(data.error);

    const cloud = $("#keywords-cloud");
    cloud.innerHTML = "";
    data.keywords.forEach((kw, i) => {
      const [color, bg] = KEYWORD_COLORS[i % KEYWORD_COLORS.length];
      const tag = document.createElement("span");
      tag.className = "keyword-tag";
      tag.textContent = kw;
      tag.style.color = color;
      tag.style.background = bg;
      tag.style.border = `1px solid ${color}40`;
      tag.style.animationDelay = `${i * 0.06}s`;
      cloud.appendChild(tag);
    });

    show($("#keywords-output"));

  } catch (err) {
    hideLoading();
    showToast("Request failed.");
  }
});


// ── Sections ──────────────────────────────────────────────────────────────────
const SECTION_ICONS = {
  "Abstract": "◎",
  "Introduction": "→",
  "Literature Review": "≡",
  "Methodology": "⬡",
  "Results": "↑",
  "Discussion": "◈",
  "Conclusion": "✦",
  "Future Scope": "◉",
  "References": "#",
  "Content": "□",
};

$("#btn-sections").addEventListener("click", async () => {
  const paperId = $("#sections-paper-select").value;
  if (!paperId) return showToast("Please select a paper.");

  showLoading("Detecting sections...");
  try {
    const res = await fetch(`${API_BASE}/api/sections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId }),
    });
    const data = await res.json();
    hideLoading();

    if (data.error) return showToast(data.error);

    const grid = $("#sections-output");
    grid.innerHTML = "";

    Object.entries(data.sections).forEach(([name, text]) => {
      const icon = SECTION_ICONS[name] || "□";
      const card = document.createElement("div");
      card.className = "section-card";
      card.innerHTML = `
        <div class="section-card-title">${icon} ${name}</div>
        <div class="section-card-text">${text}</div>
      `;
      grid.appendChild(card);
    });

    show(grid);

  } catch (err) {
    hideLoading();
    showToast("Request failed.");
  }
});


// ── Compare ───────────────────────────────────────────────────────────────────
$("#btn-compare").addEventListener("click", async () => {
  const checkboxes = $$("#compare-paper-checkboxes input:checked");
  const paperIds = Array.from(checkboxes).map(cb => cb.value);

  if (paperIds.length < 2) return showToast("Select at least 2 papers to compare.");

  showLoading("Comparing papers...");
  try {
    const res = await fetch(`${API_BASE}/api/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_ids: paperIds }),
    });
    const data = await res.json();
    hideLoading();

    if (data.error) return showToast(data.error);

    const grid = $("#compare-output");
    grid.innerHTML = "";

    data.comparison.forEach((paper, idx) => {
      const card = document.createElement("div");
      card.className = "compare-card";

      const techTagsHTML = paper.technologies.map(t =>
        `<span class="tech-tag">${t}</span>`
      ).join("");

      card.innerHTML = `
        <div class="compare-card-header">
          <div class="compare-card-num">${idx + 1}</div>
          <div class="compare-card-title">${paper.title}</div>
        </div>
        <div class="compare-field">
          <div class="compare-field-label">Objective</div>
          <div class="compare-field-value">${paper.objective || "Not found"}</div>
        </div>
        <div class="compare-field">
          <div class="compare-field-label">Methodology</div>
          <div class="compare-field-value">${paper.methodology || "Not found"}</div>
        </div>
        <div class="compare-field">
          <div class="compare-field-label">Results</div>
          <div class="compare-field-value">${paper.results || "Not found"}</div>
        </div>
        <div class="compare-field">
          <div class="compare-field-label">Conclusion</div>
          <div class="compare-field-value">${paper.conclusion || "Not found"}</div>
        </div>
        <div class="compare-field">
          <div class="compare-field-label">Limitations</div>
          <div class="compare-field-value">${paper.limitations || "Not explicitly mentioned"}</div>
        </div>
        <div class="compare-field">
          <div class="compare-field-label">Technologies</div>
          <div class="tech-tags">${techTagsHTML || '<span style="color:var(--text-3)">None detected</span>'}</div>
        </div>
        <div class="compare-field">
          <div class="compare-field-label">Word Count</div>
          <div class="compare-field-value">${paper.word_count?.toLocaleString() || "—"}</div>
        </div>
      `;
      grid.appendChild(card);
    });

    show(grid);

  } catch (err) {
    hideLoading();
    showToast("Request failed.");
  }
});


// ── Topic Visualization ───────────────────────────────────────────────────────
$("#btn-visualize").addEventListener("click", async () => {
  if (uploadedPapers.length === 0) return showToast("Upload papers first.");

  showLoading("Generating topic map...");
  try {
    const res = await fetch(`${API_BASE}/api/visualize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_ids: uploadedPapers.map(p => p.paper_id) }),
    });
    const data = await res.json();
    hideLoading();

    if (data.error) return showToast(data.error);
    if (!data.chart_data?.points) return showToast("Not enough data for visualization.");

    renderTopicChart(data.chart_data);
    show($("#visualize-output"));

  } catch (err) {
    hideLoading();
    showToast("Request failed.");
  }
});

function renderTopicChart(chartData) {
  const { points, paper_ids, colors } = chartData;

  // Group points by paper
  const datasets = paper_ids.map(pid => ({
    label: pid,
    data: points.filter(p => p.label === pid).map(p => ({ x: p.x, y: p.y, hover: p.hover })),
    backgroundColor: colors[pid] + "99",
    borderColor: colors[pid],
    borderWidth: 1,
    pointRadius: 5,
    pointHoverRadius: 8,
  }));

  // Destroy existing chart if any
  if (topicChart) topicChart.destroy();

  const ctx = $("#topic-chart").getContext("2d");
  topicChart = new Chart(ctx, {
    type: "scatter",
    data: { datasets },
    options: {
      responsive: true,
      plugins: {
        legend: {
          labels: { color: "#94a3b8", font: { family: "DM Sans", size: 12 } }
        },
        tooltip: {
          callbacks: {
            label: (context) => {
              const raw = context.raw;
              return `${context.dataset.label}: ${raw.hover || ""}`;
            }
          }
        }
      },
      scales: {
        x: {
          ticks: { color: "#475569" },
          grid: { color: "rgba(255,255,255,0.04)" },
          title: { display: true, text: "PCA Component 1", color: "#94a3b8" }
        },
        y: {
          ticks: { color: "#475569" },
          grid: { color: "rgba(255,255,255,0.04)" },
          title: { display: true, text: "PCA Component 2", color: "#94a3b8" }
        }
      },
      backgroundColor: "transparent",
    }
  });

  if (chartData.explained_variance) {
    const [v1, v2] = chartData.explained_variance;
    $("#pca-variance-info").textContent =
      `PCA explains ${((v1 + v2) * 100).toFixed(1)}% of variance (PC1: ${(v1*100).toFixed(1)}%, PC2: ${(v2*100).toFixed(1)}%)`;
  }
}


// ── Word2Vec / Concept Explorer ───────────────────────────────────────────────
$("#btn-w2v").addEventListener("click", async () => {
  const paperId = $("#w2v-paper-select").value;
  const term = $("#w2v-term").value.trim();
  if (!paperId) return showToast("Please select a paper.");
  if (!term) return showToast("Please enter a search term.");

  showLoading(`Exploring related concepts for "${term}"...`);
  try {
    const res = await fetch(`${API_BASE}/api/word2vec`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, term }),
    });
    const data = await res.json();
    hideLoading();

    if (data.error) return showToast(data.error);

    $("#w2v-query-display").textContent = data.query;
    const resultsEl = $("#w2v-results");
    resultsEl.innerHTML = "";

    data.related_terms.forEach((item, i) => {
      const scorePercent = Math.round(item.score * 100);
      const div = document.createElement("div");
      div.className = "w2v-item";
      div.style.animationDelay = `${i * 0.07}s`;
      div.innerHTML = `
        <span class="w2v-rank">${i + 1}</span>
        <span class="w2v-term">${item.term}</span>
        <div class="w2v-bar-bg">
          <div class="w2v-bar-fill" style="width:${Math.max(scorePercent, 5)}%"></div>
        </div>
        <span class="w2v-score">${item.score.toFixed(2)}</span>
      `;
      resultsEl.appendChild(div);
    });

    show($("#w2v-output"));

  } catch (err) {
    hideLoading();
    showToast("Request failed.");
  }
});

// Allow Enter key in word2vec input
$("#w2v-term").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#btn-w2v").click();
});


// ── Chat / Q&A ────────────────────────────────────────────────────────────────
window.setQuestion = function(btn) {
  const question = btn.textContent.trim();

  $("#chat-input").value = question;

  // directly ask immediately
  sendChatMessage();
};
// Send on Enter (Shift+Enter for newline)
$("#chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});
$("#btn-send").addEventListener("click", sendChatMessage);

function addChatBubble(text, role = "ai") {
  const messagesEl = $("#chat-messages");

  // Remove welcome screen on first message
  const welcome = messagesEl.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.innerHTML = `
    <div class="chat-avatar">${role === "user" ? "U" : "◎"}</div>
    <div class="chat-message-body">${text}</div>
  `;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function addTypingIndicator() {
  const messagesEl = $("#chat-messages");
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble ai";
  bubble.id = "typing-bubble";
  bubble.innerHTML = `
    <div class="chat-avatar">◎</div>
    <div class="chat-message-body">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTypingIndicator() {
  $("#typing-bubble")?.remove();
}

async function sendChatMessage() {
  if ($("#typing-bubble")) return;
  const paperId = $("#chat-paper-select").value;
  const question = $("#chat-input").value.trim();

  if (!paperId) return showToast("Please select a paper first.");
  if (!question) return;

  // Show user bubble
  addChatBubble(question, "user");
  $("#chat-input").value = "";
  addTypingIndicator();

  try {
    const res = await fetch(`${API_BASE}/api/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, question }),
    });
    const data = await res.json();

    removeTypingIndicator();

    if (data.error) {
      addChatBubble(`⚠ ${data.error}`, "ai");
    } else {
      // Format answer with line breaks preserved
      const formatted = data.answer.replace(/\n/g, "<br>");
      addChatBubble(formatted, "ai");
      const user = auth.currentUser;

try {
  const user = auth.currentUser;

  if (user) {
    const chatRef = push(ref(db, `users/${user.uid}/history/chat`));

    await set(chatRef, {
      paper_id: paperId,
      question,
      answer: data.answer,
      timestamp: new Date().toISOString()
    });
  }
} catch (firebaseErr) {
  console.error("Chat save failed:", firebaseErr);
}
    }

  } catch (err) {
    removeTypingIndicator();
    addChatBubble("Cannot connect to backend. Make sure Flask is running on port 5000.", "ai");
  }
}


// ── Export ────────────────────────────────────────────────────────────────────
$("#btn-export").addEventListener("click", async () => {
  const paperId = activePaperId ||
    (uploadedPapers.length > 0 ? uploadedPapers[0].paper_id : null);

  if (!paperId) return showToast("Please upload a paper first.");

  showLoading("Generating PDF report...");
  try {
    const res = await fetch(`${API_BASE}/api/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId }),
    });

    if (!res.ok) {
      hideLoading();
      const errData = await res.json();
      showToast(errData.error || "Export failed.");
      return;
    }

    // Trigger file download
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${paperId}_report.pdf`;
    a.click();
    URL.revokeObjectURL(url);
    hideLoading();
    showToast("Report downloaded!");

  } catch (err) {
    hideLoading();
    showToast("Export failed. Is the backend running?");
  }
});
onAuthStateChanged(auth, async (user) => {
  if (!user) return;

  const snapshot = await get(ref(db, `users/${user.uid}/papers`));

  if (snapshot.exists()) {
    const papers = snapshot.val();

    // Clear old UI before restoring
    uploadedPapers = [];
    document.querySelector("#paper-list").innerHTML = "";
    document.querySelector("#compare-paper-checkboxes").innerHTML = "";

    // Clear all selects
    [
      "#chat-paper-select",
      "#summary-paper-select",
      "#simplify-paper-select",
      "#keywords-paper-select",
      "#sections-paper-select",
      "#w2v-paper-select"
    ].forEach(sel => {
      const el = document.querySelector(sel);
      if (el) {
        el.innerHTML = `<option value="">— Select a paper —</option>`;
      }
    });

    Object.values(papers).forEach((paper) => {
      uploadedPapers.push(paper);
      addPaperToSidebar(paper);
      addPaperToSelects(paper);
      activePaperId = paper.paper_id;
    });

    console.log("Old papers restored");
  }
});
onAuthStateChanged(auth, async (user) => {
  if (!user) return;

  const snapshot = await get(ref(db, `users/${user.uid}/papers`));

  if (snapshot.exists()) {
    const papers = snapshot.val();

    uploadedPapers = [];
    document.querySelector("#paper-list").innerHTML = "";
    document.querySelector("#compare-paper-checkboxes").innerHTML = "";

    [
      "#chat-paper-select",
      "#summary-paper-select",
      "#simplify-paper-select",
      "#keywords-paper-select",
      "#sections-paper-select",
      "#w2v-paper-select"
    ].forEach(sel => {
      const el = document.querySelector(sel);
      if (el) {
        el.innerHTML = `<option value="">— Select a paper —</option>`;
      }
    });

    Object.values(papers).forEach((paper) => {
      uploadedPapers.push(paper);
      addPaperToSidebar(paper);
      addPaperToSelects(paper);
      activePaperId = paper.paper_id;
    });

    console.log("Old papers restored");
  }

  // ✅ restore old chats AFTER papers restored
  const chatSnapshot = await get(ref(db, `users/${user.uid}/history/chat`));

  if (chatSnapshot.exists()) {
    const chats = Object.values(chatSnapshot.val());

    const chatMessages = document.querySelector("#chat-messages");
    if (chatMessages) chatMessages.innerHTML = "";

    chats
      .filter(chat => chat.paper_id === activePaperId)
      .forEach(chat => {
        addChatBubble(chat.question, "user");
        addChatBubble(chat.answer, "ai");
      });

    console.log("Old chats restored");
  }
});
