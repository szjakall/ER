<template>
  <header class="bar">
    <!-- 品牌 -->
    <div class="brand">
      <div class="logo" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round">
          <rect x="4.5" y="4.5" width="15" height="9" />
          <path d="M12 13.5v3.5" />
          <ellipse cx="12" cy="18.5" rx="3" ry="2" />
        </svg>
      </div>
      <div class="brand-text">
        <span class="name">ER Studio</span>
        <span class="sub">实时规范校验</span>
      </div>
    </div>

    <div class="spacer" />

    <!-- 编辑 / 检查 / 文件 -->
    <div class="actions">
      <div class="group">
        <button class="btn icon" :disabled="!store.undoStack.length" @click="store.undo()" title="撤销（Ctrl+Z）" aria-label="撤销">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6L5 10l4 4" /><path d="M5 10h9a5 5 0 015 5v1" /></svg>
        </button>
        <button class="btn icon" :disabled="!store.redoStack.length" @click="store.redo()" title="重做（Ctrl+Y）" aria-label="重做">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l4 4-4 4" /><path d="M19 10h-9a5 5 0 00-5 5v1" /></svg>
        </button>
      </div>

      <span class="divider" aria-hidden="true" />

      <button class="btn primary" @click="store.batchCheck()" title="一次性检查整张图">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12.5l5 5L20 6.5" /></svg>
        <span>全量检查</span>
      </button>

      <button class="btn" @click="onImport" title="导入 JSON 设计">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v10" /><path d="M8 10l4 4 4-4" /><path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
        <span>导入</span>
      </button>
      <button class="btn" @click="onExport" title="导出 JSON 设计">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V10" /><path d="M8 14l4-4 4 4" /><path d="M4 8V6a2 2 0 012-2h12a2 2 0 012 2v2" /></svg>
        <span>导出</span>
      </button>

      <!-- 示例下拉 -->
      <div class="menu-wrap" ref="menuWrap">
        <button class="btn" :class="{ open: showExamples }" :aria-expanded="showExamples" @click.stop="showExamples = !showExamples">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z" /><path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" /></svg>
          <span>示例</span>
          <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
        </button>
        <transition name="menu">
          <div v-if="showExamples" class="menu">
            <div class="menu-title">内置示例图</div>
            <button @click="pickExample('library')">
              <span>学生选课</span><span class="tag">M:N</span>
            </button>
            <button @click="pickExample('ternary')">
              <span>三元联系</span><span class="tag">M:N:P</span>
            </button>
            <button @click="pickExample('weak')">
              <span>弱实体</span><span class="tag">1:N</span>
            </button>
          </div>
        </transition>
      </div>

      <button class="btn danger" @click="store.clearAll()" title="清空画布">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16" /><path d="M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2" /><path d="M6 7l1 13h10l1-13" /></svg>
        <span>清空</span>
      </button>
    </div>

    <input ref="file" type="file" accept="application/json" hidden @change="pick" />
  </header>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useErStore } from "../model/store";
import library from "../samples/library.json";
import ternary from "../samples/ternary.json";
import weak from "../samples/weak.json";

const store = useErStore();
const file = ref<HTMLInputElement | null>(null);
const menuWrap = ref<HTMLElement | null>(null);
const showExamples = ref(false);

function pickExample(kind: "library" | "ternary" | "weak") {
  if (kind === "library") store.importDiagram(library);
  else if (kind === "ternary") store.importDiagram(ternary);
  else store.importDiagram(weak);
  showExamples.value = false;
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

function onDocClick(e: MouseEvent) {
  if (menuWrap.value && !menuWrap.value.contains(e.target as Node)) showExamples.value = false;
}
onMounted(() => document.addEventListener("click", onDocClick));
onUnmounted(() => document.removeEventListener("click", onDocClick));
</script>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  height: var(--topbar-h);
  padding: 0 12px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}

/* 品牌 */
.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  flex: 0 0 auto;
}
.logo {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--accent-grad);
  color: #fff;
  box-shadow: 0 3px 8px rgba(79, 70, 229, 0.28);
}
.logo svg {
  width: 19px;
  height: 19px;
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.1;
}
.brand-text .name {
  font-weight: 750;
  font-size: 14px;
  letter-spacing: -0.01em;
}
.brand-text .sub {
  font-size: 10.5px;
  color: var(--text-3);
  margin-top: 2px;
}

.spacer {
  flex: 1;
}
.divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  flex: 0 0 auto;
}

/* 按钮 */
.actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}
.group {
  display: flex;
  align-items: center;
  gap: 2px;
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 600;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.btn svg {
  width: 15px;
  height: 15px;
}
.btn:hover {
  background: var(--panel-2);
  border-color: var(--border-strong);
  color: var(--text);
}
.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn.icon {
  padding: 0 8px;
}
.btn.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
  font-weight: 650;
  box-shadow: 0 1px 3px rgba(79, 70, 229, 0.3);
}
.btn.primary:hover {
  background: var(--brand-strong);
  border-color: var(--brand-strong);
  color: #fff;
}
.btn.danger:hover {
  background: var(--error-soft);
  border-color: #f2c3cb;
  color: var(--error);
}

/* 示例下拉 */
.menu-wrap {
  position: relative;
}
.btn.open {
  background: var(--panel-2);
  border-color: var(--border-strong);
  color: var(--text);
}
.chev {
  width: 13px;
  height: 13px;
  transition: transform var(--dur) var(--ease-out);
}
.btn.open .chev {
  transform: rotate(180deg);
}
.menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 190px;
  padding: 6px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-dropdown);
}
.menu-title {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.03em;
  padding: 6px 8px 5px;
}
.menu button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 12.5px;
  padding: 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
}
.menu button:hover {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.menu .tag {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--brand);
  background: var(--brand-soft);
  padding: 1px 7px;
  border-radius: var(--r-pill);
}
.menu-enter-active,
.menu-leave-active {
  transition: all var(--dur) var(--ease-out);
}
.menu-enter-from,
.menu-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
