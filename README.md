# Fx Nodes

> **Visual Event-Driven Automation & AI Paradigm for Blender Creators.**  
> Bringing the elegance of **Node-RED** message passing (`msg / flow / global`), **Animation Nodes** visual UI ergonomics, and deterministic **AI Agents** into Blender.

---

## ✨ Why Fx Nodes?

Fx Nodes reimagines Blender automation. Instead of linear procedural evaluation or dense scripting, Fx Nodes introduces an **asynchronous, event-driven control flow**:

- **Unified Message Model (`msg`)**: Control wires pass a structured dictionary (`msg`). Every node enriches, transforms, or routes this payload (`msg.payload`, `msg.topic`).
- **Animation Nodes Ergonomics**: Crafted with a clean, high-contrast aesthetic. All controls reside cleanly at the top of nodes, while **dynamic multi-line previews, JSON inspection, and error tracebacks render strictly below action buttons**—guaranteeing smooth interaction without UI layout shifts.
- **Blender Native Integration**: Bind complex logic to Blender `Text` datablocks with one click. Copy any property path in Blender and press **`Shift+V`** to instantly create interactive Property nodes.
- **Production-Grade Stability**: Protected by loop guards (`MAX_HOPS`), queue throttles (`MAX_QUEUE`), safe AST expression sandboxes, precise traceback line mapping, and strict execution preferences.

---

## 🏗️ Core Architecture & Paradigm

```text
[ Trigger: Timer / Key / Event ] ──▶ [ Logic: Expression / Function ] ──▶ [ Action: Set Property ] ──▶ [ Data: Debug ]
```

### 1. Message Lifecycle (`msg`)
Every trigger event initializes a fresh message object:
```python
msg = {
    "payload": ...,       # Primary data payload
    "topic": "...",       # Event routing topic
    "cache": {...}        # Custom metadata / upstream state
}
```
When a graph branches, `msg` is automatically cloned so parallel downstream executions evolve independently without race conditions.

### 2. Three-Tier Scope Hierarchy
Fx Nodes faithfully replicates Node-RED's contextual state management:

| Scope | Identifier in Expr / Script | Description |
| :--- | :--- | :--- |
| **Message** | `msg`, `payload`, `topic` | Ephemeral state traveling along control wires. |
| **Flow** | `flow` | Shared state across all nodes within the current Node Tree. |
| **Global** | `Global`, `G`, `global_context` | Persistent engine-wide state shared across trees and sessions. |
| **Runtime** | `context` | Environmental timing (`frame`, `time`, `dt`, `wall`, `fps`). |

---

## 🎨 UI Ergonomics & Animation Nodes Aesthetic

Guided by minimalist and professional UI standards, Fx Nodes features:

1. **Animation Nodes Color Palette & Visual Categories**:
   Reorganized into 7 clean, highly readable functional submenus with distinct, sophisticated AN-inspired color themes:
   - 🔴 **Trigger** `(Coral Red)`: Event endpoints (`Timer`, `Frame`, `Key`, `Click`, `Scene Event`, `Start`, `Manual`).
   - 🟢 **Property** `(Emerald Green)`: Direct Blender RNA data binding (`Get Property`, `Set Property`).
   - 🔵 **Logic** `(Sapphire Blue)`: Control flow & gates (`Switch`, `Gate`, `Counter`, `Delay`).
   - 🔷 **Script** `(Slate Blue)`: Execution & calculations (`Expression`, `Function`).
   - teal **Data** `(Marine Teal)`: Message & state mutations (`Change`, `Context`, `Cache`).
   - 🟤 **Debug** `(Bronze Amber)`: Graph inspection & console logs (`Debug`).
   - 🟣 **AI** `(Amethyst Purple)`: LLM automation (`AI Chat`, `AI → Expression`, `AI Scene Script`).
2. **Strict Control-vs-Preview Layout Separation**:
   Whether inspecting 64 rows of live JSON output, previewing an AI-generated Python script, or reviewing execution logs, previews never displace configuration controls. All interactive buttons (`Generate`, `Run`, `Clear`, `Copy JSON`) remain locked at the top.
3. **First-Class Multi-Line Editing**:
   Short StringProperties fall short for real engineering. All heavy nodes (`Function`, `Expression`, `Change`, `AI Chat`, `AI Expression`, `AI Scene Script`) natively connect to Blender **Text datablocks** via inline `+` (Create) and `TEXT` (Open Editor) buttons.
4. **Streamlined N-Panel Engine Controls**:
   Kept purely focused and clutter-free. Use the **Engine** sidebar panel to start/stop the master event scheduler, paste property paths via Shift+V, check global firing statistics, and perform one-click global clears (`Clear Debugs`, `Clear Errors`) without redundant tabs.

---

## 📦 Node Ecosystem (`Shift + A`)

### 🔴 Trigger (`When to execute`)
- **Timer**: Pulse execution every $N$ seconds in real-time. Driven by a dynamic 50 Hz master scheduler with automatic UI & Viewport live redrawing—running continuously even when your viewport or timeline is idle.
- **Frame**: Fire on viewport playback or step changes.
- **Key & Click**: Capture viewport keyboard shortcuts and mouse object raycasts.
- **Scene Event**: Listen to Depsgraph updates, file loads, and render hooks.
- **On Start & Manual**: Engine initialization and one-click debugging triggers.

### 🟢 Property (`Blender RNA scene interaction`)
- **Get Property**: Read any Blender full data path directly into a message property.
- **Set Property**: Write expressions or message values directly to Blender objects, modifiers, materials, or world settings.

### 🔵 Logic (`Control flow & gates`)
- **Switch**: Python condition routing (`msg.payload > 10` ──▶ `True` / `False`).
- **Gate**: Throttle, debounce, or pass every $N$-th signal.
- **Counter**: Increment state across loops or frames.
- **Delay**: Non-blocking asynchronous signal scheduling.

### 🔷 Script (`Code & calculations`)
- **Function**: Full Python power. Execute multi-line code, import modules, and return single messages, lists of messages, or halt execution (`return None`). Complete with precise traceback line reporting and safety preferences.
- **Expression**: Sandboxed mathematical and data expressions (`sin(payload) * 2 if len(msg['items']) > 0 else 0`). Safe against system injection.

### 🩵 Data (`Managing message & global state`)
- **Change**: Set, delete, or move attributes across `msg`, `flow`, and `Global` scopes.
- **Context**: Explicit bridge transferring variables between runtime contexts.
- **Cache**: Persist one-shot or per-frame history arrays.

### 🟤 Debug (`Inspection & diagnostics`)
- **Debug**: Pretty-print JSON data, log to Text datablocks, inspect types (`dict [4 keys]`, `list [12 items]`), and copy live payloads with one click.

### 🟣 AI (`Intelligent automation`)
- **AI Chat**: Template prompts with live runtime variables (`{payload}`, `{flow.seed}`).
- **AI → Expression**: Convert natural language requests into deterministic, syntax-validated sandboxed expressions.
- **AI Scene Script**: Natural language to executable Blender Python automation. Previews code syntax, catches compilation errors, executes inside view overrides, and returns execution summaries to `msg.payload`.

---

## ⚡ Productivity Shortcuts

### Shift+V: Instant Property Node Creation
1. Right-click any Blender interface property and select **`Copy Full Data Path`** (e.g., `bpy.data.objects['Cube'].location`).
2. Hover over the Fx Nodes editor and press **`Shift + V`**.
3. Choose **`Get Property`** or **`Set Property`**. The node spawns instantly under your mouse cursor, pre-configured with the exact target path.

---

## 🛡️ Safety & Production Stability

Because visual nodes can execute code and modify scenes at 60 FPS, Fx Nodes enforces strict safety boundaries:
- **Preference Controls**: Toggle `Enable AI Nodes`, `Allow Full Python Function`, and `Confirm before AI scene edits` in addon preferences. If untrusted files are opened, unsafe Python nodes gracefully lock down and report clear alerts.
- **Traceback Line Mapping**: When a Function script raises an error, the engine inspects the Python stack frame and highlights the exact line number of your script (`Line 4: KeyError: 'mesh'`).
- **Execution Throttling**: Infinite loop detection (`MAX_HOPS`) and queue limiters prevent runaway cycles from freezing the Blender viewport.

---

## 💻 Developer API: Create a Node in 15 Lines

Expanding Fx Nodes requires zero boilerplate. Subclass `FxLogicNode` and manipulate `signal.msg`:

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

---

## 🚀 Installation & Verification

1. Zip the `Fx_nodes/` repository directory.
2. In Blender: **Edit ──▶ Preferences ──▶ Add-ons ──▶ Install from Disk**.
3. Open a **Node Editor** area and switch the tree type to **Fx Nodes**.

### Run Automated Tests
Fx Nodes comes with headless integration and unit suites covering 100% of node registrations, socket behaviors, and expression sandboxes:
```bash
pytest
```
