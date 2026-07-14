const state = {
  apps: [],
  platform: "all",
  query: "",
};

const listElement = document.querySelector("#catalog-list");
const countElement = document.querySelector("#result-count");
const syncElement = document.querySelector("#sync-meta");
const searchInput = document.querySelector("#search-input");
const toastElement = document.querySelector("#toast");
const interfaceSection = document.querySelector("#interface-section");
const interfaceList = document.querySelector("#interface-list");
let toastTimer;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const node = element("i");
  node.setAttribute("data-lucide", name);
  node.setAttribute("aria-hidden", "true");
  return node;
}

function formatDate(value) {
  if (!value) return "更新时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "更新时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "大小未知";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  toastElement.textContent = message;
  toastElement.classList.add("is-visible");
  toastTimer = window.setTimeout(() => toastElement.classList.remove("is-visible"), 1800);
}

function legacyCopy(url) {
  const textarea = element("textarea");
  textarea.value = url;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    textarea.remove();
  }
  return copied;
}

async function copyText(text, successMessage, failureMessage) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
    await Promise.race([
      navigator.clipboard.writeText(text),
      new Promise((_, reject) => window.setTimeout(() => reject(new Error("Clipboard timeout")), 600)),
    ]);
    showToast(successMessage);
  } catch {
    showToast(legacyCopy(text) ? successMessage : failureMessage);
  }
}

function createInterfaceRow(item) {
  const row = element("div", "interface-row");
  const content = element("div", "interface-content");
  content.append(icon("link-2"));
  const text = element("div", "interface-text");
  text.append(element("strong", "", item.name), element("code", "interface-address", item.url));
  content.append(text);

  const copyButton = element("button", "copy-interface", "复制接口");
  copyButton.type = "button";
  copyButton.setAttribute("aria-label", `复制${item.name}`);
  copyButton.prepend(icon("copy"));
  copyButton.addEventListener("click", () =>
    copyText(item.url, "接口地址已复制", "复制失败，请长按接口地址复制"),
  );
  row.append(content, copyButton);
  return row;
}

function renderInterfaces(items) {
  if (!Array.isArray(items) || !items.length) return;
  interfaceList.replaceChildren(...items.map(createInterfaceRow));
  interfaceSection.hidden = false;
}

function createDownloadRow(download) {
  const row = element("div", "download-row");
  const name = element("div", "download-name");
  const title = element("strong", "", download.label);
  if (download.recommended) title.append(element("span", "recommended", "推荐"));
  name.append(title, element("div", "download-meta", `${download.architecture} · ${formatSize(download.size)}`));

  const actions = element("div", "download-actions");
  const copyButton = element("button", "icon-button");
  copyButton.type = "button";
  copyButton.title = "复制下载链接";
  copyButton.setAttribute("aria-label", `复制 ${download.label} 下载链接`);
  copyButton.append(icon("copy"));
  copyButton.addEventListener("click", () =>
    copyText(download.url, "下载链接已复制", "复制失败，请长按下载按钮复制链接"),
  );

  const link = element("a", "download-link", "下载");
  link.href = download.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.setAttribute("aria-label", `下载 ${download.label} 安装包`);
  link.prepend(icon("download"));
  actions.append(copyButton, link);

  (download.mirrors || []).forEach((mirror) => {
    const mirrorLink = element("a", "mirror-link", mirror.label);
    mirrorLink.href = mirror.url;
    mirrorLink.target = "_blank";
    mirrorLink.rel = "noreferrer";
    mirrorLink.title = `通过 ${mirror.provider} 下载`;
    mirrorLink.setAttribute("aria-label", `通过 ${mirror.provider} 下载 ${download.label} 安装包`);
    mirrorLink.prepend(icon("cloud-download"));
    actions.append(mirrorLink);
  });
  row.append(name, actions);
  return row;
}

function createReleaseCard(app, release) {
  const article = element("article", "release-card");
  const summary = element("div", "release-summary");
  const image = element("img", "app-icon");
  image.src = app.icon;
  image.alt = `${app.name} 应用图标`;
  image.width = 58;
  image.height = 58;
  image.loading = "lazy";
  image.referrerPolicy = "no-referrer";
  summary.append(
    image,
    element("p", "platform-label", release.platform === "tv" ? "Android TV" : "Android Mobile"),
    element("h3", "", `${app.name} ${release.label}`),
    element("span", "version", `v${release.version}`),
    element("span", "updated-time", `发布于 ${formatDate(release.updated_at)}`),
  );

  const detail = element("div", "release-detail");
  detail.append(element("p", "detail-title", "本次更新"));
  const notes = element("ul", "notes");
  const noteItems = release.notes?.length ? release.notes : ["上游未提供更新说明"];
  noteItems.forEach((note) => notes.append(element("li", "", note)));
  detail.append(notes, element("p", "detail-title", "选择安装包"));
  const downloads = element("div", "download-list");
  release.downloads.forEach((download) => downloads.append(createDownloadRow(download)));
  detail.append(downloads);
  article.append(summary, detail);
  return article;
}

function flattenedReleases() {
  return state.apps.flatMap((app) => app.releases.map((release) => ({ app, release })));
}

function visibleReleases() {
  const query = state.query.trim().toLocaleLowerCase("zh-CN");
  return flattenedReleases().filter(({ app, release }) => {
    const platformMatches = state.platform === "all" || release.platform === state.platform;
    const haystack = [app.name, app.description, release.label, release.version, ...release.notes]
      .join(" ")
      .toLocaleLowerCase("zh-CN");
    return platformMatches && (!query || haystack.includes(query));
  });
}

function render() {
  const entries = visibleReleases();
  listElement.replaceChildren();
  listElement.setAttribute("aria-busy", "false");
  countElement.textContent = `${entries.length} 个版本`;

  if (!entries.length) {
    listElement.append(element("div", "empty-state", "没有匹配的软件版本，请调整搜索或筛选条件。"));
  } else {
    entries.forEach(({ app, release }) => listElement.append(createReleaseCard(app, release)));
  }
  window.lucide?.createIcons();
}

function bindFilters() {
  searchInput.addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });

  document.querySelectorAll(".segment").forEach((button) => {
    button.addEventListener("click", () => {
      state.platform = button.dataset.platform;
      document.querySelectorAll(".segment").forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      render();
    });
  });
}

async function loadCatalog() {
  bindFilters();
  try {
    const response = await fetch("data/apps.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data.apps)) throw new Error("Invalid catalog");
    state.apps = data.apps;
    renderInterfaces(data.interfaces);
    syncElement.textContent = `数据更新于 ${formatDate(data.generated_at)}（北京时间）`;
    render();
  } catch (error) {
    console.error("Failed to load catalog", error);
    listElement.setAttribute("aria-busy", "false");
    listElement.replaceChildren(element("div", "error-state", "暂时无法读取下载数据，请稍后刷新页面。"));
    syncElement.textContent = "数据读取失败";
    countElement.textContent = "";
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  loadCatalog();
});
