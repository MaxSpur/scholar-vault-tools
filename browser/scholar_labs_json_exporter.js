(() => {
  "use strict";

  const schemaVersion = "0.2";

  const clean = (value) =>
    (value || "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();

  const text = (node) => clean(node ? node.textContent || "" : "");

  const attr = (node, name) => (node ? node.getAttribute(name) || "" : "");

  const absoluteUrl = (href) => {
    try {
      return href ? new URL(href, window.location.href).toString() : "";
    } catch {
      return "";
    }
  };

  const slugify = (value) =>
    clean(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 80) || "scholar-labs";

  const parseCount = (label) => {
    const match = clean(label).match(/\b(\d+)\b/);
    return match ? Number.parseInt(match[1], 10) : undefined;
  };

  const classifyLink = (label, url) => {
    const lowerLabel = clean(label).toLowerCase();
    const lowerUrl = clean(url).toLowerCase();

    if (lowerLabel.includes("cited by")) return "cited_by";
    if (lowerLabel.includes("version")) return "all_versions";
    if (lowerLabel.includes("related")) return "related";
    if (lowerLabel.includes("cached")) return "cached";
    if (lowerLabel.includes("view as html")) return "cached_html";
    if (lowerLabel.includes("full view")) return "full_view";
    if (lowerLabel.includes("pdf") || lowerUrl.includes(".pdf")) return "pdf";
    if (lowerLabel.includes("html")) return "html";

    return "html";
  };

  const getFirstNonemptyPrompt = () => {
    const promptCandidates = Array.from(document.querySelectorAll(".gs_as_np_tq"))
      .map((node) => clean(node.innerText || node.textContent || ""))
      .filter((value) => value.length > 20);

    if (promptCandidates.length > 0) {
      return promptCandidates[0];
    }

    const textareaValue = clean(document.querySelector("textarea")?.value || "");
    if (textareaValue.length > 20) return textareaValue;

    const visibleInputValue = clean(
      Array.from(document.querySelectorAll("input"))
        .map((input) => input.value || input.getAttribute("value") || "")
        .find((value) => clean(value).length > 20) || ""
    );
    if (visibleInputValue.length > 20) return visibleInputValue;

    return "";
  };

  const getResultCards = () => {
    return Array.from(document.querySelectorAll("div.gs_r[data-cid], div.gs_or[data-cid]"))
      .filter((card) => {
        const cid = attr(card, "data-cid");
        if (!cid || cid === "gs_citd") return false;

        const title = text(card.querySelector("h3.gs_rt, h3 a, h3"));
        if (!title) return false;

        const cardText = text(card);
        return cardText.length > 80;
      });
  };

  const extractSummary = (card) => {
    const summaryContainer = card.querySelector(".gs_rs");
    if (!summaryContainer) return "";

    const clone = summaryContainer.cloneNode(true);

    clone.querySelectorAll("ul, ol, li").forEach((node) => node.remove());

    return clean(clone.innerText || clone.textContent || "");
  };

  const extractRationalePoints = (card) => {
    const points = [];

    const listItems = Array.from(
      card.querySelectorAll(".gs_rs li, .gs_rs [role='listitem']")
    );

    for (const li of listItems) {
      const value = clean(li.innerText || li.textContent || "");
      if (!value || value.length < 10) continue;

      const split = value.match(/^([^:]{1,100}):\s*(.+)$/);

      if (split) {
        points.push({
          label: clean(split[1]),
          text: clean(split[2]),
        });
      } else {
        points.push({
          label: "",
          text: value,
        });
      }
    }

    return points;
  };

  const parseMetadataLine = (metadataText) => {
    const line = clean(metadataText);

    const yearMatch = line.match(/\b(19|20)\d{2}\b/);
    const year = yearMatch ? Number.parseInt(yearMatch[0], 10) : null;

    // Google Scholar format is usually:
    // Authors - Venue, Year - Host
    const parts = line.split(/\s+-\s+/).map(clean).filter(Boolean);

    const authorsPreview = parts[0] || line || null;
    const venuePreview = parts.length >= 2 ? parts[1] : null;
    const publisherOrHost = parts.length >= 3 ? parts.slice(2).join(" - ") : null;

    return {
      authors_preview: authorsPreview,
      year,
      venue_preview: venuePreview,
      publisher_or_host: publisherOrHost,
    };
  };

  const extractLinks = (card, titleLink) => {
    const links = [];
    const seen = new Set();

    const pushLink = (label, url, kindOverride = null) => {
      const cleanUrl = absoluteUrl(url);
      const cleanLabel = clean(label);

      if (!cleanUrl) return;
      if (cleanUrl.startsWith("javascript:")) return;

      const key = `${cleanLabel}|${cleanUrl}`;
      if (seen.has(key)) return;
      seen.add(key);

      const kind = kindOverride || classifyLink(cleanLabel, cleanUrl);
      const count = parseCount(cleanLabel);

      const item = {
        label: cleanLabel || kind || "link",
        url: cleanUrl,
        kind,
      };

      if (count !== undefined && (kind === "cited_by" || kind === "all_versions")) {
        item.count = count;
      }

      links.push(item);
    };

    if (titleLink) {
      pushLink("publication", attr(titleLink, "href"), "publication");
    }

    // PDF / HTML links shown on the side of Scholar results.
    card.querySelectorAll(".gs_ggs a, .gs_ggsd a, .gs_or_ggsm a").forEach((a) => {
      const label = text(a) || attr(a, "aria-label") || "file";
      pushLink(label, attr(a, "href"));
    });

    // Action links such as Cited by, Related articles, All versions, Full View.
    card.querySelectorAll(".gs_fl a").forEach((a) => {
      const label = text(a) || attr(a, "aria-label") || "link";
      pushLink(label, attr(a, "href"));
    });

    // Fallback: collect any meaningful non-title links not already captured.
    card.querySelectorAll("a").forEach((a) => {
      const label = text(a) || attr(a, "aria-label") || "";
      const href = attr(a, "href");

      if (!href) return;
      if (a === titleLink) return;
      if (href.startsWith("javascript:")) return;
      if (!label && !href.toLowerCase().includes(".pdf")) return;

      const lowerLabel = label.toLowerCase();
      if (lowerLabel === "save" || lowerLabel === "cite") return;

      pushLink(label || "link", href);
    });

    return links;
  };

  const prompt = getFirstNonemptyPrompt();

  const cards = getResultCards();
  const results = [];

  for (const card of cards) {
    const cid = attr(card, "data-cid");

    const titleHeading = card.querySelector("h3.gs_rt, h3");
    const titleLink = titleHeading?.querySelector("a") || card.querySelector("h3 a");
    const title = text(titleHeading || titleLink);

    if (!cid || !title) continue;

    const metadataNode = card.querySelector(".gs_a");
    const metadata = parseMetadataLine(text(metadataNode));

    const links = extractLinks(card, titleLink);

    // Prefer host from metadata line, but fall back to publication URL host.
    let publisherOrHost = metadata.publisher_or_host;
    if (!publisherOrHost && titleLink) {
      try {
        publisherOrHost = new URL(absoluteUrl(attr(titleLink, "href"))).hostname;
      } catch {
        publisherOrHost = null;
      }
    }

    results.push({
      rank: results.length + 1,
      scholar_cid: cid,
      title,
      authors_preview: metadata.authors_preview,
      year: metadata.year,
      venue_preview: metadata.venue_preview,
      publisher_or_host: publisherOrHost,
      summary: extractSummary(card) || null,
      rationale_points: extractRationalePoints(card),
      links,
    });
  }

  if (!prompt || results.length === 0) {
    console.warn("[Scholar Labs Export] Failed to extract expected data.", {
      prompt,
      resultCount: results.length,
      bodyClass: document.body.className,
      gsPromptCount: document.querySelectorAll(".gs_as_np_tq").length,
      gsResultCount: document.querySelectorAll("div.gs_r[data-cid], div.gs_or[data-cid]").length,
      title: document.title,
      url: window.location.href,
    });

    alert(
      "Scholar Labs exporter found no results or no prompt.\n\n" +
      "Make sure you are on a completed Scholar Labs results page, not the Scholar home page.\n\n" +
      "Open the browser console for diagnostic counts."
    );

    return;
  }

  const payload = {
    schema_version: schemaVersion,
    source: "google_scholar_labs",
    exported_at: new Date().toISOString(),
    prompt,
    results,
  };

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = `scholar-labs-${slugify(prompt)}-${timestamp}.json`;

  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json;charset=utf-8",
  });

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  URL.revokeObjectURL(url);

  console.log(`[Scholar Labs Export] Exported ${results.length} results to ${filename}`, payload);
})();