# 影视 APP 下载页

一个零依赖的静态软件下载目录。Python 脚本从 GitHub 官方接口读取最新版本、更新说明和下载地址，GitHub Actions 每 6 小时自动刷新数据，Cloudflare Pages 从 GitHub 仓库自动构建和部署网站。

## 本地运行

```bash
python scripts/update_apps.py
python -m http.server 4173
```

浏览器打开 `http://127.0.0.1:4173/`。不要直接双击 `index.html`，因为浏览器会阻止页面通过 `fetch` 读取本地 JSON。

可以在本地生成与 Cloudflare Pages 完全相同的发布目录：

```bash
python scripts/build_site.py
python -m http.server 4173 --directory dist
```

## 发布到 Cloudflare Pages

### 1. 创建仓库

在 GitHub 创建一个公开或私有的空仓库。Cloudflare Pages 可以通过 GitHub App 读取获得授权的私有仓库。不要勾选自动生成 README、`.gitignore` 或 License，避免第一次推送发生冲突。

项目中需要上传以下文件和目录：

```text
.github/
assets/
config/
data/
scripts/
tests/
.gitignore
.nojekyll
index.html
README.md
```

不要上传 `.git`、`.agents`、`__pycache__`、`dist` 等本地或生成目录。隐藏目录 `.github/workflows` 必须保留，其中的工作流负责每 6 小时抓取并提交最新数据。网站部署由 Cloudflare Pages 负责。

### 2. 推送项目

在 PowerShell 中执行以下命令，并将仓库地址替换成自己的地址：

```powershell
cd "D:\project\影视APP展示页"
git init
git add .github assets config data scripts tests .gitignore .nojekyll index.html README.md
git commit -m "Initial deploy"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

### 3. 开启 Actions 写权限

进入仓库的 `Settings > Actions > General > Workflow permissions`，选择 `Read and write permissions` 并保存。定时任务需要这个权限提交新版 `data/apps.json`。

### 4. 连接 Cloudflare Pages

登录 Cloudflare Dashboard，进入 `Workers & Pages`，创建一个 Pages 项目并选择 `Connect to Git`：

1. 连接 GitHub，并授权 Cloudflare GitHub App 访问项目仓库；私有仓库可以只授权这一个仓库。
2. 选择项目仓库，Production branch 设置为 `main`。
3. Framework preset 选择 `None`。
4. Build command 填写 `python scripts/build_site.py`。
5. Build output directory 填写 `dist`。
6. Root directory 保持 `/`。
7. 如构建环境要求指定版本，添加环境变量 `PYTHON_VERSION=3.12`。

保存并点击部署。构建脚本只会把 `index.html`、`.nojekyll`、`assets` 和 `data` 复制到 `dist`，抓取脚本、测试和源配置不会发布到网站。

### 5. 访问网站

部署成功后的访问地址通常是：

```text
https://你的项目名.pages.dev/
```

可以在 Cloudflare Pages 项目的 `Custom domains` 中绑定自己的域名。默认 `pages.dev` 和自定义域名都是公开访问；需要限制访问时，建议为自定义域名配置 Cloudflare Zero Trust Access。

### 6. 自动更新流程

无需创建 Cloudflare API Token。Cloudflare Pages 通过 Git 集成部署，GitHub Actions 使用自动提供的 `GITHUB_TOKEN` 每 6 小时检查上游版本：

1. Actions 更新 `data/apps.json` 并推送到 `main`。
2. Cloudflare Pages 检测到新提交。
3. Cloudflare 运行 `python scripts/build_site.py` 并自动发布。

也可以在 GitHub 的 `Actions` 页面手动运行 `Update downloads`。Cloudflare 构建失败时，上一版成功部署的网站仍然保留。

工作流只在 `data/apps.json` 内容发生变化时提交，避免无意义的定时提交。上游请求失败时任务会直接失败并保留上一版有效数据，不会把空结果发布出去。

### 版本历史策略

对于 `github-release` 数据源，第一次同步时会分页抓取仓库的全部正式 Release，并把每个版本的安装包、发布日期和更新说明保存在 `data/apps.json`。完成初始化后，后续定时任务只请求 GitHub 的 `releases/latest` 接口：如果最新版本已经存在，就直接复用本地历史；如果发现新版本，只解析并追加这个版本，不会重复抓取旧版本。

旧版本如果因为上游更改了资产命名而无法匹配，会跳过该版本但不会影响其他版本；最新版本资产缺失时同步会失败并保留上一份有效目录。目录型数据源（例如 FongMi）只能读取分支中的当前文件，脚本会保留它已经记录的历史版本，并在后续发现新版本时追加。

## 添加其他软件

编辑 `config/sources.json`，可增加以下两类 GitHub 数据源：

- 目录数据源：GitHub 仓库、分支和发布目录，以及包含 `name`、`code`、`desc` 字段的版本 JSON；
- Release 数据源：设置 `type: "github-release"`，并为每个安装包配置稳定的 `asset_suffix` 后缀。脚本会读取最新正式 Release 并自动匹配实际文件名。

两类数据源都需要为安装包提供平台和架构标签。Release 资产下载地址同样只允许 GitHub 官方域名。

如果同一仓库同时发布多个变体，可以在 `packages` 中使用 `tag_pattern` 或 `exclude_tag_pattern` 按 Release 标签选择安装包组。例如 `tag_pattern: "-pro$"` 只匹配 Pro 版本，`exclude_tag_pattern: "-pro$"` 匹配普通版本。这样同一个软件可以同时保留不同变体的历史版本。

当前下载地址仅允许 GitHub 官方域名。需要增加其他可信发布域名时，同时更新 `scripts/update_apps.py` 中的 `ALLOWED_DOWNLOAD_HOSTS`。

影视配置接口维护在 `config/sources.json` 的 `interfaces` 数组中，页面会显示完整地址并提供复制按钮。

下载加速服务维护在同一文件的 `download_mirrors` 数组中。`url_template` 必须使用 HTTPS，并包含一个 `{url}` 占位符；抓取器会为每个最新安装包生成对应镜像地址。

## 数据来源

当前预置数据来自 [FongMi/Release](https://github.com/FongMi/Release) 的公开发布分支，应用图标与项目归属来自 [FongMi/TV](https://github.com/FongMi/TV)。本站只整理公开信息，不修改安装包。
