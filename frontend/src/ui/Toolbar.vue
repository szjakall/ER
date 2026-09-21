<template>
  <div class="bar">
    <div class="brand">ER 实时提示</div>
    <div class="tools">
      <button
        :class="{ on: store.tool === 'entity' }"
        @click="arm('entity')"
        @dblclick="arm('entity', true)"
      >实体 ▭{{ mark('entity') }}</button>
      <button
        :class="{ on: store.tool === 'attribute' }"
        @click="arm('attribute')"
        @dblclick="arm('attribute', true)"
      >属性 ◯{{ mark('attribute') }}</button>
      <button
        :class="{ on: store.tool === 'relationship' }"
        @click="arm('relationship')"
        @dblclick="arm('relationship', true)"
      >联系 ◇{{ mark('relationship') }}</button>
      <button
        :class="{ on: store.tool === 'connect' }"
        @click="arm('connect')"
        @dblclick="arm('connect', true)"
      >连线{{ mark('connect') }}</button>
      <span class="tip">单击=建一个，双击=连续创建</span>
    </div>
    <div class="file">
      <button @click="loadLibrary">示例·学生选课</button>
      <button @click="loadTernary">示例·三元联系</button>
      <button @click="loadWeak">示例·弱实体</button>
      <button @click="onImport">导入</button>
      <button @click="onExport">导出</button>
      <button @click="store.batchCheck()">全量检查</button>
      <button @click="store.undo()">撤销</button>
      <button @click="store.redo()">重做</button>
      <button @click="store.clearAll()">清空</button>
      <input ref="file" type="file" accept="application/json" hidden @change="pick" />
    </div>
    <div class="ws" :class="store.wsStatus">{{ wsLabel }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useErStore, type Tool } from "../model/store";
import library from "../samples/library.json";
import ternary from "../samples/ternary.json";
import weak from "../samples/weak.json";

const store = useErStore();
const file = ref<HTMLInputElement | null>(null);
function arm(tool: Tool, continuous = false) {
  store.setTool(tool, continuous);
}
function mark(tool: Tool) {
  return store.tool === tool && store.continuous ? " ∞" : "";
}
const wsLabel = computed(() => {
  if (store.wsStatus === "open") return "后端已连接";
  if (store.wsStatus === "connecting") return "正在连接…";
  if (store.wsStatus === "error") return "连接失败（画布仍可用）";
  return "未连接（画布仍可用）";
});
function loadLibrary() {
  store.importDiagram(library);
}
function loadTernary() {
  store.importDiagram(ternary);
}
function loadWeak() {
  store.importDiagram(weak);
}
function onImport() {
  file.value?.click();
}
function pick(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const f = input.files?.[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      store.importDiagram(JSON.parse(String(reader.result)));
    } catch {
      store.toast("error", "JSON 无法解析");
    }
    input.value = "";
  };
  reader.readAsText(f, "utf-8");
}
function onExport() {
  const blob = new Blob([JSON.stringify(store.exportDiagram(), null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "er-diagram.json";
  a.click();
  URL.revokeObjectURL(a.href);
}
</script>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #0f172a;
  color: #e2e8f0;
  flex-wrap: wrap;
}
.brand { font-weight: 700; margin-right: 8px; }
.tools, .file { display: flex; gap: 6px; flex-wrap: wrap; }
button {
  border: 0; background: #1e293b; color: #e2e8f0;
  padding: 6px 10px; border-radius: 6px; cursor: pointer;
}
button.on, button:hover { background: #2563eb; }
.tip { font-size: 11px; color: #94a3b8; align-self: center; }
.ws { margin-left: auto; font-size: 12px; opacity: 0.85; }
.ws.open { color: #86efac; }
.ws.error, .ws.closed { color: #fca5a5; }
</style>
