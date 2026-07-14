# 影视 APP 下载页

一个零依赖的静态软件下载目录。Python 脚本从 GitHub 官方接口读取最新版本、更新说明和下载地址，GitHub Actions 每 6 小时自动刷新数据并部署到 GitHub Pages。

## 本地运行

```bash
python scripts/update_apps.py
python -m http.server 4173
```

浏览器打开 `http://127.0.0.1:4173/`。不要直接双击 `index.html`，因为浏览器会阻止页面通过 `fetch` 读取本地 JSON。

## 发布到 GitHub

1. 创建 GitHub 仓库并把本目录推送到 `main` 分支。
2. 在仓库的 `Settings > Pages > Build and deployment` 中，将 Source 设为 `GitHub Actions`。
3. 打开 `Actions`，手动运行一次 `Update downloads and deploy Pages`，之后会每 6 小时自动执行。

工作流只在 `data/apps.json` 内容发生变化时提交，避免无意义的定时提交。上游请求失败时任务会直接失败并保留上一版有效数据，不会把空结果发布出去。

## 添加其他软件

编辑 `config/sources.json`，增加一个 GitHub 目录数据源。每个数据源需要：

- GitHub 仓库、分支和发布目录；
- 包含 `name`、`code`、`desc` 字段的版本 JSON；
- 对应安装包文件名、平台和架构标签。

当前下载地址仅允许 GitHub 官方域名。需要增加其他可信发布域名时，同时更新 `scripts/update_apps.py` 中的 `ALLOWED_DOWNLOAD_HOSTS`。

影视配置接口维护在 `config/sources.json` 的 `interfaces` 数组中，页面会显示完整地址并提供复制按钮。

下载加速服务维护在同一文件的 `download_mirrors` 数组中。`url_template` 必须使用 HTTPS，并包含一个 `{url}` 占位符；抓取器会为每个最新安装包生成对应镜像地址。

## 数据来源

当前预置数据来自 [FongMi/Release](https://github.com/FongMi/Release) 的公开发布分支，应用图标与项目归属来自 [FongMi/TV](https://github.com/FongMi/TV)。本站只整理公开信息，不修改安装包。
