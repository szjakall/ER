<template>
  <div
    class="app"
    :style="{ '--dock-h': dockH + 'px', '--inspector-w': inspectorW + 'px' }"
  >
    <!-- 顶栏 -->
    <header class="app-topbar">
      <TopBar />
    </header>

    <!-- 工作区：左工具轨 | 画布 | 检查器 -->
    <main class="app-workspace">
      <LeftToolbar />
      <ErCanvasView />
      <button
        v-if="!inspectorOpen"
        class="drawer-toggle"
        aria-controls="inspector-panel"
        :aria-expanded="inspectorOpen"
        @click="inspectorOpen = true"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
          <path d="M15 4.5v15" />
        </svg>
        检查器
      </button>
      <div v-if="inspectorOpen" class="drawer-scrim" aria-hidden="true" @click="inspectorOpen = false"></div>
      <Inspector
        id="inspector-panel"
        class="inspector-drawer"
        :class="{ 'drawer-open': inspectorOpen }"
        :width="inspectorW"
        :max-width="maxInspector"
        @resize="onInspectorResize"
        @commit="commitInspector"
      />
    </main>

    <!-- 底部诊断 Dock -->
    <IssuePanel
      :height="dockH"
      :max-height="maxDock"
      @resize="onDockResize"
      @commit="commitDock"
    />

    <!-- 状态栏 -->
    <footer class="app-statusbar">
      <div class="sb-conn" :class="store.wsStatus">
        <i class="sb-dot" aria-hidden="true"></i>
        <span>{{ wsLabel }}</span>
      </div>

      <span class="sb-sep" aria-hidden="true"></span>

      <div class="sb-group">
        <span class="sb-item error">
          <i class="sb-dot" aria-hidden="true"></i>
          <span class="sb-label">错误</span>
          <b>{{ store.paintStats.error }}</b>
        </span>
        <span class="sb-item warn">
          <i class="sb-dot" aria-hidden="true"></i>
          <span class="sb-label">建议</span>
          <b>{{ store.paintStats.warn }}</b>
        </span>
        <span class="sb-item ok">
          <i class="sb-dot" aria-hidden="true"></i>
          <span class="sb-label">通过</span>
          <b>{{ store.paintStats.ok }}</b>
        </span>
        <span class="sb-item pending">
          <i class="sb-dot" aria-hidden="true"></i>
          <span class="sb-label">未检查</span>
          <b>{{ store.paintStats.pending }}</b>
        </span>
      </div>

      <span class="sb-sep" aria-hidden="true"></span>

      <div class="sb-group sb-meta">
        <span><b>{{ store.elements.length }}</b> 元素</span>
        <span><b>{{ store.connections.length }}</b> 连线</span>
      </div>

      <span class="sb-hint">{{ hint }}</span>
    </footer>

    <!-- 通知 -->
    <transition-group name="toast" tag="div" class="toasts" role="status" aria-live="polite">
      <div v-for="n in store.notices" :key="n.id" class="toast" :class="n.level">
        <span class="t-icon" aria-hidden="true">
          <svg v-if="n.level === 'error'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M15 9l-6 6M9 9l6 6" />
          </svg>
          <svg v-else-if="n.level === 'warn'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3.5l9 16H3z" />
            <path d="M12 10v4" />
            <path d="M12 17h.01" />
          </svg>
          <svg v-else-if="n.level === 'ok'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 12.5l5 5L20 6.5" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 11v5" />
            <path d="M12 8h.01" />
          </svg>
        </span>
        <span class="t-text">{{ n.text }}</span>
      </div>
    </transition-group>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useErStore } from "./model/store";
import TopBar from "./ui/TopBar.vue";
import LeftToolbar from "./ui/LeftToolbar.vue";
import Inspector from "./ui/Inspector.vue";
import IssuePanel from "./ui/IssuePanel.vue";
import ErCanvasView from "./ui/ErCanvasView.vue";
import { clampNumber, usePersistentNumber } from "./ui/usePersistentNumber";

const store = useErStore();
const inspectorOpen = ref(false);
// 仅开发环境：便于在浏览器控制台 / 回归脚本核对模型与自由端连线
if (import.meta.env.DEV) {
  (window as unknown as { __erStore?: typeof store }).__erStore = store;
}
const { value: inspectorW, set: persistInspectorW } = usePersistentNumber("erstudio.inspectorW", 320);
const { value: dockH, set: persistDockH } = usePersistentNumber("erstudio.dockH", 240);
const maxInspector = ref(560);
const maxDock = ref(520);

const hint = computed(() => {
  const cont = store.continuous ? "连续创建中 · Esc 退出" : "";
  if (store.tool === "entity") return `单击画布放置实体${cont ? " · " + cont : ""}`;
  if (store.tool === "attribute") return `单击画布放置属性椭圆${cont ? " · " + cont : ""}`;
  if (store.tool === "relationship") return `单击画布放置联系菱形${cont ? " · " + cont : ""}`;
  if (store.tool === "connect") return store.pendingFromId ? "再点目标元素完成连线" : "依次点两个元素连线";
  if (store.tool === "free")
    return store.pendingFromId
      ? "移动到任意位置，单击确认自由端点 · Esc 取消"
      : "先点一个参与者（实体 / 属性 / 联系），自由端不吸附";
  return "滚轮缩放 · 拖动空白处平移 · 空格拖拽平移 · 属性椭圆可拖动";
});

const wsLabel = computed(() => {
  if (store.wsStatus === "open") return "已连接";
  if (store.wsStatus === "connecting") return "连接中";
  if (store.wsStatus === "error") return "连接失败";
  return "未连接";
});

function measure() {
  maxInspector.value = Math.max(264, Math.min(560, window.innerWidth - 52 - 480));
  maxDock.value = Math.max(160, window.innerHeight - 52 - 32 - 220);
  inspectorW.value = clampNumber(inspectorW.value, 264, maxInspector.value);
  dockH.value = clampNumber(dockH.value, 40, maxDock.value);
}

function onInspectorResize(v: number) {
  inspectorW.value = clampNumber(v, 264, maxInspector.value);
}
function commitInspector() {
  persistInspectorW(inspectorW.value);
}
function onDockResize(v: number) {
  dockH.value = clampNumber(v, 40, maxDock.value);
}
function commitDock() {
  persistDockH(dockH.value);
}

onMounted(() => {
  measure();
  window.addEventListener("resize", measure);
});
onUnmounted(() => window.removeEventListener("resize", measure));
</script>

<style scoped>
/* ================= 应用外壳：顶栏 / 工作区 / 诊断 / 状态栏 ================= */
.app {
  height: 100%;
  display: grid;
  grid-template-rows: var(--topbar-h) minmax(0, 1fr) var(--dock-h) var(--statusbar-h);
  background: var(--bg);
  overflow: hidden;
}

.app-topbar {
  min-width: 0;
}

.app-workspace {
  display: flex;
  min-height: 0;
  min-width: 0;
  position: relative;
}

/* 窄屏抽屉式检查器 */
.drawer-toggle,
.drawer-scrim {
  display: none;
}

@media (max-width: 900px) {
  .drawer-toggle {
    position: absolute;
    top: 10px;
    right: 10px;
    z-index: 30;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--panel);
    color: var(--text-2);
    font-size: 11.5px;
    font-weight: 600;
    box-shadow: var(--shadow-sm);
    cursor: pointer;
  }
  .drawer-toggle svg {
    width: 14px;
    height: 14px;
  }
  .drawer-toggle:hover {
    color: var(--text);
    border-color: var(--border-strong);
  }
  .drawer-scrim {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 45;
    background: rgba(28, 26, 22, 0.26);
  }
  .inspector-drawer {
    position: fixed !important;
    top: var(--topbar-h);
    right: 0;
    bottom: calc(var(--statusbar-h) + var(--dock-h));
    width: min(360px, 88vw) !important;
    flex: none !important;
    z-index: 46;
    transform: translateX(100%);
    transition: transform var(--dur) var(--ease-out);
    box-shadow: var(--shadow-lg);
  }
  .inspector-drawer.drawer-open {
    transform: translateX(0);
  }
}

/* ================= 状态栏 ================= */
.app-statusbar {
  display: flex;
  align-items: center;
  gap: 12px;
  height: var(--statusbar-h);
  padding: 0 14px;
  background: var(--panel);
  border-top: 1px solid var(--border);
  font-size: var(--fs-12);
  color: var(--text-2);
  user-select: none;
  min-width: 0;
  overflow: hidden;
}

.sb-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--pending);
  flex: 0 0 auto;
}

/* 连接状态 */
.sb-conn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  font-weight: 550;
  flex: 0 0 auto;
}
.sb-conn.open {
  color: var(--ok);
}
.sb-conn.open .sb-dot {
  background: var(--ok);
}
.sb-conn.connecting {
  color: var(--warn);
}
.sb-conn.connecting .sb-dot {
  background: var(--warn);
}
.sb-conn.error {
  color: var(--error);
}
.sb-conn.error .sb-dot {
  background: var(--error);
}
.sb-conn.closed {
  color: var(--text-3);
}

/* 分隔线 */
.sb-sep {
  width: 1px;
  height: 14px;
  background: var(--border);
  flex: 0 0 auto;
}

/* 分组 */
.sb-group {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
}

.sb-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.sb-item b {
  font-weight: 650;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.sb-item .sb-label {
  color: var(--text-3);
}

.sb-item.error .sb-dot {
  background: var(--error);
}
.sb-item.warn .sb-dot {
  background: var(--warn);
}
.sb-item.ok .sb-dot {
  background: var(--ok);
}
.sb-item.pending .sb-dot {
  background: var(--pending);
}

/* 画布信息 */
.sb-meta {
  gap: 14px;
  color: var(--text-3);
}
.sb-meta b {
  font-weight: 650;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  margin-right: 1px;
}

/* 上下文提示 */
.sb-hint {
  margin-left: auto;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

/* 窄屏：收起文字标签，保留数字与提示 */
@media (max-width: 1100px) {
  .sb-item .sb-label {
    display: none;
  }
}
@media (max-width: 860px) {
  .sb-meta {
    display: none;
  }
}

/* ================= 通知 ================= */
.toasts {
  position: fixed;
  right: calc(var(--inspector-w) + 16px);
  /* 抬到画布底部工具条（比例 / 缩放）之上，避免遮挡重要控件 */
  bottom: calc(var(--statusbar-h) + var(--dock-h) + 64px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: var(--z-toast);
  pointer-events: none;
  transition: bottom var(--dur) var(--ease-out);
}
.toast {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 13px;
  border-radius: var(--r-md);
  font-size: var(--fs-13);
  line-height: 1.4;
  box-shadow: var(--shadow-md);
  /* 通知是纯信息层：即使压在控件上也绝不拦截点击 */
  pointer-events: none;
  max-width: 380px;
  background: var(--text);
  color: #fff;
}
.toast .t-icon {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.16);
  flex: 0 0 auto;
}
.toast .t-icon svg {
  width: 12px;
  height: 12px;
}
.toast.error {
  background: #a3123a;
}
.toast.warn {
  background: #9a3412;
}
.toast.ok {
  background: #166534;
}
.toast.info {
  background: var(--text);
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--dur-slow) var(--ease-out),
    transform var(--dur-slow) var(--ease-out);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
</style>
