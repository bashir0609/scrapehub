/**
 * Live Results - Card-Based Layout JavaScript
 * Handles filtering, pagination, search, and responsive behavior
 */

class LiveResults {
  constructor(jobId) {
    this.jobId = jobId;
    this.currentPage = 1;
    this.pageSize = 10;
    this.currentFilter = "all";
    this.searchQuery = "";
    this.results = [];
    this.filteredResults = [];
    this.autoRefreshEnabled = true;
    this.refreshInterval = null;

    console.log("LiveResults JS Loaded - Fixed Version");
    this.init();
  }

  init() {
    this.setupEventListeners();
    this.loadResults();
    this.startAutoRefresh();
  }

  setupEventListeners() {
    // Filter buttons
    document.querySelectorAll(".filter-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        this.handleFilterChange(e.target.dataset.filter);
      });
    });

    // Search input
    const searchInput = document.getElementById("resultsSearch");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        this.handleSearch(e.target.value);
      });
    }

    // Auto-refresh toggle
    const autoRefreshCheckbox = document.getElementById("autoRefresh");
    if (autoRefreshCheckbox) {
      autoRefreshCheckbox.addEventListener("change", (e) => {
        this.autoRefreshEnabled = e.target.checked;
        if (this.autoRefreshEnabled) {
          this.startAutoRefresh();
        } else {
          this.stopAutoRefresh();
        }
      });
    }

    // Pagination
    document.addEventListener("click", (e) => {
      if (e.target.classList.contains("pagination-btn")) {
        const page = parseInt(e.target.dataset.page);
        if (!isNaN(page)) {
          this.goToPage(page);
        }
      }

      // Details button (mobile/tablet)
      if (e.target.classList.contains("details-btn")) {
        this.toggleDetails(e.target.closest(".result-card"));
      }
    });
  }

  async loadResults() {
    try {
      // Calculate start index for server-side pagination
      const start = (this.currentPage - 1) * this.pageSize;

      // Build query parameters
      const params = new URLSearchParams({
        start: start,
        length: this.pageSize,
        search: this.searchQuery || "",
      });

      // Add filter parameter if not 'all'
      if (this.currentFilter !== "all") {
        params.append("filter", this.currentFilter);
      }

      const response = await fetch(
        `/jobs/api/${this.jobId}/results/?${params.toString()}`
      );
      const data = await response.json();

      // Store current page results
      this.results = data.data || [];
      this.totalRecords = data.recordsFiltered || 0;
      this.totalRecordsUnfiltered = data.recordsTotal || 0;

      this.renderResults();
      this.updateFilterCounts();
    } catch (error) {
      console.error("Error loading results:", error);
      this.showError("Failed to load results");
    }
  }

  renderResults() {
    const container = document.getElementById("resultsContainer");
    if (!container) return;

    // Results are already paginated from server
    if (this.results.length === 0) {
      container.innerHTML = this.renderEmptyState();
      this.renderPagination(); // Still render pagination to show "0 results"
      return;
    }

    container.innerHTML = this.results
      .map((result) => this.renderCard(result))
      .join("");
    this.renderPagination();
  }

  renderCard(result) {
    const statusClass = this.getStatusClass(result);
    const isMobile = window.innerWidth < 1024;

    return `
            <div class="result-card" data-url="${result.original_url}">
                <div class="status-dot status-${statusClass}"></div>
                
                <div class="card-content">
                    ${this.renderCardContent(result, isMobile)}
                </div>
                
                ${
                  isMobile ? '<button class="details-btn">Details</button>' : ""
                }
                
                ${this.renderCardDetails(result)}
            </div>
        `;
  }

  renderCardContent(result, isMobile) {
    if (isMobile) {
      // Mobile: Minimal info
      return `
                <div class="card-section">
                    <div class="card-url">
                        <span>${this.truncateUrl(
                          result.original_url,
                          30
                        )}</span>
                    </div>
                </div>
            `;
    } else {
      // Desktop: Full details
      return `
                <div class="card-section">
                    <div class="card-label">URL</div>
                    <div class="card-url">
                        <span>${result.original_url}</span>
                    </div>
                </div>
                
                <div class="card-section">
                    <div class="card-label">Homepage</div>
                    <div class="card-value">
                        ${this.renderHomepageStatus(result)}
                    </div>
                </div>
                
                <div class="card-section">
                    <div class="card-label">Ads.txt</div>
                    ${this.renderUrlLink(result.ads_txt && result.ads_txt.url)}
                    ${this.renderStatusBadge(result.ads_txt)}
                </div>
                
                <div class="card-section">
                    <div class="card-label">App-ads.txt</div>
                    ${this.renderUrlLink(result.app_ads_txt && result.app_ads_txt.url)}
                    ${this.renderStatusBadge(result.app_ads_txt)}
                </div>
            `;
    }
  }

  renderHomepageStatus(result) {
    if (result.error) {
      return `<span class="status-badge badge-error">
                <span class="badge-icon">✕</span> ${result.error}
            </span>`;
    }
    if (result.homepage_url) {
      return `<a href="${result.homepage_url}" target="_blank" style="color: #667eea; text-decoration: none;">
                ${result.homepage_url}
            </a>`;
    }
    return "-";
  }

  renderUrlLink(url) {
    if (!url) return '';
    return `
        <div style="font-size: 0.75rem; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px;">
            <a href="${url}" target="_blank" style="color: #64748b; text-decoration: none;">
                ${this.truncateUrl(url, 35)}
            </a>
        </div>
    `;
  }

  renderStatusBadge(data) {
    if (!data) {
      return '<span style="color: #94a3b8;">-</span>';
    }

    const isSuccess = data.status_code === 200;
    const badgeClass = isSuccess ? "badge-success" : "badge-error";
    const icon = isSuccess ? "✓" : "✕";
    const text = data.result_text || data.status_code;
    const time = data.time_ms
      ? `<div class="response-time">${data.time_ms}ms</div>`
      : "";

    return `
            <div>
                <span class="status-badge ${badgeClass}">
                    <span class="badge-icon">${icon}</span> ${text}
                </span>
                ${time}
            </div>
        `;
  }

  renderCardDetails(result) {
    return `
            <div class="card-details">
                <div class="details-grid">
                    ${this.renderDetailSection("ads.txt", result.ads_txt)}
                    ${this.renderDetailSection(
                      "app-ads.txt",
                      result.app_ads_txt
                    )}
                </div>
            </div>
        `;
  }

  renderDetailSection(title, data) {
    if (!data) {
      return `
                <div class="detail-section">
                    <h4>📄 ${title} Details</h4>
                    <p style="color: #64748b;">No data available</p>
                </div>
            `;
    }

    return `
            <div class="detail-section">
                <h4>📄 ${title} Details</h4>
                <div class="detail-row">
                    <span class="detail-label">URL:</span>
                    <span class="detail-value">
                        ${
                          data.url
                            ? `<a href="${data.url}" target="_blank" style="color: #667eea;">${data.url}</a>`
                            : "-"
                        }
                    </span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Status Code:</span>
                    <span class="detail-value">${data.status_code || "-"}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Has HTML:</span>
                    <span class="detail-value" style="color: ${
                      data.has_html === "Yes" ? "#ef4444" : "#22c55e"
                    };">
                        ${data.has_html || "-"}
                    </span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Response Time:</span>
                    <span class="detail-value">${
                      data.time_ms ? data.time_ms + " ms" : "-"
                    }</span>
                </div>
                <div style="margin-top: 12px;">
                    <span class="detail-label">Content:</span>
                    <div class="content-preview">${
                      data.content || "No content"
                    }</div>
                </div>
            </div>
        `;
  }

  renderEmptyState() {
    return `
            <div class="empty-state">
                <div class="empty-state-icon">🔍</div>
                <div class="empty-state-text">No results found</div>
                <div class="empty-state-subtext">Try adjusting your filters or search query</div>
            </div>
        `;
  }

  renderPagination() {
    const container = document.getElementById("paginationContainer");
    if (!container) return;

    const totalPages = Math.ceil((this.totalRecords || 0) / this.pageSize);
    const startIndex = (this.currentPage - 1) * this.pageSize + 1;
    const endIndex = Math.min(
      startIndex + this.pageSize - 1,
      this.totalRecords || 0
    );

    container.innerHTML = `
            <div class="pagination-info">
                Showing ${
                  this.totalRecords > 0 ? startIndex : 0
                }-${endIndex} of ${this.totalRecords || 0} results
                ${
                  this.totalRecords !== this.totalRecordsUnfiltered
                    ? `(filtered from ${this.totalRecordsUnfiltered} total)`
                    : ""
                }
            </div>
            <div class="pagination-controls">
                <button class="pagination-btn" data-page="${
                  this.currentPage - 1
                }" ${this.currentPage === 1 ? "disabled" : ""}>
                    Previous
                </button>
                ${this.renderPageNumbers(totalPages)}
                <button class="pagination-btn" data-page="${
                  this.currentPage + 1
                }" ${
      this.currentPage === totalPages || totalPages === 0 ? "disabled" : ""
    }>
                    Next
                </button>
            </div>
        `;
  }

  renderPageNumbers(totalPages) {
    let pages = "";
    const maxVisible = 5;
    let startPage = Math.max(1, this.currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);

    if (endPage - startPage < maxVisible - 1) {
      startPage = Math.max(1, endPage - maxVisible + 1);
    }

    for (let i = startPage; i <= endPage; i++) {
        // Fix for active class syntax
      pages += `
                <button class="pagination-btn ${
                  i === this.currentPage ? "active" : ""
                }" data-page="${i}">
                    ${i}
                </button>
            `;
    }

    return pages;
  }

  getStatusClass(result) {
    if (result.error) return "error";

    const adsSuccess = result.ads_txt && result.ads_txt.status_code === 200;
    const appSuccess =
      result.app_ads_txt && result.app_ads_txt.status_code === 200;

    if (adsSuccess && appSuccess) return "success";
    if (!adsSuccess && !appSuccess) return "error";
    return "warning";
  }

  handleFilterChange(filter) {
    this.currentFilter = filter;
    this.currentPage = 1; // Reset to first page

    // Update active state
    document.querySelectorAll(".filter-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.filter === filter);
    });

    // Reload results from server with new filter
    this.loadResults();
  }

  handleSearch(query) {
    this.searchQuery = query;
    this.currentPage = 1; // Reset to first page

    // Reload results from server with new search
    this.loadResults();
  }

  goToPage(page) {
    this.currentPage = page;

    // Load new page from server
    this.loadResults();

    // Scroll to top of results
    document
      .getElementById("resultsContainer")
      ?.scrollIntoView({ behavior: "smooth" });
  }

  toggleDetails(card) {
    const details = card.querySelector(".card-details");
    if (details) {
      details.classList.toggle("expanded");
    }
  }

  async updateFilterCounts() {
    try {
      // Fetch filter counts from server
      const response = await fetch(
        `/jobs/api/${this.jobId}/results/?start=0&length=0&get_counts=true`
      );
      const data = await response.json();

      const counts = data.filter_counts || {
        all: this.totalRecordsUnfiltered || 0,
        "ads-success": 0,
        "ads-error": 0,
        "app-success": 0,
        "app-error": 0,
        "errors-only": 0,
      };

      // Update count badges
      Object.keys(counts).forEach((filter) => {
        const btn = document.querySelector(`[data-filter="${filter}"] .count`);
        if (btn) btn.textContent = counts[filter];
      });
    } catch (error) {
      console.error("Error loading filter counts:", error);
      // Fallback to showing total count for 'all'
      const allBtn = document.querySelector(`[data-filter="all"] .count`);
      if (allBtn) allBtn.textContent = this.totalRecordsUnfiltered || 0;
    }
  }

  startAutoRefresh() {
    if (this.refreshInterval) return;

    this.refreshInterval = setInterval(() => {
      if (this.autoRefreshEnabled) {
        this.loadResults();
      }
    }, 5000); // Refresh every 5 seconds
  }

  stopAutoRefresh() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  truncateUrl(url, maxLength) {
    if (url.length <= maxLength) return url;
    return url.substring(0, maxLength) + '...';
  }

  showError(message) {
    const container = document.getElementById("resultsContainer");
    if (container) {
      container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div class="empty-state-text">${message}</div>
                </div>
            `;
    }
  }
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  const jobId =
    document.body.dataset.jobId || window.location.pathname.split("/")[2];
  if (jobId) {
    window.liveResults = new LiveResults(jobId);
  }
});
