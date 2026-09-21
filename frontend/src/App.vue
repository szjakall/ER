<template>
  <div class="app">
    <Toolbar />
    <div class="body">
      <IssuePanel />
      <ErCanvasView />
      <Inspector />
    </div>
    <footer>
      <span class="sw error"></span> 错误 {{ store.paintStats.error }}
      <span class="sw warn"></span> 建议 {{ store.paintStats.warn }}
      <span class="sw ok"></span> 通过 {{ store.paintStats.ok }}
      <span class="sw pending"></span> 未检查 {{ store.paintStats.pending }}
      <span class="hint">{{ hint }}</span>
    </footer>
    <div class="toasts">
      <div v-for="n in store.notices" :key="n.id" class="toast" :class="n.level">{{ n.text }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useErStore } from "./model/store";
import Toolbar from "./ui/Toolbar.vue";
import Inspector from "./ui/Inspector.vue";
import IssuePanel from "./ui/IssuePanel.vue";
import ErCanvasView from "./ui/ErCanvasView.vue";

const store = useErStore();
const hint = computed(() => {
  const cont = store.continuous ? "（连续创建中 · Esc 退出）" : "";
  if (store.tool === "entity") return `点击画布空白处放下实体${cont}`;
  if (store.tool === "attribute") return `点击画布空白处放下属性椭圆${cont}`;
  if (store.tool === "relationship") return `点击画布空白处放下联系菱形${cont}`;
  if (store.tool === "connect") return store.pendingFromId ? "再点目标元素完成连线" : `依次点两个元素连线${cont}`;
  return "单击工具建一个、双击连续建；属性椭圆可拖动；连线压到元素/属性会标红 R20";
});
</script>

<style>
html, body, #app, .app { height: 100%; margin: 0; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f1f5f9; color: #0f172a; }
.app { display: flex; flex-direction: column; }
.body { flex: 1; display: flex; min-height: 0; }
footer { display: flex; align-items: center; gap: 10px; padding: 6px 12px; background: #fff; border-top: 1px solid #e2e8f0; font-size: 12px; }
.hint { margin-left: auto; color: #64748b; }
.sw { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.sw.error { background: #e11d48; }
.sw.warn { background: #f97316; }
.sw.ok { background: #16a34a; }
.sw.pending { background: #94a3b8; }
.toasts { position: fixed; right: 16px; bottom: 40px; display: flex; flex-direction: column; gap: 8px; z-index: 20; }
.toast { background: #0f172a; color: #fff; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.toast.error { background: #be123c; }
</style>
