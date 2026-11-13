<template>
  <nav class="rail" aria-label="绘图工具">
    <div class="rail-tools">
      <button
        class="tool"
        :class="{ active: store.tool === 'select' }"
        @click="store.setTool('select')"
        title="选择 / 移动（Esc 取消）"
      >
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 3l7 16 2.2-6.2L20 11 5 3z" /></svg>
        <span>选择</span>
      </button>

      <button
        class="tool"
        :class="{ active: store.tool === 'entity' }"
        @click="arm('entity')"
        @dblclick="arm('entity', true)"
        title="实体（矩形）"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="4" y="5" width="16" height="14" rx="2" /></svg>
        <span>实体</span>
        <i v-if="mark('entity')" class="cont" aria-hidden="true">∞</i>
      </button>

      <button
        class="tool"
        :class="{ active: store.tool === 'attribute' }"
        @click="arm('attribute')"
        @dblclick="arm('attribute', true)"
        title="属性（椭圆）"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="12" rx="9" ry="6.5" /></svg>
        <span>属性</span>
        <i v-if="mark('attribute')" class="cont" aria-hidden="true">∞</i>
      </button>

      <button
        class="tool"
        :class="{ active: store.tool === 'relationship' }"
        @click="arm('relationship')"
        @dblclick="arm('relationship', true)"
        title="联系（菱形）"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3.5l7.5 8.5-7.5 8.5L4.5 12 12 3.5z" /></svg>
        <span>联系</span>
        <i v-if="mark('relationship')" class="cont" aria-hidden="true">∞</i>
      </button>

      <button
        class="tool"
        :class="{ active: store.tool === 'connect' || (store.tool !== 'free' && store.pendingFromId) }"
        @click="arm('connect')"
        @dblclick="arm('connect', true)"
        title="连线（依次点两个元素）"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M7 17L17 7" /><circle cx="7" cy="17" r="2.4" /><circle cx="17" cy="7" r="2.4" /></svg>
        <span>连线</span>
        <i v-if="mark('connect')" class="cont" aria-hidden="true">∞</i>
      </button>

      <button
        class="tool"
        :class="{ active: store.tool === 'free' }"
        @click="arm('free')"
        @dblclick="arm('free', true)"
        title="自由端连线：先点参与者，再点画布任意位置"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M7 17L18 7" />
          <circle cx="7" cy="17" r="2.4" />
          <path d="M16 5.5h3v3" opacity=".7" />
        </svg>
        <span>自由端</span>
        <i v-if="mark('free')" class="cont" aria-hidden="true">∞</i>
      </button>
    </div>

    <div class="rail-foot">
      <button
        class="tool"
        title="自动适配布局：按当前画布比例重新计算实体 / 联系 / 属性位置；不改比例、不重置视口"
        @click="store.autoLayout(store.pageRatio)"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3" />
          <rect x="8" y="8" width="8" height="8" />
        </svg>
        <span>适配</span>
      </button>
      <button class="tool" title="重新排列：保持页面比例，只重排图形（可撤销）" @click="store.relayout()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="4" y="4" width="7" height="7" />
          <rect x="13" y="13" width="7" height="7" />
          <path d="M11 7.5h5.5M7.5 11v5.5" />
        </svg>
        <span>重排</span>
      </button>
      <button
        class="tool"
        :disabled="store.pageRatio === 'free'"
        title="适应画布：把整个页面装进视口（自由画布没有页面，请用「图形」）"
        @click="store.fitPageNow()"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="5" y="5" width="14" height="14" rx="1.5" />
          <path d="M8 3v3M16 3v3M8 18v3M16 18v3M3 8h3M3 16h3M18 8h3M18 16h3" />
        </svg>
        <span>版面</span>
      </button>
      <button class="tool" title="适应全部图形：把所有实体 / 属性 / 联系装进视口" @click="store.fitContentNow()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6" />
          <circle cx="9" cy="9.5" r="2.2" />
          <rect x="13.5" y="7" width="4.5" height="4" rx=".8" />
          <path d="M8.5 16.5h8" />
        </svg>
        <span>图形</span>
      </button>
      <button
        class="tool"
        :disabled="!(store.layoutMark > 0 && store.layoutMark === store.undoStack.length)"
        title="撤销布局：回退最近一次自动适配 / 重新排列"
        @click="store.undoLayout()"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6L5 10l4 4" /><path d="M5 10h9a5 5 0 015 5v1" /></svg>
        <span>撤销</span>
      </button>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { useErStore, type Tool } from "../model/store";

const store = useErStore();

function arm(tool: Tool, continuous = false) {
  store.setTool(tool, continuous);
}
function mark(tool: Tool) {
  return store.tool === tool && store.continuous ? "∞" : "";
}
</script>

<style scoped>
.rail {
  width: var(--rail-w);
  flex: 0 0 var(--rail-w);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
  background: var(--panel-2);
  border-right: 1px solid var(--border);
  gap: 2px;
  overflow-y: auto;
}

.rail-tools {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rail-foot {
  margin-top: auto;
}

.tool {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  width: 44px;
  height: 46px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.tool svg {
  width: 18px;
  height: 18px;
}
.tool span {
  font-size: 10.5px;
  font-weight: 550;
  line-height: 1;
}
.tool:hover:not(:disabled) {
  background: var(--surface-sunken);
  color: var(--text);
}
.tool:disabled {
  opacity: 0.36;
  cursor: not-allowed;
}
.tool.active {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.tool.active::before {
  content: "";
  position: absolute;
  left: -4px;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 18px;
  border-radius: 2px;
  background: var(--brand);
}
.tool.active:hover {
  background: #e6e9ff;
  color: var(--brand-strong);
}
.tool:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
}
.cont {
  position: absolute;
  top: 3px;
  right: 3px;
  font-style: normal;
  font-size: 9px;
  font-weight: 700;
  background: var(--warn);
  color: #fff;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  line-height: 1;
}
</style>
