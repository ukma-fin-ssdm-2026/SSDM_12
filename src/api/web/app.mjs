import { Client, ApiError, allPages, formatWhen, kyivDate, kyivTimestamp, queryString } from "./client.mjs";

const client = new Client();
const root = document.querySelector("#app");
const state = { user: null, schema: {}, resources: [], route: "", search: {}, cursor: null,
  replacing: null, resourceId: "", providerTab: "slots", userQuery: "", bookingFilter: "", keys: new Map(), epoch: 0, flash: null };
const roleNames = { student: "Студент", provider: "Провайдер", admin: "Адміністратор" };
const typeNames = { room: "Аудиторія", consultation: "Консультація" };
const week = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"];
const bookingStates = { active: "Майбутнє", in_progress: "Триває", completed: "Завершено", cancelled: "Скасовано" };
const availabilityNames = { available: "Вільний", booked: "Заброньований", blocked: "Заблокований", started: "Триває", completed: "Завершений", outside_horizon: "Поза горизонтом запису" };
const routes = [
  ["search", "Знайти час", "⌕", "student"], ["bookings", "Мої бронювання", "▤", "student"],
  ["availability", "Доступність", "▦", "provider"], ["resources", "Ресурси", "▧", "admin"],
  ["calendar", "Календар ресурсу", "▦", "provider"], ["audit", "Журнал аудиту", "≡", "admin"],
  ["users", "Користувачі", "♧", "admin"], ["policy", "Правила бронювання", "⚙", "admin"],
  ["notifications", "Сповіщення", "◷", null],
];

// All API/user text enters the document as text nodes, never HTML.
function E(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (["value", "disabled", "required", "hidden", "selected"].includes(key)) el[key] = value;
    else el.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child != null && child !== false) el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}
function button(text, click, kind = "secondary", attrs = {}) {
  const node = E("button", { type: "button", class: `btn ${kind}`, ...attrs }, text);
  node.addEventListener("click", async event => {
    if (node.disabled) return;
    const pending = click(event);
    if (pending && typeof pending.then === "function") {
      node.disabled = true;
      try { await pending; } finally { node.disabled = false; }
    }
  });
  return node;
}
const pill = (text, kind = "") => E("span", { class: `pill ${kind}` }, text);
const field = (label, control, help = "") => E("label", { class: "field" }, E("span", {}, label), control, help && E("small", {}, help));
const input = (name, type = "text", value = "", attrs = {}) => E("input", { name, type, value, ...attrs });
const select = (name, options, value = "", attrs = {}) => E("select", { name, ...attrs }, options.map(([id, label]) => E("option", { value: id, selected: String(id) === String(value) }, label)));
const empty = (title, detail) => E("div", { class: "empty" }, E("h3", {}, title), E("p", {}, detail));
const loading = () => E("p", { class: "loading", role: "status" }, "Завантажуємо дані…");
const isRole = role => state.user?.roles.includes(role);
const allowedRoutes = () => routes.filter(([, , , role]) => !role || isRole(role));
const announce = text => { document.querySelector("#announcer").textContent = text; };

// Validation hints come from the same Code-First schemas as the server (A-005, SEC-001).
function constraints(model, name) {
  const property = state.schema[model]?.properties?.[name] || {};
  const p = property.anyOf?.find(s => s.type === "integer") || property;
  return { min: p.minimum, max: p.maximum, step: p.multipleOf,
    minlength: p.minLength, maxlength: p.maxLength };
}

function showNotice(text, kind = "success", target = document.querySelector("#notices"), details = []) {
  if (!target?.isConnected) return;
  const box = E("div", { class: `notice ${kind}`, role: kind === "error" ? "alert" : "status" },
    E("span", { "aria-hidden": "true" }, kind === "error" ? "!" : "✓"),
    E("div", { class: "notice-body" }, E("p", {}, text), details.length ? E("ul", {}, details.map(d => E("li", {}, d))) : null),
    button("×", () => box.remove(), "text", { "aria-label": "Закрити повідомлення" }));
  target.replaceChildren(box);
  announce(text);
}

function showError(error, target) {
  if (error instanceof ApiError && error.status === 401 && state.user) {
    state.user = null; state.epoch++; client.csrf = ""; state.keys.clear(); state.replacing = null;
    document.querySelectorAll("dialog").forEach(d => d.remove());
    renderAuth("login");
    showNotice("Сесію завершено. Увійдіть знову, щоб продовжити.", "error");
    return;
  }
  const p = error.problem || {};
  const labels = { password: "Пароль", email: "Електронна пошта", full_name: "Ім'я", starts_at: "Початок",
    ends_at: "Кінець", duration_minutes: "Тривалість", slot_minutes: "Тривалість слота", capacity: "Місткість", name: "Назва" };
  const details = (p.errors || []).map(e => `${labels[e.field.split(".").at(-1)] || "Поле форми"}: ${e.message}`);
  if (p.action) details.push(p.action);
  if (error.retryAfter) details.push(`Повторіть через ${error.retryAfter} с.`);
  if (p.request_id) details.push(`Код запиту для звернення по допомогу: ${p.request_id}`);
  showNotice(error.message || "Не вдалося виконати дію. Повторіть пізніше.", "error", target, details);
}

async function run(task, target) {
  const epoch = state.epoch;
  try { return await task(); } catch (error) { if (epoch === state.epoch) showError(error, target); return null; }
}

function form(fields, save, label, { grid = false, footer = [] } = {}) {
  const errorBox = E("div", { class: "form-errors" });
  const set = E("fieldset", { class: grid ? "form-grid" : "form-stack" }, fields,
    E("div", { class: grid ? "dialog-footer span-2" : "dialog-footer" }, footer,
      E("button", { class: "btn", type: "submit" }, label)));
  const element = E("form", { onSubmit: async event => {
    event.preventDefault();
    if (set.disabled) return;
    const data = Object.fromEntries(new FormData(element));
    set.disabled = true;
    element.setAttribute("aria-busy", "true");
    errorBox.replaceChildren();
    await run(() => save(data), errorBox);
    set.disabled = false;
    element.removeAttribute("aria-busy");
  } }, errorBox, set);
  return element;
}

function dialog(title, build) {
  document.querySelectorAll("dialog").forEach(d => d.remove());
  const modal = E("dialog", { "aria-label": title });
  const close = () => { modal.close(); modal.remove(); };
  modal.append(E("div", { class: "dialog-head" }, E("h2", {}, title),
    button("×", close, "text", { "aria-label": "Закрити вікно" })),
  E("div", { class: "dialog-body" }, build(close)));
  modal.addEventListener("close", () => modal.remove());
  document.body.append(modal);
  modal.showModal();
  modal.querySelector("input, select, textarea")?.focus();
}

function confirmAction(title, detail, label, action) {
  dialog(title, close => {
    const target = E("div");
    const confirm = button(label, () => run(async () => {
      confirm.disabled = true;
      try { await action(); close(); } finally { confirm.disabled = false; }
    }, target), /Скасувати|Зняти/.test(label) ? "danger" : "");
    return E("div", {}, target, E("p", { class: "inline-note" }, detail),
      E("div", { class: "dialog-footer" }, button("Залишити як є", close), confirm));
  });
}

function renderAuth(mode = "login", email = "") {
  state.route = "";
  announce("");
  const registering = mode === "register";
  const story = E("section", { class: "auth-story" }, E("a", { class: "brand", href: "/" }, E("span", { class: "brand-mark" }, "U"), "UniSlot"),
    E("div", { class: "story-copy" }, E("p", { class: "eyebrow" }, "Простір для зустрічей"),
      E("h1", {}, "Менше узгоджень.", E("br"), "Більше часу на важливе."),
      E("p", { class: "lead" }, "Консультації та аудиторії в одному місці. Оберіть зручний час, а про решту подбає UniSlot."),
      E("div", { class: "calendar-art", "aria-hidden": "true" }, E("div", { class: "split" }, E("strong", {}, "Ваш наступний тиждень"), "▦"),
        E("div", { class: "mini-days" }, ["Пн", "Вт", "Ср", "Чт", "Пт"].map((d, i) => E("div", { class: `mini-day ${i === 2 ? "selected" : ""}` }, d))),
        E("div", { class: "mini-event" }, "Час для нових ідей", "↗"))),
    E("p", { class: "story-foot" }, "Навчальний проєкт · НаУКМА · SSDM_12"));
  const fields = [];
  if (registering) fields.push(field("Повне ім'я", input("full_name", "text", "", { required: true, autocomplete: "name", ...constraints("RegisterIn", "full_name") })));
  fields.push(field("Електронна пошта", input("email", "email", email, { required: true, autocomplete: "username", ...constraints("RegisterIn", "email") })));
  // Python validates Unicode code points; HTML minlength/maxlength count UTF-16 units.
  const passwordRules = state.schema[registering ? "RegisterIn" : "LoginIn"]?.properties?.password || {};
  fields.push(field("Пароль", input("password", "password", "", { required: true, autocomplete: registering ? "new-password" : "current-password" }), registering ? `Щонайменше ${passwordRules.minLength || 15} символів. Можна використати довгу фразу з пробілами.` : ""));
  if (registering) fields.push(field("Повторіть пароль", input("repeat", "password", "", { required: true, autocomplete: "new-password" })));
  const content = E("div", { class: "auth-content" }, E("p", { class: "eyebrow" }, "Раді вас бачити"),
    E("h2", {}, registering ? "Створіть свій акаунт" : "Увійдіть у свій кабінет"),
    E("p", { class: "intro muted" }, registering ? "Після реєстрації ви зможете шукати й бронювати час." : "Ваші зустрічі, ресурси та сповіщення — поруч."),
    E("div", { class: "switcher", role: "group", "aria-label": "Спосіб входу" },
      button("Увійти", () => renderAuth("login"), registering ? "" : "active"),
      button("Зареєструватися", () => renderAuth("register"), registering ? "active" : "")),
    E("div", { id: "notices" }),
    form(fields, async data => {
      const length = [...data.password].length;
      if (passwordRules.minLength && length < passwordRules.minLength) throw new Error(`Пароль має містити щонайменше ${passwordRules.minLength} символів.`);
      if (passwordRules.maxLength && length > passwordRules.maxLength) throw new Error(`Пароль має містити не більше ${passwordRules.maxLength} символів.`);
      if (registering) {
        if (data.password !== data.repeat) throw new Error("Паролі не збігаються. Перевірте обидва поля.");
        await client.request("/auth/register", { method: "POST", body: { full_name: data.full_name, email: data.email, password: data.password } });
        renderAuth("login", data.email);
        showNotice("Акаунт створено. Увійдіть із вашим паролем.");
      } else {
        const signed = await client.request("/auth/login", { method: "POST", body: data });
        client.csrf = signed.csrf_token;
        state.resources = await allPages(client, "/resources");
        state.user = signed.user; state.epoch++; state.keys.clear();
        renderShell();
      }
    }, registering ? "Створити акаунт" : "Увійти в кабінет"),
    E("p", { class: "auth-note" }, "Для студентів, викладачів і відповідальних за аудиторії."));
  root.replaceChildren(E("div", { class: "auth-page" }, story, E("main", { id: "main", class: "auth-pane" }, content)));
}

function renderShell() {
  const user = state.user;
  const nav = E("nav", { "aria-label": "Головна навігація" }, allowedRoutes().map(([key, text, icon]) =>
    E("a", { href: `#/${key}`, class: "nav-link", "data-route": key }, E("span", { class: "nav-icon", "aria-hidden": "true" }, icon), text)));
  const initials = user.full_name.split(/\s+/).slice(0, 2).map(s => s[0]).join("").toUpperCase();
  root.replaceChildren(E("div", { class: "workspace" },
    E("aside", { class: "sidebar" }, E("a", { class: "brand", href: `#/${allowedRoutes()[0][0]}` }, E("span", { class: "brand-mark" }, "U"), "UniSlot"),
      nav, E("div", { class: "sidebar-foot" }, "Один простір для вашого часу.", E("br"), "НаУКМА · SSDM_12")),
    E("div", { class: "main-column" }, E("header", { class: "topbar" }, E("span", { class: "subtle" }, "Усі години — за Києвом"),
      E("div", { class: "row" }, E("div", { class: "identity" }, E("div", { class: "avatar", "aria-hidden": "true" }, initials),
        E("div", {}, E("div", { class: "identity-name" }, user.full_name), E("div", { class: "identity-role" }, user.roles.map(r => roleNames[r] || r).join(" · ")))),
      button("Вийти", () => run(async () => {
        await client.request("/auth/logout", { method: "POST" });
        state.user = null; state.epoch++; client.csrf = ""; state.replacing = null; state.keys.clear(); renderAuth();
      }), "text"))), E("main", { id: "main", class: "content", tabindex: "-1" }))));
  navigate();
}

function heading(main, title, description, action) {
  main.append(E("div", { class: "page-heading" }, E("div", {}, E("p", { class: "eyebrow" }, "Ваш кабінет"),
    E("h1", {}, title), E("p", { class: "muted" }, description)), action || pill("Europe/Kyiv")), E("div", { id: "notices" }));
}
function footer(main) { main.append(E("footer", { class: "view-footer" }, E("span", {}, "UniSlot · НаУКМА"), E("span", {}, "Усі дати та години відображено за Києвом"))); }
function go(route) { if (location.hash === `#/${route}`) navigate(); else location.hash = `/${route}`; }
function navigate() {
  if (!state.user) return;
  const requested = location.hash.replace(/^#\//, "");
  const route = allowedRoutes().some(([key]) => key === requested) ? requested : allowedRoutes()[0][0];
  state.route = route;
  document.querySelectorAll(".nav-link").forEach(a => { a.classList.toggle("active", a.dataset.route === route); if (a.dataset.route === route) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  const host = document.querySelector("#main");
  const main = E("div", { class: "page" }); host.replaceChildren(main);
  document.title = `${routes.find(([key]) => key === route)[1]} · UniSlot`;
  const pages = { search: showSearch, bookings: showBookings, availability: showAvailability, resources: showResources, users: showUsers, policy: showPolicy, notifications: showNotifications, calendar: showCalendar, audit: showAudit };
  void run(() => pages[route](main));
  if (state.flash) { showNotice(state.flash); state.flash = null; }
}
window.addEventListener("hashchange", navigate);

function offsetPager(target, metadata, load) {
  const { limit, offset, total, has_more } = metadata;
  target.append(E("div", { class: "pager" }, button("← Назад", () => load(Math.max(0, offset - limit)), "secondary small", { disabled: offset === 0 }),
    E("span", {}, total ? `${offset + 1}–${Math.min(offset + limit, total)} із ${total}` : "0 записів"),
    button("Далі →", () => load(offset + limit), "secondary small", { disabled: !has_more })));
}

async function showSearch(main) {
  heading(main, "Знайдіть зручний час", "Оберіть консультацію чи аудиторію — і забронюйте вільний слот.");
  if (state.replacing) main.append(E("div", { class: "notice info reschedule" }, E("div", { class: "notice-body" },
    E("strong", {}, "Перенесення бронювання"), E("p", {}, "Оберіть інший слот. Поки перенесення не завершене, попереднє бронювання залишається чинним.")),
    button("Скасувати перенесення", () => { state.replacing = null; navigate(); }, "secondary small")));
  const providers = [...new Map(state.resources.map(r => [r.provider.id, r.provider.full_name])).entries()];
  const type = select("resource_type", [["", "Усі типи"], ["consultation", "Консультації"], ["room", "Аудиторії"]], state.search.resource_type);
  const capacity = input("min_capacity", "number", state.search.min_capacity || "", { min: 1, max: 1000, step: 1, placeholder: "Будь-яка" });
  const toggleCapacity = () => { capacity.disabled = type.value === "consultation"; if (capacity.disabled) capacity.value = ""; };
  type.addEventListener("change", toggleCapacity); toggleCapacity();
  const results = E("div");
  const search = form([field("Тип ресурсу", type), field("Провайдер", select("provider_id", [["", "Усі провайдери"], ...providers], state.search.provider_id)),
    field("Дата за Києвом", input("date", "date", state.search.date || "", { min: kyivDate() })), field("Відвідувачів від", capacity)],
  async data => { state.search = data; state.cursor = null; await load(); }, "Знайти час");
  search.classList.add("panel"); search.querySelector("fieldset").className = "filters";
  search.querySelector(".dialog-footer").className = "filter-submit";
  main.append(search, E("div", { class: "section-heading" }, E("h2", {}, "Доступні слоти"), E("span", { class: "count" }, "Лише вільний час")), results);
  footer(main);
  let request = 0;
  async function load(cursor = null, append = false) {
    const current = ++request;
    if (!append) results.replaceChildren(loading());
    const page = await client.request(`/slots?${queryString({ ...state.search, limit: 12, cursor })}`);
    if (!main.isConnected || current !== request) return;
    let cards = results.querySelector(".cards");
    if (!append) { cards = E("div", { class: "cards" }); results.replaceChildren(cards); }
    results.querySelector(".pager")?.remove();
    if (!page.items.length && !append) results.replaceChildren(empty("Вільного часу не знайдено", "Спробуйте іншу дату, провайдера або змініть фільтри."));
    for (const slot of page.items) {
      const label = state.replacing ? "Перенести сюди" : "Забронювати";
      const book = button(label, () => confirmAction(state.replacing ? "Перенести бронювання?" : "Підтвердити бронювання?",
        `${slot.resource.name} · ${formatWhen(slot.starts_at)}. ${state.replacing ? "Попереднє місце звільниться після успішного перенесення." : "Бронювання стане активним одразу."}`,
        label, async () => {
          const old = state.replacing;
          const key = state.keys.get(slot.id) || crypto.randomUUID(); state.keys.set(slot.id, key);
          try {
            await client.request(old ? `/bookings/${old}/reschedule` : "/bookings", {
              method: "POST", body: old ? { new_slot_id: slot.id } : { slot_id: slot.id }, key: old ? undefined : key });
          } catch (error) {
            if (error instanceof ApiError && error.status < 500) state.keys.delete(slot.id);
            throw error;
          }
          state.keys.delete(slot.id); state.replacing = null;
          state.flash = old ? "Бронювання перенесено." : "Бронювання підтверджено."; go("bookings");
        }), "", { "aria-label": `${label}: ${slot.resource.name}, ${formatWhen(slot.starts_at)}` });
      cards.append(E("article", { class: "panel slot-card" }, E("div", { class: "split" }, E("span", { class: "resource-icon", "aria-hidden": "true" }, slot.resource.type === "room" ? "▧" : "◌"), pill(typeNames[slot.resource.type])),
        E("div", {}, E("h3", {}, slot.resource.name), E("p", { class: "provider" }, slot.provider.full_name)),
        E("div", {}, E("p", { class: "when" }, formatWhen(slot.starts_at)), E("p", { class: "meta" }, `${slot.duration_minutes} хв${slot.resource.capacity ? ` · до ${slot.resource.capacity} відвідувачів` : ""}`)), book));
    }
    if (page.pagination.has_more) results.append(E("div", { class: "pager" }, button("Показати ще", () => run(() => load(page.pagination.next_cursor, true)))));
  }
  await load();
}

async function showBookings(main) {
  let request = 0;
  heading(main, "Мої бронювання", "Майбутні зустрічі, минулі записи та зручне керування вашим часом.");
  const filters = select("state", [["", "Усі бронювання"], ...Object.entries(bookingStates)], state.bookingFilter);
  const list = E("div", { class: "data-list" });
  filters.addEventListener("change", () => { state.bookingFilter = filters.value; void run(() => load(0)); });
  main.append(E("div", { class: "provider-toolbar" }, field("Показати", filters)), list); footer(main);
  async function load(offset = 0) {
    const current = ++request;
    list.replaceChildren(loading());
    const page = await client.request(`/me/bookings?${queryString({ state: state.bookingFilter, limit: 12, offset })}`);
    if (!main.isConnected || current !== request) return;
    list.replaceChildren();
    if (!page.items.length) list.append(empty("Тут з'являться ваші зустрічі", "Знайдіть вільний час у розділі «Знайти час» і створіть перше бронювання."));
    for (const booking of page.items) {
      const actions = E("div", { class: "actions" });
      if (booking.can_cancel) actions.append(
        button("Перенести", () => { state.replacing = booking.id; go("search"); }, "secondary small"),
        button("Скасувати", () => confirmAction("Скасувати бронювання?", `${booking.resource.name} · ${formatWhen(booking.slot.starts_at)}. Слот стане доступним для інших студентів.`,
          "Скасувати бронювання", async () => { await client.request(`/bookings/${booking.id}/cancel`, { method: "POST" }); await load(offset); showNotice("Бронювання скасовано. Слот знову доступний."); }), "danger small"));
      const reason = booking.cancellation_kind === "rescheduled" ? "Бронювання перенесено на інший слот."
        : booking.cancellation_reason ? `Причина провайдера: ${booking.cancellation_reason}` : "";
      list.append(E("article", { class: "panel booking-card" }, E("div", {}, pill(bookingStates[booking.state], booking.state === "active" ? "green" : booking.state === "cancelled" ? "red" : ""),
        E("h3", {}, booking.resource.name), E("p", {}, formatWhen(booking.slot.starts_at)), E("small", {}, booking.provider.full_name),
        E("p", { class: "deadline" }, `Скасування та перенесення до ${formatWhen(booking.cancel_deadline_at)}`),
        !booking.can_cancel && booking.state === "active" && E("small", {}, "Строк зміни цього бронювання вже минув."),
        reason && E("p", { class: "reason" }, reason)), actions));
    }
    offsetPager(list, page.pagination, offset => run(() => load(offset)));
  }
  await load();
}

async function showAvailability(main) {
  let request = 0;
  heading(main, "Доступність ресурсів", "Публікуйте вільний час і підтримуйте розклад ваших ресурсів актуальним.");
  state.resources = await allPages(client, "/resources");
  if (!main.isConnected) return;
  const own = state.resources.filter(r => r.provider.id === state.user.id);
  if (!own.length) { main.append(empty("Вам ще не призначено ресурсів", "Адміністратор має створити ресурс або призначити вас його провайдером.")); footer(main); return; }
  if (!own.some(r => r.id === state.resourceId)) state.resourceId = own[0].id;
  const resource = select("resource", own.map(r => [r.id, r.name]), state.resourceId);
  resource.addEventListener("change", () => { state.resourceId = resource.value; void run(() => load()); });
  const tabArea = E("div", { class: "tabs", role: "group", "aria-label": "Дані доступності" });
  const list = E("div");
  for (const [key, name] of [["slots", "Опубліковані слоти"], ["templates", "Тижневі шаблони"], ["blocks", "Блокування"]]) {
    tabArea.append(button(name, () => { state.providerTab = key; void run(() => load()); }, "", { "data-tab": key }));
  }
  const create = button("+ Створити слот", () => edit(), "");
  main.append(E("div", { class: "provider-toolbar split" }, field("Ваш ресурс", resource), create), tabArea, list); footer(main);
  async function load(offset = 0) {
    const current = ++request;
    const rid = state.resourceId, tab = state.providerTab;
    create.textContent = { slots: "+ Створити слот", templates: "+ Новий шаблон", blocks: "+ Заблокувати час" }[tab];
    tabArea.querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
    list.replaceChildren(loading());
    const page = await client.request(`/resources/${rid}/${tab}?limit=12&offset=${offset}`);
    if (!main.isConnected || current !== request || rid !== state.resourceId || tab !== state.providerTab) return;
    list.replaceChildren();
    if (!page.items.length) list.append(empty("Поки що немає записів", "Скористайтеся кнопкою створення, щоб налаштувати доступність цього ресурсу."));
    const cards = E("div", { class: "data-list" }); list.append(cards);
    for (const item of page.items) {
      if (tab === "slots") cards.append(E("article", { class: "panel data-item" }, E("div", {}, E("h3", {}, formatWhen(item.starts_at)), E("p", {}, `${item.duration_minutes} хв · до ${formatWhen(item.ends_at)}`)),
        pill(availabilityNames[item.availability], item.available ? "green" : "amber")));
      if (tab === "templates") cards.append(E("article", { class: "panel data-item" }, E("div", {}, E("h3", {}, `${week[item.weekday - 1]} · ${item.start_local.slice(0, 5)}–${item.end_local.slice(0, 5)}`),
        E("p", {}, `По ${item.slot_minutes} хв · від ${item.valid_from}${item.valid_to ? ` до ${item.valid_to}` : " без кінцевої дати"}`),
        item.conflicts.length > 0 && E("div", { class: "conflicts" }, `Конфліктних проміжків: ${item.conflicts.length}. `,
          item.conflicts.slice(0, 4).map(c => E("p", {}, `${c.day} ${c.start_local.slice(0, 5)}: ${c.code === "slot_overlap" ? "перетин з іншим слотом" : "неоднозначний або неіснуючий місцевий час"}`)))),
        button("Змінити", () => edit(item), "secondary small")));
      if (tab === "blocks") cards.append(E("article", { class: "panel data-item" }, E("div", {}, E("h3", {}, item.reason), E("p", {}, `${formatWhen(item.starts_at)} — ${formatWhen(item.ends_at)}`)),
        button("Зняти блокування", () => confirmAction("Зняти блокування?", "Час знову стане доступним для нових записів. Раніше скасовані бронювання автоматично не відновляться.", "Зняти блокування", async () => {
          await client.request(`/resources/${rid}/blocks/${item.id}`, { method: "DELETE" }); await load(); showNotice("Блокування знято.");
        }), "secondary small")));
    }
    offsetPager(list, page.pagination, value => run(() => load(value)));
  }
  function edit(existing = null) {
    const rid = state.resourceId, tab = state.providerTab;
    const duration = name => field("Тривалість слота, хв", input(name, "number", existing?.slot_minutes || 30, { required: true, ...constraints("SlotCreate", "duration_minutes") }));
    const dateTime = (name, label) => field(label, input(name, "datetime-local", "", { required: true }), "Дата й час за Europe/Kyiv.");
    const id = existing?.id || crypto.randomUUID();
    dialog({ slots: "Новий разовий слот", templates: existing ? "Змінити тижневий шаблон" : "Новий тижневий шаблон", blocks: "Заблокувати час" }[tab], close => {
      const fields = tab === "slots" ? [dateTime("starts_at", "Початок слота"), duration("duration_minutes")]
        : tab === "blocks" ? [dateTime("starts_at", "Початок блокування"), dateTime("ends_at", "Кінець блокування"),
          field("Причина", E("textarea", { name: "reason", required: true, maxlength: 500 })),
          E("p", { class: "inline-note" }, "Майбутні бронювання в цьому проміжку буде скасовано. Студенти отримають повідомлення з указаною причиною.")]
        : [field("День тижня", select("weekday", week.map((name, i) => [i + 1, name]), existing?.weekday || 1)),
          field("Початок за Києвом", input("start_local", "time", existing?.start_local?.slice(0, 5) || "14:00", { required: true })),
          field("Кінець за Києвом", input("end_local", "time", existing?.end_local?.slice(0, 5) || "16:00", { required: true })), duration("slot_minutes"),
          field("Діє з", input("valid_from", "date", existing?.valid_from || kyivDate(), { required: true })),
          field("Діє до", input("valid_to", "date", existing?.valid_to || ""), "Залиште порожнім для постійного розкладу."),
          E("p", { class: "inline-note" }, "Зміни застосовуються до майбутніх вільних слотів. Чинні бронювання зберігаються; конфліктні проміжки буде показано в списку.")];
      return form(fields, async data => {
        let body = data, method = "POST", path = `/resources/${rid}/${tab}`;
        if (tab === "slots") body = { starts_at: kyivTimestamp(data.starts_at), duration_minutes: Number(data.duration_minutes) };
        if (tab === "blocks") body = { starts_at: kyivTimestamp(data.starts_at), ends_at: kyivTimestamp(data.ends_at), reason: data.reason };
        if (tab === "templates") { method = "PUT"; path += `/${id}`; body = { ...data, weekday: Number(data.weekday), slot_minutes: Number(data.slot_minutes), valid_to: data.valid_to || null }; }
        const result = await client.request(path, { method, body });
        close(); await load();
        showNotice(tab === "blocks" ? `Час заблоковано. Скасовано бронювань: ${result.cancelled_bookings}.` : tab === "templates" ? `Шаблон збережено. Створено слотів: ${result.created_slots}; конфліктів: ${result.conflicts.length}.` : "Слот опубліковано.");
      }, tab === "blocks" ? "Заблокувати час" : "Зберегти", { footer: [button("Закрити", close)] });
    });
  }
  await load();
}

async function showResources(main) {
  let request = 0;
  heading(main, "Ресурси", "Консультації та аудиторії, доступні вашій спільноті.", button("+ Новий ресурс", () => run(() => edit()), ""));
  const list = E("div"); main.append(list); footer(main);
  async function load(offset = 0) {
    const current = ++request;
    list.replaceChildren(loading());
    const page = await client.request(`/resources?limit=12&offset=${offset}`);
    if (!main.isConnected || current !== request) return;
    list.replaceChildren();
    if (!page.items.length) list.append(empty("Додайте перший ресурс", "Створіть консультацію або аудиторію й призначте відповідального провайдера."));
    const cards = E("div", { class: "data-list" }); list.append(cards);
    for (const resource of page.items) cards.append(E("article", { class: "panel data-item" }, E("div", {}, E("h3", {}, resource.name),
      E("p", {}, `${resource.provider.full_name}${resource.capacity ? ` · до ${resource.capacity} відвідувачів` : ""}`), pill(typeNames[resource.type])),
      button("Редагувати", () => run(() => edit(resource)), "secondary small")));
    offsetPager(list, page.pagination, value => run(() => load(value)));
  }
  async function edit(existing = null) {
    const users = await allPages(client, "/admin/users?role=provider");
    if (!main.isConnected) return;
    if (!users.length) { showNotice("Спочатку призначте користувачу роль провайдера в розділі «Користувачі».", "info"); return; }
    dialog(existing ? "Редагувати ресурс" : "Новий ресурс", close => {
      const type = select("type", Object.entries(typeNames), existing?.type || "consultation", { disabled: Boolean(existing) });
      const capacity = input("capacity", "number", existing?.capacity || "", constraints("ResourceCreate", "capacity"));
      const toggle = () => { capacity.disabled = type.value !== "room"; capacity.required = type.value === "room"; if (capacity.disabled) capacity.value = ""; };
      type.addEventListener("change", toggle); toggle();
      return form([field("Назва", input("name", "text", existing?.name || "", { required: true, ...constraints("ResourceCreate", "name") })), field("Тип ресурсу", type),
        field("Місткість аудиторії", capacity, "Для консультації місткість не задається."),
        field("Провайдер", select("provider_id", users.map(u => [u.id, `${u.full_name} · ${u.email}${u.is_active ? "" : " (неактивний акаунт)"}`]), existing?.provider.id || users[0].id, { required: true }))],
      async data => {
        const body = { name: data.name, provider_id: data.provider_id, capacity: type.value === "room" ? Number(data.capacity) : null };
        if (!existing) body.type = data.type;
        if (existing) {
          if (body.name === existing.name) delete body.name;
          if (body.provider_id === existing.provider.id) delete body.provider_id;
          if (body.capacity === existing.capacity) delete body.capacity;
        }
        if (Object.keys(body).length) await client.request(existing ? `/admin/resources/${existing.id}` : "/admin/resources", { method: existing ? "PATCH" : "POST", body });
        close(); state.resources = await allPages(client, "/resources"); await load(); showNotice("Ресурс збережено.");
      }, "Зберегти", { footer: [button("Закрити", close)] });
    });
  }
  await load();
}

async function showUsers(main) {
  let request = 0;
  heading(main, "Користувачі та ролі", "Знаходьте користувачів за ім'ям чи поштою та керуйте доступом.");
  const list = E("div");
  const search = form([field("Ім'я або електронна пошта", input("q", "search", state.userQuery, { maxlength: 254, placeholder: "Знайти користувача…" }))],
    async data => { state.userQuery = data.q; await load(0); }, "Знайти");
  search.className = "user-search"; search.querySelector("fieldset").className = "row";
  main.append(search, list); footer(main);
  async function load(offset = 0) {
    const current = ++request;
    list.replaceChildren(loading());
    const page = await client.request(`/admin/users?${queryString({ q: state.userQuery, offset, limit: 15 })}`);
    if (!main.isConnected || current !== request) return;
    list.replaceChildren();
    if (!page.items.length) list.append(empty("Користувачів не знайдено", "Перевірте ім'я чи адресу. Користувач має спочатку зареєструватися."));
    const rows = E("tbody");
    for (const user of page.items) {
      const actions = E("div", { class: "table-action" });
      for (const role of ["provider", "admin"]) {
        const has = user.roles.includes(role);
        const label = `${has ? "Зняти" : "Надати"}: ${roleNames[role].toLowerCase()}`;
        actions.append(button(label, () => confirmAction(has ? "Відкликати роль?" : "Надати роль?",
          `${user.full_name} · ${user.email}. ${has ? "Права зміняться з наступного запиту користувача." : `Користувач отримає права ролі «${roleNames[role]}».`}`,
          label, async () => {
            await client.request(`/admin/users/${user.id}/roles/${role}`, { method: has ? "DELETE" : "PUT" });
            const me = await client.request("/auth/me");
            if (JSON.stringify(me.roles) !== JSON.stringify(state.user.roles)) { state.user = me; renderShell(); }
            else await load(offset);
            showNotice("Ролі користувача оновлено.");
          }), "secondary small"));
      }
      rows.append(E("tr", {}, E("td", {}, E("strong", {}, user.full_name), E("small", {}, user.email)),
        E("td", {}, E("div", { class: "row" }, user.roles.map(r => pill(roleNames[r] || r))), !user.is_active && E("small", {}, "Парольний вхід вимкнено")), E("td", {}, actions)));
    }
    if (page.items.length) list.append(E("div", { class: "table-wrap" }, E("table", {}, E("thead", {}, E("tr", {}, E("th", {}, "Користувач"), E("th", {}, "Ролі"), E("th", {}, "Дії"))), rows)));
    offsetPager(list, page.pagination, value => run(() => load(value)));
  }
  await load();
}

async function showPolicy(main) {
  heading(main, "Правила бронювання", "Зміни діятимуть для нових бронювань. Дедлайни вже створених записів зберігаються.");
  const pending = loading(); main.append(pending);
  const policy = await client.request("/admin/policies/current");
  if (!main.isConnected) return;
  pending.remove();
  const cards = E("div", { class: "policy-grid" }, E("article", { class: "panel" }, E("p", { class: "eyebrow" }, "Активних бронювань"), E("p", { class: "policy-value" }, policy.booking_limit), E("p", { class: "muted" }, "Максимум одночасних майбутніх бронювань одного студента.")),
    E("article", { class: "panel" }, E("p", { class: "eyebrow" }, "Вікно скасування"), E("p", { class: "policy-value" }, `${policy.cancel_window_minutes} хв`), E("p", { class: "muted" }, "Мінімальний час до початку, коли студент ще може змінити запис.")));
  const edit = E("section", { class: "panel stack policy-editor" }, E("h2", {}, "Оновити правила"),
    form([field("Ліміт активних бронювань", input("booking_limit", "number", policy.booking_limit, { required: true, step: 1, ...constraints("PolicyUpdate", "booking_limit") })),
      field("Вікно скасування, хв", input("cancel_window_minutes", "number", policy.cancel_window_minutes, { required: true, step: 1, ...constraints("PolicyUpdate", "cancel_window_minutes") }))], async data => {
      await client.request("/admin/policies/current", { method: "PUT", body: { booking_limit: Number(data.booking_limit), cancel_window_minutes: Number(data.cancel_window_minutes) } });
      await showPolicyRefresh();
    }, "Зберегти правила", { grid: true }));
  async function showPolicyRefresh() { main.replaceChildren(); await showPolicy(main); showNotice("Нові правила збережено. Чинні бронювання не змінено."); }
  main.append(cards, edit); footer(main);
}

async function showNotifications(main) {
  let request = 0;
  heading(main, "Сповіщення", "Підтвердження, нагадування та зміни ваших зустрічей.", button("Оновити", () => navigate()));
  const list = E("div", { class: "data-list" }); main.append(list); footer(main);
  async function load(offset = 0) {
    const current = ++request;
    list.replaceChildren(loading());
    const page = await client.request(`/me/notifications?limit=12&offset=${offset}`);
    if (!main.isConnected || current !== request) return;
    list.replaceChildren();
    if (!page.items.length) list.append(empty("Поки що тихо", "Доставлені підтвердження та нагадування з'являться тут. Після створення бронювання список можна оновити."));
    const titles = { confirmation: "Бронювання підтверджено", reminder: "Нагадування про зустріч", cancelled: "Бронювання скасовано провайдером", provider_created: "Новий запис на ваш ресурс", provider_cancelled: "Студент скасував бронювання" };
    for (const notice of page.items) list.append(E("article", { class: "panel notification" }, E("span", { class: "resource-icon", "aria-hidden": "true" }, "◷"),
      E("div", {}, E("h3", {}, titles[notice.kind] || "Оновлення бронювання"), E("p", {}, notice.payload.resource_name || "Зустріч"),
        notice.payload.starts_at && E("p", { class: "muted" }, formatWhen(notice.payload.starts_at)), notice.payload.reason && E("p", {}, `Причина: ${notice.payload.reason}`),
        E("p", { class: "meta" }, `Отримано ${formatWhen(notice.delivered_at)}`))));
    offsetPager(list, page.pagination, value => run(() => load(value)));
  }
  await load();
}

function dateAfter(day, count) {
  const value = new Date(`${day}T12:00:00Z`); value.setUTCDate(value.getUTCDate() + count);
  return value.toISOString().slice(0, 10);
}

async function showCalendar(main) {
  heading(main, "Календар ресурсу", "Завантаження й інтервали власного ресурсу за обрані київські дати.");
  const own = state.resources.filter(r => r.provider.id === state.user.id);
  if (!own.length) { main.append(empty("Вам ще не призначено ресурсів", "Після призначення адміністратором тут з'явиться календар.")); return; }
  const today = kyivDate();
  let filters = { resource: own.some(r => r.id === state.resourceId) ? state.resourceId : own[0].id, date_from: today, date_to: dateAfter(today, 6) };
  let generation = 0;
  const list = E("div");
  main.append(form([field("Ваш ресурс", select("resource", own.map(r => [r.id, r.name]), filters.resource)),
    field("Від дати", input("date_from", "date", filters.date_from, {required:true})),
    field("До дати включно", input("date_to", "date", filters.date_to, {required:true}))],
    async data => { filters = data; await load(); }, "Показати календар", {grid:true}), list); footer(main);
  async function load(offset = 0) {
    const current = ++generation;
    list.replaceChildren(loading());
    const page = await client.request(`/resources/${filters.resource}/calendar?${queryString({...filters,resource:undefined,limit:100,offset})}`);
    if (!main.isConnected || current !== generation) return;
    const s = page.summary;
    list.replaceChildren(E("div", {class:"calendar-summary"}, [["Опубліковано",s.total_slots],["З бронюванням",s.booked_slots],["Заблоковано",s.blocked_slots],["Вільних майбутніх",s.available_slots]]
      .map(([title,n]) => E("article",{class:"panel"},E("p",{class:"muted"},title),E("strong",{class:"policy-value"},n)))));
    const days = new Map();
    for (const slot of page.items) {
      const key = kyivDate(slot.starts_at); if (!days.has(key)) days.set(key, []); days.get(key).push(slot);
    }
    if (!page.items.length) list.append(empty("У цьому періоді слотів немає", "Змініть дати або опублікуйте доступність."));
    for (const [day, slots] of days) list.append(E("section",{class:"panel calendar-day"},
      E("h2",{},new Intl.DateTimeFormat("uk-UA",{dateStyle:"full",timeZone:"Europe/Kyiv"}).format(new Date(`${day}T12:00:00Z`))),
      slots.map(s => E("div",{class:"data-item"},E("span",{},`${formatWhen(s.starts_at)} — ${formatWhen(s.ends_at)}`),pill(availabilityNames[s.availability],s.availability === "available" ? "green" : "amber")))));
    offsetPager(list,page.pagination,offset => run(() => load(offset)));
  }
  await load();
}

async function showAudit(main) {
  heading(main, "Журнал аудиту", "Хто, коли й що змінив. Записи доступні лише для перегляду.");
  const users = await allPages(client,"/admin/users");
  if (!main.isConnected) return;
  const today = kyivDate(); let generation = 0;
  let filters = {date_from:dateAfter(today,-6),date_to:today};
  const list = E("div",{class:"data-list"});
  main.append(form([field("Автор дії",select("actor_id",[["","Усі автори"],...users.map(u=>[u.id,`${u.full_name} · ${u.id.slice(0,8)}`])])),
    field("Назва дії",input("action","text","",{maxlength:80,placeholder:"Наприклад resource.update"})),
    field("Від дати",input("date_from","date",filters.date_from,{required:true})),field("До дати включно",input("date_to","date",filters.date_to,{required:true}))],
    async data=>{filters=data;await load();},"Застосувати фільтри",{grid:true}),list); footer(main);
  async function load(offset=0) {
    const current = ++generation; list.replaceChildren(loading());
    const page = await client.request(`/admin/audit?${queryString({...filters,limit:20,offset})}`);
    if (!main.isConnected || current !== generation) return;
    list.replaceChildren();
    if (!page.items.length) list.append(empty("Подій не знайдено","Перевірте дати, автора або точну назву дії."));
    for (const row of page.items) list.append(E("article",{class:"panel audit-entry"},
      E("div",{class:"split"},E("h3",{},row.action),pill(formatWhen(row.at))),E("p",{},row.actor_name),
      E("p",{class:"meta"},`Об'єкт: ${row.object_id || "—"}`),E("details",{},E("summary",{},"Значення до та після зміни"),
        E("p",{},"До"),E("pre",{},JSON.stringify(row.before,null,2)),E("p",{},"Після"),E("pre",{},JSON.stringify(row.after,null,2)))));
    offsetPager(list,page.pagination,offset=>run(()=>load(offset)));
  }
  await load();
}

async function boot() {
  const spec = await fetch("/openapi.json", { credentials: "same-origin" }).then(r => r.ok ? r.json() : null).catch(() => null);
  state.schema = spec?.components?.schemas || {};
  try {
    state.user = await client.request("/auth/me");
    state.resources = await allPages(client, "/resources");
    renderShell();
  } catch (error) {
    state.user = null; renderAuth();
    if (!(error instanceof ApiError && error.status === 401)) showError(error);
  }
}
void boot().catch(showError);
