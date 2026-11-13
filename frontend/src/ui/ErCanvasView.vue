<template>
  <div ref="host" class="host">
    <canvas ref="cv"></canvas>

    <!-- 空态引导 -->
    <div v-if="isEmpty" class="empty">
      <div class="empty-card">
        <div class="glyphs" aria-hidden="true">
          <span class="g rect"></span>
          <span class="g line"></span>
          <span class="g dia"></span>
          <span class="g line"></span>
          <span class="g oval"></span>
        </div>
        <h3>开始绘制 ER 图</h3>
        <p>用左侧工具栏放置实体、属性与联系；先画实体，再用连线接上联系菱形。</p>
        <div class="hints">
          <span><kbd>单击</kbd> 放置</span>
          <span><kbd>双击工具</kbd> 连续创建</span>
          <span><kbd>Esc</kbd> 退出</span>
        </div>
      </div>
    </div>

    <!-- 基数选择器 -->
    <div
      v-if="cardPicker"
      class="card-picker"
      :style="{ left: cardPicker.x + 'px', top: cardPicker.y + 'px' }"
    >
      <button
        v-for="s in cardSymbols"
        :key="s"
        :class="{ on: cardPicker.value === s }"
        @mousedown.stop
        @click="setCard(s)"
      >{{ s }}</button>
      <button class="clear" :class="{ on: !cardPicker.value }" @mousedown.stop @click="setCard(null)" title="清除">×</button>
    </div>

    <!-- 画布左下：比例 / 自动布局 / 吸附；菜单是 Teleport 浮层，不参与画布布局 -->
    <div class="canvas-tools">
      <div class="ratio-wrap" ref="ratioWrap">
        <button
          class="chip"
          :class="{ on: ratioOpen }"
          :aria-expanded="ratioOpen"
          aria-haspopup="dialog"
          title="画布比例：只改变工作画布尺寸，不移动已有图形"
          @click="toggleRatio"
        >
          <span class="ratio-glyph" :class="pageRatio" aria-hidden="true"></span>
          <span class="chip-label">画布 {{ ratioLabel(pageRatio) }}</span>
          <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </div>

      <div class="layout-wrap" ref="layoutWrap">
        <button
          class="chip"
          :class="{ on: layoutOpen }"
          :aria-expanded="layoutOpen"
          aria-haspopup="dialog"
          title="自动布局：只重新排列图形，不改变画布比例或视口缩放"
          @click="toggleLayout"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3" />
            <rect x="8" y="8" width="8" height="8" />
          </svg>
          <span class="chip-label">自动布局</span>
          <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </div>

      <CanvasAppearanceControl :model-value="appearance" @update:model-value="applyAppearance" />

      <button class="chip" :class="{ on: snap }" :aria-pressed="snap" title="拖动时吸附 8px 栅格（按住 Alt 临时关闭）" @click="toggleSnap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
          <path d="M4 9h16M4 15h16M9 4v16M15 4v16" />
        </svg>
        <span class="chip-label">吸附</span>
      </button>
    </div>

    <!-- 画布比例浮层：独立于自动布局，固定定位，绝不改变画布容器尺寸 -->
    <Teleport to="body">
      <transition name="menu">
        <div
          v-if="ratioOpen"
          ref="ratioPanelEl"
          class="ratio-menu floating-panel"
          :style="panelStyle(ratioWrap)"
          role="dialog"
          aria-modal="false"
          aria-label="画布比例"
        >
          <div class="panel-head">
            <div class="panel-heading">
              <span class="panel-title">画布比例</span>
              <span class="panel-sub">{{ pageSizeText }}</span>
            </div>
            <button class="panel-close" title="关闭（Esc）" aria-label="关闭画布比例面板" @click="ratioOpen = false">×</button>
          </div>
          <div class="panel-scroll">
            <div class="ratio-grid" role="group" aria-label="画布比例选项">
              <button
                v-for="o in PAGE_OPTIONS"
                :key="o.id"
                class="ratio-item"
                role="menuitemradio"
                :aria-checked="pageRatio === o.id"
                :class="{ on: pageRatio === o.id }"
                :title="`${o.label} · ${o.hint}`"
                @click="pickRatio(o.id)"
              >
                <span class="preview-slot" aria-hidden="true">
                  <span class="preview" :class="{ free: o.id === 'free' }" :style="previewStyle(o)"></span>
                </span>
                <span class="rlabel">{{ o.label }}</span>
              </button>
            </div>
          </div>
          <div class="panel-hint">比例只改变工作画布尺寸，不移动已有图形；图形超出时会自动扩大画布。切换比例可用 Ctrl+Z 撤销。</div>
        </div>
      </transition>
    </Teleport>

    <!-- 自动布局浮层：与比例菜单互相独立，只负责图形排列 -->
    <Teleport to="body">
      <transition name="menu">
        <div
          v-if="layoutOpen"
          ref="layoutPanelEl"
          class="layout-menu floating-panel"
          :style="panelStyle(layoutWrap)"
          role="dialog"
          aria-modal="false"
          aria-label="自动布局"
        >
          <div class="panel-head">
            <div class="panel-heading">
              <span class="panel-title">自动布局</span>
              <span class="panel-sub">按当前画布 {{ ratioLabel(pageRatio) }}</span>
            </div>
            <button class="panel-close" title="关闭（Esc）" aria-label="关闭自动布局面板" @click="layoutOpen = false">×</button>
          </div>
          <div class="panel-scroll layout-body">
            <p class="panel-note">只重新排列实体、属性、联系与连线，保留全部数据；不改变画布比例，也不重置当前视口缩放。</p>
            <button class="mact primary" @click="autoFitLayout">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3" />
                <rect x="8" y="8" width="8" height="8" />
              </svg>
              自动适配布局
            </button>
            <button class="mact" @click="relayout">重新排列</button>
            <button
              class="mact"
              :disabled="!(store.layoutMark > 0 && store.layoutMark === store.undoStack.length)"
              @click="undoLayout"
            >撤销布局</button>

            <dl v-if="store.layoutStats" class="layout-stats">
              <div><dt>参与者</dt><dd>{{ store.layoutStats.nodes }}</dd></div>
              <div><dt>页面利用</dt><dd>{{ Math.round(store.layoutStats.fill * 100) }}%</dd></div>
              <div><dt>最小字号</dt><dd>{{ Math.round(store.layoutStats.minFont) }}px</dd></div>
              <div><dt>重叠 / 交叉</dt><dd>{{ store.layoutStats.overlaps }} / {{ store.layoutStats.crossings }}</dd></div>
            </dl>
            <ul v-if="store.layoutWarnings.length" class="layout-warnings">
              <li v-for="(w, i) in store.layoutWarnings" :key="i">{{ w }}</li>
            </ul>
          </div>
        </div>
      </transition>
    </Teleport>

    <!-- 画布右下：缩放 / 适应画布 / 适应全部图形（两个适应命令完全分离） -->
    <div class="zoom">
      <button @click="zoomOut" title="缩小" aria-label="缩小">−</button>
      <button class="pct" @click="zoomReset" title="重置为 100%">{{ zoomPct }}%</button>
      <button @click="zoomIn" title="放大" aria-label="放大">+</button>
      <span class="zsep" aria-hidden="true"></span>
      <button
        class="fit"
        :disabled="pageRatio === 'free'"
        @click="fitPageView"
        title="适应画布：让整个页面显示在当前视口中"
        aria-label="适应画布"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="5" y="5" width="14" height="14" rx="1.5" />
          <path d="M8 3v3M16 3v3M8 18v3M16 18v3M3 8h3M3 16h3M18 8h3M18 16h3" />
        </svg>
      </button>
      <button
        class="fit"
        :disabled="!store.elements.length"
        @click="fitAllShapes"
        title="适应全部图形：让所有实体、属性、联系显示在当前视口中"
        aria-label="适应全部图形"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6" />
          <circle cx="9" cy="9.5" r="2.2" />
          <rect x="13.5" y="7" width="4.5" height="4" rx=".8" />
          <path d="M8.5 16.5h8" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { createErCanvas, type ErCanvasApi } from "../canvas/ErCanvas";
import {
  loadAppearance,
  normalizeAppearance,
  saveAppearance,
  type CanvasAppearance,
} from "../canvas/appearance";
import { detectOverlaps } from "../canvas/overlap";
import { PAGE_OPTIONS, ratioLabel, type PageBox, type PageOption, type PageRatio } from "../canvas/page";
import { severityOf, useErStore } from "../model/store";
import type { Cardinality, CardSymbol, PaintState, Shape } from "../protocol/types";
import { isFreeConnection } from "../protocol/types";
import CanvasAppearanceControl from "./CanvasAppearance.vue";

const store = useErStore();
const host = ref<HTMLElement | null>(null);
const cv = ref<HTMLCanvasElement | null>(null);
const viewTick = ref(0);
const zoomPct = ref(100);
const cardSymbols: CardSymbol[] = ["1", "N", "M", "P"];
const ratioOpen = ref(false);
const layoutOpen = ref(false);
const ratioWrap = ref<HTMLElement | null>(null);
const layoutWrap = ref<HTMLElement | null>(null);
const ratioPanelEl = ref<HTMLElement | null>(null);
const layoutPanelEl = ref<HTMLElement | null>(null);
const panelRevision = ref(0);
/** 画布实际页面盒（比例 / 自动布局都会更新），只用于面板显示尺寸 */
const livePageBox = ref<PageBox | null>(store.pageBox ? { ...store.pageBox } : null);
const SNAP_KEY = "erstudio.snap";
const appearance = ref<CanvasAppearance>(loadAppearance());
const pageRatio = computed(() => store.pageRatio);
let api: ErCanvasApi | null = null;
let ro: ResizeObserver | null = null;
let raf = 0;

const pageSizeText = computed(() => {
  if (pageRatio.value === "free") return "自由画布 · 无页面边界";
  const box = livePageBox.value;
  return box ? `${Math.round(box.w)} × ${Math.round(box.h)} px` : "正在计算页面尺寸…";
});

/**
 * 浮层定位：固定定位，锚在触发按钮上方；空间不足时自动改到下方。
 * 只计算屏幕坐标，不读写画布容器尺寸，也不触碰缩放 / 平移。
 */
function panelStyle(anchor: HTMLElement | null): Record<string, string> {
  // 依赖 panelRevision：窗口尺寸变化时重新计算
  void panelRevision.value;
  if (!anchor) return { left: "14px", bottom: "58px", width: "304px" };
  const r = anchor.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const margin = 8;
  const width = Math.min(304, Math.max(220, vw - margin * 2));
  const above = r.top - margin - 6;
  const below = vh - r.bottom - margin - 6;
  const openUp = above >= 220 || above >= below;
  const maxHeight = Math.max(180, Math.min(520, openUp ? above : below));
  const left = Math.min(Math.max(margin, r.left), Math.max(margin, vw - width - margin));
  const style: Record<string, string> = {
    left: `${Math.round(left)}px`,
    width: `${width}px`,
    maxHeight: `${Math.round(maxHeight)}px`,
  };
  if (openUp) style.bottom = `${Math.round(vh - r.top + 6)}px`;
  else style.top = `${Math.round(r.bottom + 6)}px`;
  return style;
}

function closePanels() {
  ratioOpen.value = false;
  layoutOpen.value = false;
}

function toggleRatio() {
  const next = !ratioOpen.value;
  layoutOpen.value = false;
  ratioOpen.value = next;
  if (next) panelRevision.value += 1;
}

function toggleLayout() {
  const next = !layoutOpen.value;
  ratioOpen.value = false;
  layoutOpen.value = next;
  if (next) panelRevision.value += 1;
}

function applyAppearance(next: CanvasAppearance) {
  const normalized = normalizeAppearance(next);
  appearance.value = normalized;
  saveAppearance(normalized);
  api?.setAppearance(normalized);
}

const snap = ref((() => {
  try {
    return localStorage.getItem(SNAP_KEY) !== "0";
  } catch {
    return true;
  }
})());

const isEmpty = computed(() => !store.elements.length);

const paint = computed(() => {
  const map: Record<string, PaintState> = {};
  // 几何重叠（连线压到其它元素 / 属性椭圆）是前端本地规则，直接叠到着色上
  const overlaps = detectOverlaps(store.elements, store.connections);
  for (const e of store.elements) map[e.id] = severityOf(store.results[e.id], !!store.painted[e.id]);
  for (const c of store.connections) {
    if (isFreeConnection(c)) {
      // 自由端连线的草稿状态：用建议色表示，不伪造后端校验结果
      map[c.id] = "warn";
      continue;
    }
    const extra = overlaps.get(c.id);
    if (extra?.length) {
      const r = store.results[c.id];
      map[c.id] = severityOf(
        { violations: [...(r?.violations ?? []), ...extra], suggestions: r?.suggestions ?? [] },
        true,
      );
    } else {
      map[c.id] = severityOf(store.results[c.id], !!store.painted[c.id]);
    }
  }
  return map;
});

/** 选中"联系分支线"时，在连线上方显示 1/N/M 选择器（贴边约束，不被裁切） */
const cardPicker = computed(() => {
  void viewTick.value;
  void store.canvasTick;
  if (store.selectedKind !== "connection" || !store.selectedId) return null;
  const c = store.findConnection(store.selectedId);
  if (!c || !store.isRelationBranch(c.id)) return null;
  const anchor = api?.connectionAnchor(c.id);
  if (!anchor) return null;
  const w = host.value?.clientWidth ?? 0;
  const h = host.value?.clientHeight ?? 0;
  return {
    x: Math.max(90, Math.min(w - 90, anchor.x)),
    y: Math.max(70, Math.min(h - 70, anchor.y)),
    value: c.cardinality,
  };
});

function setCard(s: Cardinality) {
  const id = store.selectedId;
  if (!id || store.selectedKind !== "connection") return;
  store.updateConnection(id, { cardinality: s });
}

function shapeOfTool(): Shape | null {
  if (store.tool === "entity") return "rectangle";
  if (store.tool === "attribute") return "ellipse";
  if (store.tool === "relationship") return "diamond";
  return null;
}

function resize() {
  if (!host.value || !api) return;
  const w = host.value.clientWidth;
  const h = host.value.clientHeight;
  if (w < 2 || h < 2) return;
  api.resize(w, h);
}

function scheduleResize() {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0;
    resize();
  });
}

function refreshZoom() {
  const z = api?.canvas.getZoom() ?? 1;
  zoomPct.value = Math.round(z * 100);
}
function zoomIn() {
  api?.zoomBy(1.25);
  refreshZoom();
}
function zoomOut() {
  api?.zoomBy(1 / 1.25);
  refreshZoom();
}
function zoomReset() {
  if (!api) return;
  const z = api.canvas.getZoom() || 1;
  api.zoomBy(1 / z);
  refreshZoom();
}
function fitPageView() {
  api?.fitPage();
  refreshZoom();
}
function fitAllShapes() {
  api?.fitContent();
  refreshZoom();
}

function pickRatio(id: PageRatio) {
  ratioOpen.value = false;
  // 画布比例只决定工作画布的尺寸约束：不重排图形、不改字号、不重置视口。
  // store 只会让画布重新推导页面盒，并显式执行一次「适应画布」。
  store.setPageRatio(id);
  void nextTick(refreshZoom);
}

/** 按当前页面比例重新做一次智能适配（只排图形，不动比例 / 视口） */
function autoFitLayout() {
  layoutOpen.value = false;
  if (!store.elements.length) {
    store.setPageRatio(store.pageRatio, { relayout: false });
    return;
  }
  store.autoLayout(store.pageRatio);
  refreshZoom();
}

function relayout() {
  layoutOpen.value = false;
  store.relayout();
  refreshZoom();
}

function undoLayout() {
  layoutOpen.value = false;
  store.undoLayout();
  refreshZoom();
}

function previewStyle(o: PageOption) {
  const r = o.value ?? 1;
  const maxW = 26;
  const maxH = 18;
  // 在 26×18 的格子里按比例内接，宽高都会变，比例一眼能看出来
  if (r >= maxW / maxH) {
    return { width: `${maxW}px`, height: `${Math.round(maxW / r)}px` };
  }
  return { width: `${Math.round(maxH * r)}px`, height: `${maxH}px` };
}

function toggleSnap() {
  snap.value = !snap.value;
  api?.setSnap(snap.value);
  try {
    localStorage.setItem(SNAP_KEY, snap.value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function onDocClick(e: MouseEvent) {
  const target = e.target as Node;
  if (
    ratioOpen.value &&
    !ratioWrap.value?.contains(target) &&
    !ratioPanelEl.value?.contains(target)
  ) {
    ratioOpen.value = false;
  }
  if (
    layoutOpen.value &&
    !layoutWrap.value?.contains(target) &&
    !layoutPanelEl.value?.contains(target)
  ) {
    layoutOpen.value = false;
  }
}

function onWindowResize() {
  if (ratioOpen.value || layoutOpen.value) panelRevision.value += 1;
}

let spaceHeld = false;
function onKeyDown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (e.code === "Space" && !spaceHeld) {
    spaceHeld = true;
    api?.setSpacePan(true);
    e.preventDefault();
  }
  if (e.key === "Escape") {
    store.setTool("select");
    store.pendingFromId = null;
    closePanels();
  }
  if (e.key === "Delete" || e.key === "Backspace") store.removeSelected();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    if (e.shiftKey) store.redo();
    else store.undo();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
    e.preventDefault();
    store.redo();
  }
}
function onKeyUp(e: KeyboardEvent) {
  if (e.code === "Space") {
    spaceHeld = false;
    api?.setSpacePan(false);
  }
}

onMounted(async () => {
  await nextTick();
  if (!cv.value) return;
  api = createErCanvas(cv.value, {
    onSelect: (kind, id) => store.select(kind, id),
    onSelectAttribute: (ownerId, index) => store.selectAttribute(ownerId, index),
    onClearSelection: () => store.clearSelection(),
    onBackgroundClick: (pt) => {
      const shape = shapeOfTool();
      if (shape) store.addElement(shape, pt);
      else store.clearSelection();
    },
    onNodeClick: (id) => store.clickConnectEndpoint(id),
    onConnCancel: () => {
      store.pendingFromId = null;
    },
    onFreePoint: (pt) => {
      const from = store.pendingFromId;
      if (from) store.addFreeConnection(from, pt);
    },
    onFreeEndMoved: (id, x, y) => store.updateFreeEndpoint(id, x, y),
    onElementMoved: (id, x, y) => store.updatePosition(id, x, y),
    onElementResized: (id, w, h) => store.resizeElement(id, w, h),
    onAttrMoved: (id, index, x, y) => store.updateAttrOffset(id, index, x, y),
    onViewChanged: () => {
      viewTick.value += 1;
      refreshZoom();
    },
    onPageChanged: (box) => {
      livePageBox.value = box;
      // 让 store 知道当前画布尺寸：下一次自动布局会装进这个页面，而不是另算一个。
      store.syncPageBox(box);
    },
  });
  api.setSnap(snap.value);
  resize();
  ro = new ResizeObserver(scheduleResize);
  if (host.value) ro.observe(host.value);
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("keyup", onKeyUp);
  window.addEventListener("resize", onWindowResize);
  document.addEventListener("click", onDocClick);
  store.ensureClient();
  api.setAppearance(appearance.value);
  api.sync(store.elements, store.connections, paint.value);
  if (store.pageBox) {
    api.setPageBox(store.pageBox);
    api.fitPage();
  } else if (store.pageRatio !== "free") {
    api.setPageRatio(store.pageRatio);
    api.fitPage();
  }
  refreshZoom();
});

onUnmounted(() => {
  ro?.disconnect();
  if (raf) cancelAnimationFrame(raf);
  window.removeEventListener("keydown", onKeyDown);
  window.removeEventListener("keyup", onKeyUp);
  window.removeEventListener("resize", onWindowResize);
  document.removeEventListener("click", onDocClick);
  api?.destroy();
});

watch(
  () => [store.canvasTick, store.tool, store.selectedId, store.selectedKind, store.selectedAttr] as const,
  () => {
    if (!api) return;
    api.setTool(store.tool);
    api.sync(store.elements, store.connections, paint.value);
    const attr = store.selectedAttr;
    api.selectVisual(
      store.selectedKind,
      store.selectedId,
      attr && attr.ownerId === store.selectedId ? attr.index : undefined,
    );
  },
);

// 诊断面板点击问题 → 画布闪烁高亮
watch(
  () => store.highlightTick,
  () => {
    const id = store.highlightId;
    if (id) api?.flashHighlight(id);
  },
);

// 页面尺寸变化：只应用新的页面盒 / 由内容重新推导页面。
// 这里绝不调用 fitPage / fitContent —— 页面变化与视口是两个独立系统。
watch(
  () => store.pageTick,
  () => {
    if (!api) return;
    if (store.pageBox) api.setPageBox(store.pageBox);
    else api.setPageRatio(store.pageRatio);
  },
);

// 导入 / 撤销重做 / 整理布局：按"有页面则整页、无页面则整图"适应一次
watch(
  () => store.fitTick,
  () => {
    api?.fitView();
    refreshZoom();
  },
);

// 显式「适应画布」：只装页面
watch(
  () => store.fitPageTick,
  () => {
    api?.fitPage();
    refreshZoom();
  },
);

// 显式「适应全部图形」：只装图形包围盒
watch(
  () => store.fitContentTick,
  () => {
    api?.fitContent();
    refreshZoom();
  },
);
</script>

<style scoped>
.host {
  position: relative;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  background: #efece4;
}
canvas {
  display: block;
}

/* 选中提示层（仅浮层，不改变图形） */
.card-picker {
  position: absolute;
  transform: translate(-50%, -150%);
  display: flex;
  gap: 4px;
  background: var(--panel);
  padding: 5px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  z-index: 30;
  box-shadow: var(--shadow-md);
}
.card-picker button {
  border: 1px solid var(--border-strong);
  background: var(--panel);
  color: var(--text-2);
  min-width: 30px;
  height: 28px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-weight: 700;
  font-size: 13px;
  font-family: var(--mono);
  transition: all 0.12s ease;
}
.card-picker button:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.card-picker button.on {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.card-picker button.clear {
  color: var(--text-3);
  font-size: 14px;
  font-family: inherit;
}

/* 空态 */
.empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 10;
}
.empty-card {
  text-align: center;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 30px 38px 26px;
  box-shadow: var(--shadow-md);
  max-width: 390px;
}
.glyphs {
  display: flex;
  gap: 9px;
  justify-content: center;
  align-items: center;
  margin-bottom: 18px;
  color: var(--text);
}
.g {
  display: inline-block;
}
.g.rect {
  width: 42px;
  height: 26px;
  border: 1.5px solid currentColor;
}
.g.dia {
  width: 30px;
  height: 21px;
  border: 1.5px solid currentColor;
  clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
  background: currentColor;
  position: relative;
}
.g.dia::after {
  content: "";
  position: absolute;
  inset: 1.5px;
  background: var(--panel);
  clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
}
.g.oval {
  width: 38px;
  height: 24px;
  border: 1.5px solid currentColor;
  border-radius: 50%;
}
.g.line {
  width: 14px;
  height: 1.5px;
  background: currentColor;
  opacity: 0.7;
}
.empty-card h3 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.empty-card p {
  margin: 0 0 16px;
  font-size: 12.5px;
  color: var(--text-3);
  line-height: 1.7;
}
.hints {
  display: flex;
  gap: 12px;
  justify-content: center;
  font-size: 11px;
  color: var(--text-3);
}
kbd {
  font-family: var(--mono);
  font-size: 10px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 5px;
  padding: 1px 5px;
  color: var(--text-2);
  margin-right: 3px;
}

/* 画布左下工具 */
.canvas-tools {
  position: absolute;
  left: 14px;
  bottom: 14px;
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 25;
}
.ratio-wrap,
.layout-wrap {
  position: relative;
  flex: 0 0 auto;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--shadow-xs);
  transition: all var(--dur-fast) var(--ease-out);
}
.chip:hover {
  border-color: var(--border-strong);
  color: var(--text);
}
.chip.on {
  color: var(--brand-strong);
  border-color: #cfd3ff;
  background: var(--brand-soft);
}
.chip svg {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
}
.chip .chev {
  width: 12px;
  height: 12px;
  opacity: 0.7;
  transition: transform var(--dur) var(--ease-out);
}
.chip[aria-expanded="true"] .chev {
  transform: rotate(180deg);
}
.chip-label {
  white-space: nowrap;
}
.ratio-glyph {
  width: 15px;
  height: 11px;
  border: 1.5px solid currentColor;
  border-radius: 1px;
  flex: 0 0 auto;
}
.ratio-glyph.golden {
  width: 15px;
  height: 9px;
}
.ratio-glyph.a4p {
  width: 11px;
  height: 15px;
}

/* ---------- 独立浮层：固定在视口内，不参与画布容器布局 ---------- */
.floating-panel {
  position: fixed;
  z-index: var(--z-dropdown);
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.panel-head {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 10px 8px 12px;
  border-bottom: 1px solid var(--border);
}
.panel-heading {
  min-width: 0;
}
.panel-title {
  display: block;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text);
}
.panel-sub {
  display: block;
  margin-top: 2px;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.panel-close {
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-3);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}
.panel-close:hover {
  background: var(--panel-2);
  color: var(--text);
}

.panel-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 6px;
}
.panel-hint {
  flex: 0 0 auto;
  padding: 8px 12px 10px;
  border-top: 1px solid var(--border);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--text-3);
}

/* 比例菜单：两列紧凑布局，打开时尽量少压画布 */
.ratio-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
}
.ratio-item {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 7px 7px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
  min-width: 0;
}
.ratio-item:hover {
  background: var(--panel-2);
}
.ratio-item.on {
  background: var(--brand-soft);
}
.ratio-item .preview-slot {
  width: 30px;
  height: 24px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
}
.ratio-item .preview {
  display: block;
  border: 1.5px solid var(--text-3);
  border-radius: 1px;
}
.ratio-item .preview.free {
  border-style: dashed;
}
.ratio-item.on .preview {
  border-color: var(--brand);
}
.ratio-item .rlabel {
  min-width: 0;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ratio-item.on .rlabel {
  color: var(--brand-strong);
}

/* 自动布局菜单 */
.layout-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.panel-note {
  margin: 0;
  padding: 2px 4px 4px;
  font-size: 11px;
  line-height: 1.55;
  color: var(--text-3);
}
.mact {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  width: 100%;
  padding: 8px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
}
.mact svg {
  width: 13px;
  height: 13px;
}
.mact:hover:not(:disabled) {
  border-color: var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.mact.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.mact.primary:hover:not(:disabled) {
  background: var(--brand-strong);
  border-color: var(--brand-strong);
  color: #fff;
}
.mact:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.layout-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 7px;
  margin: 2px 0 0;
  padding: 8px 9px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
}
.layout-stats > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.layout-stats dt {
  font-size: 10px;
  color: var(--text-3);
}
.layout-stats dd {
  margin: 0;
  font-family: var(--mono);
  font-size: 11.5px;
  font-weight: 650;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.layout-warnings {
  margin: 0;
  padding: 7px 9px 7px 22px;
  border-radius: var(--radius-sm);
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 10.5px;
  line-height: 1.5;
}
.layout-warnings li + li {
  margin-top: 3px;
}

.menu-enter-active,
.menu-leave-active {
  transition: opacity var(--dur) var(--ease-out), transform var(--dur) var(--ease-out);
}
.menu-enter-from,
.menu-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

/* 缩放 */
.zoom {
  position: absolute;
  right: 14px;
  bottom: 14px;
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 3px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-xs);
  z-index: 25;
}
.zoom button {
  border: 0;
  background: transparent;
  color: var(--text-2);
  width: 26px;
  height: 24px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 5px;
  cursor: pointer;
  line-height: 1;
  display: grid;
  place-items: center;
}
.zoom button:hover:not(:disabled) {
  background: var(--panel-2);
  color: var(--text);
}
.zoom button:disabled {
  opacity: 0.34;
  cursor: not-allowed;
}
.zoom button.pct {
  width: 44px;
  font-size: 11px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
}
.zoom button.fit {
  width: 28px;
}
.zoom button.fit svg {
  width: 15px;
  height: 15px;
}
.zsep {
  width: 1px;
  height: 16px;
  background: var(--border);
  margin: 0 2px;
}
</style>
