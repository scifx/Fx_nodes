# Fx Nodes — 把 Node-RED 复刻进 Blender

> Fx Nodes 的核心范式现在完全对齐 Node-RED：
> **控制线传递一个 `msg` 对象；主要负载是 `msg.payload` 和 `msg.topic`；也可以随意添加其它字段。**

## 核心模型

每次触发都会创建一个 Node-RED 风格的消息对象：

```python
msg = {
    "payload": ...,
    "topic": "...",
    # any other keys
}
```

节点沿控制线顺序执行，读写同一个 `msg`：

```text
Inject/Timer -> Function/Expression/Change -> Get/Set Property -> Debug
```

同名字段按顺序覆盖，所以下游一定看到最新值：

```text
Expression: msg.payload = 1
  -> Expression: msg.payload = payload + 1
  -> Debug sees payload == 2
```

分支时 `msg` 会复制，每个分支独立演化。

## Node-RED 上下文

支持 Node-RED 风格上下文：

```python
context          # 当前 Function 节点自己的 context
flow             # 当前节点图 / flow context
G 或 global_context  # global context
```

表达式节点里可用：

```python
payload
msg["payload"]
topic
flow["count"]
G["seed"]
global_context["seed"]
frame
time
dt
wall
```

> 注意：表达式是安全沙箱；如果需要完整 Python、import 模块、复杂逻辑，请用 Function 节点。

## 主要节点

- **Trigger / Inject 类**：Timer、Frame、Key、Click、Scene、Start、Manual。
- **Function**：完整 Python 代码能力，支持 `import`，返回 `msg` / `None` / `[msg, ...]`。
- **Expression**：安全表达式，默认写入 `msg.payload`，也可按需写到其它 `msg/flow/Global` 属性。
- **Change**：Set / Delete / Move 任意 `msg` / `flow` / `global` 属性。
- **Switch**：表达式条件分流 True / False。
- **Gate / Counter / Delay**：常用控制流节点。
- **Get Property**：读取 Blender `Copy Full Data Path` 到 msg 路径。
- **Set Property**：把表达式结果写入 Blender full data path。
- **Context**：显式读写 flow/global context。
- **Debug**：Node-RED debug 节点；按路径查看 `msg`、`payload`、`flow.xxx`、`Global.xxx`。
- **AI 节点**：默认也遵循 `msg.payload` 输入/输出；必要时可显式写入 `msg` 的其它字段，或读取 `msg/flow/Global` 里的场景参考信息。默认不在运行时自动调用网络生成，需显式开启对应的 `Generate On Flow` 选项。

## Function 节点

Function 节点是完整 Python：

```python
import math

msg["payload"] = math.sqrt(msg.get("payload", 9))
msg["topic"] = "sqrt"
flow["last"] = msg["payload"]
global_context["runs"] = global_context.get("runs", 0) + 1

return msg
```

返回规则：

```python
return msg        # 继续发送
return None       # 停止 / drop
return [msg1, msg2]  # 从同一个输出发送多条消息
```

## Shift+V：Blender 属性路径

1. 在 Blender 任意属性上右键：`Copy Full Data Path`。
2. 切到 Fx Nodes 节点图。
3. 按 **Shift+V**。
4. 弹窗选择：
   - `Get Property`
   - `Set Property`
5. 只创建你选择的一个节点。

Add 菜单在 Fx Nodes 节点图里直接显示 `Trigger / Logic / Action / Data / AI`，不会多套一层 Fx Nodes 根菜单。

## 安装

1. 把 `Fx_nodes/` 打包为 zip。
2. Blender → Edit → Preferences → Add-ons / Get Extensions → Install from Disk。
3. 新建 **Fx Nodes** 节点编辑器。
4. 可选：偏好设置里填 AI Base URL / Key / Model。

## 示例

在 Blender 文本编辑器里运行：

```python
from Fx_nodes.examples import build_all
build_all()
```

示例包含：

- Timer → Expression → Set Property → Debug
- Frame → Get Property → Debug
- Key → Counter → Expression → Set Property → Debug
- Manual → Function → Debug
- Function(收集场景信息到 payload 或 msg.scene) → Cache(默认 payload→payload，也可缓存到其它属性) → AI 节点(默认处理 payload，可选读取额外 reference)
- AI Scene Script 默认把生成的脚本写到 `msg.script`，把执行结果写到 `payload`，这样下游 Cache / AI 会拿到场景结果而不是脚本文本。
- AI Scene Script 默认**不**在运行时自动生成，也默认**不**自动执行脚本；需要时再显式开启 `Generate On Flow` / `Execute Script`。

## 超简单节点 API

新节点就是操作 `msg` 字典：

```python
from Fx_nodes.core.base import FxLogicNode
from Fx_nodes.core.registry import register_node

@register_node
class AddOneNode(FxLogicNode):
    bl_idname = "FxAddOne"
    bl_label = "Add One"
    category = "Logic"

    def init_sockets(self):
        self.add_in_flow()
        self.add_out_flow()

    def process(self, signal, engine):
        msg = signal.msg
        msg["payload"] = msg.get("payload", 0) + 1
        engine.flow_context["last_payload"] = msg["payload"]
        return self.flow_out(signal)
```

## 测试

```bash
python3 Fx_nodes/tests/test_core.py
python3 Fx_nodes/tests/test_integration.py
```
