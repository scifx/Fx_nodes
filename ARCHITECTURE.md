# NEXUS Nodes — 架构蓝图

> 一个为 Blender 4.3+ 打造的**事件驱动脚本/表达式节点系统**。
> 它不是几何节点的替代品，而是一个"反应式逻辑层"：触发器 → 逻辑/表达式 → 动作，
> 内置数据预览、AI 接口与高度可扩展的节点注册框架。

---

## 1. 设计哲学

传统的几何节点是**数据流（pull / lazy）**：从输出端回溯求值。
NEXUS 是**事件流（push / reactive）**：由触发器主动点火，沿连线把"信号 + 数据负载"向下游推送。

```
 ┌──────────┐   signal+payload   ┌──────────┐   signal+payload   ┌──────────┐
 │ Trigger  │ ─────────────────▶ │  Logic   │ ─────────────────▶ │  Action  │
 │ (定时/键)│                    │ (表达式) │                    │ (建模/动画)│
 └──────────┘                    └──────────┘                    └──────────┘
        │                              │                               │
        └──────────── 任意节点可挂 DataPreview 探针 ───────────────────┘
```

核心抽象只有 4 个，**任何新功能都是这 4 个的子类**，这就是"有了核心就能轻松扩展"的来源：

| 抽象 | 职责 | 基类 |
|------|------|------|
| **Trigger** | 决定"何时"点火 | `NexusTriggerNode` |
| **Logic**   | 决定"做什么判断/计算" | `NexusLogicNode` |
| **Action**  | 决定"产生什么副作用"（改场景） | `NexusActionNode` |
| **Socket**  | 决定数据如何在节点间流动 | `NexusSocket` 家族 |

---

## 2. 模块分层

```
nexus_nodes/
├── __init__.py            # 扩展入口：register()/unregister()，集中注册
├── blender_manifest.toml  # Blender 4.2+ 扩展清单
│
├── core/                  # ★ 不依赖具体节点的"内核"，可被单元测试
│   ├── registry.py        # 节点/插槽自动注册表 + 装饰器 @register_node
│   ├── signal.py          # Signal 信号对象（payload + context + 时间戳）
│   ├── engine.py          # ExecutionEngine：调度、点火、防环、深度限制
│   ├── runtime.py         # 全局运行时（active engine、tick handler 管理）
│   ├── expr.py            # 安全表达式求值器（AST 白名单沙箱）
│   ├── eventbus.py        # Blender handler ↔ 引擎 的事件桥
│   └── base.py            # NexusBaseNode / Trigger/Logic/Action 抽象基类
│
├── sockets/  (在 ui 下)   # 自定义插槽类型 + 颜色 + 默认值
│
├── nodes/
│   ├── triggers/          # 定时/帧/按键/点击/场景事件/启动 触发器
│   ├── logic/             # 表达式、分支、门、延迟、计数、数学
│   ├── actions/           # 变换、关键帧、可见性、生成网格、修改器、打印
│   ├── data/              # 数据预览器、变量存储、属性读写
│   └── ai/                # AI Provider 抽象 + OpenAI兼容节点 + 解析
│
├── ui/
│   ├── sockets.py         # NexusSocket 家族（Flow/Number/Vector/String/Object/Data）
│   ├── node_tree.py       # NexusNodeTree（自定义编辑器类型）
│   ├── panels.py          # N 面板：引擎控制、预览器、AI 设置
│   └── categories.py      # 添加菜单分类（nodeitems）
│
├── operators/            # 启停引擎、手动点火、安装依赖、AI测试连接
├── prefs.py              # AddonPreferences：AI key、安全开关、tick 频率
├── examples/             # 一键搭建的示例节点图（.py 生成器）
└── tests/                # 纯 Python 单元测试（mock bpy）
```

**依赖方向**：`core` 不 import 任何 `nodes/*`；`nodes/*` 依赖 `core` 与 `ui.sockets`。
单向依赖保证内核可独立测试、独立演进。

---

## 3. 执行模型（核心中的核心）

### 3.1 Signal
一次点火产生一个 `Signal`：
```python
Signal(payload: dict, source: node_id, context: dict, ts: float, hops: int)
```
- `payload`：键值数据，沿途节点可读改。
- `context`：只读环境（frame、time、event 信息）。
- `hops`：经过的节点数，超过 `MAX_HOPS` 中止（防死循环）。

### 3.2 ExecutionEngine
- `fire(node, signal)`：从某触发器节点开始 push。
- 拓扑沿 Flow 连线广度优先推进；每个节点 `process(signal) -> list[(out_socket, signal)]`。
- **求值缓存**：同一 tick 内纯数据节点只算一次（memo by node + tick）。
- **防环**：记录本次传播访问过的 (node,socket)；`hops` 上限兜底。
- 异常隔离：单节点抛错不杀全图，错误写入节点 `.error` 并在 UI 红框显示。

### 3.3 触发来源 → 引擎 的桥（eventbus）
| 触发器 | Blender 机制 |
|--------|--------------|
| 帧触发 | `bpy.app.handlers.frame_change_post` |
| 定时触发 | `bpy.app.timers.register`（间隔可调） |
| 按键触发 | modal operator + window event / 或 `event_timer` |
| 点击触发 | modal operator 捕获鼠标 / 视口 gizmo |
| 场景事件 | `depsgraph_update_post`、`render_*`、`load_post` |
| 启动触发 | register 完成时一次性 |

所有 handler 由 `runtime.py` 统一注册/注销，**绝不泄漏 handler**（unregister 全清）。

---

## 4. 安全表达式沙箱 (`core/expr.py`)
节点里的"脚本表达式"**不**用裸 `eval`。实现一个 AST 白名单求值器：
- 只允许：字面量、名称、算术/比较/布尔、下标、函数调用（白名单）、属性访问（白名单根）。
- 禁止：`import`、`__xxx__`、`exec`、`open`、`globals`、lambda（可选）。
- 暴露安全函数：`sin/cos/abs/min/max/clamp/lerp/map_range/noise/rand/floor...`
- 变量来自上游 payload + 内置 `frame/time/dt`。
这让"表达式节点"既强大又不会让 .blend 变成攻击面。

## 5. AI 层 (`nodes/ai/`)
- `AIProvider` 抽象基类：`complete(messages, **opts) -> str` / `stream(...)`。
- 内置 `OpenAICompatProvider`：标准 `/v1/chat/completions`，可填 `base_url`（OpenAI/Ollama/兼容服务）。
- 网络只用标准库 `urllib`（无第三方依赖，扩展无需 pip）。
- 节点：`AIChatNode`（prompt→文本）、`AIExpressionNode`（自然语言→受沙箱约束的表达式）、`AISceneCommandNode`（生成结构化动作指令，经校验后才执行）。
- Key 存 AddonPreferences，不写进 .blend。

## 6. 可扩展性约定（写给未来的你）
新增一个节点只需 3 步：
```python
@register_node
class MyCoolNode(NexusActionNode):
    bl_idname = "NexusMyCool"
    bl_label  = "My Cool"
    category  = "Action"
    def init_sockets(self):
        self.add_in_flow(); self.add_in("NexusNumberSocket", "Amount")
        self.add_out_flow()
    def process(self, signal, engine):
        ...                       # 副作用
        return self.flow_out(signal)
```
注册表会自动收集、自动加进添加菜单、自动出现在预览/调试里。**核心零改动**。

## 7. 数据预览器
- `DataPreviewNode`：把流经它的 signal/payload 快照到 `node["_preview"]`，在节点体里实时画表格。
- 全局 `Inspector` 面板：列出所有预览节点的最新值、点火次数、最近错误、引擎 FPS。
- 任意插槽可 hover 显示当前缓存值（draw 时读 memo）。
