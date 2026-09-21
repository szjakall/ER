<template>
  <aside class="issues">
    <h3>问题</h3>
    <p class="muted" v-if="!store.allIssues.length">暂无已返回的违规/建议。灰色表示尚未检查或已超时。</p>
    <button
      v-for="(row, i) in store.allIssues"
      :key="i"
      class="item"
      :class="row.issue.level"
      @click="store.select(row.kind, row.id)"
    >
      <strong>{{ row.issue.rule_id }}</strong>
      <span>{{ row.issue.message }}</span>
      <em>{{ row.id }}</em>
    </button>
  </aside>
</template>

<script setup lang="ts">
import { useErStore } from "../model/store";
const store = useErStore();
</script>

<style scoped>
.issues { width: 280px; background: #fff; border-right: 1px solid #e2e8f0; padding: 12px; overflow: auto; }
h3 { margin: 0 0 8px; font-size: 14px; }
.muted { font-size: 12px; color: #94a3b8; }
.item {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  width: 100%; text-align: left; margin-bottom: 8px; padding: 8px;
  border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; cursor: pointer;
}
.item.error { border-color: #fecdd3; background: #fff1f2; }
.item.warn { border-color: #fed7aa; background: #fff7ed; }
strong { font-size: 12px; }
span { font-size: 12px; color: #334155; }
em { font-size: 11px; color: #94a3b8; font-style: normal; }
</style>
