<template>
  <aside class="panel">
    <h3>属性</h3>
    <p v-if="!el && !conn" class="muted">选中元素或连线后在此编辑。拖动位置不会发检查。</p>

    <!-- 元素 -->
    <template v-if="el">
      <label>名称</label>
      <input v-model="label" @change="saveEl" />

      <!-- 弱实体开关 -->
      <template v-if="el.shape === 'rectangle'">
        <label class="check">
          <input type="checkbox" v-model="isWeak" @change="saveEl" />
          弱实体（画双线矩形）
        </label>
      </template>

      <!-- 属性列表（实体 & 联系都有） -->
      <template v-if="el.shape === 'rectangle' || el.shape === 'diamond'">
        <label>批量添加属性（一行一个，也可用逗号/空格分隔；* 开头 = 主键，# 开头 = 部分键）</label>
        <textarea
          v-model="bulk"
          rows="3"
          placeholder="学号&#10;姓名&#10;性别"
          @keydown.enter.exact.prevent="addBulk"
        ></textarea>
        <button :disabled="!bulk.trim()" @click="addBulk">一次全部添加</button>

        <label>属性（画成旁边的椭圆，用实线连到{{ el.shape === 'rectangle' ? '实体' : '联系' }}）</label>
        <div v-for="(row, i) in rows" :key="i" class="row">
          <select v-model="row.kind" @change="saveEl">
            <option value="normal">普通</option>
            <option value="pk">主键</option>
            <option value="partial">部分键</option>
          </select>
          <input v-model="row.name" placeholder="属性名" @change="saveEl" />
          <button class="ghost" @click="rows.splice(i, 1); saveEl()">删</button>
        </div>
        <button @click="rows.push({ kind: 'normal', name: '' })">添加属性</button>
      </template>

      <p class="id">{{ el.id }} · {{ el.shape }}</p>
    </template>

    <!-- 连线 -->
    <template v-if="conn">
      <template v-if="isBranch">
        <label>基数（这条线上写一个符号；三元联系可用 P）</label>
        <div class="cards">
          <button v-for="s in cardSymbols" :key="s" :class="{ on: card === s }" @click="setCard(s)">{{ s }}</button>
          <button :class="{ on: card === null }" @click="setCard(null)">清除</button>
        </div>
      </template>
      <p v-else class="muted">这是属性 / 普通连线，不写基数。</p>
      <p class="id">{{ conn.id }} · {{ conn.from }} → {{ conn.to }}</p>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useErStore } from "../model/store";
import type { Cardinality, CardSymbol } from "../protocol/types";

type Row = { kind: "normal" | "pk" | "partial"; name: string };

const store = useErStore();
const el = computed(() => store.selectedElement);
const conn = computed(() => store.selectedConnection);
const label = ref("");
const isWeak = ref(false);
const rows = ref<Row[]>([]);
const bulk = ref("");
const card = ref<Cardinality>(null);
const cardSymbols: CardSymbol[] = ["1", "N", "M", "P"];
const isBranch = computed(() => (conn.value ? store.isRelationBranch(conn.value.id) : false));

function parseAttrRow(a: unknown): Row {
  const s = String(a ?? "").trim();
  if (s.startsWith("*")) return { kind: "pk", name: s.replace(/^\*+/, "") };
  if (s.startsWith("#")) return { kind: "partial", name: s.replace(/^#+/, "") };
  return { kind: "normal", name: s };
}

watch(
  el,
  (e) => {
    if (!e) return;
    label.value = e.label;
    isWeak.value = !!e.is_weak;
    rows.value = (e.attributes ?? []).map(parseAttrRow);
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

function saveEl() {
  const e = el.value;
  if (!e) return;
  const attributes = rows.value
    .map((r) => {
      const n = r.name.trim().replace(/^\*+|^#+/, "");
      if (!n) return "";
      return r.kind === "pk" ? `*${n}` : r.kind === "partial" ? `#${n}` : n;
    })
    .filter(Boolean);
  store.updateElement(e.id, { label: label.value, attributes, is_weak: isWeak.value });
}

/** 一次把输入框里的多个属性名全部加进去（换行 / 逗号 / 空格分隔） */
function addBulk() {
  const names = bulk.value.split(/[\s,，、;；]+/).filter(Boolean);
  if (!names.length) return;
  rows.value.push(...names.map(parseAttrRow));
  bulk.value = "";
  saveEl();
}

function setCard(s: Cardinality) {
  const c = conn.value;
  if (!c) return;
  card.value = s;
  store.updateConnection(c.id, { cardinality: s });
}
</script>

<style scoped>
.panel { width: 300px; background: #fff; border-left: 1px solid #e2e8f0; padding: 12px; overflow: auto; }
h3 { margin: 0 0 8px; font-size: 14px; }
label { display: block; margin: 10px 0 4px; font-size: 12px; color: #64748b; }
label.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #334155; }
label.check input { width: auto; }
input, select { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; }
textarea { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; font: inherit; font-size: 13px; line-height: 1.5; resize: vertical; }
.row { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.row select { width: 76px; flex: 0 0 auto; }
.row input { flex: 1; min-width: 0; }
.muted, .id { font-size: 12px; color: #94a3b8; line-height: 1.5; }
.cards { display: flex; gap: 6px; margin-top: 4px; flex-wrap: wrap; }
.cards button { margin-top: 0; min-width: 40px; background: #e2e8f0; }
.cards button.on { background: #2563eb; color: #fff; }
button { margin-top: 8px; border: 0; background: #e2e8f0; padding: 6px 10px; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.ghost { margin-top: 0; background: transparent; color: #e11d48; }
</style>
