# global-app-skill

海外 Android App 调研 skill 的薄入口、资源更新器和脚本 CLI。保持 `global-app-analysis` 的下载、业务调研与 UED 图册三个分支。

## 安装

要求 Node.js >=22.12；执行调研脚本需要 `python3` >=3.9，Android 设备、SDK 和其他工具由工作流按需检查。

```sh
npx -y --prefer-online global-app-skill@latest skill install
```

默认只安装 `~/.agents/skills/global-app-analysis/SKILL.md`。也可用 `--dir /absolute/skills/global-app-analysis` 指定当前客户端实际使用的 skill 目录。所有目录使用完全相同的薄入口，只记录 CLI 版本，不写入安装路径。安装位置记录在本机状态目录，供 CLI 后续自动发现；该记录不放进 skill。已存在的 SKILL.md 会被原子替换，目录中的其他文件保留，符号链接入口拒绝覆盖。安装不下载 references，也不修改 MCP 或客户端配置。

## 执行

```sh
npx -y --prefer-online global-app-skill@latest context resolve --mode research
```

`--mode` 为 `download`、`research` 或 `ued`。CLI 每次查询 GitHub 最新正式 Release 的 `latest.json` 附件，验证清单、压缩包及逐文件 SHA-256，返回绝对 `resourceRoot` 和有序 `mustRead`。agent 读取这些文件后按原工作流编排任务。

`context resolve` 和 `run` 执行前由 CLI 自动定位已安装的薄入口，更新为当前 CLI 捆绑的版本。入口只调用通用命令，不传安装路径。入口使用 `npx --prefer-online ...@latest`，因此发布新版 CLI 后，下一次执行会更新本地 SKILL.md。

CLI 检查以下位置中的 `global-app-analysis/SKILL.md`：用户目录下的 `.agents/skills`、`.codex/skills`、`.claude/skills`、`.cursor/skills`、`.gemini/skills`、`.kiro/skills`；当前目录至最近 Git 仓库根目录之间的相同项目级目录；`CODEX_HOME/skills`；以及 CLI 安装时登记的目录。不在 Git 仓库内时，项目级发现只检查当前目录，不遍历其他工作区。

自定义安装目录通过 `skill install --dir ...` 登记在 `${XDG_STATE_HOME:-~/.local/state}/global-app-skill/installations/`，不需要把路径写进 SKILL.md。复制到另一台机器的标准 skill 目录后，CLI 会按该机器环境重新发现；移到标准目录以外的位置时，再运行一次安装命令登记新位置。`--skill-dir` 仅保留为手动指定本次更新目标的可选参数，薄入口无需使用。

自动同步只更新已经存在且属于本 CLI 的入口，不创建其他客户端的 skill，不覆盖手工维护的其他实现或符号链接，也不降级更新的入口。`context resolve` 的 `skillUpdate` 单独报告同步结果；失败会明确显示，资源解析仍可独立进行。脚本 stdout 和退出码保持不变，同步日志写入 stderr。

本地文件更新后，新入口在客户端重新加载 skill 时采用；已经读入当前任务的上下文不因磁盘替换自动改写。[Codex 官方文档](https://learn.chatgpt.com/docs/build-skills)说明会自动检测 skill 变更；如果没有显示更新，可重启 Codex。其他客户端遵循各自的重新加载规则。

```sh
npx -y --prefer-online global-app-skill@latest run preflight --mode research --resource-root /absolute/resolved/hash -- --report /absolute/task/environment.json
```

`run` 支持 `preflight`、`download`、`export_device`、`verify`、`attempts`、`inspect_package`、`long_screenshot`，`--` 后参数原样传递。它保留当前工作目录、Python 输出和退出码；下载模式进度使用 `/4`，业务/UED 使用 `/10`。

同一任务固定在已读取的快照上执行，新任务重新 resolve。省略 `--resource-root` 的 `run` 会先获取当前资源。设备环境门槛、原包与证据规则保持在动态工作流内；CLI 不自动完成反编译、页面操作、Mock 或业务验收。

## 结构与更新机制

| 路径 | 职责 |
|---|---|
| `skills/global-app-analysis/SKILL.md` | 安装到客户端的薄入口 |
| `src/` | npm CLI：安装、资源解析、校验、脚本运行 |
| `resources/global-app-analysis/references/` | 主流程和各阶段操作文档 |
| `resources/global-app-analysis/scripts/` | 原有 Python 脚本及回归测试 |
| `resources/global-app-analysis/examples/` | 业务报告模板与审查记录模板 |
| `scripts/build-resources.mjs` | 生成确定性的资源包与清单 |
| `.github/workflows/publish.yml` | tag 触发的构建、GitHub Release 和 npm 发布 |
| `scripts/release.mjs` | tag 校验、打包、校验和及发布资产核对 |
| `dist/release/` | 本次构建的 Release 资产，不提交到 Git |

分发源为 `https://github.com/shiguang-lab/global-app-skill/releases/latest/download/latest.json`。资源源码在仓库的 `resources/`，正式生成包由 Actions 上传到 GitHub Release。清单中的 `releaseTag` 决定资源包的固定下载地址，因此 latest 切换不会混用不同 Release 的清单和包。npm 包仅包含 CLI 与薄 skill；工作流资源可独立发布，不要求发布 npm 新版本。

缓存默认位于 `~/.cache/global-app-skill/releases/<resourceHash>`，可用 `GLOBAL_APP_SKILL_CACHE` 或 `--cache-dir` 指定。下载先在临时目录完整校验，再发布快照。网络或完整性失败会报错，不静默使用旧资源；损坏的固定快照拒绝执行，重新 resolve 可修复。旧快照保留供现有任务使用。运行产物写入工作区，不写回资源缓存。

## 开发与发布

在当前仓库编辑资源后：

```sh
npm test
npm run test:python
npm run release:prepare
```

Python 回归测试中的长图部分需要 Pillow。CLI 无第三方 Node 依赖。`--feed` 可指定 HTTPS 清单，测试允许 loopback HTTP。`release:prepare` 在本地预演与 Actions 相同的构建，默认 tag 为 `v<package.json.version>`，也可指定 `RELEASE_TAG`。构建结果进入忽略的 `dist/release/`，不手工上传。

`npm run resources:check` 只校验已生成的 `dist/resources`，本地需先执行 `npm run resources:build`；`release:prepare` 会自动重建并核对。

### 发布 CLI、薄入口与资源

修改源码并更新 `package.json` 的版本，提交、push 后创建对应版本的 tag。例如版本为 `0.1.8` 时：

```sh
git tag v0.1.8
git push origin v0.1.8
```

`publish.yml` 校验 tag 与 package.json 一致，执行 Node/Python 测试，从 tag 源码生成以下资产：

- `latest.json`：资源清单、Release tag、最低 CLI 版本、逐文件哈希。
- `<resourceHash>.json.gz`：references、scripts、examples 的完整快照。
- `global-app-skill.tgz`：同一 tag 构建的 CLI 安装包。
- `SHA256SUMS`：上述三个资产的校验和。

Actions 先创建草稿 Release，上传所有已验证资产后发布为 latest，随后把同一个 CLI tgz 发布到 npm。npm 发布失败不会删除已经完整发布的 GitHub Release。重跑时先核对已发布资产；正式 Release 不覆盖不同字节的包。

### 仅发布资源

修改资源源码并提交，创建独立的资源 tag，例如：

```sh
git tag resources-v0.1.4
git push origin resources-v0.1.4
```

该 tag 只发布 GitHub Release，跳过 npm。客户端下次 resolve 自动获取新资源。资源工作流仍包含完整快照，删除的源文件不会残留到新快照。已有任务继续使用其固定快照。不要删除历史 Release 的资源资产。

### 一次性配置 npm 发布认证

在 GitHub 仓库 Actions secrets 中配置拥有 `global-app-skill` 发布权限的 `NPM_TOKEN`，工作流将其绑定到 npm 使用的 `NODE_AUTH_TOKEN`，不读取或复制本机 token。也可在 npm 包 Settings 中配置 GitHub Actions Trusted Publisher：组织 `shiguang-lab`、仓库 `global-app-skill`、工作流文件 `publish.yml`、允许 `npm publish`，不设置 environment。工作流保留 `id-token: write`，供 OIDC 与 provenance 使用。GitHub Release 使用 Actions 自带的 `GITHUB_TOKEN` 与 `contents: write`。

以后只推 tag，由 Actions 发布，不在本机执行 `npm publish`。当前项目未授予开源许可证，npm 元数据使用 `UNLICENSED`。
