"use strict";
const el = id => document.getElementById(id);
let lastResult = null;
async function api(path, body) {
  const headers = {Authorization: `Bearer ${el("token").value}`};
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(`/v1/ghostpay/${path}`, {method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined, cache: "no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
  return data;
}
function list(id, values) {
  el(id).replaceChildren(...(values.length ? values : ["None reported"]).map(value => {
    const li = document.createElement("li"); li.textContent = value; return li;
  }));
}
function render(data, simulation) {
  lastResult = data;
  el("results").hidden = false;
  el("mode").textContent = simulation ? "SIMULATION — NO PAYMENT EXECUTED" : "READ-ONLY REPLAY — NO PAYMENT EXECUTED";
  el("verdict").replaceChildren(...[
    ["Recorded", data.original_outcome], ["Recomputed", data.recomputed_outcome],
    ["Consistency", data.consistency_status], ["Integrity", data.integrity_valid ? "Checks passed" : "Failure detected"]
  ].map(([name, value]) => {const div = document.createElement("div"); const small = document.createElement("small"); small.textContent = name; const strong = document.createElement("strong"); strong.textContent = value; div.append(small, strong); return div;}));
  el("reasons").textContent = `Original: ${data.original_reason_codes.join(", ")}\nRecomputed: ${data.recomputed_reason_codes.join(", ")}`;
  list("anomalies", [...data.changed_constraints, ...data.anomalies]);
  list("missing", data.missing_evidence);
  list("timeline", data.timeline.map(event => `${event.sequence_number} · ${event.occurred_at} · ${event.summary} · integrity ${event.integrity_verified ? "passed" : "failed"}`));
  el("raw").textContent = JSON.stringify(data, null, 2);
}
async function run(action) {
  el("results").hidden = true;
  lastResult = null;
  const buttons = document.querySelectorAll("button"); buttons.forEach(button => button.disabled = true);
  el("message").textContent = "Working…";
  try {await action(); el("message").textContent = "Complete. No financial action was executed.";}
  catch (error) {el("message").textContent = error.message;}
  finally {buttons.forEach(button => button.disabled = false);}
}
el("sample").onclick = () => run(async () => {const sample = await api("example"); el("record").value = JSON.stringify(sample.request, null, 2); el("source").textContent = "SOURCE: SYNTHETIC DEMO — NOT A LIVE PAYMENT";});
el("record").oninput = () => {el("source").textContent = "SOURCE: USER-SUPPLIED / NOT AUTHENTICATED"; el("results").hidden = true; lastResult = null;};
el("file").onchange = () => run(async () => {const file = el("file").files[0]; if (!file) return; if (file.size > 2000000) throw new Error("Snapshot exceeds 2 MB"); const record = JSON.parse(await file.text()); el("record").value = JSON.stringify(record, null, 2); el("record").oninput();});
el("replay").onclick = () => run(async () => render(await api("replay", JSON.parse(el("record").value)), false));
el("simulate").onclick = () => run(async () => {
  const overrides = {};
  for (const [id, field] of [["limit", "per_tx_limit_minor"], ["amount", "amount_override_minor"]]) {
    if (el(id).value !== "") {const value = Number(el(id).value); if (!Number.isSafeInteger(value)) throw new Error("Use integer minor units"); overrides[field] = value;}
  }
  if (el("merchant").value.trim()) overrides.merchant_override = el("merchant").value.trim();
  render(await api("simulate", {request: JSON.parse(el("record").value), overrides}), true);
});
el("export").onclick = () => {if (!lastResult) return; const link = document.createElement("a"); const url = URL.createObjectURL(new Blob([JSON.stringify(lastResult, null, 2)], {type:"application/json"})); link.href = url; link.download = "ghostpay-result.json"; link.click(); URL.revokeObjectURL(url);};
