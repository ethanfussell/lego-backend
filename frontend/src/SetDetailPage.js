// frontend/src/SetDetailPage.js
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import SetCard from "./SetCard";

const API_BASE = "http://localhost:8000";

// derive username from token (works for dev-* and fake-token-for-*)
function getUsernameFromToken(token) {
  if (!token) return null;
  if (token.startsWith("fake-token-for-")) return token.replace("fake-token-for-", "");
  if (token.startsWith("dev-")) return token.replace("dev-", "");
  return token;
}

function clampRating(value) {
  let v = Number(value);
  if (Number.isNaN(v)) return null;
  v = Math.round(v * 2) / 2; // 0.5 steps
  if (v < 0.5) v = 0.5;
  if (v > 5) v = 5;
  return v;
}

async function fetchJSON(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `Request failed (${resp.status})`);
  }
  return resp.json();
}

function SetDetailPage({
  token,
  ownedSetNums,
  wishlistSetNums,
  onMarkOwned,
  onAddWishlist,
  onEnsureOwned,
  myLists, // not used yet, kept for future
}) {
  const { setNum } = useParams();
  const navigate = useNavigate();

  const storedToken = localStorage.getItem("lego_token") || "";
  const effectiveToken = token || storedToken || "";
  const isLoggedIn = !!effectiveToken;

  // optional: we try /auth/me for “true” username; fallback to token parsing
  const [meUsername, setMeUsername] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function loadMe() {
      if (!effectiveToken) {
        setMeUsername(null);
        return;
      }
      try {
        const data = await fetchJSON(`${API_BASE}/auth/me`, {
          headers: { Authorization: `Bearer ${effectiveToken}` },
        });
        if (!cancelled) setMeUsername(data?.username ?? null);
      } catch {
        if (!cancelled) setMeUsername(null);
      }
    }

    loadMe();
    return () => {
      cancelled = true;
    };
  }, [effectiveToken]);

  const currentUsername = meUsername || getUsernameFromToken(effectiveToken);

  // -------------------------------
  // Basic set + reviews state
  // -------------------------------
  const [setDetail, setSetDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [reviews, setReviews] = useState([]);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState(null);

  // -------------------------------
  // Rating state (user)
  // -------------------------------
  const [userRating, setUserRating] = useState(null);
  const [hoverRating, setHoverRating] = useState(null);
  const [savingRating, setSavingRating] = useState(false);
  const [ratingError, setRatingError] = useState(null);

  // Review UI
  const [showReviewForm, setShowReviewForm] = useState(false);
  const [reviewText, setReviewText] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [reviewSubmitError, setReviewSubmitError] = useState(null);

  // Similar sets
  const [similarSets, setSimilarSets] = useState([]);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [similarError, setSimilarError] = useState(null);
  const similarRowRef = useRef(null);

  // Derived collection state
  const isOwned = ownedSetNums ? ownedSetNums.has(setNum) : false;
  const isInWishlist = wishlistSetNums ? wishlistSetNums.has(setNum) : false;

  // My review (from loaded list)
  const myReview = useMemo(() => {
    if (!currentUsername || !Array.isArray(reviews)) return null;
    return reviews.find((r) => (r.user || r.username) === currentUsername) || null;
  }, [reviews, currentUsername]);

  // Display global ratings (from set detail response)
  const displayAvgRating = useMemo(() => {
    const v = setDetail?.average_rating ?? setDetail?.rating_avg ?? null;
    return typeof v === "number" ? v : null;
  }, [setDetail]);

  const displayRatingCount = useMemo(() => {
    const v = setDetail?.rating_count ?? null;
    return typeof v === "number" ? v : 0;
  }, [setDetail]);

  async function refreshSetDetail() {
    const data = await fetchJSON(`${API_BASE}/sets/${encodeURIComponent(setNum)}`);
    setSetDetail(data);
  }

  async function refreshReviews() {
    const data = await fetchJSON(
      `${API_BASE}/sets/${encodeURIComponent(setNum)}/reviews?limit=50`
    );
    setReviews(Array.isArray(data) ? data : []);
  }

  // -------------------------------
  // Load set detail + reviews
  // -------------------------------
  useEffect(() => {
    if (!setNum) return;

    let cancelled = false;

    async function fetchData() {
      try {
        setLoading(true);
        setError(null);
        setReviewsError(null);
        setRatingError(null);

        // 1) Set detail (includes average_rating + rating_count)
        const detailData = await fetchJSON(
          `${API_BASE}/sets/${encodeURIComponent(setNum)}`
        );
        if (cancelled) return;
        setSetDetail(detailData);

        // 2) Reviews
        setReviewsLoading(true);
        const reviewsData = await fetchJSON(
          `${API_BASE}/sets/${encodeURIComponent(setNum)}/reviews?limit=50`
        );
        if (cancelled) return;
        setReviews(Array.isArray(reviewsData) ? reviewsData : []);

        // 3) Sync my rating from my review (if any)
        if (currentUsername && Array.isArray(reviewsData)) {
          const mine = reviewsData.find(
            (r) => (r.user || r.username) === currentUsername
          );
          setUserRating(mine && typeof mine.rating === "number" ? mine.rating : null);

          // If we are not actively editing, keep textarea in sync too
          if (!showReviewForm) {
            setReviewText(mine && typeof mine.text === "string" ? mine.text : "");
          }
        } else {
          setUserRating(null);
          if (!showReviewForm) setReviewText("");
        }
      } catch (err) {
        if (!cancelled) {
          console.error("Error loading set detail:", err);
          setError(err.message || String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setReviewsLoading(false);
        }
      }
    }

    fetchData();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setNum, currentUsername]);

  // -------------------------------
  // Similar sets
  // -------------------------------
  useEffect(() => {
    if (!setDetail || !setDetail.theme) {
      setSimilarSets([]);
      return;
    }

    let cancelled = false;

    async function fetchSimilar() {
      try {
        setSimilarLoading(true);
        setSimilarError(null);

        const params = new URLSearchParams();
        params.set("q", setDetail.theme);
        params.set("sort", "rating");
        params.set("order", "desc");
        params.set("page", "1");
        params.set("limit", "24");

        const resp = await fetch(`${API_BASE}/sets?${params.toString()}`);
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(`Similar sets fetch failed (${resp.status}): ${text}`);
        }

        const data = await resp.json();
        let items = Array.isArray(data) ? data : data.results || [];
        items = items.filter((s) => s.set_num !== setNum);

        if (!cancelled) setSimilarSets(items.slice(0, 12));
      } catch (err) {
        if (!cancelled) {
          console.error("Error loading similar sets:", err);
          setSimilarError(err.message || String(err));
        }
      } finally {
        if (!cancelled) setSimilarLoading(false);
      }
    }

    fetchSimilar();
    return () => {
      cancelled = true;
    };
  }, [setDetail, setNum]);

  // -------------------------------
  // Owned / Wishlist
  // -------------------------------
  function handleMarkOwnedClick() {
    if (!isLoggedIn) {
      alert("Please log in to track your collection.");
      navigate("/login");
      return;
    }
    onMarkOwned?.(setNum);
  }

  function handleAddWishlistClick() {
    if (!isLoggedIn) {
      alert("Please log in to track your collection.");
      navigate("/login");
      return;
    }
    onAddWishlist?.(setNum);
  }

  // -------------------------------
  // Rating + Review helpers
  // -------------------------------
  async function upsertReview({ rating, text }) {
    const payload = {};
    if (rating !== undefined) payload.rating = rating; // allow null if you want
    if (text !== undefined) payload.text = text;

    const created = await fetchJSON(
      `${API_BASE}/sets/${encodeURIComponent(setNum)}/reviews`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${effectiveToken}`,
        },
        body: JSON.stringify(payload),
      }
    );

    // Update reviews list locally (replace mine)
    setReviews((prev) => {
      const others = prev.filter(
        (r) => (r.user || r.username) !== (created.user || created.username)
      );
      return [created, ...others];
    });

    // Make sure Owned gets set (one call, no spam)
    onEnsureOwned?.(setNum);

    // Refresh global stats (avg/count)
    await refreshSetDetail();

    return created;
  }

  async function clearMyReview() {
    if (!isLoggedIn) {
      alert("Please log in first.");
      navigate("/login");
      return;
    }

    try {
      setSavingRating(true);
      setRatingError(null);

      const resp = await fetch(
        `${API_BASE}/sets/${encodeURIComponent(setNum)}/reviews/me`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${effectiveToken}` },
        }
      );

      if (!resp.ok && resp.status !== 404) {
        const text = await resp.text();
        throw new Error(text || `Delete failed (${resp.status})`);
      }

      setReviews((prev) =>
        prev.filter((r) => (r.user || r.username) !== currentUsername)
      );
      setUserRating(null);
      setReviewText("");
      setShowReviewForm(false);

      await refreshSetDetail();
    } catch (err) {
      console.error("Error deleting review:", err);
      setRatingError(err.message || String(err));
    } finally {
      setSavingRating(false);
    }
  }

  async function handleStarClick(value) {
    if (!isLoggedIn) {
      alert("Please log in to rate this set.");
      navigate("/login");
      return;
    }

    const numeric = clampRating(value);
    if (numeric == null) return;

    // clicking same rating toggles (deletes my review)
    if (userRating != null && Number(userRating) === Number(numeric)) {
      await clearMyReview();
      return;
    }

    try {
      setSavingRating(true);
      setRatingError(null);
      setUserRating(numeric);

      // Important: do NOT send text at all so we don’t overwrite it.
      await upsertReview({ rating: numeric });
    } catch (err) {
      setRatingError(err.message || String(err));
    } finally {
      setSavingRating(false);
    }
  }

  async function handleReviewSubmit(e) {
    e.preventDefault();

    if (!isLoggedIn) {
      alert("Please log in to leave a review.");
      navigate("/login");
      return;
    }

    const text = reviewText.trim();
    const numericRating = userRating == null ? null : clampRating(userRating);

    if (!text && numericRating == null) {
      setReviewSubmitError("Please provide a rating, some text, or both.");
      return;
    }

    try {
      setReviewSubmitting(true);
      setReviewSubmitError(null);

      // Only send fields we actually want to change
      const payload = {};
      if (numericRating !== null) payload.rating = numericRating;
      if (text) payload.text = text;

      await upsertReview(payload);

      setShowReviewForm(false);
    } catch (err) {
      console.error("Error submitting review:", err);
      setReviewSubmitError(err.message || String(err));
    } finally {
      setReviewSubmitting(false);
    }
  }

  function scrollSimilar(direction) {
    const node = similarRowRef.current;
    if (!node) return;
    node.scrollBy({ left: direction * 240, behavior: "smooth" });
  }

  // -------------------------------
  // Loading / error / not found
  // -------------------------------
  if (loading) return <p style={{ padding: "1.5rem" }}>Loading set…</p>;

  if (error) {
    return (
      <div style={{ padding: "1.5rem" }}>
        <p style={{ color: "red" }}>Error: {error}</p>
        <button onClick={() => navigate(-1)}>← Back</button>
      </div>
    );
  }

  if (!setDetail) {
    return (
      <div style={{ padding: "1.5rem" }}>
        <p>Set not found.</p>
        <button onClick={() => navigate(-1)}>← Back</button>
      </div>
    );
  }

  const { name, year, theme, pieces, image_url, description } = setDetail;
  const isRetired =
    setDetail.status === "retired" ||
    setDetail.is_retired === true ||
    setDetail.retired === true;

  const textReviews = Array.isArray(reviews)
    ? reviews.filter((r) => typeof r.text === "string" && r.text.trim() !== "")
    : [];

  // -------------------------------
  // Render
  // -------------------------------
  return (
    <div style={{ padding: "1.5rem", maxWidth: "1000px", margin: "0 auto" }}>
      <button
        onClick={() => navigate(-1)}
        style={{
          marginBottom: "1.25rem",
          padding: "0.35rem 0.75rem",
          borderRadius: "999px",
          border: "1px solid #ddd",
          background: "white",
          cursor: "pointer",
          fontSize: "0.9rem",
        }}
      >
        ← Back
      </button>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 360px) minmax(0, 1fr)",
          gap: "2rem",
          alignItems: "flex-start",
        }}
      >
        <div style={{ maxWidth: "360px" }}>
          <div
            style={{
              borderRadius: "16px",
              border: "1px solid #eee",
              background: "white",
              padding: "1.25rem",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "260px",
            }}
          >
            {image_url ? (
              <img
                src={image_url}
                alt={name || setNum}
                style={{
                  maxWidth: "100%",
                  maxHeight: "320px",
                  objectFit: "contain",
                  display: "block",
                }}
              />
            ) : (
              <div
                style={{
                  width: "100%",
                  paddingTop: "70%",
                  borderRadius: "8px",
                  background:
                    "repeating-linear-gradient(45deg, #eee, #eee 10px, #f8f8f8 10px, #f8f8f8 20px)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#999",
                  fontSize: "0.9rem",
                }}
              >
                No image available
              </div>
            )}
          </div>
        </div>

        <div>
          <h1 style={{ margin: "0 0 0.25rem 0" }}>{name || "Unknown set"}</h1>
          <p style={{ margin: 0, color: "#555" }}>
            <strong>{setNum}</strong>
            {year && <> · {year}</>}
          </p>
          {theme && <p style={{ margin: "0.25rem 0 0 0", color: "#777" }}>{theme}</p>}
          {pieces && <p style={{ margin: "0.1rem 0 0 0", color: "#777" }}>{pieces} pieces</p>}
          {isRetired && (
            <p style={{ marginTop: "0.35rem", fontSize: "0.85rem", color: "#b45309" }}>
              ⏳ This set is retired
            </p>
          )}

          <p style={{ marginTop: "0.6rem", color: "#444", fontSize: "0.9rem" }}>
            ⭐ <strong>{displayAvgRating != null ? displayAvgRating.toFixed(1) : "—"}</strong>{" "}
            <span style={{ color: "#777" }}>
              (
              {displayRatingCount === 0
                ? "no ratings yet"
                : `${displayRatingCount} rating${displayRatingCount === 1 ? "" : "s"}`}
              )
            </span>
          </p>

          <section
            style={{
              marginTop: "1rem",
              padding: "0.9rem 1rem",
              borderRadius: "12px",
              border: "1px solid #e0e0e0",
              background: "#fafafa",
              display: "flex",
              flexDirection: "column",
              gap: "0.9rem",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              <button
                onClick={handleMarkOwnedClick}
                style={{
                  padding: "0.45rem 0.9rem",
                  borderRadius: "999px",
                  border: isOwned ? "none" : "1px solid #ccc",
                  backgroundColor: isOwned ? "#1f883d" : "#f5f5f5",
                  color: isOwned ? "white" : "#222",
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {isOwned ? "Owned ✓" : "Mark Owned"}
              </button>

              <button
                onClick={handleAddWishlistClick}
                style={{
                  padding: "0.45rem 0.9rem",
                  borderRadius: "999px",
                  border: isInWishlist ? "none" : "1px solid #ccc",
                  backgroundColor: isInWishlist ? "#b16be3" : "#f5f5f5",
                  color: isInWishlist ? "white" : "#222",
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {isInWishlist ? "In Wishlist ★" : "Add to Wishlist"}
              </button>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
              <span style={{ fontSize: "0.9rem", color: "#444" }}>Your rating:</span>

              <div
                style={{
                  position: "relative",
                  display: "inline-block",
                  fontSize: "1.8rem",
                  cursor: savingRating ? "default" : "pointer",
                  lineHeight: 1,
                  opacity: savingRating ? 0.7 : 1,
                }}
                onMouseMove={(e) => {
                  if (savingRating) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const x = e.clientX - rect.left;
                  const relative = x / rect.width;
                  setHoverRating(clampRating(relative * 5));
                }}
                onMouseLeave={() => setHoverRating(null)}
                onClick={(e) => {
                  if (savingRating) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const x = e.clientX - rect.left;
                  const relative = x / rect.width;
                  handleStarClick(clampRating(relative * 5));
                }}
              >
                <div style={{ color: "#ccc" }}>★★★★★</div>
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    overflow: "hidden",
                    whiteSpace: "nowrap",
                    color: "#f39c12",
                    width: `${(((hoverRating ?? userRating) || 0) / 5) * 100}%`,
                    pointerEvents: "none",
                  }}
                >
                  ★★★★★
                </div>
              </div>

              {userRating != null && (
                <span style={{ fontSize: "0.9rem", color: "#555" }}>
                  {Number(userRating).toFixed(1)}
                </span>
              )}

              {ratingError && (
                <span style={{ fontSize: "0.85rem", color: "red" }}>{ratingError}</span>
              )}
            </div>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.5rem",
                alignItems: "center",
              }}
            >
              <button
                type="button"
                onClick={() => {
                  const t =
                    myReview && typeof myReview.text === "string" ? myReview.text : "";
                  setReviewText(t);
                  setShowReviewForm((prev) => !prev);
                }}
                style={{
                  padding: "0.45rem 0.9rem", // same as Owned/Wishlist
                  borderRadius: "999px",
                  border: "1px solid #ccc",
                  backgroundColor: "#f5f5f5",
                  color: "#222",
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {showReviewForm
                  ? "Cancel"
                  : myReview
                  ? "Edit my review"
                  : "Leave a review"}
              </button>

              {myReview && (
                <button
                  type="button"
                  onClick={clearMyReview}
                  disabled={savingRating}
                  style={{
                    padding: "0.45rem 0.9rem", // same size
                    borderRadius: "999px",
                    border: "1px solid #dc2626",
                    backgroundColor: "white",
                    color: "#dc2626",
                    fontWeight: 600,
                    cursor: savingRating ? "default" : "pointer",
                    opacity: savingRating ? 0.7 : 1,
                  }}
                >
                  Delete my review
                </button>
              )}

              {!effectiveToken && (
                <span style={{ fontSize: "0.85rem", color: "#777" }}>
                  Log in to rate or review this set.
                </span>
              )}
            </div>

          </section>
        </div>
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2 style={{ marginTop: 0, marginBottom: "0.5rem", fontSize: "1.1rem" }}>About this set</h2>
        {description ? (
          <p style={{ marginTop: 0, color: "#444" }}>{description}</p>
        ) : (
          <p style={{ marginTop: 0, color: "#777" }}>No description available yet.</p>
        )}
      </section>

      <section style={{ marginTop: "2.5rem" }}>
        <h2 style={{ marginBottom: "0.75rem", fontSize: "1.1rem" }}>Reviews</h2>

        {showReviewForm && (
          <form
            onSubmit={handleReviewSubmit}
            style={{
              marginBottom: "1rem",
              borderRadius: "8px",
              border: "1px solid #e0e0e0",
              padding: "0.75rem 0.9rem",
              background: "#fafafa",
            }}
          >
            <textarea
              value={reviewText}
              onChange={(e) => setReviewText(e.target.value)}
              placeholder="What did you think of this set?"
              style={{
                width: "100%",
                minHeight: "80px",
                padding: "0.5rem",
                borderRadius: "6px",
                border: "1px solid #ccc",
                fontFamily: "inherit",
                fontSize: "0.95rem",
              }}
            />

            {reviewSubmitError && (
              <p style={{ color: "red", marginTop: "0.35rem" }}>{reviewSubmitError}</p>
            )}

            <button
              type="submit"
              disabled={reviewSubmitting}
              style={{
                marginTop: "0.5rem",
                padding: "0.45rem 0.9rem",
                borderRadius: "999px",
                border: "none",
                backgroundColor: reviewSubmitting ? "#888" : "#1f883d",
                color: "white",
                fontWeight: 600,
                cursor: reviewSubmitting ? "default" : "pointer",
              }}
            >
              {reviewSubmitting ? "Saving…" : "Save review"}
            </button>
          </form>
        )}

        {reviewsLoading && <p>Loading reviews…</p>}
        {reviewsError && <p style={{ color: "red" }}>Error loading reviews: {reviewsError}</p>}

        {!reviewsLoading && !reviewsError && textReviews.length === 0 && (
          <p style={{ color: "#666" }}>No reviews yet. Be the first!</p>
        )}

        {!reviewsLoading && !reviewsError && textReviews.length > 0 && (
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: "0.75rem",
            }}
          >
            {textReviews.map((r) => {
              const u = r.user || r.username;
              const isMine = currentUsername && u === currentUsername;
              return (
                <li
                  key={r.id ?? `${u}-${r.created_at ?? Math.random()}`}
                  style={{
                    border: "1px solid #e0e0e0",
                    borderRadius: "8px",
                    padding: "0.75rem 0.9rem",
                    background: isMine ? "#f0fdf4" : "white",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "0.25rem",
                    }}
                  >
                    <div style={{ fontSize: "0.9rem", color: "#555" }}>
                      <strong>{isMine ? "You" : u || "Anonymous"}</strong>
                    </div>
                    {typeof r.rating === "number" && (
                      <div style={{ fontSize: "0.9rem", color: "#f39c12" }}>
                        {r.rating.toFixed(1)} ★
                      </div>
                    )}
                  </div>

                  {r.text && <p style={{ margin: 0, fontSize: "0.95rem", color: "#333" }}>{r.text}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {(similarLoading || similarError || (similarSets && similarSets.length > 0)) && (
        <section style={{ marginTop: "2.5rem", marginBottom: "1rem" }}>
          <h2 style={{ marginTop: 0, marginBottom: "0.5rem", fontSize: "1.1rem" }}>
            Similar sets you might like
          </h2>

          {similarLoading && <p>Loading similar sets…</p>}
          {similarError && <p style={{ color: "red" }}>Error loading similar sets: {similarError}</p>}

          {!similarLoading && !similarError && similarSets && similarSets.length > 0 && (
            <div style={{ position: "relative", marginTop: "0.5rem" }}>
              <div ref={similarRowRef} style={{ overflowX: "auto", paddingBottom: "0.5rem" }}>
                <ul style={{ display: "flex", gap: "0.75rem", listStyle: "none", padding: 0, margin: 0 }}>
                  {similarSets.map((s) => (
                    <li key={s.set_num} style={{ minWidth: "220px", maxWidth: "220px", flex: "0 0 auto" }}>
                      <SetCard
                        set={s}
                        isOwned={ownedSetNums ? ownedSetNums.has(s.set_num) : false}
                        isInWishlist={wishlistSetNums ? wishlistSetNums.has(s.set_num) : false}
                        onMarkOwned={onMarkOwned}
                        onAddWishlist={onAddWishlist}
                        variant="default"
                      />
                    </li>
                  ))}
                </ul>
              </div>

              <button
                type="button"
                onClick={() => scrollSimilar(-1)}
                style={{
                  position: "absolute",
                  top: "50%",
                  left: 0,
                  transform: "translateY(-50%)",
                  borderRadius: "999px",
                  border: "1px solid #ddd",
                  background: "white",
                  padding: "0.2rem 0.4rem",
                  cursor: "pointer",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                }}
              >
                ←
              </button>

              <button
                type="button"
                onClick={() => scrollSimilar(1)}
                style={{
                  position: "absolute",
                  top: "50%",
                  right: 0,
                  transform: "translateY(-50%)",
                  borderRadius: "999px",
                  border: "1px solid #ddd",
                  background: "white",
                  padding: "0.2rem 0.4rem",
                  cursor: "pointer",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                }}
              >
                →
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default SetDetailPage;