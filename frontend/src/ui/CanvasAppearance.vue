<template>
  <div ref="wrap" class="look-wrap">
    <button
      class="chip"
      :aria-expanded="open"
      aria-haspopup="dialog"
      title="画布外观：背景、网格与图形主题"
      @click="toggle"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 3.5v17M3.5 12h17" />
        <path d="M12 7h5v5h-5z" fill="currentColor" stroke="none" opacity=".22" />
      </svg>
      <span class="chip-label">画布外观</span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>

    <transition name="menu">
      <div v-if="open" class="look-menu" role="dialog" aria-label="画布外观设置">
        <div class="menu-head">
          <span class="menu-title">画布外观</span>
          <button class="reset" @click="reset">恢复默认</button>
        </div>

        <div class="section-label">背景</div>
        <div class="swatches" role="group" aria-label="背景颜色">
          <button
            v-for="p in BACKGROUND_PRESETS"
            :key="p.id"
            class="swatch"
            :data-bg="p.id"
            :class="{ on: same(draft.background, p.value) }"
            :style="{ background: p.value }"
            :title="p.label"
            :aria-label="p.label"
            :aria-pressed="same(draft.background, p.value)"
            @click="setBackground(p.value)"
          ></button>
        </div>
        <label class="custom-row">
          <span>自定义</span>
          <input class="color" type="color" :value="draft.background" @input="onCustomColor" aria-label="自定义背景颜色" />
          <code>{{ draft.background }}</code>
        </label>

        <div class="section-label">网格</div>
        <div class="seg three" role="group" aria-label="网格样式">
          <button v-for="g in GRID_OPTIONS" :key="g.id" :data-grid="g.id" :class="{ on: draft.grid === g.id }" @click="setGrid(g.id)">
            <span class="grid-glyph" :class="g.id" aria-hidden="true"></span>
            {{ g.label }}
          </button>
        </div>

        <div class="section-label">图形主题</div>
        <div class="seg two" role="group" aria-label="图形主题">
          <button :data-theme="'textbook'" :class="{ on: draft.theme === 'textbook' }" @click="setTheme('textbook')">教材规范</button>
          <button :data-theme="'display'" :class="{ on: draft.theme === 'display' }" @click="setTheme('display')">展示主题</button>
        </div>

        <div v-if="draft.theme === 'display'" class="accents" role="group" aria-label="展示主题配色">
          <button
            v-for="a in ACCENT_PRESETS"
            :key="a.id"
            class="accent"
            :data-accent="a.id"
            :class="{ on: same(draft.accent, a.value) }"
            :style="{ '--swatch': a.value }"
            :title="a.label"
            :aria-label="a.label"
            :aria-pressed="same(draft.accent, a.value)"
            @click="setAccent(a.value)"
          >
            <i aria-hidden="true"></i>
            {{ a.label }}
          </button>
        </div>

        <p class="note">
          背景与网格只改变画布外观；图形主题只改变渲染，不改变实体、属性、联系的业务含义，也不会写入 ER 数据。
        </p>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  ACCENT_PRESETS,
  BACKGROUND_PRESETS,
  DEFAULT_APPEARANCE,
  normalizeAppearance,
  type CanvasAppearance,
  type GridMode,
  type ShapeTheme,
} from "../canvas/appearance";

const props = defineProps<{ modelValue: CanvasAppearance }>();
const emit = defineEmits<{ (e: "update:model-value", value: CanvasAppearance): void }>();

const GRID_OPTIONS: Array<{ id: GridMode; label: string }> = [
  { id: "dots", label: "点阵" },
  { id: "lines", label: "细线" },
  { id: "off", label: "关闭" },
];

const wrap = ref<HTMLElement | null>(null);
const open = ref(false);
const draft = computed(() => normalizeAppearance(props.modelValue));

function same(a: string, b: string) {
  return a.toLowerCase() === b.toLowerCase();
}
function emitNext(patch: Partial<CanvasAppearance>) {
  emit("update:model-value", normalizeAppearance({ ...draft.value, ...patch }));
}
function toggle() {
  open.value = !open.value;
}
function setBackground(value: string) {
  emitNext({ background: value });
}
function onCustomColor(e: Event) {
  const value = (e.target as HTMLInputElement).value;
  emitNext({ background: value });
}
function setGrid(grid: GridMode) {
  emitNext({ grid });
}
function setTheme(theme: ShapeTheme) {
  emitNext({ theme });
}
function setAccent(accent: string) {
  emitNext({ accent });
}
function reset() {
  emit("update:model-value", { ...DEFAULT_APPEARANCE });
}
function onDocClick(e: MouseEvent) {
  if (wrap.value && !wrap.value.contains(e.target as Node)) open.value = false;
}
onMounted(() => document.addEventListener("click", onDocClick, true));
onUnmounted(() => document.removeEventListener("click", onDocClick, true));
</script>

<style scoped>
.look-wrap {
  position: relative;
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
.chip[aria-expanded="true"] {
  color: var(--brand-strong);
  border-color: #cfd3ff;
  background: var(--brand-soft);
}
.chip[aria-expanded="true"] .chev {
  transform: rotate(180deg);
}
.chip-label {
  white-space: nowrap;
}

.look-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  width: 292px;
  max-height: min(70vh, 560px);
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 12px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-dropdown);
}

.menu-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 4px;
}
.menu-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text);
}
.reset {
  border: 0;
  background: transparent;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 0;
}
.reset:hover {
  color: var(--brand);
}

.section-label {
  margin: 12px 0 6px;
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0.04em;
  color: var(--text-3);
}

.swatches {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px;
}
.swatch {
  position: relative;
  height: 30px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  cursor: pointer;
  transition: box-shadow var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.swatch:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}
.swatch.on {
  box-shadow: 0 0 0 2px var(--panel), 0 0 0 4px var(--brand);
}
.swatch.on::after {
  content: "";
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--brand);
  box-shadow: 0 0 0 1.5px var(--panel);
}
.swatch[style*="#FFFFFF"],
.swatch[style*="#FAF7F0"] {
  box-shadow: inset 0 0 0 1px rgba(28, 26, 22, 0.06);
}

.custom-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-2);
}
.custom-row > span {
  flex: 0 0 auto;
  color: var(--text-3);
}
.color {
  width: 32px;
  height: 26px;
  padding: 0;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--panel);
  cursor: pointer;
}
.custom-row code {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-3);
  letter-spacing: 0.02em;
}

.seg {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
}
.seg button {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.seg button:hover {
  color: var(--text);
}
.seg button.on {
  background: var(--panel);
  color: var(--text);
  box-shadow: var(--shadow-xs);
}
.seg.two button.on {
  color: var(--brand-strong);
}

.grid-glyph {
  width: 11px;
  height: 11px;
  border: 1px solid currentColor;
  opacity: 0.65;
  flex: 0 0 auto;
}
.grid-glyph.dots {
  background-image: radial-gradient(currentColor 1px, transparent 1.2px);
  background-size: 4px 4px;
  background-position: 1px 1px;
}
.grid-glyph.lines {
  background-image: linear-gradient(currentColor 1px, transparent 1px), linear-gradient(90deg, currentColor 1px, transparent 1px);
  background-size: 4px 4px;
}
.grid-glyph.off {
  border-style: dashed;
  opacity: 0.4;
}

.accents {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}
.accent {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 7px 0 5px;
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  background: var(--panel);
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 600;
  cursor: pointer;
}
.accent i {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--swatch);
  border: 1px solid rgba(28, 26, 22, 0.12);
}
.accent.on {
  border-color: var(--brand);
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.note {
  margin: 12px 0 0;
  padding-top: 9px;
  border-top: 1px solid var(--border);
  font-size: 10.5px;
  line-height: 1.55;
  color: var(--text-3);
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

@media (max-width: 980px) {
  .chip-label {
    display: none;
  }
}
</style>
