(() => {
  const schemaVersion = "0.2";

  const text = (node) => (node ? node.textContent.replace(/\s+/g, " ").trim() : "");
  const attr = (node, name) => (node ? node.getAttribute(name) || "" : "");
  const absoluteUrl = (href) => {
    try {
      return href ? new URL(href, window.location.href).toString() : "";
    } catch {
      return "";
    }
  };

  const prompt =
    text(document.querySelector("textarea")) ||
    text(document.querySelector("input[type='search']")) ||
    text(document.querySelector("input[aria-label*='prompt' i]")) ||
    text(document.querySelector("main h1")) ||
    document.title;

  const likelyCards = Array.from(
    document.querySelectorAll("article, main section, main li, main > div")
  ).filter((node) => {
    const titleNode = node.querySelector("h1, h2, h3, h4, a");
    const bodyText = text(node);
    return titleNode && bodyText.length > 80;
  });

  const seenTitles = new Set();
  const results = [];

  likelyCards.forEach((card, index) => {
    const titleNode =
      card.querySelector("h1, h2, h3, h4") ||
      Array.from(card.querySelectorAll("a")).find((link) => text(link).length > 20);
    const title = text(titleNode);
    if (!title || seenTitles.has(title)) {
      return;
    }
    seenTitles.add(title);

    const cardText = text(card);
    const yearMatch = cardText.match(/\b(19|20)\d{2}\b/);
    const summaryNode =
      Array.from(card.querySelectorAll("p, div")).find((node) => {
        const value = text(node);
        return value.length > 60 && value !== cardText && value !== title;
      }) || null;

    const rationalePoints = Array.from(card.querySelectorAll("li, [role='listitem'], button"))
      .map((node) => text(node))
      .filter((value) => value.length > 10)
      .slice(0, 8)
      .map((value) => {
        const parts = value.split(/:\s+/, 2);
        if (parts.length === 2 && parts[0].length < 40) {
          return { label: parts[0], text: parts[1] };
        }
        return { label: "", text: value };
      });

    const links = Array.from(card.querySelectorAll("a"))
      .map((link) => {
        const label = text(link) || attr(link, "aria-label") || "link";
        const url = absoluteUrl(attr(link, "href"));
        const countMatch = label.match(/\b(\d+)\b/);
        const lower = label.toLowerCase();
        let kind = "html";
        if (url.toLowerCase().endsWith(".pdf") || lower.includes("pdf")) {
          kind = "pdf";
        } else if (lower.includes("cited by")) {
          kind = "cited_by";
        } else if (lower.includes("version")) {
          kind = "all_versions";
        }
        return {
          label,
          url,
          kind,
          ...(countMatch ? { count: Number.parseInt(countMatch[1], 10) } : {}),
        };
      })
      .filter((item) => item.url);

    const scholarCid =
      attr(card, "data-cid") ||
      attr(card, "data-result-id") ||
      attr(card.querySelector("[data-cid], [data-result-id]"), "data-cid") ||
      attr(card.querySelector("[data-cid], [data-result-id]"), "data-result-id") ||
      "";

    const authorSource =
      Array.from(card.querySelectorAll("p, div, span"))
        .map((node) => text(node))
        .find((value) => /\b(19|20)\d{2}\b/.test(value) && /,| and |&/.test(value)) || "";

    const metadataLine =
      Array.from(card.querySelectorAll("p, div, span"))
        .map((node) => text(node))
        .find((value) => value !== authorSource && /\b(19|20)\d{2}\b/.test(value)) || "";

    results.push({
      rank: index + 1,
      scholar_cid: scholarCid || null,
      title,
      authors_preview: authorSource || null,
      year: yearMatch ? Number.parseInt(yearMatch[0], 10) : null,
      venue_preview: metadataLine || null,
      publisher_or_host: card.hostname || null,
      summary: text(summaryNode) || null,
      rationale_points: rationalePoints,
      links,
    });
  });

  const payload = {
    schema_version: schemaVersion,
    source: "google_scholar_labs",
    exported_at: new Date().toISOString(),
    prompt,
    results,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const promptSlug = prompt.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "scholar-labs";
  const filename = `scholar-labs-${promptSlug}-${timestamp}.json`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
})();
