/*
 * Framework-independent frontend helpers.
 *
 * The wrapper exports the same functions to browsers and Node's test runner,
 * keeping validation, query construction, payload shaping, and HTML escaping
 * testable without starting Django or manipulating the DOM.
 */
(function exposeDreamEscapesLogic(root, factory) {
  const logic = factory();
  if (typeof module === "object" && module.exports) module.exports = logic;
  root.DreamEscapesLogic = logic;
}(typeof globalThis !== "undefined" ? globalThis : this, function buildLogic() {
  // Convert only supported, non-empty search filters to a URL query string.
  function buildSearchQuery(values) {
    const params = new URLSearchParams();
    ["name", "keyword", "country", "category", "attraction_type"].forEach((key) => {
      const value = String(values[key] || "").trim();
      if (value) params.set(key, value);
    });
    return params.toString();
  }

  // Return the first registration validation error, or an empty string.
  function registrationError(values) {
    if (!String(values.username || "").trim()) return "Username is required.";
    if (!String(values.email || "").trim()) return "Email is required.";
    if (!String(values.password || "")) return "Password is required.";
    if (String(values.password).length < 8) return "Password must be at least 8 characters.";
    if (values.password !== values.confirmPassword) return "Passwords do not match.";
    return "";
  }

  // Validate the required comment and 1-5 whole-number rating client-side.
  function reviewError(values) {
    const rating = Number(values.rating);
    if (!String(values.comment || "").trim()) return "Review comment is required.";
    if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
      return "Rating must be a whole number from 1 to 5.";
    }
    return "";
  }

  // Mirror the required community fields before making a network request.
  function communityPostError(values) {
    if (!["experience", "question"].includes(String(values.post_type || ""))) {
      return "Choose a travel experience or question post type.";
    }
    if (String(values.title || "").trim().length < 3) {
      return "Post title must be at least 3 characters."
    }
    if (String(values.body || "").trim().length < 10) {
      return "Post text must be at least 10 characters."
    }
    const pictureUrl = String(values.picture_url || "").trim();
    if (pictureUrl && !/^https?:\/\/[^\s]+$/i.test(pictureUrl)) {
      return "Picture URL must be a valid HTTP or HTTPS address."
    }
    return "";
  }

  // Translate backend cache state into a short message for the search UI.
  function cacheMessage(status, warning) {
    if (warning) return warning;
    if (status === "fresh") return "Fresh cached destination data used.";
    if (status === "stale") return "Cached destination data may be out of date.";
    if (status === "refreshed") return "Destination data refreshed from Geoapify.";
    return "";
  }

  // Distinguish an expired authenticated session from rejected login details.
  function isExpiredSessionError(status, code) {
    return Number(status) === 401 && code === "AUTHENTICATION_REQUIRED";
  }

  // Shape a destination result into the API's bucket-list request contract.
  function destinationToBucketPayload(destination) {
    return {
      destination_name: destination.name,
      city: destination.city || "Unknown city",
      country: destination.country || "Unknown country",
      categories: destination.categories || [],
      latitude: destination.latitude,
      longitude: destination.longitude,
      place_id: destination.place_id,
      travel_type_label: "dream-trip"
    };
  }

  // Escape untrusted API values before inserting them into HTML templates.
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // Expose the pure helpers used by app.js and the Node contract tests.
  return {
    buildSearchQuery,
    cacheMessage,
    communityPostError,
    destinationToBucketPayload,
    escapeHtml,
    isExpiredSessionError,
    reviewError,
    registrationError
  };
}));
