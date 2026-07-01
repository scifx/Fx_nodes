# Fx_nodes debug 分支修复报告 v2

日期：2026-07-01
分支：debug → fix/key-swallow-debug-msg-v2

用户二次反馈：
- 不需要向 `"value"` 的向后兼容
- 不应该默认屏蔽重复触发，重复触发应作为可选项（默认关闭）

## 修复的问题

### 1. 按键触发器（Key Trigger）绑定后未屏蔽原有按键行为

**最终方案：**
- `core/runtime.py::handle_input_event()` 返回 consumed bool
- `operators/__init__.py::FXNODES_OT_input_listener.modal()`：
  - consumed → `{'RUNNING_MODAL'}` 彻底阻断 Blender 原生快捷键
  - 未消费 → `{'PASS_THROUGH'}`
- `KeyTriggerNode`：
  - `swallow: BoolProperty(default=True)` – 默认屏蔽
  - `block_repeats: BoolProperty(default=False)` – **默认允许重复触发**，用户可选开启去抖
  - key 列表扩充：A-Z、0-9、F1-F12、TAB、ESC 等
- Click Trigger 同样增加 `swallow`（默认 False，谨慎）

msg 输出 Node-RED 化：
```python
msg = {
  "payload": event.type,
  "key": event.type,
  "value": event.value,
  "ctrl": ...,
  "shift": ...,
  "alt": ...,
  "oskey": ...
}
```

### 2. Debug 节点显示的 msg 是 values，不正确

**用户原话：** `debug显示的msg是values是不对的`

**根因：**
1. `show_context=True` 时输出 `{"value": <msg>, ...}`，msg 被包在 `"value"` 键下
2. `_json_safe()` 未处理 `dict_values` / `dict_keys` / `set`，导致出现 `"dict_values(...)"` 字符串
3. `msgpath.get("msg", ...)` 无 fast-path 保护

**v2 最终修复（移除 value 向后兼容）：**
- `DebugNode.process()`：
  - `path` fast-path：
    ```python
    if pl in ("msg","message"): value = signal.msg
    elif pl == "payload": value = signal.msg.get("payload", missing)
    elif pl == "topic": value = signal.msg.get("topic", missing)
    ```
  - **show_context 输出彻底移除 `"value"` 键**，完全 Node-RED 风格：
    ```python
    output = {
      "msg": <完整msg dict>,
      "payload": msg.get("payload"),
      "topic": msg.get("topic"),
      "path": path,
      "_extracted": <提取值>,   # 内部调试用，带下划线避免与 msg 键冲突
      "context": {...},
      "flow": {...},
      "global": {...},
      "Global": {...}  # 保留大写别名
    }
    ```
  - 不再输出顶层 `"value"`，**无向后兼容**，符合用户要求
- `_json_safe()`：
  - 支持 `set` / `frozenset` / `dict_keys` / `dict_values` / `dict_items`
  - 映射型对象自动 `items()` 转 dict
  - 上限提升至 128 项
- `draw_previews()`：
  - 标题显示 `msg: dict[3]` / `payload → list[5]`
  - show_context 模式读取 `_extracted` 字段显示类型

- `operators/_build_signal_from_upstream()`：
  - 适配新结构：优先 `_extracted` → `msg` → `payload`
  - 移除对旧 `"value"` 键的主路径依赖

## 改动文件

1. **core/runtime.py**
   - `handle_input_event(): bool` – 返回是否消费
   - key/click swallow 支持
   - msg Node-RED 化，`payload` 为主键
   - click 的 object 存 `obj.name`

2. **operators/__init__.py**
   - modal: consumed ? RUNNING_MODAL : PASS_THROUGH
   - `_build_signal_from_upstream()`: 解析新 Debug 格式 `_extracted` / `msg` / `payload`，移除 value 向后兼容主路径

3. **nodes/triggers/__init__.py**
   - `KeyTriggerNode`: +swallow(default True), +block_repeats(**default False**)
   - `ClickTriggerNode`: +swallow(default False)
   - key 列表大幅扩展

4. **nodes/data/__init__.py**
   - `DebugNode`:
     - `_json_safe`: 支持 dict_views / set
     - `process`: msg 路径 fast-path，**输出无 "value" 键**，改为 `"msg"` + `"_extracted"`
     - `draw_previews`: 显示 path 名称

## 测试

```
41 passed
test_debug_reads_global_and_show_context_includes_global PASSED
test_debug_missing_path_reports_error_instead_of_null PASSED
```

## 使用

- **Key Trigger**：勾选 **Swallow Key**（默认开）即可屏蔽 Blender 原生快捷键。**Block Repeats 默认关闭**，长按会重复触发；需要去抖时手动开启。
- **Debug**：`Path=msg` 直接输出完整 msg dict。开启 Show Runtime Context 后，预览顶层即是：
  ```
  msg: {...}
  payload: ...
  topic: ...
  context: ...
  flow: ...
  global: ...
  ```
  不再出现 `value` / `values` 混淆。
