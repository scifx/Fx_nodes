# Fx Nodes 设计审查与本次修复

> 视角：把 Fx Nodes 当成面向 Blender 创作者的 Node-RED 式事件自动化产品，而不是单纯脚本插件。

## 本次已修复

### 1. Function 节点支持多行代码

原问题：`StringProperty` 在节点 UI 中只能舒适地输入单行/短文本，多行 Python 代码体验很差。

修复方案：

- `FunctionNode` 新增 `code_text_name`，可绑定 Blender `Text` datablock。
- 节点上提供：
  - `+`：为当前 Function 创建/复用多行 Text。
  - `TEXT` 图标：打开绑定的 Text Editor。
- 执行时优先读取 Text datablock 的完整内容；没有绑定 Text 时回退到旧的 `code` 字段，兼容旧文件。
- 节点内展示前 4 行代码预览，超过则显示剩余行数。

修改文件：

- `nodes/logic/__init__.py`
- `operators/__init__.py`

### 2. Debug 节点支持多行预览与完整日志

原问题：Debug 只在节点里以单行/短字符串显示，复杂 dict/list 无法阅读，也不利于追踪历史。

修复方案：

- Debug 节点改为 pretty JSON 多行预览。
- `Max Rows` 上限从 32 提到 64。
- 新增 `Log To Text`，默认开启。
- 新增 `debug_text_name`，把每次 fire 的完整 debug 输出 append 到 Blender `Text` datablock。
- 节点上提供 Text 选择与打开按钮。

修改文件：

- `nodes/data/__init__.py`
- `operators/__init__.py`

## 从“天才设计者”角度看整体产品

### 当前核心优点

1. **定位清晰**：把 Node-RED 的 `msg / flow / global` 心智模型放进 Blender，这个方向非常有价值。
2. **架构简单**：`core` 与 `bpy UI` 分离，节点注册清晰，新节点扩展成本低。
3. **触发器体系有潜力**：Timer、Frame、Key、Click、Scene Event 覆盖了创作自动化里最常见的入口。
4. **Property Get/Set 很实用**：Shift+V 从 Copy Full Data Path 创建节点，是非常符合 Blender 用户习惯的设计。
5. **AI 节点方向正确**：把 AI 作为表达式/计划生成器，而不是硬塞进所有流程。

### 当前最大设计问题

#### 1. 节点编辑体验还不够“创作者友好”

- Function、AI Prompt、Expression、Change value_expr 都可能需要多行编辑。
- 节点面板里的单行文本只适合参数，不适合代码/Prompt/JSON。

建议：

- 把所有长文本字段统一升级为“Text datablock + 节点内预览 + 打开编辑器”。
- 为表达式节点增加“扩展编辑”按钮。
- 对 AI Prompt / Scene Plan 也使用 Text datablock，避免长 prompt 挤在节点上。

#### 2. Debug 需要成为真正的“观察系统”

Debug 不应只是节点上看几行，而应该承担运行时观察、历史追踪、错误定位。

建议：

- 增加 Debug Panel：集中显示所有 Debug 节点的最新输出。
- 增加 Clear Log、Copy JSON、Pin、Search、Filter。
- 每条 Debug 记录包含：时间、节点名、signal id、path、value、context。
- 支持暂停日志，防止 Timer 高频刷爆 Text。

#### 3. Function 节点是强能力，也需要安全边界

当前 Function 允许 `exec` 和 `import`，这符合 power-user 需求，但也需要明确标识风险。

建议：

- 节点上加 “Full Python / Unsafe” 标识。
- 首次运行 Function 弹出确认或在插件偏好中加入 `Allow Full Python Function`。
- 错误信息显示 traceback 行号，而不是只有 `TypeError: ...`。
- 支持 `node.warn()`、`node.error()`、`node.status()` 这类 Node-RED 风格辅助函数。

#### 4. 错误反馈不够可定位

当前 `_error` 只显示前 60 字符，复杂错误不够。

建议：

- 所有节点增加统一错误详情 Text log。
- UI 中短错误 + “打开详情”。
- Function 编译错误应映射到用户代码行号。
- Engine 层增加 error event，让 Debug/Panel 可订阅错误。

#### 5. 缺少“快速上手”的黄金路径

插件潜力大，但新用户需要模板。

建议：

- Add menu 顶部提供 Examples/Templates：
  - Timer 改物体位置
  - Key 切换材质
  - Click 选择物体并写入 msg
  - Function 处理 msg
  - AI 生成表达式
- 新建树时显示欢迎节点/注释框：解释 `msg.payload`、flow 线、Debug。

#### 6. 数据路径与类型提示可以更聪明

`msgpath` 是核心，但用户容易输错。

建议：

- Path 字段增加常用项下拉：`msg`、`payload`、`topic`、`flow.xxx`、`global.xxx`。
- Debug 节点显示数据类型与长度，例如 `list[24]`、`dict[8]`。
- Change/Expression 节点显示输出预览。

#### 7. 运行时状态需要更明显

用户需要知道引擎是否正在运行、哪个节点刚执行、流是否堵住。

建议：

- 节点执行后短暂高亮。
- 节点标题显示 fire count / last runtime。
- 全局面板显示 Running/Stopped、活跃触发器、最近错误。
- 高频触发器默认加节流提示。

#### 8. AI 节点应避免“黑箱感”

建议：

- AI 节点保存最后一次 request/response 到 Text。
- 让用户可检查 prompt、model、temperature。
- AI Expression 输出旁边提供 Validate / Apply / Revert。
- Scene Plan 应有 dry-run preview，不应直接执行复杂操作。

## 建议优先级路线图

### P0：立刻提升可用性

- 已完成：Function 多行 Text。
- 已完成：Debug 多行预览 + Text 日志。
- 下一步：Function traceback 行号修复。
- 下一步：Debug Clear Log / Copy JSON。

### P1：降低学习成本

- 模板流 / 示例流一键创建。
- 节点内 tooltip 更具体。
- Add menu 分类和搜索关键词优化。

### P2：专业化运行观察

- Runtime Inspector Panel。
- 节点执行高亮。
- 错误历史与日志。

### P3：扩展表达能力

- 多输出 Function：允许 `return {'True': msg1, 'False': msg2}` 或 `node.send()`。
- HTTP/WebSocket/MQTT 节点。
- File / JSON / CSV 节点。
- Timeline / Animation 专用节点。

## 本次修改的兼容性说明

- 旧的 Function `code` 字段保留，不会破坏已有文件。
- 新 Function 只是在存在 `code_text_name` 时优先读取 Text datablock。
- Debug 仍保留节点内预览，只是从单行改为 pretty 多行。
- Debug 的 Text 日志默认开启，若担心高频触发导致日志过大，可在节点上关闭 `Log To Text`。
