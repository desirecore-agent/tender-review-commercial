# 候选委派输入准备

这是尚未发布的 `taskSource` / `delegation_input_contract` 平台能力的私有候选，不填写最低客户端版本或发布 pin。结构投影 v1 仅约束必填和形状，不等价于原 TaskSpec Schema，不证明授权、语义完整、真实执行或业务通过。

Lead 自有 `scripts/prepare_delegation_input.py`，使用 Lead 获授权的 Python 标准库运行，不运行 Evidence 解释器。`--request`、`--assignment`、`--spec`、`--preflight`、`--execution-receipt`、`--authority` 各接收明确授权的原文件路径及独立预期完整 SHA-256。helper 不打开文件内容中发现的路径。`--target-agent-id` 使用当前核实的真实目标标识，不固定发布 UUID；`--role` 为语义角色。`--output-directory` 必须已存在且明确获授权，`--output-name` 为新的 ASCII 版本名称（字母/数字/下划线/短横线，最长80字符）。helper不创建目录，输出为 `<stem>.task.json` 和 `<stem>.manifest.json`。

分支：
- `--kind lead-request --role lead`：只需原请求和 assignment。Entry 无需先有专业 TaskSpec 才能把用户工作请求交给 Lead。
- `--kind metadata-preflight --role evidence`：原请求、assignment、完整待检 Spec、独立准备的 authority。有限分支只执行已有公开只读 checker 前检，不做专业业务或递归前检；Evidence 使用自身已核环境，产出实际原 checker JSON 与真实命令/退出码回执。
- `--kind business --role <专业角色>`：原请求、assignment、完整已审 Spec、实际 checker JSON、真实执行回执的文件绑定。assignment 范围/资源/Plan/交付须等于 Spec；源摘要与 result.spec_sha256 匹配。伪造的 pass 文件仍可能满足一致性与形状：工具不能认证执行，派发前须独立读取真实工具/运行回执，核对源、命令、输出和退出码。

Assignment JSON 恰含 `role_task`、`io_scope`、`resources`、`parent_plan`、`delivery_requirements`，沿用已有 TaskSpec 含义，完整列出本任务实际需要的当前资源（适用时含角色自有解释器、已审锁和真实初始化回执）。metadata assignment 描述 Evidence checker 范围/环境，不冒充未来业务成员的运行时。原请求按准确 UTF-8 字节读入，Spec 完整解析值与 checker 完整结果不删字段嵌入；SHA 绑定原文件字节，不是重新序列化值。

成功后将 `<stem>.manifest.json.taskSource` 原样传给真实支持的 Delegate sync/async action 及核实目标。不得同时带 `task`/`context`、重新打字或概括 JSON、降级 SendMessage 业务派发，或用于不支持的 worker/subtask/handoff/resume source。独立角色任务仍并行，各有单独任务文件与自有输出目录。控制/恢复操作按当前 ToolCatalog，本 helper 不提供绕过。

单个输入和输出 task 上限均为 256 KiB，拒绝 BOM/NUL/坏 UTF-8/重复 JSON key/非有限数字。当前 helper 需 POSIX 安全打开标志、准确绝对路径、普通单链接文件，无符号链接目录或路径穿越；发布前复核显式源 hash，但不是多文件原子快照，也不能认证调用方权限。已有同名task或manifest文件一律拒绝（同输入重试也拒绝），使用新版本名而不覆盖。目录fd保持锚定，文件以排他open创建并持有fd至路径身份/字节复核完成；失败保留部分文件。双文件输出不是原子事务，失败后遗留的manifest不代表成功；仅helper最终复核成功返回才构成准备回执，同OS权限并发写者仍可在返回后修改，消费者仍须再次核hash。manifest 不含自身 hash。helper 不安装、不联网、不执行 checker、不委派、不授予访问权。

保留原 Skill/TaskSpec 实质检查与原始证据。结构准入不等于执行或生产就绪。真人直接请求仍按现有授权处理。本候选不改既有 `accepts_messages`、`accepts_handoff`；它们并非输入契约别名，可能开放其他通信工作流。发布前核查平台覆盖和真机行为，不假定增加契约就已保护全部通道。

当前 Entry 使用带 teamId 的 handoff(task/context)切入 Lead，而新 taskSource 不支持 handoff。因此 Lead 配置片段仅在 design-only 保留，不应激活；不改真人直接总审/维护路径。4专业 accepts_messages 必须保持开启，因为普通 Delegate/fanout/resume 也受该开关约束；不能拿关闭它当只关闭 SendMessage。accepts_handoff 可另行评估关闭专业角色，不影响普通 Delegate 或 governed SendUserMessage 返回，但本候选不修改这些配置，需真机验收。

所检查的平台基线中，SendMessage 仍是未封闭的程序化入口；平台拒绝覆盖与真机验证完成前，不宣称所有派发入口均已强制收口。
