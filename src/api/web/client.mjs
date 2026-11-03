// HTTP and time conversion stay separate from the DOM so edge cases are executable tests.
export const ZONE = "Europe/Kyiv";
const partsFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23", numberingSystem: "latn",
});
const displayFormatter = new Intl.DateTimeFormat("uk-UA", {
  timeZone: ZONE, weekday: "short", day: "numeric", month: "short", year: "numeric",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

function parts(value) {
  return Object.fromEntries(partsFormatter.formatToParts(new Date(value))
    .filter(p => ["year", "month", "day", "hour", "minute"].includes(p.type))
    .map(p => [p.type, Number(p.value)]));
}
function wallEpoch(p) { return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute); }
export function kyivDate(value = Date.now()) {
  const p = parts(value);
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}
export function formatWhen(value) { return displayFormatter.format(new Date(value)); }

export function kyivTimestamp(localValue) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(localValue);
  if (!match) throw new Error("Укажіть дату й час у форматі рік-місяць-день, години та хвилини.");
  const [, y, m, d, h, min] = match.map(Number);
  const wanted = { year: y, month: m, day: d, hour: h, minute: min };
  const naive = wallEpoch(wanted);
  const offsets = new Set([-36, 0, 36].map(hours => {
    const stamp = naive + hours * 3600000;
    return wallEpoch(parts(stamp)) - stamp;
  }));
  const matches = [...offsets].map(offset => naive - offset)
    .filter(stamp => Object.keys(wanted).every(key => parts(stamp)[key] === wanted[key]));
  if (matches.length !== 1) {
    throw new Error(matches.length ? "Цей час повторюється при переході на зимовий час. Оберіть однозначний час."
      : "Такої місцевої дати чи години немає, зокрема через перехід на літній час. Оберіть інший час.");
  }
  return new Date(matches[0]).toISOString();
}

export function csrfCookie(cookie = globalThis.document?.cookie || "") {
  const entry = cookie.split(";").map(p => p.trim()).find(p => p.startsWith("unislot_csrf="));
  try { return entry ? decodeURIComponent(entry.slice("unislot_csrf=".length)) : ""; }
  catch { return ""; }
}

export class ApiError extends Error {
  constructor(status, problem, retryAfter = 0) {
    super(problem.detail || problem.title || "Не вдалося виконати запит.");
    this.status = status;
    this.problem = problem;
    this.retryAfter = retryAfter;
  }
}

export class Client {
  constructor(fetcher = (...args) => globalThis.fetch(...args), readCsrf = csrfCookie) {
    this.fetcher = fetcher;
    this.readCsrf = readCsrf;
    this.csrf = "";
  }
  async request(path, { method = "GET", body, key } = {}) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      const csrf = this.csrf || this.readCsrf();
      if (csrf) headers["X-CSRF-Token"] = csrf;
    }
    if (key) headers["Idempotency-Key"] = key;
    let response;
    try {
      response = await this.fetcher(`/api/v1${path}`, {
        method, headers, credentials: "same-origin", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20000),
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new Error("Немає з'єднання із сервером. Перевірте мережу й повторіть дію. Стан бронювання можна перевірити в «Мої бронювання».");
    }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const seconds = Number(response.headers.get("Retry-After"));
      throw new ApiError(response.status, data || { title: "Сервер тимчасово недоступний. Повторіть дію пізніше." },
        Number.isFinite(seconds) && seconds > 0 ? seconds : 0);
    }
    return data;
  }
}

export function queryString(values) {
  return new URLSearchParams(Object.entries(values).filter(([, value]) => value !== "" && value != null)).toString();
}

export async function allPages(client, path) {
  const result = [];
  for (let offset = 0; offset <= 10000;) {
    const separator = path.includes("?") ? "&" : "?";
    const page = await client.request(`${path}${separator}limit=100&offset=${offset}`);
    if (!page || !Array.isArray(page.items)) throw new Error("Не вдалося прочитати список. Оновіть сторінку.");
    result.push(...page.items);
    if (!page.pagination?.has_more) return result;
    if (!page.items.length) throw new Error("Не вдалося завантажити наступну сторінку. Повторіть пошук.");
    offset += page.items.length;
  }
  throw new Error("Список завеликий для повного завантаження. Звузьте пошук.");
}
