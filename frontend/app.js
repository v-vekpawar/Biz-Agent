// Change this once your backend is deployed (Phase 10).
// For local dev, this matches `uvicorn app.main:app --reload` on port 8000.
const API_BASE_URL = "http://127.0.0.1:8000";

const pingBtn = document.getElementById("pingBtn");
const result = document.getElementById("result");

pingBtn.addEventListener("click", async () => {
  result.textContent = "Pinging...";
  result.className = "text-sm font-mono mt-4 text-slate-400";

  try {
    const res = await fetch(`${API_BASE_URL}/api/hello`);
    if (!res.ok) throw new Error(`Server responded ${res.status}`);
    const data = await res.json();

    result.textContent = `✅ ${data.message}`;
    result.className = "text-sm font-mono mt-4 text-green-600";
  } catch (err) {
    result.textContent = `❌ Could not reach backend: ${err.message}`;
    result.className = "text-sm font-mono mt-4 text-red-600";
  }
});
