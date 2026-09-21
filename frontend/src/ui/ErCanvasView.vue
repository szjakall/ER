<template>
  <div ref="host" class="host">
    <canvas ref="cv"></canvas>
    <div v-if="tip" class="tip">
      <div v-for="(line, i) in tip" :key="i">{{ line }}</div>
    </div>
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
      <button :class="{ on: !cardPicker.value }" @mousedown.stop @click="setCard(null)">×</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { createErCanvas, type ErCanvasApi } from "../canvas/ErCanvas";
import { detectOverlaps } from "../canvas/overlap";
import { severityOf, useErStore } from "../model/store";
import type { Cardinality, CardSymbol, PaintState, Shape } from "../protocol/types";

const store = useErStore();
const host = ref<HTMLElement | null>(null);
const cv = ref<HTMLCanvasElement | null>(null);
const tip = ref<string[] | null>(null);
const viewTick = ref(0);
const cardSymbols: CardSymbol[] = ["1", "N", "M", "P"];
let api: ErCanvasApi | null = null;

const paint = computed(() => {
  const map: Record<string, PaintState> = {};
  // 几何重叠（连线压到其它元素 / 属性椭圆）是前端本地规则，直接叠到着色上
  const overlaps = detectOverlaps(store.elements, store.connections);
  for (const e of store.elements) map[e.id] = severityOf(store.results[e.id], !!store.painted[e.id]);
  for (const c of store.connections) {
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

/** 选中"联系分支线"时，在连线上方显示 1/N/M 选择器 */
const cardPicker = computed(() => {
  void viewTick.value;
  void store.canvasTick;
  if (store.selectedKind !== "connection" || !store.selectedId) return null;
  const c = store.findConnection(store.selectedId);
  if (!c || !store.isRelationBranch(c.id)) return null;
  const anchor = api?.connectionAnchor(c.id);
  if (!anchor) return null;
  return { x: anchor.x, y: anchor.y, value: c.cardinality };
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
  api.resize(host.value.clientWidth, host.value.clientHeight);
}

function onKey(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (e.key === "Escape") {
    store.setTool("select");
    store.pendingFromId = null;
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

onMounted(async () => {
  await nextTick();
  if (!cv.value) return;
  api = createErCanvas(cv.value, {
    onSelect: (kind, id) => store.select(kind, id),
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
    onElementMoved: (id, x, y) => store.updatePosition(id, x, y),
    onAttrMoved: (id, index, x, y) => store.updateAttrOffset(id, index, x, y),
    onViewChanged: () => {
      viewTick.value += 1;
    },
  });
  resize();
  window.addEventListener("resize", resize);
  window.addEventListener("keydown", onKey);
  store.ensureClient();
  api.sync(store.elements, store.connections, paint.value);
});

onUnmounted(() => {
  window.removeEventListener("resize", resize);
  window.removeEventListener("keydown", onKey);
  api?.destroy();
});

watch(
  () => [store.canvasTick, store.tool, store.selectedId, store.selectedKind] as const,
  () => {
    if (!api) return;
    api.setTool(store.tool);
    api.sync(store.elements, store.connections, paint.value);
    api.selectVisual(store.selectedKind, store.selectedId);
  },
);

watch(
  () => [store.selectedId, store.painted, store.results] as const,
  () => {
    const id = store.selectedId;
    if (!id) {
      tip.value = null;
      return;
    }
    if (!store.painted[id]) {
      tip.value = [`${id} 尚未检查（灰）`];
      return;
    }
    const r = store.results[id];
    const lines = [...(r?.violations ?? []), ...(r?.suggestions ?? [])].map(
      (i) => `${i.rule_id} ${i.message}`,
    );
    tip.value = lines.length ? lines : [`${id} 通过`];
  },
  { deep: true },
);
</script>

<style scoped>
.host { position: relative; flex: 1; min-width: 0; background: #f8fafc; overflow: hidden; }
canvas { display: block; }
.tip {
  position: absolute; left: 16px; top: 16px; max-width: 360px;
  background: rgba(15, 23, 42, 0.92); color: #fff; padding: 8px 10px;
  border-radius: 8px; font-size: 12px; pointer-events: none; line-height: 1.45;
}
.card-picker {
  position: absolute;
  transform: translate(-50%, -140%);
  display: flex; gap: 4px;
  background: #0f172a; padding: 4px;
  border-radius: 8px; z-index: 30;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
}
.card-picker button {
  border: 0; background: #1e293b; color: #e2e8f0;
  min-width: 30px; height: 28px; border-radius: 6px; cursor: pointer;
  font-weight: 700; font-size: 14px;
}
.card-picker button.on { background: #2563eb; color: #fff; }
</style>
