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
  const titleRow = element("div", "release-title");
  titleRow.append(element("h3", "", `${app.name} ${release.label}`));
  if (app.homepage) {
    const sourceLink = element("a", "release-source-link", "上游项目");
    sourceLink.href = app.homepage;
    sourceLink.target = "_blank";
    sourceLink.rel = "noreferrer";
    sourceLink.setAttribute("aria-label", `打开 ${app.name} 上游项目`);
    sourceLink.prepend(icon("github"));
    titleRow.append(sourceLink);
  }
  summary.append(
    image,
    element("p", "platform-label", release.platform === "tv" ? "Android TV" : "Android Mobile"),
    titleRow,
    element("span", "version", `v${release.version}`),
    element("span", "updated-time", `发布于 ${formatDate(release.updated_at)}`),
  );

  const detail = element("div", "release-detail");
  detail.append(element("p", "detail-title", "本次更新"));
  const notes = element("ul", "notes");
  const noteItems = release.notes?.length ? release.notes : ["上游未提供更新说明"];
  const notesSection = element("div", "notes-section");
  const hiddenNotes = [];
  noteItems.forEach((note, index) => {
    const item = element("li", "", note);
    if (index >= 5) {
      item.hidden = true;
      hiddenNotes.push(item);
    }
    notes.append(item);
  });
  notesSection.append(notes);
  if (hiddenNotes.length) {
    let expanded = false;
    const toggle = element("button", "notes-toggle", "更多");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", "false");
    toggle.prepend(icon("chevron-down"));
    toggle.addEventListener("click", () => {
      expanded = !expanded;
      hiddenNotes.forEach((item) => {
        item.hidden = !expanded;
      });
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.replaceChildren(icon(expanded ? "chevron-up" : "chevron-down"), expanded ? "收起" : "更多");
      window.lucide?.createIcons();
    });
    notesSection.append(toggle);
  }
  detail.append(notesSection, element("p", "detail-title", "选择安装包"));
  const downloads = element("div", "download-list");
  release.downloads.forEach((download) => downloads.append(createDownloadRow(download)));
  detail.append(downloads);
  article.append(summary, detail);
  return article;
}

function releaseVersionKey(release) {
  return String(release.tag_name || release.version || `${release.updated_at || ""}-${release.id || ""}`);
}

function releaseSortTime(release) {
  const timestamp = Date.parse(release.updated_at || "");
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function releaseMatches(app, release) {
  const query = state.query.trim().toLocaleLowerCase("zh-CN");
  const platformMatches = state.platform === "all" || release.platform === state.platform;
  const haystack = [app.name, app.description, release.label, release.version, ...(release.notes || [])]
    .join(" ")
    .toLocaleLowerCase("zh-CN");
  return platformMatches && (!query || haystack.includes(query));
}

function releaseGroups() {
  return state.apps.map((app) => {
    const releases = [...(app.releases || [])].sort((a, b) => releaseSortTime(b) - releaseSortTime(a));
    const latestKey = releases.length ? releaseVersionKey(releases[0]) : "";
    return {
      app,
      latest: releases.filter((release) => releaseVersionKey(release) === latestKey),
      history: releases.filter((release) => releaseVersionKey(release) !== latestKey),
    };
  });
}

function createHistorySection(app, releases) {
  const details = element("details", "release-history");
  const summary = element("summary", "", `历史版本（${releases.length}）`);
  summary.prepend(icon("archive"));
  const list = element("div", "release-history-list");
  releases.forEach((release) => list.append(createReleaseCard(app, release)));
  details.append(summary, list);
  if (state.query.trim()) details.open = true;
  return details;
}

function render() {
  const groups = releaseGroups();
  let count = 0;
  listElement.replaceChildren();
  listElement.setAttribute("aria-busy", "false");

  groups.forEach(({ app, latest, history }) => {
    const latestVisible = latest.filter((release) => releaseMatches(app, release));
    const historyVisible = history.filter((release) => releaseMatches(app, release));
    count += latestVisible.length + historyVisible.length;
    latestVisible.forEach((release) => listElement.append(createReleaseCard(app, release)));
    if (historyVisible.length) listElement.append(createHistorySection(app, historyVisible));
  });
  countElement.textContent = `${count} 个版本`;

  if (!count) {
    listElement.append(element("div", "empty-state", "没有匹配的软件版本，请调整搜索或筛选条件。"));
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
