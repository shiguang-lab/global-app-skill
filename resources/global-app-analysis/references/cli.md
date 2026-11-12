# 动态资源与 CLI 执行

`context resolve` 在每个新任务开始检查 GitHub 最新正式 Release 的 `latest.json` 附件，再按清单中的 `releaseTag` 下载该 tag 下的资源包，验证 references、scripts 和 examples。资源由 tag 触发的 Actions 构建并上传，不从 main 分支读取生成包。返回的 `resourceHash` 对应完整快照；`mustRead` 是本次模式开始前需依次读取的文件。网络失败、协议不兼容或完整性检查失败时停止依赖工作，不使用过期缓存冒充最新资源。

同一任务保留返回的绝对 `resourceRoot`，后续读文档、读模板和执行脚本均使用该目录；模式变化时读取该快照内相应工作流，不必重取新版本。新任务重新 resolve。资源只读，产物写入用户工作区，不能写入缓存或 skill 安装目录。

## 运行命令

入口使用 `npx -y --prefer-online global-app-skill@latest`；下文 `CLI` 表示这一整段命令。`RESOURCE_ROOT` 替换为实际返回路径，包含空格时加引号。

```sh
CLI run preflight --mode research --resource-root RESOURCE_ROOT -- --report /absolute/task/environment.json
CLI run download --mode download --resource-root RESOURCE_ROOT -- --help
CLI run verify --mode download --resource-root RESOURCE_ROOT -- --input /absolute/task/sample --package com.example.app
CLI run attempts --resource-root RESOURCE_ROOT -- --help
CLI run inspect_package --resource-root RESOURCE_ROOT -- --help
CLI run long_screenshot --mode ued --resource-root RESOURCE_ROOT -- --help
```

可执行脚本：`preflight`、`download`、`export_device`、`verify`、`attempts`、`inspect_package`、`long_screenshot`。`apk_utils` 和 `progress` 是内部依赖。参数在 `--` 后原样传给 Python，先查相应脚本的 `--help`。CLI 保留当前工作目录、脚本 stdout/stderr 和退出码（包括设备门槛的退出码 4）；显式传 `--mode download` 使用 `/4`，业务/UED 使用 `/10`。

上述可执行脚本的 `python3 scripts/NAME.py 参数` 示例使用 `CLI run NAME --mode MODE --resource-root RESOURCE_ROOT -- 参数` 执行。[审查与交付校验](delivery-record.md)直接使用已校验快照内的 Python 脚本。示例中的 `scripts/`、`references/` 和 `examples/` 均相对于资源快照。

省略 `--resource-root` 时，`run` 会先 resolve 当前模式并验证资源；任务中应显式传入已读快照，避免版本变化。缓存损坏时 `run` 直接失败，重新 resolve 可下载修复；旧快照保留以便正在执行的任务继续使用。

## 责任边界

CLI 自动处理资源更新、完整性验证和脚本启动；任务分支、环境门槛、取包预算、动态 H5 页面范围、Mock、业务事实复核与交付由 agent 按当前文档执行。解析资源不会自动运行设备盘点，也不会表示十步流程已经完成。Python 脚本所需环境与额外工具仍以各模块的检查结果为准。脚本日志不能代替聊天正文进度。
