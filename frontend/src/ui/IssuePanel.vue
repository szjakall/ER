<template>
  <aside class="dock" :class="{ collapsed }">
    <SplitHandle
      orientation="horizontal"
      :value="height"
      :min="40"
      :max="maxHeight"
      label="调整问题诊断面板高度"
      @update="$emit('resize', $event)"
      @commit="$emit('commit')"
      @reset="resetHeight"
    />

    <header class="dock-head">
      <div class="dh-title">
        <span class="dh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3l9 16H3z" /><path d="M12 10v4" /><path d="M12 17h.01" />
          </svg>
        </span>
        <h3>问题诊断</h3>
        <span v-if="total" class="badge">{{ total }}</span>
      </div>

      <div v-if="total" class="dh-counts">
        <span class="cnt error"><i class="dot"></i>错误 <b>{{ errors.length }}</b></span>
        <span class="cnt warn"><i class="dot"></i>建议 <b>{{ warns.length }}</b></span>
      </div>

      <div class="filters" role="tablist" aria-label="按级别筛选">
        <button
          v-for="f in filters"
          :key="f.id"
          role="tab"
          :aria-selected="filter === f.id"
          :class="{ on: filter === f.id }"
          @click="filter = f.id"
        >{{ f.label }}</button>
      </div>

      <div class="spacer"></div>

      <button class="collapse" :title="collapsed ? '展开' : '折叠'" :aria-expanded="!collapsed" @click="toggle">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path v-if="collapsed" d="M6 15l6-6 6 6" />
          <path v-else d="M6 9l6 6 6-6" />
        </svg>
      </button>
    </header>

    <div v-if="!collapsed" class="dock-body" :class="{ 'is-empty': !total }">
      <div v-if="!total" class="empty">
        <span class="empty-mark" aria-hidden="true">✓</span>
        <div class="empty-text">
          <strong>没有发现问题</strong>
          <span>红 = 刚性错误，橙 = 建议。画图时会自动校验。</span>
        </div>
      </div>

      <template v-else>
        <template v-if="showErrors">
          <div class="group-title">错误 <em>{{ errors.length }}</em></div>
          <button
            v-for="(row, i) in errors"
            :key="'e' + i"
            class="issue error"
            :class="{ active: store.selectedId === row.id }"
            @click="store.focus(row.kind, row.id)"
          >
            <span class="mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                <circle cx="12" cy="12" r="8.5" /><path d="M15 9l-6 6M9 9l6 6" />
              </svg>
            </span>
            <span class="content">
              <span class="line">
                <span class="rule">{{ row.issue.rule_id }}</span>
                <span class="msg">{{ row.issue.message }}</span>
              </span>
              <span class="meta">{{ kindLabel(row.kind) }} · {{ refLabel(row.id) }}</span>
            </span>
            <svg class="go" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M9 6l6 6-6 6" />
            </svg>
          </button>
        </template>

        <template v-if="showWarns">
          <div class="group-title">建议 <em>{{ warns.length }}</em></div>
          <button
            v-for="(row, i) in warns"
            :key="'w' + i"
            class="issue warn"
            :class="{ active: store.selectedId === row.id }"
            @click="store.focus(row.kind, row.id)"
          >
            <span class="mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 4l8.5 15H3.5z" /><path d="M12 10v3.5" /><path d="M12 16.5h.01" />
              </svg>
            </span>
            <span class="content">
              <span class="line">
                <span class="rule">{{ row.issue.rule_id }}</span>
                <span class="msg">{{ row.issue.message }}</span>
              </span>
              <span class="meta">{{ kindLabel(row.kind) }} · {{ refLabel(row.id) }}</span>
            </span>
            <svg class="go" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M9 6l6 6-6 6" />
            </svg>
          </button>
        </template>

        <div v-if="!showErrors && !showWarns" class="empty">
          <span class="empty-mark" aria-hidden="true">✓</span>
          <div class="empty-text">
            <strong>该筛选下没有内容</strong>
            <span>切到「全部」查看其它级别的提示。</span>
          </div>
        </div>
      </template>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useErStore } from "../model/store";
import SplitHandle from "./SplitHandle.vue";

const props = defineProps<{ height: number; maxHeight: number }>();
const emit = defineEmits<{
  (e: "resize", value: number): void;
  (e: "commit"): void;
}>();

const store = useErStore();
const filter = ref<"all" | "error" | "warn">("all");
const filters = [
  { id: "all" as const, label: "全部" },
  { id: "error" as const, label: "错误" },
  { id: "warn" as const, label: "建议" },
];
const lastHeight = ref(240);
const collapsed = computed(() => props.height <= 44);

const errors = computed(() => store.allIssues.filter((r) => r.issue.level === "error"));
const warns = computed(() => store.allIssues.filter((r) => r.issue.level === "warn"));
const total = computed(() => errors.value.length + warns.value.length);
const showErrors = computed(() => filter.value !== "warn" && errors.value.length > 0);
const showWarns = computed(() => filter.value !== "error" && warns.value.length > 0);

watch(
  () => props.height,
  (h) => {
    if (h > 44) lastHeight.value = h;
  },
  { immediate: true },
);

function toggle() {
  if (collapsed.value) emit("resize", Math.max(160, lastHeight.value));
  else {
    lastHeight.value = Math.max(160, props.height);
    emit("resize", 40);
  }
  emit("commit");
}

function resetHeight() {
  emit("resize", 240);
  emit("commit");
}

function kindLabel(kind: "element" | "connection") {
  return kind === "connection" ? "连线" : "元素";
}
function refLabel(id: string) {
  const el = store.findElement(id);
  if (el) return el.label || el.id;
  const c = store.findConnection(id);
  if (c) {
    const a = store.findElement(c.from);
    if (c.mode === "free") return `${a?.label || c.from} → 自由端`;
    const b = store.findElement(c.to);
    return `${a?.label || c.from} → ${b?.label || c.to}`;
  }
  return id;
}
</script>

<style scoped>
.dock {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--panel);
  border-top: 1px solid var(--border);
}

.dock-head {
  display: flex;
  align-items: center;
  gap: 12px;
  height: var(--dock-head-h);
  padding: 0 12px 0 14px;
  flex: 0 0 auto;
}
.dh-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}
.dh-icon {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text-2);
}
.dh-icon svg {
  width: 14px;
  height: 14px;
}
.dh-title h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: -0.005em;
}
.badge {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 1px 7px;
  border-radius: var(--r-pill);
  font-variant-numeric: tabular-nums;
}

.dh-counts {
  display: flex;
  gap: 12px;
  flex: 0 0 auto;
}
.cnt {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-3);
}
.cnt .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.cnt.error .dot {
  background: var(--error);
}
.cnt.warn .dot {
  background: var(--warn);
}
.cnt b {
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.filters {
  display: flex;
  gap: 2px;
  padding: 2px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  flex: 0 0 auto;
}
.filters button {
  border: 0;
  background: transparent;
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.filters button:hover {
  color: var(--text);
}
.filters button.on {
  background: var(--panel);
  color: var(--text);
  box-shadow: var(--shadow-xs);
}

.spacer {
  flex: 1;
}

.collapse {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  border-radius: var(--r-sm);
  cursor: pointer;
  display: grid;
  place-items: center;
}
.collapse:hover {
  background: var(--surface-sunken);
  color: var(--text);
}
.collapse svg {
  width: 16px;
  height: 16px;
}
.collapse:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
}

.dock-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 2px 14px 14px;
  border-top: 1px solid var(--border);
}
.dock-body.is-empty {
  display: grid;
  place-items: center;
  padding-bottom: 20px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 10px 2px 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-3);
  letter-spacing: 0.03em;
}
.group-title em {
  font-style: normal;
  font-size: 10px;
  color: var(--text-2);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  padding: 0 6px;
  font-variant-numeric: tabular-nums;
}

.issue {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  margin-bottom: 6px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.issue:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}
.issue.error:hover {
  border-color: #e9a7b3;
}
.issue.warn:hover {
  border-color: #ecc392;
}
.issue.active {
  border-color: var(--brand);
  box-shadow: var(--shadow-sel);
}
.issue:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
}

.mark {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
}
.issue.error .mark {
  color: var(--error);
  background: var(--error-soft);
}
.issue.warn .mark {
  color: var(--warn);
  background: var(--warn-soft);
}
.mark svg {
  width: 15px;
  height: 15px;
}

.content {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.rule {
  flex: 0 0 auto;
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 700;
  color: var(--error);
  letter-spacing: -0.01em;
}
.issue.warn .rule {
  color: var(--warn);
}
.msg {
  min-width: 0;
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta {
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.go {
  flex: 0 0 auto;
  width: 15px;
  height: 15px;
  color: var(--text-faint);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.issue:hover .go {
  opacity: 1;
  transform: translateX(1px);
}

.empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 2px;
}
.empty-mark {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
  color: var(--ok);
  background: var(--ok-soft);
  border: 1px solid #bcd9c6;
  flex: 0 0 auto;
}
.empty-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.empty-text strong {
  font-size: 12.5px;
  font-weight: 650;
  color: var(--text);
}
.empty-text span {
  font-size: 11.5px;
  color: var(--text-3);
}
</style>
