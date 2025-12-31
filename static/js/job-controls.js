/**
 * Job Controls and Event Timeline JavaScript
 * Handles job control actions (pause, resume, stop) and event timeline pagination
 */

// Get job ID and CSRF token from page
const jobId =
  document.body.dataset.jobId || window.location.pathname.split("/")[2];
const csrfToken =
  document.querySelector("[name=csrfmiddlewaretoken]")?.value ||
  document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
  getCookie("csrftoken");

// Helper function to get CSRF token from cookies
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === name + "=") {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

/**
 * Pause the current job
 */
window.pauseJob = async () => {
  if (!confirm("Pause this job?")) return;

  try {
    const response = await fetch(`/jobs/api/${jobId}/pause/`, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "Content-Type": "application/json",
      },
    });

    if (response.ok) {
      location.reload();
    } else {
      const data = await response.json();
      alert(`Error pausing job: ${data.error || "Unknown error"}`);
    }
  } catch (error) {
    console.error("Error pausing job:", error);
    alert("Error pausing job. Please try again.");
  }
};

/**
 * Resume the current job
 */
window.resumeJob = async () => {
  try {
    const response = await fetch(`/jobs/api/${jobId}/resume/`, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "Content-Type": "application/json",
      },
    });

    if (response.ok) {
      location.reload();
    } else {
      const data = await response.json();
      alert(`Error resuming job: ${data.error || "Unknown error"}`);
    }
  } catch (error) {
    console.error("Error resuming job:", error);
    alert("Error resuming job. Please try again.");
  }
};

/**
 * Stop the current job
 */
window.stopJob = async () => {
  if (!confirm("Stop this job? This action cannot be undone.")) return;

  try {
    const response = await fetch(`/jobs/api/${jobId}/stop/`, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "Content-Type": "application/json",
      },
    });

    if (response.ok) {
      location.reload();
    } else {
      const data = await response.json();
      alert(`Error stopping job: ${data.error || "Unknown error"}`);
    }
  } catch (error) {
    console.error("Error stopping job:", error);
    alert("Error stopping job. Please try again.");
  }
};

/**
 * Event Timeline Pagination
 * Shows more events when "Show More Events" button is clicked
 */
document.addEventListener("DOMContentLoaded", () => {
  let visibleEventCount = 10;
  const showMoreBtn = document.getElementById("showMoreEvents");

  if (showMoreBtn) {
    showMoreBtn.addEventListener("click", function () {
      visibleEventCount += 10;

      // Show more timeline items
      document.querySelectorAll(".timeline-item").forEach((item) => {
        const index = parseInt(item.dataset.eventIndex);
        if (index <= visibleEventCount) {
          item.style.display = "flex";
        }
      });

      // Hide button if all events are visible
      const totalEvents = document.querySelectorAll(".timeline-item").length;
      if (visibleEventCount >= totalEvents) {
        showMoreBtn.style.display = "none";
      }
    });
  }

  // Start status polling
  startStatusPolling();
});

/**
 * Status Polling
 * Polls the server for job status updates and updates the UI
 */
let lastProcessedItems = 0;
let lastUpdateTime = Date.now();
let processingRateHistory = [];

async function pollStatus() {
  try {
    const response = await fetch(`/jobs/api/${jobId}/status/`);
    const data = await response.json();

    // Update Progress
    if (data.progress !== undefined) {
      const progressText = document.getElementById("progressText");
      const progressBarText = document.getElementById("progressBarText");
      const progressBar = document.getElementById("progressBar");

      if (progressText) progressText.textContent = data.progress;
      if (progressBarText) progressBarText.textContent = data.progress + "%";
      if (progressBar) progressBar.style.width = data.progress + "%";
    }

    if (data.processed_items !== undefined) {
      const statProcessedItems = document.getElementById("statProcessedItems");
      if (statProcessedItems)
        statProcessedItems.textContent = data.processed_items;
    }

    // Update Stats
    if (data.stats) {
      const countAdsSuccess = document.getElementById("countAdsSuccess");
      const countAdsErrors = document.getElementById("countAdsErrors");
      const countAppAdsSuccess = document.getElementById("countAppAdsSuccess");
      const countAppAdsErrors = document.getElementById("countAppAdsErrors");
      const statsCard = document.getElementById("statsCard");

      if (countAdsSuccess) countAdsSuccess.textContent = data.stats.ads_success;
      if (countAdsErrors) countAdsErrors.textContent = data.stats.ads_error;
      if (countAppAdsSuccess)
        countAppAdsSuccess.textContent = data.stats.app_success;
      if (countAppAdsErrors)
        countAppAdsErrors.textContent = data.stats.app_error;
      if (statsCard) statsCard.style.display = "block";
    }

    // Calculate Batch Processing Rate & ETA
    if (data.processed_items !== undefined && data.total_items !== undefined) {
      const now = Date.now();
      const timeDiff = (now - lastUpdateTime) / 1000; // seconds
      const itemsDiff = data.processed_items - lastProcessedItems;

      if (timeDiff > 0 && itemsDiff > 0) {
        const rate = itemsDiff / timeDiff; // items per second
        processingRateHistory.push(rate);

        // Keep only last 5 measurements for averaging
        if (processingRateHistory.length > 5) {
          processingRateHistory.shift();
        }

        // Calculate average rate
        const avgRate =
          processingRateHistory.reduce((a, b) => a + b, 0) /
          processingRateHistory.length;
        const itemsPerMin = (avgRate * 60).toFixed(1);

        // Calculate batch progress (50 items per batch)
        const batchSize = 50;
        const currentBatch = Math.ceil(data.processed_items / batchSize);
        const totalBatches = Math.ceil(data.total_items / batchSize);
        const batchProgress = document.getElementById("batchProgress");
        if (batchProgress)
          batchProgress.textContent = `${currentBatch} / ${totalBatches}`;

        // Update rate display
        const processingRate = document.getElementById("processingRate");
        if (processingRate)
          processingRate.textContent = `${itemsPerMin} items/min`;

        // Calculate ETA
        const remainingItems = data.total_items - data.processed_items;
        const etaSeconds = remainingItems / avgRate;
        const estimatedTime = document.getElementById("estimatedTime");

        if (estimatedTime) {
          if (etaSeconds < 3600) {
            const minutes = Math.round(etaSeconds / 60);
            estimatedTime.textContent = `~${minutes} min`;
          } else {
            const hours = (etaSeconds / 3600).toFixed(1);
            estimatedTime.textContent = `~${hours} hrs`;
          }
        }

        lastProcessedItems = data.processed_items;
        lastUpdateTime = now;
      }
    }

    // Show Download Options on Completion
    if (data.status === "completed" || data.status === "failed") {
      const downloadContainer = document.getElementById("downloadContainer");
      const liveIndicators = document.querySelectorAll(".live-indicator");
      const batchStatus = document.getElementById("batchStatus");

      if (downloadContainer) downloadContainer.style.display = "block";
      liveIndicators.forEach((el) => (el.style.display = "none"));
      if (batchStatus) batchStatus.style.display = "none";
      return; // Stop polling if done
    }

    // Smart polling: adjust interval based on job status
    let nextPollInterval;
    if (data.status === "running") {
      nextPollInterval = 5000; // 5 seconds for active jobs
    } else if (data.status === "paused" || data.status === "auto_paused") {
      nextPollInterval = 30000; // 30 seconds for paused jobs
    } else {
      // Stop polling for completed/failed jobs
      return;
    }

    setTimeout(pollStatus, nextPollInterval);
  } catch (error) {
    console.error("Polling error:", error);
    setTimeout(pollStatus, 10000); // Retry after 10 seconds on error
  }
}

function startStatusPolling() {
  // Get initial processed items from page
  const statProcessedItems = document.getElementById("statProcessedItems");
  if (statProcessedItems) {
    lastProcessedItems = parseInt(statProcessedItems.textContent) || 0;
  }

  // Start polling
  pollStatus();
}
