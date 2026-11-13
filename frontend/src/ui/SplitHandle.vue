<template>
  <div
    class="split"
    :class="[orientation, { dragging }]"
    role="separator"
    :aria-orientation="orientation"
    :aria-label="label"
    :aria-valuenow="Math.round(value)"
    :aria-valuemin="min"
    :aria-valuemax="max"
    tabindex="0"
    @pointerdown="onDown"
    @dblclick="$emit('reset')"
    @keydown="onKey"
  >
    <span class="grip" aria-hidden="true"></span>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

const props = withDefaults(
  defineProps<{
    orientation: "vertical" | "horizontal";
    value: number;
    min: number;
    max: number;
    label: string;
    step?: number;
  }>(),
  { step: 16 },
);
const emit = defineEmits<{
  (e: "update", value: number): void;
  (e: "commit"): void;
  (e: "reset"): void;
}>();

const dragging = ref(false);
let startPos = 0;
let startValue = 0;

function apply(v: number) {
  emit("update", Math.max(props.min, Math.min(props.max, v)));
}

function onDown(e: PointerEvent) {
  if (e.button !== 0) return;
  e.preventDefault();
  dragging.value = true;
  startPos = props.orientation === "vertical" ? e.clientX : e.clientY;
  startValue = props.value;
  document.documentElement.classList.add("resizing");
  document.documentElement.style.cursor = props.orientation === "vertical" ? "col-resize" : "row-resize";
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onUp);
}

function onMove(e: PointerEvent) {
  if (!dragging.value) return;
  // 竖分隔条：向左拖 = 变宽；横分隔条：向上拖 = 变高
  const delta =
    props.orientation === "vertical" ? startPos - e.clientX : startPos - e.clientY;
  apply(startValue + delta);
}

function onUp() {
  if (!dragging.value) return;
  dragging.value = false;
  document.documentElement.classList.remove("resizing");
  document.documentElement.style.cursor = "";
  window.removeEventListener("pointermove", onMove);
  window.removeEventListener("pointerup", onUp);
  window.removeEventListener("pointercancel", onUp);
  emit("commit");
}

function onKey(e: KeyboardEvent) {
  const step = props.step;
  const grow = props.orientation === "vertical" ? "ArrowLeft" : "ArrowUp";
  const shrink = props.orientation === "vertical" ? "ArrowRight" : "ArrowDown";
  let next: number | null = null;
  if (e.key === grow) next = props.value + step;
  else if (e.key === shrink) next = props.value - step;
  else if (e.key === "Home") next = props.min;
  else if (e.key === "End") next = props.max;
  if (next === null) return;
  e.preventDefault();
  apply(next);
  emit("commit");
}
</script>

<style scoped>
.split {
  position: absolute;
  z-index: 25;
  touch-action: none;
  outline: none;
}
.split.vertical {
  top: 0;
  bottom: 0;
  left: -4px;
  width: 8px;
  cursor: col-resize;
}
.split.horizontal {
  left: 0;
  right: 0;
  top: -4px;
  height: 8px;
  cursor: row-resize;
}

/* 1px 细线：hover / 拖动时变成 2px 品牌色 */
.split::before {
  content: "";
  position: absolute;
  background: var(--border);
  transition: background var(--dur-fast) var(--ease-out), width var(--dur-fast) var(--ease-out),
    height var(--dur-fast) var(--ease-out);
}
.split.vertical::before {
  top: 0;
  bottom: 0;
  left: 3px;
  width: 1px;
}
.split.horizontal::before {
  left: 0;
  right: 0;
  top: 3px;
  height: 1px;
}
.split:hover::before,
.split.dragging::before,
.split:focus-visible::before {
  background: var(--brand);
}
.split.vertical:hover::before,
.split.vertical.dragging::before {
  left: 2px;
  width: 2px;
}
.split.horizontal:hover::before,
.split.horizontal.dragging::before {
  top: 2px;
  height: 2px;
}

/* 握把：明确告诉用户「这里可以拉」 */
.grip {
  position: absolute;
  background: var(--border-strong);
  border-radius: var(--r-pill);
  transition: background var(--dur-fast) var(--ease-out);
}
.split.vertical .grip {
  left: 1px;
  top: 50%;
  width: 4px;
  height: 36px;
  transform: translateY(-50%);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.split.horizontal .grip {
  top: 1px;
  left: 50%;
  width: 40px;
  height: 4px;
  transform: translateX(-50%);
}
.split:hover .grip,
.split.dragging .grip,
.split:focus-visible .grip {
  background: var(--brand);
  opacity: 1;
}

/* 拖动期间禁止误选 */
:global(html.resizing) {
  user-select: none;
}
:global(html.resizing *) {
  user-select: none !important;
}
</style>
