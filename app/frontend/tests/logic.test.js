"use strict";

// Unit tests for the pure browser helpers; no DOM or backend is required.
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildSearchQuery,
  cacheMessage,
  destinationToBucketPayload,
  escapeHtml,
  isExpiredSessionError,
  registrationError
} = require("../logic.js");

test("buildSearchQuery includes supported non-empty filters", () => {
  const query = buildSearchQuery({
    name: " Paris ",
    keyword: "",
    country: "France",
    category: "culture",
    attraction_type: "museum"
  });
  const values = new URLSearchParams(query);
  assert.equal(values.get("name"), "Paris");
  assert.equal(values.get("country"), "France");
  assert.equal(values.get("category"), "culture");
  assert.equal(values.get("attraction_type"), "museum");
  assert.equal(values.has("keyword"), false);
});

test("registration validation covers missing and mismatched fields", () => {
  assert.equal(
    registrationError({ username: "", email: "", password: "", confirmPassword: "" }),
    "Username is required."
  );
  assert.equal(
    registrationError({
      username: "Alex",
      email: "alex@example.com",
      password: "long-enough",
      confirmPassword: "different"
    }),
    "Passwords do not match."
  );
  assert.equal(
    registrationError({
      username: "Alex",
      email: "alex@example.com",
      password: "long-enough",
      confirmPassword: "long-enough"
    }),
    ""
  );
});

test("cache status produces clear user-facing messages", () => {
  assert.equal(cacheMessage("fresh", ""), "Fresh cached destination data used.");
  assert.equal(
    cacheMessage("stale", "Cached result may be old."),
    "Cached result may be old."
  );
  assert.equal(
    cacheMessage("refreshed", ""),
    "Destination data refreshed from Geoapify."
  );
});

test("only authentication-required 401 responses represent expired sessions", () => {
  assert.equal(isExpiredSessionError(401, "AUTHENTICATION_REQUIRED"), true);
  assert.equal(isExpiredSessionError(401, "INVALID_CREDENTIALS"), false);
  assert.equal(isExpiredSessionError(403, "AUTHENTICATION_REQUIRED"), false);
});

test("destination save payload includes all backend-required fields", () => {
  assert.deepEqual(
    destinationToBucketPayload({
      name: "The Museum",
      city: "Newark",
      country: "United States",
      categories: ["museum"],
      latitude: 40.7,
      longitude: -74.1,
      place_id: "place-1"
    }),
    {
      destination_name: "The Museum",
      city: "Newark",
      country: "United States",
      categories: ["museum"],
      latitude: 40.7,
      longitude: -74.1,
      place_id: "place-1",
      travel_type_label: "dream-trip"
    }
  );
});

test("escapeHtml protects dynamic API values inserted into templates", () => {
  assert.equal(
    escapeHtml('<script>alert("x")</script>'),
    "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
  );
});
