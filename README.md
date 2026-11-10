# global-app-skill

海外 Android App 调研 skill 的薄入口、资源更新器和脚本 CLI。保持 `overseas-app-research` 的下载、业务调研与 UED 图册三个分支。

## 安装

要求 Node.js >=22.12；执行调研脚本需要 `python3` >=3.9，Android 设备、SDK 和其他工具由工作流按需检查。

```sh
npx -y --prefer-online global-app-skill@latest skill install
```

默认只安装 `~/.agents/skills/overseas-app-research/SKILL.md`。也可用 `--dir /absolute/skills/overseas-app-research` 指定当前客户端实际使用的 skill 目录。已存在的 SKILL.md 会被原子替换，目录中的其他文件保留，符号链接入口拒绝覆盖。安装不下载 references，也不修改 MCP 或客户端配置。安装后让客户端重新加载 skills。

## 执行

```sh
npx -y --prefer-online global-app-skill@latest context resolve --mode research
```

`--mode` 为 `download`、`research` 或 `ued`。CLI 每次查询 GitHub 的 `releases/latest.json`，验证清单、压缩包及逐文件 SHA-256，返回绝对 `resourceRoot` 和有序 `mustRead`。agent 读取这些文件后按原工作流编排任务。

```sh
npx -y --prefer-online global-app-skill@latest run preflight --mode research --resource-root /absolute/resolved/hash -- --report /absolute/task/environment.json
```

`run` 支持 `preflight`、`download`、`export_device`、`verify`、`attempts`、`inspect_package`、`long_screenshot`，`--` 后参数原样传递。它保留当前工作目录、Python 输出和退出码；下载模式进度使用 `/4`，业务/UED 使用 `/10`。

同一任务固定在已读取的快照上执行，新任务重新 resolve。省略 `--resource-root` 的 `run` 会先获取当前资源。设备环境门槛、原包与证据规则保持在动态工作流内；CLI 不自动完成反编译、页面操作、Mock 或业务验收。

## 结构与更新机制

| 路径 | 职责 |
|---|---|
| `skills/overseas-app-research/SKILL.md` | 安装到客户端的薄入口 |
| `src/` | npm CLI：安装、资源解析、校验、脚本运行 |
| `resources/overseas-app-research/references/` | 主流程和各阶段操作文档 |
| `resources/overseas-app-research/scripts/` | 原有 Python 脚本及回归测试 |
| `resources/overseas-app-research/examples/` | 业务报告模板 |
| `scripts/build-resources.mjs` | 生成确定性的资源包与清单 |
| `releases/` | GitHub 托管的最新清单与按哈希命名的资源包 |

分发源为 `https://raw.githubusercontent.com/shiguang-lab/global-app-skill/main/releases/latest.json`。npm 包仅包含 CLI 与薄 skill，工作流资源独立从 GitHub 更新，无需为文档或 Python 脚本修改发布 npm 新版本。

缓存默认位于 `~/.cache/global-app-skill/releases/<resourceHash>`，可用 `GLOBAL_APP_SKILL_CACHE` 或 `--cache-dir` 指定。下载先在临时目录完整校验，再发布快照。网络或完整性失败会报错，不静默使用旧资源；损坏的固定快照拒绝执行，重新 resolve 可修复。旧快照保留供现有任务使用。运行产物写入工作区，不写回资源缓存。

## 开发与发布

在当前仓库编辑资源后：

```sh
npm run resources:build
npm test
npm run test:python
npm run resources:check
```

Python 回归测试中的长图部分需要 Pillow。CLI 无第三方 Node 依赖。`--feed` 可指定 HTTPS 清单，测试允许 loopback HTTP，用于在发布前验证同一协议。

将资源源文件、`releases/latest.json` 和新资源包一起提交并 push 到 GitHub 的 `main`。保留旧资源包，避免读到旧清单的客户端遇到 404。只修改资源时到此即可，后续任务自动获取最新快照；每个快照完整包含 references、scripts 和 examples，删除的源文件不会残留到新快照。

修改 CLI 或薄入口时更新 `package.json` 的版本，完成检查并推送代码后执行 `npm publish`。`prepublishOnly` 会执行 Node/Python 测试和资源一致性检查。初次发布需要 npm 登录和账号所要求的发布认证；GitHub 仓库需公开可读，才能使用默认免认证资源源。当前项目未授予开源许可证，npm 元数据使用 `UNLICENSED`。
