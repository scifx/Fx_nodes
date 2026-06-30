# Fx Nodes — Node-RED in Blender

Fx Nodes 的目标已经收敛为：**把 Node-RED 范式复刻进 Blender，并保留 Blender/Python/表达式/属性路径能力。**

---

## 1. 核心范式

```text
control wire passes msg downstream
```

每条控制线传递一个 `msg` dict：

```python
msg = {
    "payload": ...,
    "topic": "...",
    # arbitrary keys are allowed
}
```

节点顺序执行，直接读写 `msg`。同名字段按执行顺序覆盖，分支时浅拷贝 `msg`。

---

## 2. Context 模型

对齐 Node-RED：

| Store | Python object | Scope |
|---|---|---|
| node context | `engine.node_context(node_uid)` | 单个节点 |
| flow context | `engine.flow_context` | 当前 FxNodeTree / engine |
| global context | `engine.global_context` | 当前 engine 的全局表 |

Function 节点里可用：

```python
msg
context
flow
global_context
node
engine
```

Expression 节点里可用：

```python
payload
topic
msg
flow
G
global_context
frame/time/dt/wall
```

---

## 3. 模块结构

```text
Fx_nodes/
├── core/
│   ├── signal.py      # Signal.msg: Node-RED message object
│   ├── engine.py      # push execution + node/flow/global context
│   ├── msgpath.py     # Node-RED-like msg/flow/global property paths
│   ├── path.py        # safe Blender full data path get/set
│   ├── expr.py        # sandbox expression evaluator
│   ├── base.py        # simple node API
│   └── runtime.py     # Blender handlers/timers/modal listener
├── nodes/
│   ├── triggers/      # Inject-like event sources
│   ├── logic/         # Function / Expression / Switch / Gate / Counter / Delay
│   ├── data/          # Debug / Change / Context / Get Property
│   ├── actions/       # Set Property
│   └── ai/
├── ui/
├── operators/
├── prefs.py
└── examples/
```

---

## 4. Node API

写新节点应该非常简单：

```python
def process(self, signal, engine):
    msg = signal.msg
    msg["payload"] = msg.get("payload", 0) + 1
    engine.flow_context["last"] = msg["payload"]
    return self.flow_out(signal)
```

常用 helper：

```python
self.msg(signal)
self.payload(signal)
self.set_payload(signal, value)
self.node_context(engine)
self.flow_context(engine)
self.global_context(engine)
self.expr_vars(signal, engine)
```

---

## 5. 主要节点

- **Function**：完整 Python，允许 import，返回 `msg` / `None` / `[msg, ...]`。
- **Expression**：安全表达式，写入 msg/flow/global path。
- **Change**：Set / Delete / Move msg/flow/global path。
- **Switch**：条件分流。
- **Debug**：按路径查看 msg/flow/global。
- **Get Property / Set Property**：桥接 Blender RNA full data path。

---

## 6. Blender 属性路径

Shift+V 工作流：

1. Blender 属性上 Copy Full Data Path。
2. Fx Nodes 中按 Shift+V。
3. 选择 Get Property 或 Set Property。
4. 节点保存安全校验后的 Blender full data path。

`core/path.py` 只允许：

```python
bpy.data.objects["Cube"].location[0]
bpy.context.scene.render.fps
```

禁止任意函数调用/dunder/import。

---

## 7. 安全边界

- Expression 节点：安全 AST 沙箱。
- Blender Property path：安全 AST 路径解析。
- Function 节点：按用户要求提供完整 Python 能力，包括 import；因此它是显式的 power-user escape hatch。
