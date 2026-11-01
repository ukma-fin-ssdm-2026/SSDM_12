// Requirements: A-007, FR-030, FR-051, SEC-002, USAB-001, QA-09.
import test from "node:test";
import assert from "node:assert/strict";
import { Client, ApiError, allPages, csrfCookie, kyivTimestamp, kyivDate, queryString } from "../../src/api/web/client.mjs";

test("Kyiv wall time uses correct winter and summer offsets independently of machine TZ", () => {
  assert.equal(kyivTimestamp("2026-11-01T10:00"), "2026-11-01T08:00:00.000Z");
  assert.equal(kyivTimestamp("2026-06-01T10:00"), "2026-06-01T07:00:00.000Z");
  assert.equal(kyivDate("2026-10-31T23:15:00Z"), "2026-11-01");
});
test("nonexistent spring time and repeated autumn time are rejected without silent movement", () => {
  assert.throws(() => kyivTimestamp("2026-03-29T03:30"), /немає/);
  assert.throws(() => kyivTimestamp("2026-10-25T03:30"), /повторюється/);
  assert.throws(() => kyivTimestamp("2026-02-31T10:00"), /немає/);
  assert.throws(() => kyivTimestamp("bad"), /форматі/);
});
test("only CSRF cookie is read; malformed encoding fails closed", () => {
  assert.equal(csrfCookie("other=1; unislot_csrf=test-value; unislot_session=invisible"), "test-value");
  assert.equal(csrfCookie("unislot_csrf=%XX"), "");
  assert.equal(csrfCookie("other=1"), "");
});
test("writes use same-origin cookies, CSRF and explicit idempotency keys", async () => {
  let actual;
  const client = new Client(async (...args) => { actual = args; return new Response('{"id":"booking"}', { status: 201 }); }, () => "csrf-fixture");
  const result = await client.request("/bookings", { method: "POST", body: { slot_id: "slot" }, key: "idempotency-fixture" });
  assert.equal(result.id, "booking");
  assert.equal(actual[0], "/api/v1/bookings");
  assert.equal(actual[1].credentials, "same-origin");
  assert.equal(actual[1].headers["X-CSRF-Token"], "csrf-fixture");
  assert.equal(actual[1].headers["Idempotency-Key"], "idempotency-fixture");
  assert.equal(actual[1].headers.Authorization, undefined);
});
test("GET sends no CSRF or request body; session revocation accepts 204", async () => {
  let options;
  const client = new Client(async (_, args) => { options = args; return new Response(null, { status: 204 }); });
  assert.equal(await client.request("/auth/me"), null);
  assert.equal(options.headers["X-CSRF-Token"], undefined);
  assert.equal(options.body, undefined);
});
test("problem responses preserve actionable details and retry delay", async () => {
  const client = new Client(async () => new Response(JSON.stringify({ code: "LOGIN_THROTTLED", detail: "Зачекайте", action: "Спробуйте пізніше" }), { status: 429, headers: { "Retry-After": "30" } }));
  await assert.rejects(client.request("/auth/login", { method: "POST" }), error => error instanceof ApiError && error.status === 429 && error.retryAfter === 30 && error.problem.code === "LOGIN_THROTTLED");
});
test("network loss and non-JSON server failure are understandable errors", async () => {
  const offline = new Client(async () => { throw new TypeError("network fixture"); });
  await assert.rejects(offline.request("/bookings"), /Немає з'єднання/);
  const unavailable = new Client(async () => new Response("not JSON", { status: 503 }));
  await assert.rejects(unavailable.request("/bookings"), error => error instanceof ApiError && error.status === 503);
});
test("offset pagination loads every page and cannot loop on empty has_more", async () => {
  const paths = [];
  const records = await allPages({ request: async path => {
    paths.push(path); return { items: paths.length === 1 ? ["first"] : ["second"], pagination: { has_more: paths.length === 1 } };
  } }, "/resources?type=room");
  assert.deepEqual(records, ["first", "second"]);
  assert.equal(paths[1], "/resources?type=room&limit=100&offset=1");
  await assert.rejects(allPages({ request: async () => ({ items: [], pagination: { has_more: true } }) }, "/resources"), /наступну сторінку/);
});
test("query strings omit empty filters but retain zero and escape values", () => {
  assert.equal(queryString({ date: "", cursor: null, offset: 0, q: "a+b" }), "offset=0&q=a%2Bb");
});
