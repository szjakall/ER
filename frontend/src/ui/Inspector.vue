<template>
  <aside class="panel">
    <SplitHandle
      orientation="vertical"
      :value="width"
      :min="264"
      :max="maxWidth"
      label="调整属性检查器宽度"
      @update="$emit('resize', $event)"
      @commit="$emit('commit')"
      @reset="resetWidth"
    />

    <!-- 空态 -->
    <div v-if="!el && !conn" class="empty">
      <div class="empty-mark" aria-hidden="true">
        <svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.4">
          <rect x="5" y="15" width="12" height="10" />
          <path d="M17 20h6" />
          <path d="M23 20l7-5v10l-7 5z" transform="translate(0,-5)" />
          <ellipse cx="33" cy="12" rx="5" ry="3.2" />
          <path d="M28 12h-5" />
        </svg>
      </div>
      <h3>属性检查器</h3>
      <p>选中画布上的元素或连线，在这里编辑名称、属性和基数。拖动位置不会触发检查。</p>
      <div class="empty-hint">
        <span><kbd>Delete</kbd> 删除</span>
        <span><kbd>Esc</kbd> 取消选择</span>
      </div>
    </div>

    <!-- 元素 -->
    <template v-if="el">
      <header class="panel-head">
        <div class="head-glyph" :class="el.shape" aria-hidden="true">
          <svg v-if="el.shape === 'rectangle'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="4" y="7" width="16" height="10" /></svg>
          <svg v-else-if="el.shape === 'ellipse'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><ellipse cx="12" cy="12" rx="8" ry="5.5" /></svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 5l7 7-7 7-7-7z" /></svg>
        </div>
        <div class="head-text">
          <h2 :title="el.label">{{ el.label || shapeName(el.shape) }}</h2>
          <p class="id">{{ el.id }}</p>
        </div>
        <span class="head-pill" :class="el.shape">{{ shapeName(el.shape) }}</span>
      </header>

      <div class="scroll">
        <!-- 基本信息 -->
        <section class="block">
          <div class="block-title">基本信息</div>
          <label class="field">
            <span>名称</span>
            <input v-model="label" class="text" placeholder="输入名称" @change="saveEl" />
          </label>
        </section>

        <!-- 属性管理 -->
        <template v-if="el.shape === 'rectangle' || el.shape === 'diamond'">
          <section class="block">
            <div class="block-title">
              属性
              <span class="count">{{ rows.length }}</span>
            </div>

            <label class="field">
              <span>批量添加</span>
              <textarea
                v-model="bulk"
                rows="2"
                placeholder="一行一个；* 主键，# 部分键&#10;学号 / 姓名 / *学号"
                @keydown.enter.exact.prevent="addBulk"
              ></textarea>
            </label>
            <button class="btn soft block-add" :disabled="!bulk.trim()" @click="addBulk">全部添加</button>

            <div class="attr-list">
              <div
                v-for="(row, i) in rows"
                :key="i"
                class="attr-row"
                :class="{ active: selectedAttr && selectedAttr.index === i }"
              >
                <button
                  class="kind"
                  :class="row.kind"
                  :title="kindTitle(row.kind)"
                  @click="cycleKind(i)"
                >{{ kindGlyph(row.kind) }}</button>
                <input v-model="row.name" class="attr-name" placeholder="属性名" @change="saveEl" />
                <select v-model="row.shape" class="attr-shape" title="属性画法" @change="saveEl">
                  <option value="normal">椭圆</option>
                  <option value="multi">多值</option>
                  <option value="derived">派生</option>
                </select>
                <button class="del" title="删除该属性" @click="removeRow(i)">✕</button>
              </div>
            </div>
            <button class="btn ghost block-add" @click="addRow">+ 添加属性</button>

            <p class="hint">
              <span><i class="k pk">PK</i>主键（实线下划线）</span>
              <span><i class="k partial">#</i>部分键（虚线）</span>
            </p>
          </section>
        </template>

        <!-- 高级 -->
        <section v-if="el.shape === 'rectangle' || el.shape === 'diamond'" class="block">
          <div class="block-title">高级</div>
          <label v-if="el.shape === 'rectangle'" class="check">
            <input type="checkbox" v-model="isWeak" @change="saveEl" />
            <span class="check-box"></span>
            <span>弱实体（双线矩形）</span>
          </label>
          <p v-if="el.shape === 'rectangle'" class="desc">
            弱实体需要至少一个部分键（# 前缀）。
          </p>
          <template v-if="el.shape === 'diamond'">
            <label class="check">
              <input type="checkbox" v-model="isIdentifying" @change="saveEl" />
              <span class="check-box"></span>
              <span>标识联系（双线菱形）</span>
            </label>
            <p class="desc">连接弱实体与其所有者实体时使用。</p>
          </template>
        </section>

        <!-- 检查结果 -->
        <section class="block">
          <div class="block-title">
            检查结果
            <span v-if="issues.length" class="count error">{{ issues.length }}</span>
          </div>
          <div v-if="!store.painted[el.id]" class="result-note">尚未检查，编辑后会重新校验。</div>
          <div v-else-if="!issues.length" class="result-note ok">
            <span class="ok-mark" aria-hidden="true">✓</span> 本元素未发现问题
          </div>
          <ul v-else class="result-list">
            <li v-for="(row, i) in issues" :key="i" :class="row.issue.level">
              <span class="rule">{{ row.issue.rule_id }}</span>
              <span class="msg">{{ row.issue.message }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>

    <!-- 连线 -->
    <template v-if="conn">
      <header class="panel-head">
        <div class="head-glyph connection" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 17L18 7" /><circle cx="6" cy="17" r="2" /><circle cx="18" cy="7" r="2" /></svg>
        </div>
        <div class="head-text">
          <h2>{{ isFree ? '自由端连线' : '连线' }}</h2>
          <p class="id">{{ conn.id }}</p>
        </div>
        <span class="head-pill" :class="{ free: isFree }">{{ isFree ? '自由端' : conn.type === 'diamond_line' ? '联系' : '普通' }}</span>
      </header>

      <div class="scroll">
        <section v-if="isFree" class="block">
          <div class="block-title">自由端点</div>
          <div class="free-coord">
            <span>x <b>{{ Math.round(conn.free_end?.x ?? 0) }}</b></span>
            <span>y <b>{{ Math.round(conn.free_end?.y ?? 0) }}</b></span>
          </div>
          <p class="desc">
            选中连线后会出现临时控制点；拖动它即可独立移动自由端，不会吸附到其它图形。起点仍跟随
            「{{ nameOf(conn.from) }}」。
          </p>
        </section>

        <section v-else class="block">
          <div class="block-title">基数</div>
          <template v-if="isBranch">
            <div class="seg">
              <button v-for="s in cardSymbols" :key="s" :class="{ on: card === s }" @click="setCard(s)">{{ s }}</button>
              <button class="clear" :class="{ on: card === null }" @click="setCard(null)">清除</button>
            </div>
            <p class="desc">这条线只写一个符号；联系两端各一个符号，合起来才是 1:N / M:N。</p>
          </template>
          <p v-else class="desc">属性 / 普通连线不写基数。</p>
        </section>

        <section class="block">
          <div class="block-title">连接</div>
          <div class="link-info">
            <span class="end">{{ nameOf(conn.from) }}</span>
            <span class="arrow" aria-hidden="true">→</span>
            <span class="end" :class="{ free: isFree }">{{ conn.to ? nameOf(conn.to) : '自由端' }}</span>
          </div>
          <button v-if="diamondId" class="btn ghost block-add" @click="openDiamond">
            联系名写在菱形「{{ nameOf(diamondId) }}」里 →
          </button>
        </section>

        <section class="block">
          <div class="block-title">
            检查结果
            <span v-if="issues.length" class="count error">{{ issues.length }}</span>
          </div>
          <div v-if="!isFree && !store.painted[conn.id]" class="result-note">尚未检查。</div>
          <div v-else-if="!issues.length" class="result-note ok">
            <span class="ok-mark" aria-hidden="true">✓</span> 这条连线未发现问题
          </div>
          <ul v-else class="result-list">
            <li v-for="(row, i) in issues" :key="i" :class="row.issue.level">
              <span class="rule">{{ row.issue.rule_id }}</span>
              <span class="msg">{{ row.issue.message }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useErStore } from "../model/store";
import type { AttrShape, Cardinality, CardSymbol, Shape } from "../protocol/types";
import { isFreeConnection } from "../protocol/types";
import SplitHandle from "./SplitHandle.vue";

const props = defineProps<{ width: number; maxWidth: number }>();
const emit = defineEmits<{
  (e: "resize", value: number): void;
  (e: "commit"): void;
}>();

type Row = { kind: "normal" | "pk" | "partial"; name: string; shape: AttrShape };

const store = useErStore();
const el = computed(() => store.selectedElement);
const conn = computed(() => store.selectedConnection);
const selectedAttr = computed(() => store.selectedAttr);
const label = ref("");
const isWeak = ref(false);
const isIdentifying = ref(false);
const rows = ref<Row[]>([]);
const bulk = ref("");
const card = ref<Cardinality>(null);
const cardSymbols: CardSymbol[] = ["1", "N", "M", "P"];
const isBranch = computed(() => (conn.value ? store.isRelationBranch(conn.value.id) : false));
const isFree = computed(() => isFreeConnection(conn.value));

const shapeNames: Record<Shape, string> = { rectangle: "实体", ellipse: "属性", diamond: "联系" };
function shapeName(s: Shape) {
  return shapeNames[s] ?? "元素";
}
function nameOf(id: string) {
  const e = store.findElement(id);
  return e?.label || e?.id || id;
}
function resetWidth() {
  emit("resize", 320);
  emit("commit");
}

const issues = computed(() => {
  const id = store.selectedId;
  if (!id) return [];
  return store.allIssues.filter((r) => r.id === id);
});

const diamondId = computed(() => {
  const c = conn.value;
  if (!c) return "";
  const a = store.findElement(c.from);
  const b = store.findElement(c.to);
  if (a?.shape === "diamond") return a.id;
  if (b?.shape === "diamond") return b.id;
  return "";
});

function parseAttrRow(a: unknown, index: number, element = el.value): Row {
  const s = String(a ?? "").trim();
  const shape = (element?.attr_style?.[String(index)] ?? "normal") as AttrShape;
  if (s.startsWith("*")) return { kind: "pk", name: s.replace(/^\*+/, ""), shape };
  if (s.startsWith("#")) return { kind: "partial", name: s.replace(/^#+/, ""), shape };
  return { kind: "normal", name: s, shape };
}

watch(
  el,
  (e) => {
    if (!e) return;
    label.value = e.label;
    isWeak.value = !!e.is_weak;
    isIdentifying.value = !!e.is_identifying;
    rows.value = (e.attributes ?? []).map((a, i) => parseAttrRow(a, i, e));
  },
  { immediate: true },
);

watch(
  conn,
  (c) => {
    if (!c) return;
    card.value = c.cardinality;
  },
  { immediate: true },
);

watch(
  () => [store.selectedAttr, store.canvasTick] as const,
  () => {
    const current = el.value;
    if (!current) return;
    const next = (current.attributes ?? []).map((a, i) => parseAttrRow(a, i, current));
    // 仅在属性名 / 类型确实变化时覆盖输入框，避免打字被回写打断
    if (JSON.stringify(next) !== JSON.stringify(rows.value)) rows.value = next;
    label.value = current.label;
    isWeak.value = !!current.is_weak;
    isIdentifying.value = !!current.is_identifying;
  },
);

/** 属性数组与 attr_style 必须用同一套过滤后的下标，否则空行会把样式错位 */
function buildPayload() {
  const attrs: string[] = [];
  const style: Record<string, AttrShape> = {};
  for (const row of rows.value) {
    const name = row.name.trim().replace(/^\*+|^#+/, "").trim();
    if (!name) continue;
    const index = attrs.length;
    attrs.push(row.kind === "pk" ? `*${name}` : row.kind === "partial" ? `#${name}` : name);
    if (row.shape !== "normal") style[String(index)] = row.shape;
  }
  return { attrs, style };
}

function saveEl() {
  const e = el.value;
  if (!e) return;
  const { attrs, style } = buildPayload();
  store.updateElement(e.id, {
    label: label.value,
    attributes: attrs,
    attr_style: style,
    is_weak: isWeak.value,
    is_identifying: isIdentifying.value,
  });
}

/** 一次把输入框里的多个属性名全部加进去（换行 / 逗号 / 空格分隔） */
function addBulk() {
  const names = bulk.value.split(/[\s,，、;；]+/).filter(Boolean);
  if (!names.length) return;
  rows.value.push(...names.map((name) => parseAttrRow(name, 0, undefined)));
  bulk.value = "";
  saveEl();
}

function addRow() {
  rows.value.push({ kind: "normal", name: "", shape: "normal" });
}
function removeRow(index: number) {
  rows.value.splice(index, 1);
  if (store.selectedAttr && store.selectedAttr.index === index) store.selectedAttr = null;
  saveEl();
}
function cycleKind(index: number) {
  const row = rows.value[index];
  row.kind = row.kind === "normal" ? "pk" : row.kind === "pk" ? "partial" : "normal";
  saveEl();
}
function kindGlyph(kind: Row["kind"]) {
  if (kind === "pk") return "PK";
  if (kind === "partial") return "#";
  return "·";
}
function kindTitle(kind: Row["kind"]) {
  if (kind === "pk") return "主键（实线下划线）";
  if (kind === "partial") return "部分键（虚线下划线）";
  return "普通属性";
}

function setCard(s: Cardinality) {
  const c = conn.value;
  if (!c) return;
  card.value = s;
  store.updateConnection(c.id, { cardinality: s });
}
function openDiamond() {
  if (diamondId.value) store.select("element", diamondId.value);
}
</script>

<style scoped>
.panel {
  position: relative;
  width: var(--inspector-w);
  flex: 0 0 var(--inspector-w);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--panel);
  border-left: 1px solid var(--border);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--border);
  flex: 0 0 auto;
}
.head-glyph {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: var(--r-md);
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text-2);
}
.head-glyph svg {
  width: 20px;
  height: 20px;
}
.head-glyph.rectangle {
  color: var(--brand);
}
.head-text {
  min-width: 0;
  flex: 1;
}
.head-text h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.id {
  margin: 3px 0 0;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.head-pill {
  flex: 0 0 auto;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text-2);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  padding: 2px 8px;
}
.head-pill.free {
  color: var(--warn);
  background: var(--warn-soft);
  border-color: #f2d3ae;
}

.scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 14px 24px;
}

.block {
  padding: 2px 0 14px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 14px;
}
.block:last-child {
  border-bottom: 0;
  margin-bottom: 0;
}
.block-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-2);
  letter-spacing: 0.02em;
}
.count {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--text-2);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  padding: 0 6px;
}
.count.error {
  color: var(--error);
  background: var(--error-soft);
  border-color: #f2c3cb;
}

.field {
  display: block;
  margin-bottom: 8px;
}
.field > span {
  display: block;
  margin-bottom: 5px;
  font-size: 12px;
  font-weight: 550;
  color: var(--text-2);
}

.text, textarea, select, .attr-name {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 9px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font: inherit;
  font-size: 13px;
  color: var(--text);
  background: var(--panel);
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}
.text:focus, textarea:focus, select:focus, .attr-name:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.13);
}
textarea {
  line-height: 1.5;
  resize: vertical;
  min-height: 52px;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 600;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.btn:hover {
  border-color: var(--border-strong);
  color: var(--text);
}
.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.btn.soft {
  background: var(--brand-soft);
  border-color: transparent;
  color: var(--brand-strong);
}
.btn.soft:hover {
  background: #e4e7ff;
  color: var(--brand-strong);
}
.btn.ghost {
  width: 100%;
  border-style: dashed;
  background: transparent;
}
.btn.ghost:hover {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}
.block-add {
  margin-top: 8px;
}

.attr-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}
.attr-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px;
  margin: -3px;
  border-radius: var(--radius-sm);
}
.attr-row.active {
  background: var(--brand-soft);
  box-shadow: 0 0 0 1px rgba(79, 70, 229, 0.22);
}
.kind {
  flex: 0 0 auto;
  width: 28px;
  height: 30px;
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: var(--radius-sm);
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 700;
  color: var(--text-3);
  cursor: pointer;
}
.kind.pk {
  color: var(--brand);
  border-color: #cfd3ff;
  background: var(--brand-soft);
}
.kind.partial {
  color: var(--warn);
  border-color: #f2d3ae;
  background: var(--warn-soft);
}
.attr-name {
  flex: 1;
  min-width: 0;
  padding: 5px 8px;
}
.attr-shape {
  flex: 0 0 auto;
  width: 66px;
  padding: 5px 4px;
  font-size: 11.5px;
}
.del {
  flex: 0 0 auto;
  width: 26px;
  height: 28px;
  border: 0;
  background: transparent;
  color: var(--text-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
}
.del:hover {
  background: var(--error-soft);
  color: var(--error);
}

.hint {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 10px 0 0;
  font-size: 11px;
  color: var(--text-3);
}
.hint .k {
  font-style: normal;
  font-family: var(--mono);
  font-weight: 700;
  font-size: 10px;
  margin-right: 3px;
}
.k.pk {
  color: var(--brand);
}
.k.partial {
  color: var(--warn);
}

.check {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
  cursor: pointer;
  margin-top: 2px;
}
.check input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}
.check-box {
  width: 16px;
  height: 16px;
  border: 1.5px solid var(--border-strong);
  border-radius: 4px;
  background: var(--panel);
  flex: 0 0 auto;
  position: relative;
  transition: all 0.12s ease;
}
.check input:checked + .check-box {
  background: var(--brand);
  border-color: var(--brand);
}
.check input:checked + .check-box::after {
  content: "";
  position: absolute;
  left: 4.5px;
  top: 1.5px;
  width: 4px;
  height: 8px;
  border: solid #fff;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

.desc {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}

.seg {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.seg button {
  min-width: 40px;
  height: 32px;
  border: 1px solid var(--border-strong);
  background: var(--panel);
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 700;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.12s ease;
}
.seg button:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.seg button.on {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.seg button.clear {
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
}

.link-info {
  display: flex;
  align-items: center;
  gap: 8px;
}
.end {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 6px 9px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  font-weight: 550;
}
.arrow {
  color: var(--text-3);
  flex: 0 0 auto;
}
.end.free {
  color: var(--warn);
  border-style: dashed;
  background: var(--warn-soft);
}

.free-coord {
  display: flex;
  gap: 8px;
  margin-bottom: 2px;
}
.free-coord span {
  flex: 1;
  display: inline-flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 9px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-3);
}
.free-coord b {
  font-weight: 700;
  font-size: 12.5px;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.result-note {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}
.result-note.ok {
  color: var(--ok);
}
.ok-mark {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--ok-soft);
  border: 1px solid #bcd9c6;
  font-size: 10px;
  flex: 0 0 auto;
}
.result-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.result-list li {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-2);
  font-size: 12px;
  line-height: 1.55;
}
.result-list li.error {
  border-color: #f2c3cb;
  background: var(--error-soft);
}
.result-list li.warn {
  border-color: #f2d3ae;
  background: var(--warn-soft);
}
.result-list .rule {
  flex: 0 0 auto;
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 700;
  color: var(--error);
  padding-top: 1px;
}
.result-list li.warn .rule {
  color: var(--warn);
}
.result-list .msg {
  color: var(--text);
  min-width: 0;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 56px 24px;
}
.empty-mark {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  background: var(--panel-2);
  border: 1px solid var(--border);
}
.empty-mark svg {
  width: 36px;
  height: 36px;
}
.empty h3 {
  margin: 16px 0 6px;
  font-size: 14px;
  font-weight: 700;
}
.empty p {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-3);
  line-height: 1.75;
  max-width: 240px;
}
.empty-hint {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  font-size: 11px;
  color: var(--text-3);
}
kbd {
  font-family: var(--mono);
  font-size: 10px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 5px;
  padding: 1px 5px;
  color: var(--text-2);
  margin-right: 3px;
}
</style>
