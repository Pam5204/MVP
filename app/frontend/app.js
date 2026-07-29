"use strict";

/*
 * Browser controller for the DreamEscapes single-page frontend.
 *
 * This file owns session-aware routing, API requests, page rendering, and DOM
 * event handlers. Pure validation and payload helpers remain in logic.js.
 */

// Runtime configuration, storage keys, and shared pure helper functions.
const BACKEND_BASE_URL = (window.BACKEND_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
const SESSION_STORAGE_KEY = "dreamescapesSession";
const SELECTED_PLACE_KEY = "dreamescapesSelectedPlace";
const SESSION_DURATION_MS = 30 * 60 * 1000;
const {
  buildSearchQuery,
  cacheMessage,
  destinationToBucketPayload,
  escapeHtml,
  isExpiredSessionError,
  registrationError
} = window.DreamEscapesLogic;

class ApiError extends Error {
  // Preserve the HTTP status and public backend error code for UI decisions.
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// In-memory data loaded from the API during the current browser session.
const state = {
  session: loadSession(),
  destinations: [],
  selectedDestination: null,
  bucketList: [],
  adminUsers: [],
  adminDestinations: [],
  adminAudit: []
};

// Cache view and frequently updated element references once at startup.
const views = {
  login: document.querySelector("#loginView"),
  register: document.querySelector("#registerView"),
  dashboard: document.querySelector("#dashboardView"),
  details: document.querySelector("#detailsView"),
  bucket: document.querySelector("#bucketView"),
  profile: document.querySelector("#profileView"),
  admin: document.querySelector("#adminView")
};

const protectedRoutes = new Set(["dashboard", "details", "bucket", "profile"]);
const sessionStatus = document.querySelector("#sessionStatus");
const globalMessage = document.querySelector("#globalMessage");
const destinationGrid = document.querySelector("#destinationGrid");
const destinationDetails = document.querySelector("#destinationDetails");
const nearbyAttractions = document.querySelector("#nearbyAttractions");
const pointsOfInterest = document.querySelector("#pointsOfInterest");
const bucketListContainer = document.querySelector("#bucketList");
const searchStatus = document.querySelector("#searchStatus");
const bucketStatus = document.querySelector("#bucketStatus");

// Session storage and authentication-aware navigation helpers.
function loadSession() {
  try {
    const session = JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY));
    if (!session || !session.expiresAt || Date.now() >= session.expiresAt) {
      localStorage.removeItem(SESSION_STORAGE_KEY);
      return null;
    }
    return session;
  } catch (_error) {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    return null;
  }
}

function saveSession(user) {
  state.session = {
    user_id: user.user_id,
    username: user.username,
    email: user.email,
    role: user.role || "user",
    account_status: user.account_status || "enabled",
    expiresAt: Date.now() + SESSION_DURATION_MS
  };
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(state.session));
  updateAuthUI();
}

function clearSession() {
  state.session = null;
  state.bucketList = [];
  localStorage.removeItem(SESSION_STORAGE_KEY);
  sessionStorage.removeItem(SELECTED_PLACE_KEY);
  updateAuthUI();
}

function isLoggedIn() {
  return Boolean(state.session && Date.now() < state.session.expiresAt);
}

function isAdmin() {
  return isLoggedIn() && state.session.role === "admin";
}

function updateAuthUI() {
  document.querySelectorAll('[data-auth-view="logged-in"]').forEach((element) => {
    element.classList.toggle("is-hidden", !isLoggedIn());
  });
  document.querySelectorAll('[data-auth-view="logged-out"]').forEach((element) => {
    element.classList.toggle("is-hidden", isLoggedIn());
  });
  document.querySelectorAll("[data-admin-view]").forEach((element) => {
    element.classList.toggle("is-hidden", !isAdmin());
  });
  sessionStatus.innerHTML = isLoggedIn()
    ? `<span class="session-label">Signed in</span>
       <strong>${escapeHtml(state.session.email)}</strong>
       <span>${escapeHtml(state.session.role)}</span>`
    : `<span class="session-label">Signed out</span>
       <strong>Login required for account features</strong>`;
}

// Shared UI feedback, loading-state, and request-correlation helpers.
function setMessage(target, message = "", type = "") {
  const element = typeof target === "string" ? document.getElementById(target) : target;
  if (!element) return;
  element.textContent = message;
  element.classList.remove("success", "error", "warning");
  if (type) element.classList.add(type);
}

function setBusy(elementId, busy) {
  const element = document.getElementById(elementId);
  if (element) element.hidden = !busy;
}

function newCorrelationId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `request-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// Make one bounded JSON API request with cookies and a correlation identifier.
async function apiRequest(path, options = {}) {
  const method = options.method || "GET";
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  const headers = {
    Accept: "application/json",
    "X-Correlation-ID": newCorrelationId()
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  try {
    const response = await fetch(`${BACKEND_BASE_URL}${path}`, {
      method,
      credentials: "include",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      throw new ApiError(
        payload.error || "The request could not be completed.",
        response.status,
        payload.error_code
      );
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError("The request timed out. Please try again.", 504, "TIMEOUT");
    }
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      "DreamEscapes is temporarily unavailable. Please try again.",
      0,
      "NETWORK_ERROR"
    );
  } finally {
    window.clearTimeout(timeout);
  }
}

function handleApiError(error, target = globalMessage) {
  // Only protected-route failures represent an expired session. A rejected
  // login is also HTTP 401, but its INVALID_CREDENTIALS message belongs on
  // the login form and must replace the temporary "Logging in…" status.
  if (isExpiredSessionError(error.status, error.code)) {
    clearSession();
    setMessage(globalMessage, "Your session expired. Please log in again.", "error");
    setRoute("login");
    return;
  }
  setMessage(target, error.message, error.status === 403 ? "error" : "error");
}

// Hash-based routing protects signed-in and administrator-only views.
function routeFromHash() {
  return location.hash.replace(/^#/, "").split("/")[0] || (isLoggedIn() ? "dashboard" : "login");
}

async function setRoute(route) {
  if (protectedRoutes.has(route) && !isLoggedIn()) {
    setMessage(globalMessage, "Please log in to view that page.", "error");
    route = "login";
  }
  if (route === "admin" && !isAdmin()) {
    setMessage(globalMessage, "Administrator access is required.", "error");
    route = isLoggedIn() ? "dashboard" : "login";
  }
  if (!views[route]) route = isLoggedIn() ? "dashboard" : "login";

  Object.entries(views).forEach(([name, view]) => {
    view.classList.toggle("active", name === route);
  });
  document.querySelectorAll("[data-route]").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === route);
  });
  if (location.hash !== `#${route}`) history.replaceState(null, "", `#${route}`);
  if (route === "profile") await loadProfile();
  if (route === "bucket") await loadBucketList();
  if (route === "details") await loadDestinationDetails();
  if (route === "admin") await loadAdminDashboard();
}

// Destination search, detail rendering, caching messages, and save actions.
function renderDestinations(results) {
  destinationGrid.innerHTML = "";
  if (!results.length) {
    destinationGrid.innerHTML = '<p class="empty-state">No destinations matched your search.</p>';
    return;
  }
  results.forEach((destination) => {
    const card = document.createElement("article");
    card.className = "destination-card";
    card.innerHTML = `
      <div class="destination-art" aria-hidden="true"></div>
      <h3>${escapeHtml(destination.name)}</h3>
      <p>${escapeHtml(destination.city || "Unknown city")}, ${escapeHtml(destination.country || "Unknown country")}</p>
      <p>${escapeHtml((destination.categories || []).slice(0, 3).join(", ") || "Destination")}</p>
      <p>${escapeHtml(destination.formatted_address || "Address unavailable")}</p>
      <div class="card-actions">
        <button class="ghost-button details-button" type="button" data-place-id="${escapeHtml(destination.place_id)}">Details</button>
        <button class="primary-button save-button" type="button" data-place-id="${escapeHtml(destination.place_id)}">Save</button>
      </div>`;
    destinationGrid.append(card);
  });
}

async function runSearch(form) {
  const values = Object.fromEntries(new FormData(form).entries());
  const query = buildSearchQuery(values);
  if (!query) {
    setMessage(searchStatus, "Enter a destination name, keyword, or country.", "error");
    return;
  }
  setBusy("searchLoading", true);
  setMessage(searchStatus, "Searching…");
  destinationGrid.innerHTML = "";
  try {
    const result = await apiRequest(`/api/destinations/search?${query}`);
    state.destinations = result.results || [];
    renderDestinations(state.destinations);
    const cacheText = cacheMessage(result.cache_status, result.cache_warning);
    setMessage(
      searchStatus,
      `${result.message}${cacheText ? ` ${cacheText}` : ""}`,
      result.cache_status === "stale" ? "warning" : "success"
    );
  } catch (error) {
    handleApiError(error, searchStatus);
  } finally {
    setBusy("searchLoading", false);
  }
}

function findDestination(placeId) {
  if (state.selectedDestination?.place_id === placeId) return state.selectedDestination;
  return state.destinations.find((item) => item.place_id === placeId);
}

async function loadDestinationDetails() {
  const placeId = sessionStorage.getItem(SELECTED_PLACE_KEY);
  if (!placeId) {
    setMessage(globalMessage, "Select a destination from search results.", "warning");
    await setRoute("dashboard");
    return;
  }
  setBusy("detailsLoading", true);
  setMessage("detailsStatus", "Loading…");
  destinationDetails.innerHTML = "";
  nearbyAttractions.innerHTML = "";
  pointsOfInterest.innerHTML = "";
  try {
    const result = await apiRequest(`/api/destinations/${encodeURIComponent(placeId)}`);
    const destination = result.destination;
    state.selectedDestination = destination;
    document.querySelector("#detailsTitle").textContent = destination.name;
    destinationDetails.innerHTML = `
      <p>${escapeHtml(destination.description || "No description is available for this destination.")}</p>
      <div class="detail-meta">
        <p><strong>City</strong><br>${escapeHtml(destination.city || "Unknown")}</p>
        <p><strong>Country</strong><br>${escapeHtml(destination.country || "Unknown")}</p>
        <p><strong>Categories</strong><br>${escapeHtml((destination.categories || []).join(", ") || "Not available")}</p>
        <p><strong>Coordinates</strong><br>${escapeHtml(destination.latitude)}, ${escapeHtml(destination.longitude)}</p>
        <p><strong>Address</strong><br>${escapeHtml(destination.formatted_address || "Not available")}</p>
        <p><strong>Place ID</strong><br>${escapeHtml(destination.place_id)}</p>
      </div>
      <button class="primary-button detail-save-button" type="button">Save to bucket list</button>`;
    renderInfoList(nearbyAttractions, destination.nearby_attractions, "No nearby attractions were returned.");
    renderInfoList(pointsOfInterest, destination.points_of_interest, "No points of interest were returned.");
    const cacheText = cacheMessage(result.cache_status, result.cache_warning);
    setMessage(
      "detailsStatus",
      cacheText,
      result.cache_status === "stale" ? "warning" : "success"
    );
  } catch (error) {
    handleApiError(error, document.querySelector("#detailsStatus"));
  } finally {
    setBusy("detailsLoading", false);
  }
}

function renderInfoList(container, items = [], emptyMessage) {
  container.innerHTML = items.length
    ? items.map((item) => `
        <li><strong>${escapeHtml(item.name)}</strong><br>
        ${escapeHtml(item.formatted_address || item.city || "")}
        ${item.distance != null ? `<br>${escapeHtml(item.distance)} m away` : ""}</li>
      `).join("")
    : `<li>${escapeHtml(emptyMessage)}</li>`;
}

async function saveDestination(destination) {
  if (!destination) return;
  try {
    const result = await apiRequest("/api/bucket-list", {
      method: "POST",
      body: destinationToBucketPayload(destination)
    });
    state.bucketList.unshift(result.bucket_list_item);
    setMessage(globalMessage, result.message, "success");
  } catch (error) {
    handleApiError(error, globalMessage);
  }
}

// Bucket-list loading, rendering, editing, and deletion.
async function loadBucketList() {
  setBusy("bucketLoading", true);
  setMessage(bucketStatus, "Loading…");
  try {
    const result = await apiRequest("/api/bucket-list");
    state.bucketList = result.bucket_list || [];
    renderBucketList();
    setMessage(
      bucketStatus,
      result.count ? `${result.count} saved destination${result.count === 1 ? "" : "s"}.` : "Your bucket list is empty."
    );
  } catch (error) {
    handleApiError(error, bucketStatus);
  } finally {
    setBusy("bucketLoading", false);
  }
}

function renderBucketList() {
  bucketListContainer.innerHTML = state.bucketList.length
    ? state.bucketList.map((item) => `
      <article class="bucket-card" data-bucket-id="${item.bucket_item_id}">
        <h3>${escapeHtml(item.destination_name)}</h3>
        <p>${escapeHtml(item.city)}, ${escapeHtml(item.country)}</p>
        <p>${escapeHtml((item.categories || []).join(", ") || "No category")}</p>
        <form class="bucket-edit-form" data-bucket-id="${item.bucket_item_id}">
          <label>Categories
            <input name="categories" value="${escapeHtml((item.categories || []).join(", "))}" placeholder="culture, museum">
          </label>
          <label>Travel label
            <input name="travel_type_label" value="${escapeHtml(item.travel_type_label || "")}" placeholder="dream-trip">
          </label>
          <div class="card-actions">
            <button class="ghost-button" type="submit">Update</button>
            <button class="ghost-button bucket-remove" type="button" data-bucket-id="${item.bucket_item_id}">Delete</button>
          </div>
        </form>
      </article>`).join("")
    : '<p class="empty-state">Save a destination from search or details to begin your bucket list.</p>';
}

// Profile and administrator data loaders and renderers.
async function loadProfile() {
  setMessage("profileMessage", "Loading profile…");
  try {
    const result = await apiRequest("/api/profile");
    const profile = result.profile;
    document.querySelector("#profileSummary").innerHTML = `
      <p><strong>Username:</strong> ${escapeHtml(profile.username)}</p>
      <p><strong>Email:</strong> ${escapeHtml(profile.email)}</p>
      <p><strong>Role:</strong> ${escapeHtml(profile.role)}</p>
      <p><strong>Status:</strong> ${escapeHtml(profile.account_status)}</p>
      <p><strong>Travel preferences:</strong> ${escapeHtml(profile.travel_preferences || "Not set")}</p>`;
    const form = document.querySelector("#profileForm");
    form.elements.username.value = profile.username;
    form.elements.email.value = profile.email;
    form.elements.travel_preferences.value = profile.travel_preferences || "";
    setMessage("profileMessage");
  } catch (error) {
    handleApiError(error, document.querySelector("#profileMessage"));
  }
}

async function loadAdminDashboard() {
  setBusy("adminLoading", true);
  document.querySelector("#adminContent").hidden = false;
  setMessage("adminAccessMessage");
  try {
    const [users, destinations, audit] = await Promise.all([
      apiRequest("/api/admin/users"),
      apiRequest("/api/admin/destinations"),
      apiRequest("/api/admin/audit-logs")
    ]);
    state.adminUsers = users.users || [];
    state.adminDestinations = destinations.destinations || [];
    state.adminAudit = audit.audit_logs || [];
    renderAdminUsers();
    renderAdminDestinations();
    renderAdminAudit();
  } catch (error) {
    document.querySelector("#adminContent").hidden = true;
    handleApiError(error, document.querySelector("#adminAccessMessage"));
  } finally {
    setBusy("adminLoading", false);
  }
}

function renderAdminUsers() {
  const table = document.querySelector("#adminUsersTable");
  table.innerHTML = `
    <div class="table-row header"><span>User</span><span>Role</span><span>Status</span><span>Action</span></div>
    ${state.adminUsers.map((user) => `
      <div class="table-row" data-user-id="${user.user_id}">
        <span><strong>${escapeHtml(user.username)}</strong><br>${escapeHtml(user.email)}</span>
        <select class="role-select" aria-label="Role for ${escapeHtml(user.email)}">
          <option value="user" ${user.role === "user" ? "selected" : ""}>user</option>
          <option value="admin" ${user.role === "admin" ? "selected" : ""}>admin</option>
        </select>
        <select class="status-select" aria-label="Status for ${escapeHtml(user.email)}">
          <option value="enabled" ${user.account_status === "enabled" ? "selected" : ""}>enabled</option>
          <option value="disabled" ${user.account_status === "disabled" ? "selected" : ""}>disabled</option>
        </select>
        <button class="ghost-button admin-user-save" type="button" data-user-id="${user.user_id}">Save</button>
      </div>`).join("")}`;
}

function renderAdminDestinations() {
  const table = document.querySelector("#adminDestinationReview");
  table.innerHTML = state.adminDestinations.length
    ? state.adminDestinations.map((item) => `
      <div class="review-row">
        <div><strong>${escapeHtml(item.destination_name || item.place_id)}</strong><br>
        ${escapeHtml(item.country)} · ${escapeHtml(item.categories)}<br>
        Cached: ${escapeHtml(item.cached_at)}</div>
        <button class="ghost-button destination-review" type="button" data-cache-id="${item.cache_id}">Record review</button>
      </div>`).join("")
    : '<p class="empty-state">No cached destinations are available for review.</p>';
}

function renderAdminAudit() {
  document.querySelector("#adminAuditLog").innerHTML = state.adminAudit.length
    ? state.adminAudit.map((item) => `
      <li><strong>${escapeHtml(item.action_type)}</strong> by ${escapeHtml(item.admin_email)}
      — ${escapeHtml(item.notes)}<br>${escapeHtml(item.created_at)}</li>`).join("")
    : "<li>No admin actions have been recorded.</li>";
}

// Navigation and authentication form event handlers.
document.querySelectorAll("[data-route]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    setMessage(globalMessage);
    setRoute(link.dataset.route);
  });
});

document.querySelector("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const email = form.elements.email.value.trim();
  const password = form.elements.password.value;
  if (!email || !password) {
    setMessage("loginMessage", "Email and password are required.", "error");
    return;
  }
  setMessage("loginMessage", "Logging in…");
  try {
    const result = await apiRequest("/api/login", {
      method: "POST",
      body: { email, password }
    });
    saveSession(result.user);
    form.reset();
    setMessage("loginMessage", result.message, "success");
    await setRoute("dashboard");
  } catch (error) {
    form.elements.password.value = "";
    handleApiError(error, document.querySelector("#loginMessage"));
  }
});

document.querySelector("#registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  const validationMessage = registrationError(values);
  if (validationMessage) {
    setMessage("registerMessage", validationMessage, "error");
    return;
  }
  setMessage("registerMessage", "Creating account…");
  try {
    const result = await apiRequest("/api/register", {
      method: "POST",
      body: {
        username: values.username.trim(),
        email: values.email.trim(),
        password: values.password
      }
    });
    form.reset();
    setMessage("registerMessage", result.message, "success");
  } catch (error) {
    form.elements.password.value = "";
    form.elements.confirmPassword.value = "";
    handleApiError(error, document.querySelector("#registerMessage"));
  }
});

document.querySelector("#logoutButton").addEventListener("click", async () => {
  try {
    await apiRequest("/api/logout", { method: "POST", body: {} });
  } catch (_error) {
    // Local session cleanup is still required when the server is unavailable.
  }
  clearSession();
  await setRoute("login");
});

document.querySelector("#searchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await runSearch(event.currentTarget);
});

// Delegated destination and bucket-list handlers support dynamically rendered cards.
destinationGrid.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-place-id]");
  if (!button) return;
  const destination = findDestination(button.dataset.placeId);
  if (button.classList.contains("save-button")) {
    await saveDestination(destination);
    return;
  }
  sessionStorage.setItem(SELECTED_PLACE_KEY, button.dataset.placeId);
  await setRoute("details");
});

destinationDetails.addEventListener("click", async (event) => {
  if (event.target.closest(".detail-save-button")) {
    await saveDestination(state.selectedDestination);
  }
});

bucketListContainer.addEventListener("submit", async (event) => {
  const form = event.target.closest(".bucket-edit-form");
  if (!form) return;
  event.preventDefault();
  const bucketId = Number(form.dataset.bucketId);
  try {
    const result = await apiRequest(`/api/bucket-list/${bucketId}`, {
      method: "PUT",
      body: {
        categories: form.elements.categories.value,
        travel_type_label: form.elements.travel_type_label.value
      }
    });
    const index = state.bucketList.findIndex((item) => item.bucket_item_id === bucketId);
    if (index >= 0) state.bucketList[index] = result.bucket_list_item;
    renderBucketList();
    setMessage(bucketStatus, result.message, "success");
  } catch (error) {
    handleApiError(error, bucketStatus);
  }
});

bucketListContainer.addEventListener("click", async (event) => {
  const button = event.target.closest(".bucket-remove");
  if (!button) return;
  const bucketId = Number(button.dataset.bucketId);
  try {
    const result = await apiRequest(`/api/bucket-list/${bucketId}`, {
      method: "DELETE"
    });
    state.bucketList = state.bucketList.filter((item) => item.bucket_item_id !== bucketId);
    renderBucketList();
    setMessage(bucketStatus, result.message, "success");
  } catch (error) {
    handleApiError(error, bucketStatus);
  }
});

document.querySelector("#profileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.elements.username.value.trim() || !form.elements.email.value.trim()) {
    setMessage("profileMessage", "Username and email are required.", "error");
    return;
  }
  try {
    const result = await apiRequest("/api/profile", {
      method: "PUT",
      body: {
        username: form.elements.username.value.trim(),
        email: form.elements.email.value.trim(),
        password: form.elements.password.value,
        travel_preferences: form.elements.travel_preferences.value.trim()
      }
    });
    saveSession(result.profile);
    form.elements.password.value = "";
    await loadProfile();
    setMessage("profileMessage", "Profile updated successfully.", "success");
  } catch (error) {
    form.elements.password.value = "";
    handleApiError(error, document.querySelector("#profileMessage"));
  }
});

// Administrator actions update users, review destinations, and switch tabs.
document.querySelector("#adminUsersTable").addEventListener("click", async (event) => {
  const button = event.target.closest(".admin-user-save");
  if (!button) return;
  const row = button.closest("[data-user-id]");
  const userId = Number(row.dataset.userId);
  try {
    const roleResult = await apiRequest(`/api/admin/users/${userId}/role`, {
      method: "PUT",
      body: { role: row.querySelector(".role-select").value }
    });
    await apiRequest(`/api/admin/users/${userId}/status`, {
      method: "PUT",
      body: { account_status: row.querySelector(".status-select").value }
    });
    setMessage("adminMessage", `Updated ${roleResult.user.email}.`, "success");
    await loadAdminDashboard();
  } catch (error) {
    handleApiError(error, document.querySelector("#adminMessage"));
  }
});

document.querySelector("#adminDestinationReview").addEventListener("click", async (event) => {
  const button = event.target.closest(".destination-review");
  if (!button) return;
  try {
    const result = await apiRequest(
      `/api/admin/destinations/${Number(button.dataset.cacheId)}/review`,
      { method: "POST", body: {} }
    );
    setMessage("adminMessage", result.message, "success");
    await loadAdminDashboard();
  } catch (error) {
    handleApiError(error, document.querySelector("#adminMessage"));
  }
});

document.querySelectorAll(".admin-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const sectionIds = {
      users: "adminUsersSection",
      destinations: "adminDestinationsSection",
      audit: "adminAuditSection"
    };
    document.querySelectorAll(".admin-tab").forEach((item) => {
      item.classList.toggle("active", item === tab);
    });
    document.querySelectorAll(".admin-section").forEach((section) => {
      section.classList.toggle("active", section.id === sectionIds[tab.dataset.adminSection]);
    });
  });
});

window.addEventListener("hashchange", () => setRoute(routeFromHash()));

// Render authentication state and the URL-selected view on first load.
updateAuthUI();
setRoute(routeFromHash());
